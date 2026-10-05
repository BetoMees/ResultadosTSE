"""Agregações somente-leitura sobre o SQLite dos logs da urna."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from urna_tse.elections import UF_NAMES


IBGE_UF = {
    "11": "ro",
    "12": "ac",
    "13": "am",
    "14": "rr",
    "15": "pa",
    "16": "ap",
    "17": "to",
    "21": "ma",
    "22": "pi",
    "23": "ce",
    "24": "rn",
    "25": "pb",
    "26": "pe",
    "27": "al",
    "28": "se",
    "29": "ba",
    "31": "mg",
    "32": "es",
    "33": "rj",
    "35": "sp",
    "41": "pr",
    "42": "sc",
    "43": "rs",
    "50": "ms",
    "51": "mt",
    "52": "go",
    "53": "df",
}


def uf_display_name(uf: str, stored: Optional[str] = None) -> str:
    """Nome do estado; ignora placeholder igual à sigla (comum no import ZIP)."""
    uf = (uf or "").lower()
    if stored:
        s = str(stored).strip()
        if s and s.lower() not in {uf, uf.upper()}:
            return s
    return UF_NAMES.get(uf) or (uf.upper() if uf else "—")


def connect(db_path: Path) -> sqlite3.Connection:
    path = Path(db_path).resolve()
    try:
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=60)
    except sqlite3.OperationalError:
        conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
    except sqlite3.OperationalError:
        pass
    return conn


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, params))


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else row[0]


def _normalize_modelo(modelo: Optional[str]) -> Optional[str]:
    """Modelo UE filtrável; fatias “(faltando)” / placeholders não aplicam filtro."""
    m = (modelo or "").strip()
    if not m or m.startswith("("):
        return None
    return m


def overview(conn: sqlite3.Connection) -> dict[str, Any]:
    meta = {r["key"]: r["value"] for r in _rows(conn, "SELECT key, value FROM meta")}
    logs_ok = int(_scalar(conn, "SELECT COUNT(*) FROM arquivos WHERE tipo='log' AND status='ok'") or 0)
    logs_pending = int(_scalar(conn, "SELECT COUNT(*) FROM arquivos WHERE tipo='log' AND status!='ok'") or 0)
    bytes_ok = int(_scalar(conn, "SELECT COALESCE(SUM(size_bytes),0) FROM arquivos WHERE tipo='log' AND status='ok'") or 0)
    avg_bytes = float(_scalar(conn, "SELECT COALESCE(AVG(size_bytes),0) FROM arquivos WHERE tipo='log' AND status='ok'") or 0)
    aux_ok = int(_scalar(conn, "SELECT COUNT(*) FROM aux WHERE http_status=200") or 0)
    return {
        "meta": meta,
        "ufs": int(_scalar(conn, "SELECT COUNT(*) FROM uf_config") or 0),
        "secoes": int(_scalar(conn, "SELECT COUNT(*) FROM secoes") or 0),
        "municipios": int(_scalar(conn, "SELECT COUNT(DISTINCT uf || '-' || municipio_cd) FROM secoes") or 0),
        "aux_ok": aux_ok,
        "aux_total": int(_scalar(conn, "SELECT COUNT(*) FROM aux") or 0),
        "cargas": int(_scalar(conn, "SELECT COUNT(*) FROM cargas") or 0),
        "logs_ok": logs_ok,
        "logs_pending": logs_pending,
        "logs_total": logs_ok + logs_pending,
        "bytes_ok": bytes_ok,
        "avg_log_bytes": avg_bytes,
        "db_path": str(Path(conn.execute("PRAGMA database_list").fetchone()["file"])),
    }


def ufs(conn: sqlite3.Connection, modelo: Optional[str] = None) -> list[dict[str, Any]]:
    modelo = _normalize_modelo(modelo)
    modelo_params: tuple = (modelo,) if modelo else ()
    modelo_secoes = " WHERE modelo_urna = ?" if modelo else ""
    modelo_join = " AND s.modelo_urna = ?" if modelo else ""

    configs = {
        r["uf"]: dict(r)
        for r in _rows(conn, "SELECT uf, nome, n_secoes, dg, hg FROM uf_config")
    }
    secoes = {
        r["uf"]: r["c"]
        for r in _rows(conn, f"SELECT uf, COUNT(*) c FROM secoes{modelo_secoes} GROUP BY uf", modelo_params)
    }
    municipios = {
        r["uf"]: r["c"]
        for r in _rows(
            conn,
            f"SELECT uf, COUNT(DISTINCT municipio_cd) c FROM secoes{modelo_secoes} GROUP BY uf",
            modelo_params,
        )
    }
    aux_ok = {
        r["uf"]: r["c"]
        for r in _rows(
            conn,
            f"""
            SELECT s.uf, COUNT(*) c
            FROM aux a JOIN secoes s ON s.id = a.secao_id
            WHERE a.http_status = 200{modelo_join}
            GROUP BY s.uf
            """,
            modelo_params,
        )
    }
    totalizada = {
        r["uf"]: r["c"]
        for r in _rows(
            conn,
            f"""
            SELECT s.uf, COUNT(*) c
            FROM aux a JOIN secoes s ON s.id = a.secao_id
            WHERE a.st = 'Totalizada'{modelo_join}
            GROUP BY s.uf
            """,
            modelo_params,
        )
    }
    logs_ok = {
        r["uf"]: r["c"]
        for r in _rows(
            conn,
            f"""
            SELECT s.uf, COUNT(*) c
            FROM arquivos ar
            JOIN secoes s ON s.id = ar.secao_id
            WHERE ar.tipo = 'log' AND ar.status = 'ok'{modelo_join}
            GROUP BY s.uf
            """,
            modelo_params,
        )
    }
    logs_bytes = {
        r["uf"]: r["b"]
        for r in _rows(
            conn,
            f"""
            SELECT s.uf, COALESCE(SUM(ar.size_bytes),0) b
            FROM arquivos ar
            JOIN secoes s ON s.id = ar.secao_id
            WHERE ar.tipo = 'log' AND ar.status = 'ok'{modelo_join}
            GROUP BY s.uf
            """,
            modelo_params,
        )
    }
    # Com filtro de modelo, só UFs que têm seções daquele modelo.
    keys = sorted(
        (set(secoes) if modelo else (set(configs) | set(secoes))),
        key=lambda u: secoes.get(u, 0),
        reverse=True,
    )
    out = []
    for uf in keys:
        n = int(secoes.get(uf, 0))
        cfg = configs.get(uf, {})
        lo = int(logs_ok.get(uf, 0))
        ao = int(aux_ok.get(uf, 0))
        row = {
            "uf": uf,
            "nome": uf_display_name(uf, cfg.get("nome")),
            "ibge": next((k for k, v in IBGE_UF.items() if v == uf), None),
            "n_secoes": int(cfg.get("n_secoes") or n) if not modelo else n,
            "secoes": n,
            "municipios": int(municipios.get(uf, 0)),
            "aux_ok": ao,
            "totalizada": int(totalizada.get(uf, 0)),
            "logs_ok": lo,
            "bytes_ok": int(logs_bytes.get(uf, 0)),
            "cobertura_aux": (ao / n) if n else 0,
            "cobertura_log": (lo / n) if n else 0,
        }
        if modelo:
            row["filtro_modelo"] = modelo
        out.append(row)
    return out


def aux_status(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = _rows(
        conn,
        """
        SELECT COALESCE(NULLIF(st, ''), '(sem status)') AS st, COUNT(*) AS c
        FROM aux
        GROUP BY COALESCE(NULLIF(st, ''), '(sem status)')
        ORDER BY c DESC
        """,
    )
    return [{"status": r["st"], "count": r["c"]} for r in rows]


def apuracao(conn: sqlite3.Connection) -> dict[str, Any]:
    por_data = [
        {"data": r["data_apuracao"] or "(sem data)", "count": r["c"]}
        for r in _rows(
            conn,
            """
            SELECT data_apuracao, COUNT(*) c
            FROM secoes
            GROUP BY data_apuracao
            ORDER BY CASE WHEN data_apuracao IS NULL THEN 1 ELSE 0 END, data_apuracao
            """,
        )
    ]
    horas: dict[str, int] = defaultdict(int)
    for r in _rows(conn, "SELECT hora_apuracao, COUNT(*) c FROM secoes WHERE hora_apuracao IS NOT NULL GROUP BY hora_apuracao"):
        hora = (r["hora_apuracao"] or "00:00:00")[:2]
        horas[hora] += r["c"]
    por_hora = [{"hora": f"{h:02d}h", "count": horas.get(f"{h:02d}", 0)} for h in range(24)]
    return {"por_data": por_data, "por_hora": por_hora}


def tamanhos(conn: sqlite3.Connection) -> dict[str, Any]:
    stats = conn.execute(
        """
        SELECT COUNT(*) n,
               COALESCE(MIN(size_bytes),0) mn,
               COALESCE(MAX(size_bytes),0) mx,
               COALESCE(AVG(size_bytes),0) av
        FROM arquivos
        WHERE tipo = 'log' AND status = 'ok' AND size_bytes IS NOT NULL
        """
    ).fetchone()
    n = int(stats["n"] or 0)
    if not n:
        return {"n": 0, "min": 0, "max": 0, "avg": 0, "p50": 0, "histogram": []}
    p50 = int(
        _scalar(
            conn,
            """
            SELECT size_bytes FROM arquivos
            WHERE tipo = 'log' AND status = 'ok' AND size_bytes IS NOT NULL
            ORDER BY size_bytes
            LIMIT 1 OFFSET ?
            """,
            (n // 2,),
        )
        or 0
    )
    hist_rows = _rows(
        conn,
        """
        SELECT (size_bytes / 25000) * 25000 AS bucket, COUNT(*) c
        FROM arquivos
        WHERE tipo = 'log' AND status = 'ok' AND size_bytes IS NOT NULL
        GROUP BY bucket
        ORDER BY bucket
        """,
    )
    histogram = [{"from": int(r["bucket"]), "to": int(r["bucket"]) + 25000, "count": r["c"]} for r in hist_rows]
    return {
        "n": n,
        "min": int(stats["mn"]),
        "max": int(stats["mx"]),
        "avg": float(stats["av"]),
        "p50": p50,
        "histogram": histogram,
    }


def municipios(
    conn: sqlite3.Connection,
    uf: Optional[str] = None,
    limit: int = 40,
    modelo: Optional[str] = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    modelo = _normalize_modelo(modelo)
    if uf:
        params: tuple = (uf.lower(),)
        modelo_sql = ""
        if modelo:
            modelo_sql = " AND s.modelo_urna = ?"
            params = (uf.lower(), modelo)
        sql = f"""
            SELECT s.uf, s.municipio_cd, s.municipio_nm,
                   COUNT(*) AS secoes,
                   SUM(CASE WHEN a.http_status = 200 THEN 1 ELSE 0 END) AS aux_ok,
                   SUM(CASE WHEN ar.status = 'ok' THEN 1 ELSE 0 END) AS logs_ok
            FROM secoes s
            LEFT JOIN aux a ON a.secao_id = s.id
            LEFT JOIN arquivos ar ON ar.secao_id = s.id AND ar.tipo = 'log'
            WHERE s.uf = ?{modelo_sql}
            GROUP BY s.uf, s.municipio_cd, s.municipio_nm
            ORDER BY secoes DESC
            LIMIT {limit}
        """
    else:
        params = ()
        modelo_sql = ""
        if modelo:
            modelo_sql = " WHERE modelo_urna = ?"
            params = (modelo,)
        sql = f"""
            SELECT uf, municipio_cd, municipio_nm, COUNT(*) AS secoes,
                   0 AS aux_ok, 0 AS logs_ok
            FROM secoes
            {modelo_sql}
            GROUP BY uf, municipio_cd, municipio_nm
            ORDER BY secoes DESC
            LIMIT {limit}
        """
    return [
        {
            "uf": r["uf"],
            "municipio_cd": r["municipio_cd"],
            "municipio_nm": r["municipio_nm"],
            "secoes": r["secoes"],
            "aux_ok": r["aux_ok"] or 0,
            "logs_ok": r["logs_ok"] or 0,
            **({"filtro_modelo": modelo} if modelo else {}),
        }
        for r in _rows(conn, sql, params)
    ]


def _pl_pt_numeros(conn: sqlite3.Connection) -> tuple[str, str]:
    """Resolve números de urna PL/PT em votos_candidatos (abr=br). Fallback 22/13."""
    by_partido = {
        (r["partido"] or "").strip().upper(): str(r["numero"])
        for r in _rows(
            conn,
            "SELECT numero, partido FROM votos_candidatos WHERE abr='br'",
        )
    }
    return by_partido.get("PL", "22"), by_partido.get("PT", "13")


def modelos(conn: sqlite3.Connection) -> dict[str, Any]:
    """Votos válidos de Presidente por modelo de urna (BU) + fatia faltante.

    Segmentos = SUM(votos_secao.votos_validos) por modelo_urna.
    Faltando = max(0, votos_validos oficiais BR em votos_abr − soma já atribuída).
    Se o oficial for menor que a soma (amostra/quirks), faltando=0.

    Sem votos_secao (ex.: import só de logs), cai no inventário de seções/logs
    por modelo_urna para o painel acompanhar a eleição ativa.
    """
    MISSING_LABEL = "(faltando)"

    br_row = conn.execute(
        "SELECT votos_validos FROM votos_abr WHERE abr = 'br'"
    ).fetchone()
    votos_validos_br = int(br_row["votos_validos"] or 0) if br_row else 0

    num_pl, num_pt = _pl_pt_numeros(conn)
    bu_rows = _rows(
        conn,
        """
        SELECT modelo_urna AS modelo,
               COUNT(*) AS n_secoes_bu,
               COALESCE(SUM(votos_validos), 0) AS votos_validos
        FROM votos_secao
        WHERE status = 'ok'
          AND modelo_urna IS NOT NULL
          AND modelo_urna != ''
          AND modelo_urna NOT LIKE '(%'
        GROUP BY modelo_urna
        ORDER BY votos_validos DESC, modelo
        """,
    )

    total_com_log = int(
        conn.execute(
            "SELECT COUNT(*) FROM arquivos WHERE tipo = 'log' AND status = 'ok'"
        ).fetchone()[0]
        or 0
    )

    # Fallback: só logs / seções (sem BU parseado nesta eleição).
    if not bu_rows:
        inv_rows = _rows(
            conn,
            """
            SELECT COALESCE(NULLIF(modelo_urna, ''), '(não identificado)') AS modelo,
                   COUNT(*) AS n_secoes
            FROM secoes
            WHERE modelo_urna IS NOT NULL AND modelo_urna != '' AND modelo_urna NOT LIKE '(%'
            GROUP BY 1
            ORDER BY n_secoes DESC, modelo
            """,
        )
        if not inv_rows:
            inv_rows = _rows(
                conn,
                """
                SELECT COALESCE(NULLIF(modelo_urna, ''), '(não identificado)') AS modelo,
                       COUNT(*) AS n_secoes
                FROM arquivos
                WHERE tipo = 'log' AND status = 'ok'
                  AND modelo_urna IS NOT NULL AND modelo_urna != '' AND modelo_urna NOT LIKE '(%'
                GROUP BY 1
                ORDER BY n_secoes DESC, modelo
                """,
            )
        total_inv = sum(int(r["n_secoes"] or 0) for r in inv_rows) or 1
        items = [
            {
                "modelo": r["modelo"],
                "votos": int(r["n_secoes"] or 0),
                "count": int(r["n_secoes"] or 0),
                "pct": (int(r["n_secoes"] or 0) / total_inv) if total_inv else 0,
                "pct_pl": None,
                "pct_pt": None,
                "votos_pl": None,
                "votos_pt": None,
                "votos_validos": 0,
                "n_secoes_bu": 0,
                "n_secoes": int(r["n_secoes"] or 0),
                "filterable": True,
                "missing": False,
                "metric": "secoes",
                "numero_pl": num_pl,
                "numero_pt": num_pt,
            }
            for r in inv_rows
        ]
        return {
            "total_com_log": total_com_log,
            "votos_validos_br": votos_validos_br,
            "votos_atribuidos": 0,
            "votos_faltando": 0,
            "numero_pl": num_pl,
            "numero_pt": num_pt,
            "source": "inventario",
            "hint": (
                "Sem votos_secao nesta eleição: gráfico/tabela mostram seções com log "
                "por modelo_urna. PL/PT ficam vazios até sincronizar BUs."
            ),
            "items": items,
            "por_uf": [],
        }

    bu_votos: dict[str, dict[str, int]] = defaultdict(lambda: {"votos_pl": 0, "votos_pt": 0})
    for r in _rows(
        conn,
        """
        SELECT v.modelo_urna AS modelo, c.numero, COALESCE(SUM(c.votos), 0) AS votos
        FROM votos_secao_cand c
        JOIN votos_secao v ON v.secao_id = c.secao_id
        WHERE v.status = 'ok'
          AND v.modelo_urna IS NOT NULL AND v.modelo_urna != ''
          AND v.modelo_urna NOT LIKE '(%'
          AND c.numero IN (?, ?)
        GROUP BY v.modelo_urna, c.numero
        """,
        (num_pl, num_pt),
    ):
        key = "votos_pl" if str(r["numero"]) == num_pl else "votos_pt"
        bu_votos[r["modelo"]][key] = int(r["votos"] or 0)

    soma_atribuida = sum(int(r["votos_validos"] or 0) for r in bu_rows)
    faltando = max(0, votos_validos_br - soma_atribuida)
    denom = votos_validos_br if votos_validos_br > 0 else (soma_atribuida + faltando)

    items: list[dict[str, Any]] = []
    for r in bu_rows:
        modelo = r["modelo"]
        votos_validos = int(r["votos_validos"] or 0)
        n_secoes_bu = int(r["n_secoes_bu"] or 0)
        vv = bu_votos.get(modelo, {"votos_pl": 0, "votos_pt": 0})
        votos_pl = int(vv["votos_pl"])
        votos_pt = int(vv["votos_pt"])
        if votos_validos > 0:
            pct_pl = round(votos_pl / votos_validos * 100.0, 2)
            pct_pt = round(votos_pt / votos_validos * 100.0, 2)
        else:
            pct_pl = None
            pct_pt = None
        items.append(
            {
                "modelo": modelo,
                "votos": votos_validos,
                "count": n_secoes_bu,
                "pct": (votos_validos / denom) if denom else 0,
                "pct_pl": pct_pl,
                "pct_pt": pct_pt,
                "votos_pl": votos_pl,
                "votos_pt": votos_pt,
                "votos_validos": votos_validos,
                "n_secoes_bu": n_secoes_bu,
                "filterable": True,
                "missing": False,
                "metric": "votos",
                "numero_pl": num_pl,
                "numero_pt": num_pt,
            }
        )

    if faltando > 0 or votos_validos_br > 0:
        items.append(
            {
                "modelo": MISSING_LABEL,
                "votos": faltando,
                "count": 0,
                "pct": (faltando / denom) if denom else 0,
                "pct_pl": None,
                "pct_pt": None,
                "votos_pl": None,
                "votos_pt": None,
                "votos_validos": faltando,
                "n_secoes_bu": 0,
                "filterable": False,
                "missing": True,
                "metric": "votos",
                "numero_pl": num_pl,
                "numero_pt": num_pt,
            }
        )

    return {
        "total_com_log": total_com_log,
        "votos_validos_br": votos_validos_br,
        "votos_atribuidos": soma_atribuida,
        "votos_faltando": faltando,
        "numero_pl": num_pl,
        "numero_pt": num_pt,
        "source": "votos_secao",
        "hint": (
            "Faltando = max(0, votos_validos oficiais BR - soma dos votos_validos "
            "ja atribuidos a modelos via BU/votos_secao). Logs/BU incompletos "
            "entram nessa fatia. Se o oficial for menor que a soma, faltando=0."
        ),
        "items": items,
        "por_uf": [],
    }
