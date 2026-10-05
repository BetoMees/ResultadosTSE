"""Orquestra descoberta e download dos logs da urna."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Optional

from .api import DEFAULT_UFS, TseResultadosClient, pad
from .db import Database
from .modelo import parse_modelo_from_jez, parse_modelo_from_text

log = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode_log_bytes(raw: bytes) -> str:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _pick_logd_name(names: list[str]) -> Optional[str]:
    target = next((n for n in names if n.lower().endswith("logd.dat")), None)
    if target:
        return target
    return names[0] if names else None


def extract_logd_dat(jez_bytes: bytes) -> Optional[str]:
    """Extrai logd.dat de .jez (ZIP) ou .logjez (7z) do TSE."""
    if not jez_bytes:
        return None
    if jez_bytes[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(jez_bytes)) as zf:
            target = _pick_logd_name(zf.namelist())
            if not target:
                return None
            return _decode_log_bytes(zf.read(target))
    # .logjez histórico (2022/2024) é 7-Zip
    if jez_bytes[:6] == b"7z\xbc\xaf'\x1c":
        try:
            import py7zr
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Instale py7zr para ler .logjez (7z)") from exc
        import tempfile
        from pathlib import Path as _Path

        with tempfile.TemporaryDirectory() as tmp:
            with py7zr.SevenZipFile(io.BytesIO(jez_bytes), mode="r") as zf:
                names = list(zf.getnames())
                target = _pick_logd_name(names)
                if not target:
                    return None
                zf.extract(targets=[target], path=tmp)
            raw_path = _Path(tmp) / target
            if not raw_path.is_file():
                # alguns pacotes usam path relativo aninhado
                found = next((_Path(tmp) / n for n in names if n.lower().endswith("logd.dat")), None)
                if found and found.is_file():
                    raw_path = found
                else:
                    return None
            return _decode_log_bytes(raw_path.read_bytes())
    return None


def iter_secoes_from_cs(cs: dict[str, Any], uf: str) -> list[tuple]:
    rows: list[tuple] = []
    for abr in cs.get("abr", []):
        for mu in abr.get("mu", []):
            mun_cd = pad(mu.get("cd"), 5)
            mun_nm = mu.get("nm")
            for zon in mu.get("zon", []):
                zona = pad(zon.get("cd"), 4)
                for sec in zon.get("sec", []):
                    secao = pad(sec.get("ns"), 4)
                    rows.append((uf, mun_cd, mun_nm, zona, secao, sec.get("da"), sec.get("ha")))
    return rows


class UrnaLogDownloader:
    def __init__(
        self,
        db: Database,
        client: TseResultadosClient,
        eleicao: str = "6257",
        workers: int = 32,
        store_blob: bool = True,
        extract_text: bool = False,
        aux_refresh_seconds: float = 1800.0,
    ) -> None:
        self.db = db
        self.client = client
        self.eleicao = str(eleicao)
        self.workers = max(1, workers)
        self.store_blob = store_blob
        self.extract_text = extract_text
        self.aux_refresh_seconds = float(aux_refresh_seconds)
        self.ciclo: str = ""
        self.pleito: str = ""

    def bootstrap(self) -> dict[str, Any]:
        info = self.client.resolve_election(self.eleicao)
        self.ciclo = info["ciclo"]
        self.pleito = info["pleito"]
        for k, v in {
            "eleicao": info["eleicao"],
            "eleicao_nome": info["eleicao_nome"],
            "pleito": info["pleito"],
            "ciclo": info["ciclo"],
            "turno": info["turno"],
            "data": info["data"],
            "host": self.client.host,
            "ambiente": self.client.ambiente,
        }.items():
            self.db.set_meta(k, v)
        log.info(
            "Eleição %s | pleito=%s | ciclo=%s | %s",
            self.eleicao,
            self.pleito,
            self.ciclo,
            info["eleicao_nome"],
        )
        return info

    def discover(self, ufs: Optional[list[str]] = None) -> int:
        if not self.ciclo:
            self.bootstrap()
        ufs = [u.lower() for u in (ufs or list(DEFAULT_UFS))]
        total_new = 0
        for uf in ufs:
            status, data, url = self.client.fetch_cs(self.ciclo, self.pleito, uf)
            now = utc_now()
            if status != 200 or not data:
                log.warning("CS indisponível para %s (%s): %s", uf, status, url)
                self.db.upsert_uf_config(uf, None, None, None, None, 0, status, None, now)
                self.db.commit()
                continue
            rows = iter_secoes_from_cs(data, uf)
            nome = None
            if data.get("abr"):
                nome = data["abr"][0].get("ds")
            self.db.upsert_uf_config(
                uf,
                nome,
                str(data.get("cdp")) if data.get("cdp") is not None else self.pleito,
                data.get("dg"),
                data.get("hg"),
                len(rows),
                status,
                json.dumps(data, ensure_ascii=False),
                now,
            )
            inserted = self.db.insert_secoes(rows)
            self.db.commit()
            total_new += max(inserted, 0)
            log.info("UF %s: %s seções no CS (%s novas)", uf, len(rows), max(inserted, 0))
        return total_new

    def _fetch_aux(self, row: Any) -> dict[str, Any]:
        status, data, url = self.client.fetch_aux(
            self.ciclo,
            self.pleito,
            row["uf"],
            row["municipio_cd"],
            row["zona"],
            row["secao"],
        )
        return {
            "secao_id": row["id"],
            "status": status,
            "data": data,
            "url": url,
            "uf": row["uf"],
            "municipio_cd": row["municipio_cd"],
            "zona": row["zona"],
            "secao": row["secao"],
        }

    def download_aux(self, ufs: Optional[list[str]] = None, limit: Optional[int] = None) -> int:
        if not self.ciclo:
            self.bootstrap()
        pending = self.db.pending_secoes_for_aux(
            ufs, limit, refresh_after_seconds=self.aux_refresh_seconds
        )
        if not pending:
            log.info("Nenhuma seção pendente de aux.json")
            return 0
        log.info(
            "Baixando aux.json de %s seções (workers=%s refresh=%ss)",
            len(pending),
            self.workers,
            int(self.aux_refresh_seconds),
        )
        done = 0
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = [pool.submit(self._fetch_aux, row) for row in pending]
            for fut in as_completed(futures):
                now = utc_now()
                try:
                    result = fut.result()
                    if result["status"] != 200 or not result["data"]:
                        self.db.upsert_aux(
                            result["secao_id"],
                            result["status"],
                            None,
                            None,
                            f"HTTP {result['status']} {result['url']}",
                            now,
                            [],
                        )
                    else:
                        data = result["data"]
                        self.db.upsert_aux(
                            result["secao_id"],
                            result["status"],
                            data.get("st"),
                            json.dumps(data, ensure_ascii=False),
                            None,
                            now,
                            data.get("hashes") or [],
                        )
                except Exception as exc:  # noqa: BLE001
                    log.error("aux falhou: %s", exc)
                done += 1
                if done % 100 == 0:
                    self.db.commit()
                    log.info("aux progresso: %s/%s", done, len(pending))
        self.db.commit()
        return done

    def _fetch_log(self, row: Any) -> dict[str, Any]:
        status, content, url = self.client.fetch_arquivo(
            self.ciclo,
            self.pleito,
            row["uf"],
            row["municipio_cd"],
            row["zona"],
            row["secao"],
            row["hash"],
            row["nome"],
        )
        return {
            "arquivo_id": row["arquivo_id"],
            "status": status,
            "content": content,
            "url": url,
            "meta": row,
        }

    def download_logs(self, ufs: Optional[list[str]] = None, limit: Optional[int] = None) -> int:
        if not self.ciclo:
            self.bootstrap()
        pending = self.db.pending_logs(ufs, limit)
        if not pending:
            log.info("Nenhum log pendente")
            return 0
        log.info("Baixando %s logs (workers=%s)", len(pending), self.workers)
        done = 0
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = [pool.submit(self._fetch_log, row) for row in pending]
            for fut in as_completed(futures):
                now = utc_now()
                try:
                    result = fut.result()
                    arquivo_id = result["arquivo_id"]
                    if result["status"] != 200:
                        self.db.mark_arquivo(
                            arquivo_id,
                            status="missing" if result["status"] == 404 else "error",
                            url=result["url"],
                            error=f"HTTP {result['status']}",
                            downloaded_at=now,
                        )
                    else:
                        content = result["content"]
                        digest = hashlib.sha256(content).hexdigest()
                        log_text = extract_logd_dat(content) if self.extract_text else None
                        modelo = parse_modelo_from_text(log_text) if log_text else None
                        if not modelo:
                            modelo = parse_modelo_from_jez(content)
                        # Evita NULL no dashboard: falha de parse ≠ "ainda não extraído"
                        modelo = modelo or "(não identificado)"
                        self.db.mark_arquivo(
                            arquivo_id,
                            status="ok",
                            url=result["url"],
                            size_bytes=len(content),
                            sha256=digest,
                            content=content if self.store_blob else None,
                            log_text=log_text,
                            modelo_urna=modelo,
                            error=None,
                            downloaded_at=now,
                        )
                except Exception as exc:  # noqa: BLE001
                    log.error("log falhou: %s", exc)
                done += 1
                if done % 50 == 0:
                    self.db.commit()
                    log.info("logs progresso: %s/%s | stats=%s", done, len(pending), self.db.stats())
        self.db.commit()
        return done
