"""Cliente, parsing e leitura/gravação dos resultados de Presidente no SQLite."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from .api import DEFAULT_UFS
from .db import Database

HOST = "https://resultados.tse.jus.br"
CICLO = "ele2026"
ELEICAO = "6257"
CARGO = "0001"


def _int(s: Any) -> int:
    try:
        return int(str(s).replace(".", "").replace(",", ""))
    except (TypeError, ValueError):
        return 0


def _float_br(s: Any) -> float:
    try:
        return float(str(s).replace(".", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def url_u(abr: str = "br") -> str:
    abr = abr.lower()
    return f"{HOST}/oficial/{CICLO}/{ELEICAO}/dados/{abr}/{abr}-c{CARGO}-e00{ELEICAO}-u.json"


def parse_presidente(data: dict[str, Any], abr: str) -> dict[str, Any]:
    s = data.get("s") or {}
    v = data.get("v") or {}
    e = data.get("e") or {}
    carg = next((c for c in data.get("carg") or [] if str(c.get("cd")) == "1"), None)
    candidatos: list[dict[str, Any]] = []
    if carg:
        for agr in carg.get("agr") or []:
            for par in agr.get("par") or []:
                partido = par.get("sg") or agr.get("com") or ""
                for cand in par.get("cand") or []:
                    candidatos.append(
                        {
                            "numero": str(cand.get("n") or ""),
                            "nome": cand.get("nmu") or cand.get("nm") or "",
                            "nome_completo": cand.get("nm") or "",
                            "partido": partido,
                            "votos": _int(cand.get("vap")),
                            "pct": _float_br(cand.get("pvap")),
                            "pct_str": cand.get("pvap"),
                            "seq": _int(cand.get("seq")),
                            "eleito": cand.get("e"),
                            "situacao": cand.get("st") or "",
                        }
                    )
    candidatos.sort(key=lambda c: (-c["votos"], c["numero"]))
    return {
        "abr": abr.lower(),
        "eleicao": data.get("ele"),
        "turno": data.get("t"),
        "atualizado_em": f"{data.get('dt') or ''} {data.get('ht') or ''}".strip(),
        "secoes_totalizadas_pct": s.get("pst"),
        "secoes_totalizadas": _int(s.get("st")),
        "secoes_total": _int(s.get("ts")),
        "eleitorado_aptos": _int(e.get("te") or e.get("a")),
        "votos_total": _int(v.get("tv")),
        "votos_validos": _int(v.get("vv") or v.get("vnom")),
        "votos_brancos": _int(v.get("vb")),
        "votos_nulos": _int(v.get("vn")),
        "abstencoes": _int(e.get("a")) if e.get("te") else 0,
        "candidatos": candidatos,
        "lider": candidatos[0] if candidatos else None,
    }


def fetch_raw(abr: str = "br", timeout: float = 45.0) -> Optional[dict[str, Any]]:
    r = requests.get(
        url_u(abr),
        timeout=timeout,
        headers={"User-Agent": "UrnaTSE-Downloader/1.0 (+pesquisa; dados publicos)"},
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def fetch_presidente(abr: str = "br", timeout: float = 45.0) -> Optional[dict[str, Any]]:
    raw = fetch_raw(abr, timeout=timeout)
    if raw is None:
        return None
    return parse_presidente(raw, abr)


def sync_presidente_to_db(
    db: Database,
    abrs: Optional[list[str]] = None,
    timeout: float = 45.0,
) -> dict[str, int]:
    """Baixa resultados de Presidente (BR + UFs) e grava no SQLite."""
    targets = abrs or (["br"] + list(DEFAULT_UFS))
    ok = 0
    fail = 0
    now = utc_now()
    for abr in targets:
        try:
            raw = fetch_raw(abr, timeout=timeout)
            if raw is None:
                fail += 1
                continue
            parsed = parse_presidente(raw, abr)
            db.upsert_votos_presidente(
                parsed,
                raw_json=json.dumps(raw, ensure_ascii=False),
                downloaded_at=now,
                cargo="1",
            )
            ok += 1
        except requests.RequestException:
            fail += 1
    db.commit()
    db.set_meta("votos_presidente_synced_at", now)
    return {"ok": ok, "fail": fail}


def load_presidente_from_db(db: Database, abr: str = "br") -> Optional[dict[str, Any]]:
    abr = abr.lower()
    row = db.conn.execute("SELECT * FROM votos_abr WHERE abr=?", (abr,)).fetchone()
    if not row:
        return None
    cands = list(
        db.conn.execute(
            """
            SELECT numero, nome, nome_completo, partido, votos, pct, pct_str, seq, eleito, situacao
            FROM votos_candidatos
            WHERE abr=?
            ORDER BY votos DESC, numero
            """,
            (abr,),
        )
    )
    candidatos = [
        {
            "numero": c["numero"],
            "nome": c["nome"],
            "nome_completo": c["nome_completo"],
            "partido": c["partido"],
            "votos": c["votos"] or 0,
            "pct": c["pct"] or 0,
            "pct_str": c["pct_str"],
            "seq": c["seq"] or 0,
            "eleito": c["eleito"],
            "situacao": c["situacao"] or "",
        }
        for c in cands
    ]
    return {
        "abr": abr,
        "eleicao": row["eleicao"],
        "turno": row["turno"],
        "atualizado_em": row["atualizado_em"],
        "secoes_totalizadas_pct": row["secoes_totalizadas_pct"],
        "secoes_totalizadas": row["secoes_totalizadas"] or 0,
        "secoes_total": row["secoes_total"] or 0,
        "eleitorado_aptos": row["eleitorado_aptos"] or 0,
        "votos_total": row["votos_total"] or 0,
        "votos_validos": row["votos_validos"] or 0,
        "votos_brancos": row["votos_brancos"] or 0,
        "votos_nulos": row["votos_nulos"] or 0,
        "abstencoes": row["abstencoes"] or 0,
        "downloaded_at": row["downloaded_at"],
        "candidatos": candidatos,
        "lider": candidatos[0] if candidatos else None,
    }


def load_presidente_ufs_from_db(db: Database) -> list[dict[str, Any]]:
    abrs = [
        r["abr"]
        for r in db.conn.execute(
            "SELECT abr FROM votos_abr WHERE abr != 'br' ORDER BY abr"
        )
    ]
    out = []
    for abr in abrs:
        row = load_presidente_from_db(db, abr)
        if row:
            out.append(row)
    return out


def _cand_name_index(db: Database) -> dict[str, dict[str, Any]]:
    return {
        r["numero"]: dict(r)
        for r in db.conn.execute(
            """
            SELECT numero, nome, nome_completo, partido, seq, eleito, situacao
            FROM votos_candidatos WHERE abr='br'
            """
        )
    }


def _candidatos_from_rows(
    rows: list[Any],
    votos_validos: int,
    names: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    candidatos: list[dict[str, Any]] = []
    for r in rows:
        meta = names.get(r["numero"], {})
        votos = int(r["votos"] or 0)
        pct = (votos / votos_validos * 100.0) if votos_validos else 0.0
        candidatos.append(
            {
                "numero": r["numero"],
                "nome": meta.get("nome") or r["numero"],
                "nome_completo": meta.get("nome_completo") or "",
                "partido": meta.get("partido") or "",
                "votos": votos,
                "pct": round(pct, 2),
                "pct_str": f"{pct:.2f}".replace(".", ","),
                "seq": meta.get("seq") or 0,
                "eleito": meta.get("eleito"),
                "situacao": meta.get("situacao") or "",
            }
        )
    return candidatos


def load_presidente_ufs_by_modelo(db: Database, modelo: str) -> list[dict[str, Any]]:
    """Agrega votos de Presidente por UF para um modelo_urna (votos_secao*)."""
    modelo = (modelo or "").strip()
    names = _cand_name_index(db)
    uf_totals = {
        str(r["uf"]).lower(): {
            "votos_validos": int(r["votos_validos"] or 0),
            "n_secoes": int(r["n_secoes"] or 0),
        }
        for r in db.conn.execute(
            """
            SELECT LOWER(uf) AS uf,
                   COALESCE(SUM(votos_validos), 0) AS votos_validos,
                   COUNT(*) AS n_secoes
            FROM votos_secao
            WHERE status='ok' AND modelo_urna=? AND uf IS NOT NULL AND uf != ''
            GROUP BY LOWER(uf)
            """,
            (modelo,),
        )
    }
    cand_by_uf: dict[str, list[Any]] = {}
    for r in db.conn.execute(
        """
        SELECT LOWER(v.uf) AS uf, c.numero, COALESCE(SUM(c.votos), 0) AS votos
        FROM votos_secao_cand c
        JOIN votos_secao v ON v.secao_id = c.secao_id
        WHERE v.status='ok' AND v.modelo_urna=? AND v.uf IS NOT NULL AND v.uf != ''
        GROUP BY LOWER(v.uf), c.numero
        ORDER BY uf, votos DESC, c.numero
        """,
        (modelo,),
    ):
        cand_by_uf.setdefault(str(r["uf"]).lower(), []).append(r)

    out: list[dict[str, Any]] = []
    for uf in sorted(uf_totals.keys()):
        vv = uf_totals[uf]["votos_validos"]
        candidatos = _candidatos_from_rows(cand_by_uf.get(uf, []), vv, names)
        out.append(
            {
                "uf": uf,
                "abr": uf,
                "n_secoes": uf_totals[uf]["n_secoes"],
                "votos_validos": vv,
                "lider": candidatos[0] if candidatos else None,
                "candidatos": candidatos[:3],
            }
        )
    return out


def load_presidente_by_modelo(db: Database, modelo: str) -> dict[str, Any]:
    """Agrega votos de Presidente por modelo_urna a partir dos BUs (votos_secao*)."""
    modelo = (modelo or "").strip()
    n_secoes = int(
        db.conn.execute(
            """
            SELECT COUNT(*) FROM votos_secao
            WHERE status='ok' AND modelo_urna=?
            """,
            (modelo,),
        ).fetchone()[0]
    )
    votos_validos = int(
        db.conn.execute(
            """
            SELECT COALESCE(SUM(votos_validos), 0) FROM votos_secao
            WHERE status='ok' AND modelo_urna=?
            """,
            (modelo,),
        ).fetchone()[0]
        or 0
    )
    rows = list(
        db.conn.execute(
            """
            SELECT c.numero, COALESCE(SUM(c.votos), 0) AS votos
            FROM votos_secao_cand c
            JOIN votos_secao v ON v.secao_id = c.secao_id
            WHERE v.status='ok' AND v.modelo_urna=?
            GROUP BY c.numero
            ORDER BY votos DESC, c.numero
            """,
            (modelo,),
        )
    )
    names = _cand_name_index(db)
    candidatos = _candidatos_from_rows(rows, votos_validos, names)
    ufs = load_presidente_ufs_by_modelo(db, modelo)
    return {
        "abr": "br",
        "modelo": modelo,
        "filtro_modelo": modelo,
        "n_secoes": n_secoes,
        "n_ufs": len(ufs),
        "votos_validos": votos_validos,
        "votos_total": votos_validos,
        "votos_brancos": 0,
        "votos_nulos": 0,
        "abstencoes": 0,
        "secoes_totalizadas": n_secoes,
        "secoes_total": n_secoes,
        "secoes_totalizadas_pct": "100" if n_secoes else "0",
        "atualizado_em": db.get_meta("votos_secao_bu_synced_at"),
        "source": "votos_secao",
        "candidatos": candidatos,
        "lider": candidatos[0] if candidatos else None,
        "ufs": ufs,
    }
