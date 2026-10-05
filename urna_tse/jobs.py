"""Jobs de download disparados pelo dashboard (background)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .bulk_zip import BulkZipImporter
from .db import Database
from .elections import default_ufs, get_election

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STATUS_PATH = DATA / "download_status.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    except Exception:  # noqa: BLE001
        return False
    return True


def _read_status_file() -> Optional[dict[str, Any]]:
    if not STATUS_PATH.exists():
        return None
    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data
    except Exception:  # noqa: BLE001
        return None


def _write_status_file(job: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    payload = dict(job)
    payload["pid"] = os.getpid()
    payload["updated_at"] = utc_now()
    tmp = STATUS_PATH.with_suffix(".partial")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATUS_PATH)


_EXT_CACHE: dict[str, Any] = {"at": 0.0, "job": None}


def _discover_external_download() -> Optional[dict[str, Any]]:
    """Detecta tools/run_bulk_*.py ou download_logs_urna.py em outro processo."""
    now = time.time()
    if now - float(_EXT_CACHE["at"] or 0) < 4.0:
        return _EXT_CACHE["job"]  # type: ignore[return-value]
    found: Optional[dict[str, Any]] = None
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress",
            ],
            text=True,
            timeout=8,
            stderr=subprocess.DEVNULL,
        )
        if out.strip():
            rows = json.loads(out)
            if isinstance(rows, dict):
                rows = [rows]
            me = os.getpid()
            for row in rows or []:
                pid = int(row.get("ProcessId") or 0)
                cmd = str(row.get("CommandLine") or "")
                if not pid or pid == me:
                    continue
                low = cmd.lower().replace("\\", "/")
                if "run_bulk_" in low or "download_logs_urna.py" in low:
                    eid = "2022-1t"
                    if "2022_2" in low or "2022-2" in low:
                        eid = "2022-2t"
                    elif "2026" in low:
                        eid = "2026"
                    found = {
                        "status": "running",
                        "election_id": eid,
                        "message": f"Download externo em andamento (pid {pid})",
                        "pid": pid,
                        "progress": {"phase": "external", "pid": pid},
                        "external": True,
                    }
                    break
    except Exception:  # noqa: BLE001
        found = None
    _EXT_CACHE["at"] = now
    _EXT_CACHE["job"] = found
    return found


class DownloadJobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._job: dict[str, Any] = {
            "status": "idle",
            "election_id": None,
            "message": "",
            "started_at": None,
            "finished_at": None,
            "progress": {},
            "result": None,
            "error": None,
        }
        self._thread: Optional[threading.Thread] = None
        self._proc: Optional[subprocess.Popen] = None
        self._importer: Optional[BulkZipImporter] = None
        self._stop = False

    def _local_work_active(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
        if self._proc is not None and self._proc.poll() is None:
            return True
        return self._importer is not None

    def _mark_finished(self, **kwargs: Any) -> dict[str, Any]:
        payload = {
            "status": "cancelled",
            "message": "Download interrompido",
            "finished_at": utc_now(),
            "error": None,
            **kwargs,
        }
        with self._lock:
            self._job.update(payload)
            snap = dict(self._job)
        try:
            _write_status_file(snap)
        except Exception:  # noqa: BLE001
            pass
        _EXT_CACHE["at"] = 0.0
        _EXT_CACHE["job"] = None
        return snap

    def status(self) -> dict[str, Any]:
        with self._lock:
            local = dict(self._job)
        file_job = _read_status_file()
        local_busy = local.get("status") in ("running", "starting", "stopping")

        # Status "stopping/running" sem worker local: ou há download externo, ou está preso.
        if local_busy and not self._local_work_active():
            ext = _discover_external_download()
            if ext:
                return ext
            healed = self._mark_finished(
                election_id=local.get("election_id"),
                status="cancelled" if local.get("status") == "stopping" else "error",
                message=(
                    "Download interrompido"
                    if local.get("status") == "stopping"
                    else "Download interrompido (processo encerrado)"
                ),
                progress=local.get("progress") or {},
            )
            return healed

        if local_busy:
            return local

        if file_job:
            file_busy = file_job.get("status") in ("running", "starting", "stopping")
            file_pid = int(file_job.get("pid") or 0)
            # PID do próprio dashboard não conta como worker de download
            foreign_alive = (
                file_busy
                and file_pid
                and file_pid != os.getpid()
                and _pid_alive(file_pid)
            )
            if foreign_alive:
                return file_job
            if file_busy:
                ext = _discover_external_download()
                if ext:
                    return ext
                healed = {
                    **file_job,
                    "status": "cancelled"
                    if file_job.get("status") == "stopping"
                    else "error",
                    "message": (
                        "Download interrompido"
                        if file_job.get("status") == "stopping"
                        else "Download interrompido (processo encerrado)"
                    ),
                    "error": None
                    if file_job.get("status") == "stopping"
                    else "process_dead",
                    "finished_at": utc_now(),
                }
                try:
                    _write_status_file(healed)
                except Exception:  # noqa: BLE001
                    pass
                with self._lock:
                    self._job.update(healed)
                return healed
            if file_job.get("status") not in (None, "idle"):
                ext = _discover_external_download()
                if ext:
                    return ext
                return file_job

        ext = _discover_external_download()
        if ext:
            return ext
        return local

    def _set(self, **kwargs: Any) -> None:
        with self._lock:
            self._job.update(kwargs)
            snap = dict(self._job)
        try:
            _write_status_file(snap)
        except Exception:  # noqa: BLE001
            log.debug("falha ao persistir status", exc_info=True)

    def stop(self) -> dict[str, Any]:
        self._stop = True
        if self._importer:
            self._importer.cancel()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

        cur = self.status()
        pid = int(cur.get("pid") or 0)
        # Encerra download em outro processo (ex.: tools/run_bulk_*.py)
        if pid and pid != os.getpid() and _pid_alive(pid):
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        check=False,
                        capture_output=True,
                        timeout=15,
                    )
                else:
                    os.kill(pid, 15)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"Não foi possível parar o processo {pid}: {exc}") from exc

        # Ainda há worker neste processo — aguarda o thread marcar o fim
        if self._local_work_active():
            self._set(status="stopping", message="Cancelando…")
            return self.status()

        return self._mark_finished(
            election_id=cur.get("election_id"),
            progress=cur.get("progress") or {},
        )

    def start(
        self,
        election_id: str,
        *,
        ufs: Optional[list[str]] = None,
        store_blob: bool = True,
        workers: int = 6,
        min_interval: float = 0.1,
    ) -> dict[str, Any]:
        election = get_election(election_id)
        cur = self.status()
        if cur.get("status") in ("running", "starting", "stopping"):
            raise RuntimeError("Já existe um download em andamento")
        if election.get("mode") == "bulk_zip" and not election.get("bulk_available", False):
            raise RuntimeError(election.get("note") or "Pacote em massa indisponível")

        # Continuar: só UFs ainda incompletas no banco
        if ufs is None:
            missing = missing_ufs_for_election(election)
            if missing:
                ufs = missing

        with self._lock:
            self._stop = False
            self._job = {
                "status": "starting",
                "election_id": election["id"],
                "mode": election["mode"],
                "label": election["label"],
                "note": election.get("note"),
                "message": f"Iniciando {election['label']}…",
                "started_at": utc_now(),
                "finished_at": None,
                "progress": {},
                "result": None,
                "error": None,
                "db_filename": election["db_filename"],
                "ufs": ufs,
            }

        self._thread = threading.Thread(
            target=self._run,
            kwargs={
                "election": election,
                "ufs": ufs,
                "store_blob": store_blob,
                "workers": workers,
                "min_interval": min_interval,
            },
            daemon=True,
            name=f"download-{election['id']}",
        )
        self._thread.start()
        self._set()  # persiste starting
        return self.status()

    def _run(
        self,
        *,
        election: dict[str, Any],
        ufs: Optional[list[str]],
        store_blob: bool,
        workers: int,
        min_interval: float,
    ) -> None:
        db_path = DATA / election["db_filename"]
        try:
            self._set(status="running", message=f"Download {election['label']} em execução")
            if election["mode"] == "bulk_zip":
                result = self._run_bulk(election, db_path, ufs=ufs, store_blob=store_blob)
            elif election["mode"] == "regional":
                result = self._run_regional(
                    election,
                    db_path,
                    ufs=ufs,
                    workers=workers,
                    min_interval=min_interval,
                )
            else:
                raise RuntimeError(f"Modo desconhecido: {election['mode']}")
            if self._stop:
                self._set(
                    status="cancelled",
                    message="Download cancelado",
                    finished_at=utc_now(),
                    result=result,
                )
            else:
                self._set(
                    status="done",
                    message="Download concluído",
                    finished_at=utc_now(),
                    result=result,
                )
        except Exception as exc:  # noqa: BLE001
            log.exception("Job falhou")
            self._set(
                status="error",
                message=str(exc),
                error=str(exc),
                finished_at=utc_now(),
            )
        finally:
            self._importer = None
            self._proc = None

    def _run_bulk(
        self,
        election: dict[str, Any],
        db_path: Path,
        *,
        ufs: Optional[list[str]],
        store_blob: bool,
    ) -> dict[str, Any]:
        db = Database(db_path)

        def on_progress(info: dict[str, Any]) -> None:
            self._set(progress=info, message=self._fmt_progress(election["id"], info))

        importer = BulkZipImporter(
            db,
            year=int(election["year"]),
            turno=int(election.get("turno") or 1),
            store_blob=store_blob,
            progress_cb=on_progress,
            election_id=election["id"],
        )
        self._importer = importer
        try:
            return importer.run(ufs=ufs)
        finally:
            db.close()

    def _run_regional(
        self,
        election: dict[str, Any],
        db_path: Path,
        *,
        ufs: Optional[list[str]],
        workers: int,
        min_interval: float,
    ) -> dict[str, Any]:
        script = ROOT / "download_logs_urna.py"
        log_path = DATA / f"download_{election['id']}.err.log"
        cmd = [
            sys.executable,
            "-u",
            str(script),
            "--eleicao",
            str(election["eleicao"]),
            "--db",
            str(db_path),
            "--workers",
            str(max(1, workers)),
            "--min-interval",
            str(min_interval),
            "--batch-size",
            "1000",
        ]
        if ufs:
            cmd.extend(["--ufs", *[u.lower() for u in ufs]])
        self._set(progress={"phase": "regional", "cmd": " ".join(cmd)}, message="Downloader regional iniciado")
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"\n==== {utc_now()} start {' '.join(cmd)}\n")
            fh.flush()
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=fh,
                stderr=subprocess.STDOUT,
            )
            while True:
                if self._stop and self._proc.poll() is None:
                    self._proc.terminate()
                    break
                code = self._proc.poll()
                if code is not None:
                    if code != 0 and not self._stop:
                        raise RuntimeError(f"Downloader saiu com código {code} (ver {log_path.name})")
                    break
                time.sleep(2)
                self._set(
                    progress={"phase": "regional", "pid": self._proc.pid, "log": log_path.name},
                    message=f"Download regional em andamento (pid {self._proc.pid})",
                )
        return {"log": str(log_path), "db": str(db_path)}

    @staticmethod
    def _fmt_progress(election_id: str, info: dict[str, Any]) -> str:
        phase = info.get("phase") or "?"
        uf = (info.get("uf") or "").upper()
        if phase == "download":
            b = info.get("bytes")
            return f"{election_id}: baixando ZIP {uf}" + (f" ({b} bytes)" if b else "")
        if phase == "import":
            done = info.get("done")
            total = info.get("total")
            if done and total:
                return f"{election_id}: importando {uf} {done}/{total}"
            return f"{election_id}: importando {uf}"
        if phase == "error":
            return f"{election_id}: erro em {uf}: {info.get('error')}"
        return f"{election_id}: {phase} {uf}".strip()


_COVERAGE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def election_coverage(election: dict[str, Any]) -> dict[str, Any]:
    """Cobertura do download: UFs faltando / logs vs seções (modo regional)."""
    db_path = DATA / election["db_filename"]
    cache_key = f"{election.get('id')}|{election.get('mode')}|{db_path.name}"
    now = time.time()
    hit = _COVERAGE_CACHE.get(cache_key)
    if hit and now - hit[0] < 8.0:
        return dict(hit[1])

    expected = default_ufs()
    empty = {
        "ufs_expected": len(expected),
        "ufs_done": 0,
        "ufs_missing": list(expected),
        "logs_ok": 0,
        "secoes": 0,
        "partial": False,
        "complete": False,
    }
    if not db_path.exists():
        _COVERAGE_CACHE[cache_key] = (now, empty)
        return dict(empty)

    try:
        import sqlite3

        uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            if election.get("mode") == "bulk_zip":
                have = {
                    str(r[0]).lower()
                    for r in conn.execute("SELECT DISTINCT uf FROM secoes")
                }
                missing = [u for u in expected if u not in have]
                logs_ok = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM arquivos WHERE tipo='log' AND status='ok'"
                    ).fetchone()[0]
                    or 0
                )
                secoes = int(conn.execute("SELECT COUNT(*) FROM secoes").fetchone()[0] or 0)
                done = len(expected) - len(missing)
                info = {
                    "ufs_expected": len(expected),
                    "ufs_done": done,
                    "ufs_missing": missing,
                    "logs_ok": logs_ok,
                    "secoes": secoes,
                    "partial": bool(logs_ok > 0 or secoes > 0) and bool(missing),
                    "complete": not missing and (logs_ok > 0 or secoes > 0),
                }
            else:
                # Regional: UF completa só se logs ok >= seções cadastradas.
                rows = conn.execute(
                    """
                    SELECT s.uf,
                           COUNT(*) AS n_secoes,
                           SUM(CASE WHEN a.status='ok' THEN 1 ELSE 0 END) AS logs_ok
                    FROM secoes s
                    LEFT JOIN arquivos a ON a.secao_id = s.id AND a.tipo = 'log'
                    GROUP BY s.uf
                    """
                ).fetchall()
                by_uf = {str(r[0]).lower(): (int(r[1] or 0), int(r[2] or 0)) for r in rows}
                if not by_uf:
                    # sem CS ainda
                    info = dict(empty)
                else:
                    ufs_all = sorted(by_uf.keys())
                    missing = [
                        u for u in ufs_all if by_uf[u][1] < by_uf[u][0]
                    ]
                    # inclui UFs do catálogo que nem entraram no banco
                    for u in expected:
                        if u not in by_uf and u not in missing:
                            missing.append(u)
                    logs_ok = sum(v[1] for v in by_uf.values())
                    secoes = sum(v[0] for v in by_uf.values())
                    done = len(ufs_all) - sum(1 for u in ufs_all if by_uf[u][1] < by_uf[u][0])
                    info = {
                        "ufs_expected": max(len(ufs_all), len(expected)),
                        "ufs_done": max(0, done),
                        "ufs_missing": missing,
                        "logs_ok": logs_ok,
                        "secoes": secoes,
                        "partial": logs_ok > 0 and logs_ok < secoes,
                        "complete": secoes > 0 and logs_ok >= secoes and not missing,
                    }
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        info = dict(empty)

    _COVERAGE_CACHE[cache_key] = (now, info)
    return dict(info)


def missing_ufs_for_election(election: dict[str, Any]) -> list[str]:
    """UFs ainda incompletas no SQLite da eleição (para continuar download)."""
    return list(election_coverage(election).get("ufs_missing") or [])


JOBS = DownloadJobManager()
