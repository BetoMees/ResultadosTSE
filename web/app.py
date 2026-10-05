"""Dashboard de estatísticas dos logs da urna (TSE Resultados)."""

from __future__ import annotations

import time
from functools import wraps
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from urna_tse.db import Database
from urna_tse.elections import default_ufs, get_election, list_elections
from urna_tse.jobs import JOBS, election_coverage
from urna_tse.votos import (
    load_presidente_by_modelo,
    load_presidente_from_db,
    load_presidente_ufs_from_db,
    sync_presidente_to_db,
)
from urna_tse.votos_csv import sync_presidente_from_munzona
from web.queries import (
    apuracao,
    aux_status,
    connect,
    modelos,
    municipios,
    overview,
    tamanhos,
    ufs,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DEFAULT_DB = DATA / "urna_logs_6257.sqlite3"
STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Urna TSE — estatísticas")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.state.db_path = DEFAULT_DB

_cache: dict[str, tuple[float, object]] = {}
TTL = 20.0


class StartDownloadBody(BaseModel):
    election_id: str = Field(..., description="2022-1t | 2022-2t | 2026")
    ufs: Optional[list[str]] = None
    store_blob: bool = True
    workers: int = 6
    min_interval: float = 0.1
    switch_db: bool = True


class SelectDbBody(BaseModel):
    election_id: str


def cached(ttl: float = TTL):
    def deco(fn: Callable):
        @wraps(fn)
        def inner(*args, **kwargs):
            # Durante download, não servir cache — KPIs/cobertura mudam a cada commit no SQLite.
            try:
                job = JOBS.status()
                downloading = job.get("status") in ("running", "starting", "stopping")
            except Exception:  # noqa: BLE001
                downloading = False
            if downloading:
                return fn(*args, **kwargs)
            # Inclui o DB ativo na chave — senão "Ver no painel" reaproveita cache da eleição anterior.
            key = (
                fn.__name__
                + "|"
                + str(db_path())
                + "|"
                + repr(args)
                + repr(sorted(kwargs.items()))
            )
            now = time.time()
            hit = _cache.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
            value = fn(*args, **kwargs)
            _cache[key] = (now, value)
            return value

        return inner

    return deco


def db_path() -> Path:
    return Path(getattr(app.state, "db_path", DEFAULT_DB))


def clear_cache() -> None:
    _cache.clear()


def set_active_db(path: Path) -> None:
    app.state.db_path = path
    clear_cache()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/.well-known/appspecific/com.chrome.devtools.json")
def chrome_devtools_well_known():
    """Chrome DevTools probe — evita 404 ruidoso nos logs (não é erro do painel)."""
    return {}


@cached()
def _overview():
    path = db_path()
    if not path.exists():
        return {
            "secoes": 0,
            "municipios": 0,
            "aux_ok": 0,
            "logs_ok": 0,
            "bytes_ok": 0,
            "meta": {},
            "db_exists": False,
            "db_bytes": 0,
            "db_path": str(path),
            "db_name": path.name,
        }
    with connect(path) as conn:
        data = overview(conn)
        data["db_exists"] = True
        data["db_bytes"] = path.stat().st_size
        data["db_path"] = str(path)
        data["db_name"] = path.name
        return data


@cached()
def _ufs(modelo: Optional[str] = None):
    with connect(db_path()) as conn:
        return ufs(conn, modelo=modelo)


@cached()
def _aux():
    with connect(db_path()) as conn:
        return aux_status(conn)


@cached()
def _apuracao():
    with connect(db_path()) as conn:
        return apuracao(conn)


@cached()
def _tamanhos():
    with connect(db_path()) as conn:
        return tamanhos(conn)


@cached()
def _modelos():
    with connect(db_path()) as conn:
        return modelos(conn)


@cached()
def _municipios(uf: Optional[str], limit: int, modelo: Optional[str] = None):
    with connect(db_path()) as conn:
        return municipios(conn, uf=uf, limit=limit, modelo=modelo)


@cached()
def _presidente_payload():
    db = Database(db_path())
    try:
        br = load_presidente_from_db(db, "br")
        por_uf = load_presidente_ufs_from_db(db)
        return {
            "source": "sqlite",
            "synced_at": db.get_meta("votos_presidente_synced_at"),
            "brasil": br,
            "ufs": [
                {
                    "uf": row["abr"],
                    "secoes_totalizadas_pct": row["secoes_totalizadas_pct"],
                    "votos_validos": row["votos_validos"],
                    "lider": row["lider"],
                    "candidatos": row["candidatos"][:3],
                }
                for row in por_uf
            ],
        }
    finally:
        db.close()


@app.get("/api/overview")
def api_overview():
    return _overview()


@app.get("/api/elections")
def api_elections():
    active = db_path().name
    job = JOBS.status()
    busy_election = (
        job.get("election_id")
        if job.get("status") in ("running", "starting", "stopping")
        else None
    )
    items = []
    for e in list_elections():
        db_file = DATA / e["db_filename"]
        logs_ok = 0
        secoes = 0
        if db_file.exists():
            try:
                with connect(db_file) as conn:
                    logs_ok = int(
                        conn.execute(
                            "SELECT COUNT(*) FROM arquivos WHERE tipo='log' AND status='ok'"
                        ).fetchone()[0]
                        or 0
                    )
                    secoes = int(conn.execute("SELECT COUNT(*) FROM secoes").fetchone()[0] or 0)
            except Exception:  # noqa: BLE001
                logs_ok = 0
                secoes = 0
        downloading = busy_election == e["id"]
        has_data = logs_ok > 0 or secoes > 0
        can_download = (
            e["mode"] == "regional"
            or (e["mode"] == "bulk_zip" and e.get("bulk_available", False))
        )
        cov = election_coverage(e) if has_data or db_file.exists() else {
            "ufs_expected": len(default_ufs()),
            "ufs_done": 0,
            "ufs_missing": list(default_ufs()),
            "logs_ok": 0,
            "secoes": 0,
            "partial": False,
            "complete": False,
        }
        # Preferir contagens frescas do DB aberto acima quando disponíveis
        if logs_ok:
            cov["logs_ok"] = logs_ok
        if secoes:
            cov["secoes"] = secoes
        partial = bool(cov.get("partial")) or (
            has_data and not cov.get("complete") and bool(cov.get("ufs_missing"))
        )
        incomplete = bool(has_data and partial and not downloading)
        items.append(
            {
                **e,
                "db_exists": db_file.exists(),
                "db_bytes": db_file.stat().st_size if db_file.exists() else 0,
                "logs_ok": logs_ok,
                "secoes": secoes,
                "has_data": has_data,
                "active": e["db_filename"] == active,
                "downloading": downloading,
                "partial": partial,
                "ufs_expected": cov.get("ufs_expected"),
                "ufs_done": cov.get("ufs_done"),
                "ufs_missing": cov.get("ufs_missing") or [],
                # Iniciar só se ainda não há dados e nada está baixando.
                "can_start": can_download and not has_data and busy_election is None,
                # Continuar quando parou no meio (faltam UFs / logs).
                "can_continue": can_download and incomplete and busy_election is None,
                # Remover: não apagar enquanto esta eleição está baixando.
                "can_remove": has_data and not downloading,
                # Pode ver no painel com dados parciais, mesmo com download em curso.
                "can_view": has_data,
                "can_download": can_download,
            }
        )
    return {"elections": items, "active_db": active, "job": job}


@app.post("/api/elections/select")
def api_select_election(body: SelectDbBody):
    try:
        election = get_election(body.election_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    path = DATA / election["db_filename"]
    if not path.exists():
        raise HTTPException(409, "Download ainda não iniciado para esta eleição.")
    try:
        with connect(path) as conn:
            logs_ok = int(
                conn.execute(
                    "SELECT COUNT(*) FROM arquivos WHERE tipo='log' AND status='ok'"
                ).fetchone()[0]
                or 0
            )
            secoes = int(conn.execute("SELECT COUNT(*) FROM secoes").fetchone()[0] or 0)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(409, f"Banco indisponível: {exc}") from exc
    if logs_ok <= 0 and secoes <= 0:
        raise HTTPException(409, "Aguarde o download ter dados antes de ver no painel.")
    set_active_db(path)
    job = JOBS.status()
    downloading_here = (
        job.get("election_id") == election["id"]
        and job.get("status") in ("running", "starting", "stopping")
    )
    # Enquanto o importer escreve neste SQLite, não rode syncs auxiliares
    # (presidente/modelos/nomes) — evita lock e trava na seleção.
    if downloading_here:
        return {
            "ok": True,
            "election": election,
            "db_path": str(path),
            "db_exists": True,
            "logs_ok": logs_ok,
            "secoes": secoes,
            "partial": True,
        }
    # Se ainda não há totais de Presidente e o banco veio de ZIP/odsele, importa o CSV.
    source = None
    year_meta = None
    turno_meta = None
    try:
        with connect(path) as conn:
            has_pres = int(
                conn.execute("SELECT COUNT(*) FROM votos_abr WHERE abr='br'").fetchone()[0] or 0
            )
            meta = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM meta")}
            source = meta.get("source") or ""
            year_meta = meta.get("eleicao_ano")
            turno_meta = meta.get("turno") or "1"
    except Exception:  # noqa: BLE001
        has_pres = 0
    if has_pres <= 0 and (
        (source or "").startswith("dados_abertos")
        or (year_meta and year_meta.isdigit() and int(year_meta) <= 2024)
    ):
        db_sync = Database(path)
        try:
            sync_presidente_from_munzona(
                db_sync,
                year=int(year_meta or election.get("year") or 2022),
                turno=int(turno_meta or election.get("turno") or 1),
            )
            clear_cache()
        except Exception:  # noqa: BLE001
            pass
        finally:
            db_sync.close()
    # Completa Modelos (PL/PT) cruzando CSV de votação por seção com modelo_urna dos logs.
    try:
        with connect(path) as conn:
            has_vs = int(conn.execute("SELECT COUNT(*) FROM votos_secao WHERE status='ok'").fetchone()[0] or 0)
            meta = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM meta")}
            source = meta.get("source") or source or ""
            year_meta = meta.get("eleicao_ano") or year_meta
            turno_meta = meta.get("turno") or turno_meta or "1"
            n_modelo = int(
                conn.execute(
                    "SELECT COUNT(*) FROM secoes WHERE modelo_urna LIKE 'UE%'"
                ).fetchone()[0]
                or 0
            )
    except Exception:  # noqa: BLE001
        has_vs = 0
        n_modelo = 0
    if (
        has_vs <= 0
        and n_modelo > 0
        and (
            (source or "").startswith("dados_abertos")
            or (year_meta and str(year_meta).isdigit() and int(year_meta) <= 2024)
        )
    ):
        from urna_tse.votos_csv import sync_votos_secao_from_csv

        db_sync = Database(path)
        try:
            sync_votos_secao_from_csv(
                db_sync,
                year=int(year_meta or election.get("year") or 2022),
                turno=int(turno_meta or election.get("turno") or 1),
            )
            clear_cache()
        except Exception:  # noqa: BLE001
            pass
        finally:
            db_sync.close()
    # Nomes de município faltando (import ZIP só traz código).
    try:
        with connect(path) as conn:
            missing_nm = int(
                conn.execute(
                    "SELECT COUNT(*) FROM secoes WHERE municipio_nm IS NULL OR TRIM(municipio_nm)=''"
                ).fetchone()[0]
                or 0
            )
            meta = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM meta")}
            year_meta = meta.get("eleicao_ano") or year_meta
    except Exception:  # noqa: BLE001
        missing_nm = 0
    if missing_nm > 0 and year_meta and str(year_meta).isdigit():
        from urna_tse.votos_csv import backfill_municipio_names_from_csv

        db_sync = Database(path)
        try:
            backfill_municipio_names_from_csv(
                db_sync,
                year=int(year_meta),
            )
            clear_cache()
        except Exception:  # noqa: BLE001
            pass
        finally:
            db_sync.close()
    return {
        "ok": True,
        "election": election,
        "db_path": str(path),
        "db_exists": True,
        "logs_ok": logs_ok,
        "secoes": secoes,
    }


class RemoveElectionBody(BaseModel):
    election_id: str
    remove_zips: bool = False


def _unlink_quiet(path: Path) -> bool:
    try:
        if path.exists():
            path.unlink()
            return True
    except OSError:
        return False
    return False


@app.post("/api/elections/remove")
def api_remove_election(body: RemoveElectionBody):
    try:
        election = get_election(body.election_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc

    job = JOBS.status()
    if (
        job.get("election_id") == election["id"]
        and job.get("status") in ("running", "starting", "stopping")
    ):
        raise HTTPException(409, "Não é possível remover enquanto o download está em andamento.")

    path = DATA / election["db_filename"]
    was_active = db_path().resolve() == path.resolve() if path.exists() else (
        db_path().name == election["db_filename"]
    )

    removed: list[str] = []
    for candidate in (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    ):
        if _unlink_quiet(candidate):
            removed.append(candidate.name)

    if body.remove_zips and election.get("mode") == "bulk_zip":
        cache = DATA / "cache_zips"
        year = election.get("year")
        turno = election.get("turno")
        if cache.is_dir() and year and turno:
            pattern = f"bu_imgbu_logjez_rdv_vscmr_{year}_{turno}t_*.zip"
            for z in cache.glob(pattern):
                if _unlink_quiet(z):
                    removed.append(z.name)

    if was_active:
        # Volta para outra eleição com dados, senão o default 2026.
        fallback = DEFAULT_DB
        for e in list_elections():
            other = DATA / e["db_filename"]
            if other.resolve() == path.resolve():
                continue
            if other.exists() and other.stat().st_size > 0:
                fallback = other
                break
        set_active_db(fallback)
    else:
        clear_cache()

    return {
        "ok": True,
        "election_id": election["id"],
        "removed": removed,
        "active_db": db_path().name,
    }


@app.get("/api/downloads/status")
def api_download_status():
    return JOBS.status()


@app.post("/api/downloads/start")
def api_download_start(body: StartDownloadBody):
    try:
        election = get_election(body.election_id)
        if body.switch_db:
            set_active_db(DATA / election["db_filename"])
        status = JOBS.start(
            body.election_id,
            ufs=body.ufs,
            store_blob=body.store_blob,
            workers=body.workers,
            min_interval=body.min_interval,
        )
        return {"ok": True, "job": status, "election": election}
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/downloads/stop")
def api_download_stop():
    try:
        return {"ok": True, "job": JOBS.stop()}
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/ufs")
def api_ufs(modelo: Optional[str] = Query(None)):
    rows = _ufs(modelo)
    payload: dict = {"ufs": rows}
    if rows and rows[0].get("filtro_modelo"):
        payload["filtro_modelo"] = rows[0]["filtro_modelo"]
    elif modelo and not (modelo or "").strip().startswith("("):
        payload["filtro_modelo"] = (modelo or "").strip()
    return payload


@app.get("/api/aux-status")
def api_aux():
    return {"items": _aux()}


@app.get("/api/apuracao")
def api_apuracao():
    return _apuracao()


@app.get("/api/tamanhos")
def api_tamanhos():
    return _tamanhos()


@app.get("/api/modelos")
def api_modelos():
    return _modelos()


@app.get("/api/municipios")
def api_municipios(
    uf: Optional[str] = Query(None),
    limit: int = Query(40, ge=1, le=200),
    modelo: Optional[str] = Query(None),
):
    rows = _municipios(uf, limit, modelo)
    payload: dict = {"municipios": rows}
    if rows and rows[0].get("filtro_modelo"):
        payload["filtro_modelo"] = rows[0]["filtro_modelo"]
    elif modelo and not (modelo or "").strip().startswith("("):
        payload["filtro_modelo"] = (modelo or "").strip()
    return payload


@app.get("/api/presidente")
def api_presidente(
    uf: Optional[str] = Query(None),
    modelo: Optional[str] = Query(None),
):
    if modelo:
        db = Database(db_path())
        try:
            filtered = load_presidente_by_modelo(db, modelo)
            return {
                "source": "votos_secao",
                "synced_at": db.get_meta("votos_secao_bu_synced_at"),
                "filtro_modelo": filtered["modelo"],
                "n_secoes": filtered["n_secoes"],
                "n_ufs": filtered.get("n_ufs") or len(filtered.get("ufs") or []),
                "votos_validos": filtered["votos_validos"],
                "brasil": filtered,
                "ufs": filtered.get("ufs") or [],
            }
        finally:
            db.close()
    if uf:
        db = Database(db_path())
        try:
            data = load_presidente_from_db(db, uf.lower())
            return data or {"error": "sem dados no SQLite — rode sync_votos_presidente.py", "abr": uf.lower()}
        finally:
            db.close()
    return _presidente_payload()


@app.post("/api/presidente/sync")
def api_presidente_sync():
    db = Database(db_path())
    try:
        year_meta = db.get_meta("eleicao_ano")
        turno_meta = db.get_meta("turno") or "1"
        source = db.get_meta("source") or ""
        # Bancos importados via ZIP (2022+) usam CSV odsele — API Resultados histórica some.
        if source.startswith("dados_abertos") or (year_meta and year_meta.isdigit() and int(year_meta) <= 2024):
            year = int(year_meta or "2022")
            turno = int(turno_meta or 1)
            stats = sync_presidente_from_munzona(db, year=year, turno=turno)
        else:
            stats = sync_presidente_to_db(db)
        clear_cache()
        return {"ok": True, **stats, "synced_at": db.get_meta("votos_presidente_synced_at")}
    finally:
        db.close()
