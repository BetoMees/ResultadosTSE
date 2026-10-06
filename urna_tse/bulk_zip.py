"""Importa logs a partir dos ZIPs oficiais (arqurnatot) do Dados Abertos."""

from __future__ import annotations

import logging
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from .api import rate_limit_wait_seconds
from .db import Database
from .elections import UF_NAMES, bulk_zip_url, default_ufs, get_election

log = logging.getLogger(__name__)

LOG_NAME_RE = re.compile(
    r"^o(?P<pleito>\d+)-(?P<mun>\d{5})(?P<zona>\d{4})(?P<secao>\d{4})\.(?P<ext>logjez|jez)$",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_log_filename(name: str) -> Optional[dict[str, str]]:
    base = Path(name).name
    m = LOG_NAME_RE.match(base)
    if not m:
        return None
    return {
        "pleito": m.group("pleito"),
        "municipio_cd": m.group("mun"),
        "zona": m.group("zona"),
        "secao": m.group("secao"),
        "ext": m.group("ext").lower(),
        "nome": base,
    }


class BulkZipImporter:
    def __init__(
        self,
        db: Database,
        *,
        year: int,
        turno: int = 1,
        store_blob: bool = True,
        extract_text: bool = False,
        cache_dir: Optional[Path] = None,
        timeout: float = 600.0,
        progress_cb: Optional[Callable[[dict[str, Any]], None]] = None,
        election_id: Optional[str] = None,
        max_retries: int = 8,
        user_agent: str = "UrnaTSE-Downloader/1.0 (+pesquisa; dados publicos)",
    ) -> None:
        self.db = db
        self.year = int(year)
        self.turno = int(turno)
        self.store_blob = store_blob
        self.extract_text = extract_text
        self.cache_dir = Path(cache_dir) if cache_dir else db.path.parent / "cache_zips"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.progress_cb = progress_cb
        self.election_id = election_id or f"{year}-{turno}t"
        self.max_retries = max(1, int(max_retries))
        self.user_agent = user_agent
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def _emit(self, **kwargs: Any) -> None:
        if self.progress_cb:
            self.progress_cb(kwargs)

    def zip_path(self, uf: str) -> Path:
        return self.cache_dir / f"bu_imgbu_logjez_rdv_vscmr_{self.year}_{self.turno}t_{uf.upper()}.zip"

    def download_uf_zip(self, uf: str, *, force: bool = False) -> Path:
        path = self.zip_path(uf)
        if path.exists() and path.stat().st_size > 0 and not force:
            self._emit(phase="cache", uf=uf, path=str(path), bytes=path.stat().st_size)
            return path
        url = bulk_zip_url(self.year, self.turno, uf)
        self._emit(phase="download", uf=uf, url=url)
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            if self._cancel:
                raise RuntimeError("cancelado")
            try:
                with requests.get(
                    url,
                    stream=True,
                    timeout=self.timeout,
                    headers={"User-Agent": self.user_agent},
                ) as resp:
                    if resp.status_code == 404:
                        raise FileNotFoundError(f"ZIP indisponível (HTTP 404): {url}")
                    if resp.status_code in (429, 500, 502, 503, 504):
                        wait = rate_limit_wait_seconds(attempt, resp=resp)
                        log.warning(
                            "HTTP %s ao baixar ZIP %s (tentativa %s/%s); aguardando %.0fs",
                            resp.status_code,
                            uf.upper(),
                            attempt,
                            self.max_retries,
                            wait,
                        )
                        self._emit(
                            phase="rate_limit",
                            uf=uf,
                            status=resp.status_code,
                            wait_s=wait,
                            attempt=attempt,
                        )
                        time.sleep(wait)
                        continue
                    resp.raise_for_status()
                    tmp = path.with_suffix(".partial")
                    total = 0
                    with open(tmp, "wb") as fh:
                        for chunk in resp.iter_content(chunk_size=1024 * 1024):
                            if self._cancel:
                                raise RuntimeError("cancelado")
                            if not chunk:
                                continue
                            fh.write(chunk)
                            total += len(chunk)
                            if total and total % (8 * 1024 * 1024) == 0:
                                self._emit(phase="download", uf=uf, bytes=total)
                    tmp.replace(path)
                self._emit(phase="downloaded", uf=uf, path=str(path), bytes=path.stat().st_size)
                return path
            except FileNotFoundError:
                raise
            except RuntimeError:
                raise
            except requests.RequestException as exc:
                last_err = exc
                wait = rate_limit_wait_seconds(attempt, resp=getattr(exc, "response", None))
                log.warning(
                    "Falha de rede no ZIP %s (tentativa %s/%s): %s; aguardando %.0fs",
                    uf.upper(),
                    attempt,
                    self.max_retries,
                    exc,
                    wait,
                )
                self._emit(
                    phase="rate_limit",
                    uf=uf,
                    error=str(exc),
                    wait_s=wait,
                    attempt=attempt,
                )
                time.sleep(wait)
        raise RuntimeError(f"Rate limit / falha ao baixar {url}: {last_err}")

    def import_zip(self, uf: str, zip_path: Path) -> dict[str, int]:
        uf = uf.lower()
        imported = 0
        skipped = 0
        errors = 0
        now = utc_now()
        with zipfile.ZipFile(zip_path) as zf:
            members = [n for n in zf.namelist() if n.lower().endswith((".logjez", ".jez"))]
            self._emit(phase="import", uf=uf, total=len(members))
            for i, name in enumerate(members, 1):
                if self._cancel:
                    raise RuntimeError("cancelado")
                meta = parse_log_filename(name)
                if not meta:
                    skipped += 1
                    continue
                try:
                    content = zf.read(name)
                    self.db.import_bulk_log(
                        uf=uf,
                        municipio_cd=meta["municipio_cd"],
                        zona=meta["zona"],
                        secao=meta["secao"],
                        nome=meta["nome"],
                        content=content,
                        url=str(zip_path),
                        store_blob=self.store_blob,
                        extract_text=self.extract_text,
                        downloaded_at=now,
                    )
                    imported += 1
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    log.warning("Falha ao importar %s/%s: %s", uf, name, exc)
                if i % 200 == 0:
                    self.db.commit()
                    self._emit(phase="import", uf=uf, done=i, total=len(members), imported=imported)
        self.db.commit()
        # Atualiza uf_config com nome legível (Detalhe por UF / mapa).
        n_secoes = self.db.count("secoes", "uf=?", (uf,))
        self.db.upsert_uf_config(
            uf,
            UF_NAMES.get(uf) or uf.upper(),
            None,
            None,
            None,
            n_secoes,
            200,
            None,
            now,
        )
        self.db.commit()
        try:
            self.db.rebuild_painel_stats()
        except Exception:  # noqa: BLE001
            log.exception("rebuild painel_stats falhou após import %s", uf)
        return {"imported": imported, "skipped": skipped, "errors": errors, "members": len(members)}

    def run(
        self,
        ufs: Optional[list[str]] = None,
        *,
        force_download: bool = False,
    ) -> dict[str, Any]:
        election = get_election(self.election_id)
        if not election.get("bulk_available", True):
            raise RuntimeError(election.get("note") or "Pacote em massa indisponível")

        self.db.set_meta("eleicao_ano", str(self.year))
        self.db.set_meta("turno", str(self.turno))
        self.db.set_meta("source", "dados_abertos_arqurnatot")
        if election.get("pleito"):
            self.db.set_meta("pleito", str(election["pleito"]))
        self.db.set_meta("eleicao_nome", election.get("label") or f"{self.year}")
        self.db.commit()

        targets = [u.lower() for u in (ufs or default_ufs())]
        summary: dict[str, Any] = {"ufs": {}, "imported": 0, "errors": 0}
        for uf in targets:
            if self._cancel:
                summary["cancelled"] = True
                break
            try:
                path = self.download_uf_zip(uf, force=force_download)
                stats = self.import_zip(uf, path)
                summary["ufs"][uf] = {"ok": True, **stats, "zip_bytes": path.stat().st_size}
                summary["imported"] += stats["imported"]
                summary["errors"] += stats["errors"]
            except Exception as exc:  # noqa: BLE001
                log.exception("UF %s falhou", uf)
                summary["ufs"][uf] = {"ok": False, "error": str(exc)}
                summary["errors"] += 1
                self._emit(phase="error", uf=uf, error=str(exc))
        summary["stats"] = self.db.stats()
        return summary
