"""Importa totais de Presidente a partir dos CSV odsele (votacao_candidato_munzona)."""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from .db import Database

log = logging.getLogger(__name__)

MUNZONA_URL = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/"
    "votacao_candidato_munzona_{year}.zip"
)

DETALHE_MUNZONA_URL = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_munzona/"
    "detalhe_votacao_munzona_{year}.zip"
)

VOTACAO_SECAO_URL = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_secao/"
    "votacao_secao_{year}_BR.zip"
)

# Códigos especiais de votável (não entram em votos nominais válidos).
_SPECIAL_VOTAVEL = {"95", "96", "97", "98"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _download_zip(url: str, path: Path, timeout: float = 600.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        return path
    log.info("Baixando %s", url)
    with requests.get(
        url,
        stream=True,
        timeout=timeout,
        headers={"User-Agent": "UrnaTSE-Downloader/1.0 (+pesquisa; dados publicos)"},
    ) as resp:
        resp.raise_for_status()
        tmp = path.with_suffix(".partial")
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(1024 * 1024):
                if chunk:
                    fh.write(chunk)
        tmp.replace(path)
    return path


def ensure_munzona_zip(year: int, cache_dir: Path, timeout: float = 600.0) -> Path:
    return _download_zip(MUNZONA_URL.format(year=year), cache_dir / f"votacao_candidato_munzona_{year}.zip", timeout)


def ensure_detalhe_munzona_zip(year: int, cache_dir: Path, timeout: float = 600.0) -> Path:
    return _download_zip(
        DETALHE_MUNZONA_URL.format(year=year),
        cache_dir / f"detalhe_votacao_munzona_{year}.zip",
        timeout,
    )


def _gi(row: dict[str, str], *keys: str) -> int:
    for key in keys:
        if key not in row:
            continue
        raw = str(row.get(key) or "0").replace(".", "").replace(",", "").strip()
        if raw:
            try:
                return int(raw)
            except ValueError:
                continue
    return 0


def load_detalhe_presidente_by_uf(
    year: int,
    turno: int,
    *,
    zip_path: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
) -> dict[str, dict[str, int]]:
    """Brancos/nulos/aptos/comparecimento por UF a partir de detalhe_votacao_munzona."""
    cache_dir = cache_dir or Path("data/cache_zips")
    zpath = Path(zip_path) if zip_path else ensure_detalhe_munzona_zip(year, cache_dir)
    with zipfile.ZipFile(zpath) as zf:
        member = next(
            (
                n
                for n in zf.namelist()
                if n.endswith(f"detalhe_votacao_munzona_{year}_BRASIL.csv")
                or n.endswith(f"detalhe_votacao_munzona_{year}_BR.csv")
            ),
            None,
        )
        if not member:
            members = [
                n
                for n in zf.namelist()
                if n.startswith(f"detalhe_votacao_munzona_{year}_") and n.endswith(".csv")
            ]
            texts = [_decode_csv_bytes(zf.read(m)) for m in members]
            text = texts[0]
            for part in texts[1:]:
                text += "\n" + "\n".join(part.splitlines()[1:])
        else:
            text = _decode_csv_bytes(zf.read(member))

    by_uf: dict[str, dict[str, int]] = {}
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    for row in reader:
        if str(row.get("NR_TURNO") or "") != str(turno):
            continue
        cargo = (row.get("DS_CARGO") or "").upper()
        cd = str(row.get("CD_CARGO") or "").strip()
        if cd != "1" and not cargo.startswith("PRESIDENTE"):
            continue
        uf = (row.get("SG_UF") or "").lower()
        if not uf:
            continue
        bucket = by_uf.setdefault(
            uf,
            {
                "brancos": 0,
                "nulos": 0,
                "validos": 0,
                "votos_total": 0,
                "aptos": 0,
                "comparecimento": 0,
                "abstencoes": 0,
            },
        )
        bucket["brancos"] += _gi(row, "QT_VOTOS_BRANCOS")
        bucket["nulos"] += _gi(row, "QT_VOTOS_NULOS", "QT_TOTAL_VOTOS_NULOS")
        bucket["validos"] += _gi(row, "QT_VOTOS_NOMINAIS_VALIDOS", "QT_TOTAL_VOTOS_VALIDOS")
        bucket["votos_total"] += _gi(row, "QT_VOTOS", "QT_COMPARECIMENTO")
        bucket["aptos"] += _gi(row, "QT_APTOS")
        bucket["comparecimento"] += _gi(row, "QT_COMPARECIMENTO")
        bucket["abstencoes"] += _gi(row, "QT_ABSTENCOES")
    return by_uf


def _decode_csv_bytes(raw: bytes) -> str:
    for enc in ("latin-1", "cp1252", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _agg_from_rows(rows: list[dict[str, str]], turno: int) -> dict[str, dict[str, Any]]:
    """Retorna abr -> {candidatos: {num: meta}, validos: int}."""
    by_abr: dict[str, dict[str, Any]] = {}
    for r in rows:
        if str(r.get("NR_TURNO") or "") != str(turno):
            continue
        cargo = (r.get("DS_CARGO") or "").upper()
        if not cargo.startswith("PRESIDENTE"):
            continue
        uf = (r.get("SG_UF") or "").lower()
        if not uf:
            continue
        num = str(r.get("NR_CANDIDATO") or "").strip()
        if not num or num in _SPECIAL_VOTAVEL:
            continue
        votos = int(
            str(r.get("QT_VOTOS_NOMINAIS_VALIDOS") or r.get("QT_VOTOS_NOMINAIS") or "0")
            .replace(".", "")
            .replace(",", "")
            or 0
        )
        bucket = by_abr.setdefault(
            uf,
            {
                "candidatos": {},
                "validos": 0,
                "brancos": 0,
                "nulos": 0,
                "votos_total": 0,
                "aptos": 0,
                "abstencoes": 0,
            },
        )
        cand = bucket["candidatos"].setdefault(
            num,
            {
                "numero": num,
                "nome": r.get("NM_URNA_CANDIDATO") or r.get("NM_CANDIDATO") or num,
                "nome_completo": r.get("NM_CANDIDATO") or "",
                "partido": r.get("SG_PARTIDO") or "",
                "votos": 0,
                "eleito": None,
                "situacao": r.get("DS_SIT_TOT_TURNO") or "",
            },
        )
        cand["votos"] += votos
        bucket["validos"] += votos
    return by_abr


def _parsed_from_bucket(abr: str, bucket: dict[str, Any], *, year: int, turno: int) -> dict[str, Any]:
    candidatos = sorted(bucket["candidatos"].values(), key=lambda c: (-c["votos"], c["numero"]))
    validos = int(bucket["validos"] or 0)
    brancos = int(bucket.get("brancos") or 0)
    nulos = int(bucket.get("nulos") or 0)
    aptos = int(bucket.get("aptos") or 0)
    abstencoes = int(bucket.get("abstencoes") or 0)
    votos_total = int(bucket.get("votos_total") or 0) or (validos + brancos + nulos)
    for i, c in enumerate(candidatos, 1):
        c["seq"] = i
        pct = (c["votos"] / validos * 100.0) if validos else 0.0
        c["pct"] = round(pct, 2)
        c["pct_str"] = f"{pct:.2f}".replace(".", ",")
    return {
        "abr": abr,
        "eleicao": str(year),
        "turno": str(turno),
        "atualizado_em": f"CSV odsele {year} turno {turno}",
        "secoes_totalizadas_pct": "100,00",
        "secoes_totalizadas": None,
        "secoes_total": None,
        "eleitorado_aptos": aptos,
        "votos_total": votos_total,
        "votos_validos": validos,
        "votos_brancos": brancos,
        "votos_nulos": nulos,
        "abstencoes": abstencoes,
        "candidatos": candidatos,
        "lider": candidatos[0] if candidatos else None,
    }


def sync_presidente_from_munzona(
    db: Database,
    *,
    year: int,
    turno: int = 1,
    zip_path: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Preenche votos_abr / votos_candidatos a partir do CSV oficial por mun/zona."""
    cache_dir = cache_dir or (db.path.parent / "cache_zips")
    zpath = Path(zip_path) if zip_path else ensure_munzona_zip(year, cache_dir)
    member = f"votacao_candidato_munzona_{year}_BR.csv"
    with zipfile.ZipFile(zpath) as zf:
        if member not in zf.namelist():
            # fallback: concatenar UFs
            members = [
                n
                for n in zf.namelist()
                if n.startswith(f"votacao_candidato_munzona_{year}_")
                and n.endswith(".csv")
                and not n.endswith("_BRASIL.csv")
                and not n.endswith("_BR.csv")
            ]
            text_parts = [_decode_csv_bytes(zf.read(m)) for m in members]
            # reuse header from first
            text = text_parts[0]
            for part in text_parts[1:]:
                lines = part.splitlines()
                text += "\n" + "\n".join(lines[1:])
        else:
            text = _decode_csv_bytes(zf.read(member))

    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    rows = list(reader)
    by_uf = _agg_from_rows(rows, turno)
    if not by_uf:
        raise RuntimeError(f"Nenhuma linha de Presidente turno {turno} em {zpath.name}")

    # Brancos/nulos/aptos vêm do detalhe_votacao_munzona (não estão no CSV de candidatos).
    detalhe = load_detalhe_presidente_by_uf(year, turno, cache_dir=cache_dir)
    for uf, extra in detalhe.items():
        bucket = by_uf.setdefault(
            uf,
            {
                "candidatos": {},
                "validos": 0,
                "brancos": 0,
                "nulos": 0,
                "votos_total": 0,
                "aptos": 0,
                "abstencoes": 0,
            },
        )
        bucket["brancos"] = int(extra.get("brancos") or 0)
        bucket["nulos"] = int(extra.get("nulos") or 0)
        bucket["votos_total"] = int(extra.get("votos_total") or 0)
        bucket["aptos"] = int(extra.get("aptos") or 0)
        bucket["abstencoes"] = int(extra.get("abstencoes") or 0)
        # Preferir válidos do detalhe quando disponível (bate com total oficial).
        if extra.get("validos"):
            bucket["validos"] = int(extra["validos"])

    # Totais Brasil = soma das UFs
    br_bucket: dict[str, Any] = {
        "candidatos": {},
        "validos": 0,
        "brancos": 0,
        "nulos": 0,
        "votos_total": 0,
        "aptos": 0,
        "abstencoes": 0,
    }
    for uf_bucket in by_uf.values():
        br_bucket["validos"] += int(uf_bucket.get("validos") or 0)
        br_bucket["brancos"] += int(uf_bucket.get("brancos") or 0)
        br_bucket["nulos"] += int(uf_bucket.get("nulos") or 0)
        br_bucket["votos_total"] += int(uf_bucket.get("votos_total") or 0)
        br_bucket["aptos"] += int(uf_bucket.get("aptos") or 0)
        br_bucket["abstencoes"] += int(uf_bucket.get("abstencoes") or 0)
        for num, cand in uf_bucket["candidatos"].items():
            dest = br_bucket["candidatos"].setdefault(
                num,
                {
                    "numero": cand["numero"],
                    "nome": cand["nome"],
                    "nome_completo": cand["nome_completo"],
                    "partido": cand["partido"],
                    "votos": 0,
                    "eleito": cand.get("eleito"),
                    "situacao": cand.get("situacao") or "",
                },
            )
            dest["votos"] += cand["votos"]

    now = utc_now()
    written = 0
    for abr, bucket in [("br", br_bucket), *sorted(by_uf.items())]:
        parsed = _parsed_from_bucket(abr, bucket, year=year, turno=turno)
        db.upsert_votos_presidente(parsed, raw_json=None, downloaded_at=now, cargo="1")
        written += 1
    db.set_meta("votos_presidente_synced_at", now)
    db.set_meta("votos_presidente_source", f"odsele_munzona+detalhe_{year}_t{turno}")
    db.commit()
    return {
        "ok": written,
        "year": year,
        "turno": turno,
        "votos_validos_br": int(br_bucket["validos"]),
        "votos_brancos_br": int(br_bucket["brancos"]),
        "votos_nulos_br": int(br_bucket["nulos"]),
        "candidatos_br": len(br_bucket["candidatos"]),
        "zip": str(zpath),
    }


def ensure_votacao_secao_zip(year: int, cache_dir: Path, timeout: float = 600.0) -> Path:
    return _download_zip(
        VOTACAO_SECAO_URL.format(year=year),
        cache_dir / f"votacao_secao_{year}_BR.zip",
        timeout,
    )


def _pad(value: Any, width: int) -> str:
    return str(value).strip().zfill(width)


def sync_votos_secao_from_csv(
    db: Database,
    *,
    year: int,
    turno: int = 1,
    zip_path: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
    only_known_candidates: bool = True,
) -> dict[str, Any]:
    """Cruza logs (modelo_urna) com votação por seção do Dados Abertos.

    Preenche votos_secao / votos_secao_cand para as seções já presentes no SQLite,
    habilitando a aba Modelos (votos + % PL/PT).
    """
    cache_dir = cache_dir or (db.path.parent / "cache_zips")
    zpath = Path(zip_path) if zip_path else ensure_votacao_secao_zip(year, cache_dir)

    known: set[str] = set()
    if only_known_candidates:
        known = {
            str(r["numero"])
            for r in db.conn.execute("SELECT numero FROM votos_candidatos WHERE abr='br'")
        }
        # fallback clássico 2022
        if not known:
            known = {"12", "13", "14", "15", "16", "21", "22", "27", "30", "44", "80"}

    index: dict[str, dict[str, Any]] = {}
    for r in db.conn.execute(
        """
        SELECT id, uf, municipio_cd, zona, secao, modelo_urna
        FROM secoes
        WHERE modelo_urna IS NOT NULL AND modelo_urna LIKE 'UE%'
        """
    ):
        key = f"{r['uf'].lower()}|{_pad(r['municipio_cd'],5)}|{_pad(r['zona'],4)}|{_pad(r['secao'],4)}"
        index[key] = {
            "secao_id": int(r["id"]),
            "uf": r["uf"].lower(),
            "modelo": r["modelo_urna"],
            "votos": defaultdict(int),
        }

    if not index:
        raise RuntimeError("Nenhuma seção com modelo_urna no banco — baixe os logs antes.")

    member = f"votacao_secao_{year}_BR.csv"
    matched_rows = 0
    with zipfile.ZipFile(zpath) as zf:
        with zf.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="latin-1", newline="")
            reader = csv.DictReader(text, delimiter=";")
            for row in reader:
                if str(row.get("NR_TURNO") or "") != str(turno):
                    continue
                cargo = (row.get("DS_CARGO") or "").upper()
                if not cargo.startswith("PRESIDENTE"):
                    continue
                uf = (row.get("SG_UF") or "").lower()
                key = (
                    f"{uf}|{_pad(row.get('CD_MUNICIPIO'),5)}|"
                    f"{_pad(row.get('NR_ZONA'),4)}|{_pad(row.get('NR_SECAO'),4)}"
                )
                bucket = index.get(key)
                if not bucket:
                    continue
                num = str(row.get("NR_VOTAVEL") or "").strip()
                if not num or num in _SPECIAL_VOTAVEL:
                    continue
                if only_known_candidates and known and num not in known:
                    continue
                qtd = int(str(row.get("QT_VOTOS") or "0").replace(".", "") or 0)
                if qtd <= 0:
                    continue
                bucket["votos"][num] += qtd
                matched_rows += 1

    now = utc_now()
    written = 0
    empty = 0
    for bucket in index.values():
        votos = {k: int(v) for k, v in bucket["votos"].items() if v}
        if not votos:
            empty += 1
            continue
        db.upsert_votos_secao(
            bucket["secao_id"],
            modelo_urna=bucket["modelo"],
            uf=bucket["uf"],
            votos=votos,
            status="ok",
            error=None,
            downloaded_at=now,
        )
        written += 1
        if written % 2000 == 0:
            db.commit()
            log.info("votos_secao progresso %s", written)

    db.set_meta("votos_secao_bu_synced_at", now)
    db.set_meta("votos_secao_source", f"odsele_votacao_secao_{year}_t{turno}")
    db.commit()
    return {
        "ok": written,
        "empty": empty,
        "secoes_com_modelo": len(index),
        "csv_rows_matched": matched_rows,
        "year": year,
        "turno": turno,
        "zip": str(zpath),
    }


def backfill_municipio_names_from_csv(
    db: Database,
    *,
    year: int,
    zip_path: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Preenche secoes.municipio_nm a partir do CSV votacao_secao (NM_MUNICIPIO)."""
    cache_dir = cache_dir or (db.path.parent / "cache_zips")
    zpath = Path(zip_path) if zip_path else ensure_votacao_secao_zip(year, cache_dir)
    member = f"votacao_secao_{year}_BR.csv"

    needed = {
        f"{r['uf'].lower()}|{_pad(r['municipio_cd'], 5)}"
        for r in db.conn.execute(
            """
            SELECT DISTINCT uf, municipio_cd FROM secoes
            WHERE municipio_nm IS NULL OR TRIM(municipio_nm) = ''
            """
        )
    }
    if not needed:
        return {"updated": 0, "names": 0, "zip": str(zpath)}

    names: dict[str, str] = {}
    with zipfile.ZipFile(zpath) as zf:
        with zf.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="latin-1", newline="")
            reader = csv.DictReader(text, delimiter=";")
            for row in reader:
                uf = (row.get("SG_UF") or "").lower()
                key = f"{uf}|{_pad(row.get('CD_MUNICIPIO'), 5)}"
                if key not in needed or key in names:
                    continue
                nm = (row.get("NM_MUNICIPIO") or "").strip()
                if nm:
                    names[key] = nm
                if len(names) >= len(needed):
                    break

    updated = 0
    for key, nm in names.items():
        uf, mun = key.split("|", 1)
        cur = db.conn.execute(
            """
            UPDATE secoes
            SET municipio_nm = ?
            WHERE uf = ? AND municipio_cd = ?
              AND (municipio_nm IS NULL OR TRIM(municipio_nm) = '')
            """,
            (nm, uf, mun),
        )
        updated += cur.rowcount or 0
    db.commit()
    return {"updated": updated, "names": len(names), "needed": len(needed), "zip": str(zpath)}
