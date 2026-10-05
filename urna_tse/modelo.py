"""Extrai o modelo da urna a partir do conteúdo do log (.jez / logd.dat)."""

from __future__ import annotations

import re
from typing import Optional

_MODELO_RE = re.compile(
    r"Identifica[cç][aã]o do Modelo de Urna:\s*(UE\s*\d{4})",
    re.IGNORECASE,
)
_MODELO_RE2 = re.compile(r"\b(UE\s*20(?:09|10|11|13|15|20|22|24))\b", re.IGNORECASE)


def normalize_modelo(raw: str) -> str:
    return re.sub(r"\s+", "", raw.upper())


def parse_modelo_from_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = _MODELO_RE.search(text)
    if m:
        return normalize_modelo(m.group(1))
    for line in text.splitlines():
        if "modelo de urna" in line.lower():
            m2 = _MODELO_RE2.search(line)
            if m2:
                return normalize_modelo(m2.group(1))
    return None


def parse_modelo_from_jez(jez_bytes: Optional[bytes]) -> Optional[str]:
    if not jez_bytes:
        return None
    from .downloader import extract_logd_dat  # lazy: evita import circular

    return parse_modelo_from_text(extract_logd_dat(jez_bytes))
