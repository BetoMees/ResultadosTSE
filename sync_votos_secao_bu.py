#!/usr/bin/env python3
"""Baixa BUs de seções com modelo_urna, extrai votos de Presidente e grava no SQLite.

Resumível: pula seções já com votos_secao.status='ok'.
"""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from urna_tse.api import TseResultadosClient
from urna_tse.bu_parser import extract_presidente_votes
from urna_tse.db import Database
from urna_tse.downloader import utc_now

DEFAULT_DB = ROOT / "data" / "urna_logs_6257.sqlite3"
log = logging.getLogger("sync_bu")


def candidate_numbers(db: Database) -> set[int]:
    rows = db.conn.execute(
        "SELECT numero FROM votos_candidatos WHERE abr='br'"
    ).fetchall()
    out: set[int] = set()
    for r in rows:
        try:
            out.add(int(r["numero"]))
        except (TypeError, ValueError):
            continue
    if not out:
        # fallback típico 2026
        out = {13, 14, 16, 21, 22, 27, 29, 30, 35, 55, 70, 80}
    return out


def pending_bus(
    db: Database,
    *,
    ufs: Optional[list[str]] = None,
    modelos: Optional[list[str]] = None,
    limit: Optional[int] = None,
    include_without_modelo: bool = False,
) -> list[Any]:
    rows = db.pending_bus(ufs=ufs, limit=limit)
    if include_without_modelo and not modelos:
        return list(rows)
    out = []
    for r in rows:
        modelo = r["modelo_urna"]
        if modelos:
            if modelo not in modelos:
                continue
        elif not include_without_modelo:
            if not modelo or not str(modelo).startswith("UE"):
                continue
        out.append(r)
    return out


def _fetch_one(
    client: TseResultadosClient,
    ciclo: str,
    pleito: str,
    row: Any,
) -> dict[str, Any]:
    status, content, url = client.fetch_arquivo(
        ciclo,
        pleito,
        row["uf"],
        row["municipio_cd"],
        row["zona"],
        row["secao"],
        row["hash"],
        row["nome"],
    )
    return {
        "row": row,
        "status": status,
        "content": content,
        "url": url,
    }


def sync_batch(
    db: Database,
    client: TseResultadosClient,
    *,
    limit: int = 400,
    workers: int = 6,
    ufs: Optional[list[str]] = None,
    modelos: Optional[list[str]] = None,
    store_blob: bool = False,
) -> dict[str, int]:
    ciclo = db.get_meta("ciclo") or "ele2026"
    pleito = db.get_meta("pleito") or "3220"
    cands = candidate_numbers(db)
    pending = pending_bus(db, ufs=ufs, modelos=modelos, limit=limit)
    if not pending:
        log.info("Nenhum BU pendente com modelo_urna")
        return {"pending": 0, "ok": 0, "empty": 0, "fail": 0, "http_err": 0}

    log.info(
        "Baixando/parsing %s BUs (workers=%s, cands=%s)",
        len(pending),
        workers,
        sorted(cands),
    )
    stats = {"pending": len(pending), "ok": 0, "empty": 0, "fail": 0, "http_err": 0}
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [
            pool.submit(_fetch_one, client, ciclo, pleito, row) for row in pending
        ]
        for fut in as_completed(futures):
            now = utc_now()
            try:
                result = fut.result()
                row = result["row"]
                secao_id = int(row["secao_id"])
                modelo = row["modelo_urna"]
                arquivo_id = int(row["arquivo_id"])
                if result["status"] != 200 or not result["content"]:
                    db.mark_arquivo(
                        arquivo_id,
                        status="missing" if result["status"] == 404 else "error",
                        url=result["url"],
                        error=f"HTTP {result['status']}",
                        downloaded_at=now,
                    )
                    db.upsert_votos_secao(
                        secao_id,
                        modelo_urna=modelo,
                        uf=row["uf"],
                        votos={},
                        status="error",
                        error=f"HTTP {result['status']}",
                        downloaded_at=now,
                    )
                    stats["http_err"] += 1
                else:
                    content = result["content"]
                    votes = extract_presidente_votes(content, cands)
                    digest = __import__("hashlib").sha256(content).hexdigest()
                    db.mark_arquivo(
                        arquivo_id,
                        status="ok",
                        url=result["url"],
                        size_bytes=len(content),
                        sha256=digest,
                        content=content if store_blob else None,
                        error=None,
                        downloaded_at=now,
                    )
                    if votes:
                        db.upsert_votos_secao(
                            secao_id,
                            modelo_urna=modelo,
                            uf=row["uf"],
                            votos=votes,
                            status="ok",
                            error=None,
                            downloaded_at=now,
                        )
                        # espelha modelo na seção se faltar
                        if modelo and str(modelo).startswith("UE"):
                            db.conn.execute(
                                "UPDATE secoes SET modelo_urna=? WHERE id=? AND (modelo_urna IS NULL OR modelo_urna='')",
                                (modelo, secao_id),
                            )
                        stats["ok"] += 1
                    else:
                        db.upsert_votos_secao(
                            secao_id,
                            modelo_urna=modelo,
                            uf=row["uf"],
                            votos={},
                            status="empty",
                            error="parser sem votos Presidente",
                            downloaded_at=now,
                        )
                        stats["empty"] += 1
            except Exception as exc:  # noqa: BLE001
                log.error("BU falhou: %s", exc)
                stats["fail"] += 1
            done += 1
            if done % 50 == 0:
                db.commit()
                log.info(
                    "progresso %s/%s | ok=%s empty=%s http_err=%s fail=%s",
                    done,
                    len(pending),
                    stats["ok"],
                    stats["empty"],
                    stats["http_err"],
                    stats["fail"],
                )
    db.commit()
    db.set_meta("votos_secao_bu_synced_at", utc_now())
    return stats


def main() -> int:
    p = argparse.ArgumentParser(description="Sincroniza votos por seção a partir dos BUs")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--limit", type=int, default=400, help="Máx. BUs neste lote")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--ufs", nargs="*", help="Filtrar UFs")
    p.add_argument("--modelos", nargs="*", help="Filtrar modelos (ex.: UE2022)")
    p.add_argument("--store-blob", action="store_true")
    p.add_argument("--min-interval", type=float, default=0.04)
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    db = Database(args.db)
    client = TseResultadosClient(min_interval=args.min_interval)
    try:
        stats = sync_batch(
            db,
            client,
            limit=args.limit,
            workers=args.workers,
            ufs=[u.lower() for u in args.ufs] if args.ufs else None,
            modelos=args.modelos,
            store_blob=args.store_blob,
        )
        ok_total = db.count("votos_secao", "status='ok'")
        log.info("lote: %s | votos_secao ok total=%s", stats, ok_total)
        by_mod = list(
            db.conn.execute(
                """
                SELECT COALESCE(modelo_urna,'(null)') m, COUNT(*) c
                FROM votos_secao WHERE status='ok'
                GROUP BY 1 ORDER BY c DESC
                """
            )
        )
        for r in by_mod:
            log.info("  %s: %s seções", r["m"], r["c"])
    finally:
        client.close()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
