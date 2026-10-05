"""Catálogo de eleições suportadas pelo painel / downloaders."""

from __future__ import annotations

from typing import Any

from .api import DEFAULT_UFS

# URL oficial dos pacotes "Arquivos transmitidos para totalização" (Dados Abertos).
BULK_ZIP_URL = (
    "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{year}/arqurnatot/"
    "bu_imgbu_logjez_rdv_vscmr_{year}_{turno}t_{UF}.zip"
)

UF_NAMES = {
    "ac": "Acre",
    "al": "Alagoas",
    "am": "Amazonas",
    "ap": "Amapá",
    "ba": "Bahia",
    "ce": "Ceará",
    "df": "Distrito Federal",
    "es": "Espírito Santo",
    "go": "Goiás",
    "ma": "Maranhão",
    "mg": "Minas Gerais",
    "ms": "Mato Grosso do Sul",
    "mt": "Mato Grosso",
    "pa": "Pará",
    "pb": "Paraíba",
    "pe": "Pernambuco",
    "pi": "Piauí",
    "pr": "Paraná",
    "rj": "Rio de Janeiro",
    "rn": "Rio Grande do Norte",
    "ro": "Rondônia",
    "rr": "Roraima",
    "rs": "Rio Grande do Sul",
    "sc": "Santa Catarina",
    "se": "Sergipe",
    "sp": "São Paulo",
    "to": "Tocantins",
    "zz": "Exterior",
}

ELECTIONS: dict[str, dict[str, Any]] = {
    "2022-1t": {
        "id": "2022-1t",
        "year": 2022,
        "label": "2022 · 1º turno",
        "mode": "bulk_zip",
        "turno": 1,
        "pleito": "406",
        "db_filename": "urna_logs_2022_1t.sqlite3",
        "bulk_available": True,
        "note": (
            "Pacote completo por UF no Dados Abertos (CDN arqurnatot). "
            "Baixa um ZIP por estado e importa os .logjez."
        ),
    },
    "2022-2t": {
        "id": "2022-2t",
        "year": 2022,
        "label": "2022 · 2º turno",
        "mode": "bulk_zip",
        "turno": 2,
        "pleito": "407",
        "db_filename": "urna_logs_2022_2t.sqlite3",
        "bulk_available": True,
        "note": (
            "Pacote completo por UF no Dados Abertos (CDN arqurnatot, 2º turno). "
            "Baixa um ZIP por estado e importa os .logjez."
        ),
    },
    "2026": {
        "id": "2026",
        "year": 2026,
        "label": "2026 · 1º turno",
        "mode": "regional",
        "eleicao": "6257",
        "turno": 1,
        "db_filename": "urna_logs_6257.sqlite3",
        "bulk_available": False,
        "note": (
            "Ainda não existe o arquivo completo (ZIP por UF) no Dados Abertos. "
            "O download será feito por região/seção no portal Resultados."
        ),
    },
}

ORDER = ("2022-1t", "2022-2t", "2026")


def list_elections() -> list[dict[str, Any]]:
    return [dict(ELECTIONS[k]) for k in ORDER]


def get_election(election_id: str) -> dict[str, Any]:
    key = str(election_id).strip()
    # Compat: ids antigos do painel
    aliases = {"2022": "2022-1t", "2022-1": "2022-1t", "2022-2": "2022-2t"}
    key = aliases.get(key, key)
    if key not in ELECTIONS:
        raise KeyError(f"Eleição desconhecida: {election_id}")
    return dict(ELECTIONS[key])


def bulk_zip_url(year: int, turno: int, uf: str) -> str:
    return BULK_ZIP_URL.format(year=year, turno=turno, UF=uf.upper())


def default_ufs() -> list[str]:
    return [u for u in DEFAULT_UFS if u != "zz"]
