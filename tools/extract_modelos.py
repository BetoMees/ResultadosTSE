#!/usr/bin/env python3
"""Varre logs já baixados e grava modelo_urna em arquivos + secoes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from urna_tse.db import Database
from urna_tse.modelo import parse_modelo_from_jez, parse_modelo_from_text


_PENDING_SQL = """
    tipo='log' AND status='ok'
    AND (modelo_urna IS NULL OR modelo_urna = '(ainda não extraído)')
    AND (content IS NOT NULL OR log_text IS NOT NULL)
"""


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=ROOT / "data" / "urna_logs_6257.sqlite3")
    p.add_argument("--batch", type=int, default=100)
    p.add_argument("--limit", type=int)
    args = p.parse_args()

    db = Database(args.db)
    db.conn.execute("PRAGMA busy_timeout=120000")
    pending = db.conn.execute(
        f"SELECT COUNT(*) FROM arquivos WHERE {_PENDING_SQL}"
    ).fetchone()[0]
    target = min(pending, args.limit) if args.limit else pending
    print(f"pendentes: {pending} (processar: {target})", flush=True)

    done = 0
    while done < target:
        chunk = min(args.batch, target - done)
        rows = list(
            db.conn.execute(
                f"""
                SELECT id, secao_id, content, log_text
                FROM arquivos
                WHERE {_PENDING_SQL}
                LIMIT ?
                """,
                (chunk,),
            )
        )
        if not rows:
            break
        for r in rows:
            modelo = parse_modelo_from_text(r["log_text"]) if r["log_text"] else None
            if not modelo and r["content"] is not None:
                modelo = parse_modelo_from_jez(r["content"])
            modelo = modelo or "(não identificado)"
            db.set_modelo_arquivo(r["id"], modelo, secao_id=r["secao_id"])
            done += 1
        db.commit()
        print(f"  modelos: {done}/{target}", flush=True)

    # espelha modelos já gravados em arquivos para secoes
    cur = db.conn.execute(
        """
        UPDATE secoes
        SET modelo_urna = (
            SELECT a.modelo_urna FROM arquivos a
            WHERE a.secao_id = secoes.id AND a.tipo='log' AND a.status='ok'
              AND a.modelo_urna IS NOT NULL
              AND a.modelo_urna != '(ainda não extraído)'
            LIMIT 1
        )
        WHERE EXISTS (
            SELECT 1 FROM arquivos a
            WHERE a.secao_id = secoes.id AND a.tipo='log' AND a.status='ok'
              AND a.modelo_urna IS NOT NULL
              AND a.modelo_urna != '(ainda não extraído)'
        )
        AND (
            secoes.modelo_urna IS NULL
            OR secoes.modelo_urna = '(ainda não extraído)'
            OR secoes.modelo_urna != (
                SELECT a.modelo_urna FROM arquivos a
                WHERE a.secao_id = secoes.id AND a.tipo='log' AND a.status='ok'
                  AND a.modelo_urna IS NOT NULL
                  AND a.modelo_urna != '(ainda não extraído)'
                LIMIT 1
            )
        )
        """
    )
    db.commit()
    print(f"secoes espelhadas: {cur.rowcount}", flush=True)

    stats = list(
        db.conn.execute(
            """
            SELECT COALESCE(modelo_urna,'(ainda não extraído)') m, COUNT(*) c
            FROM arquivos WHERE tipo='log' AND status='ok'
            GROUP BY modelo_urna ORDER BY c DESC
            """
        )
    )
    print(f"atualizados: {done}", flush=True)
    for m, c in stats:
        print(f"  {m}: {c}", flush=True)
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
