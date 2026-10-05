#!/usr/bin/env python3
"""Extract URL/path patterns from TSE Resultados SPA bundle."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: python tools/analyze_spa.py <caminho-do-bundle.js>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"Arquivo não encontrado: {path}", file=sys.stderr)
        return 1
    s = path.read_text(encoding="utf-8", errors="ignore")
    print("len", len(s))

    needles = [
        "arquivo-urna",
        "logjez",
        "log-da-urna",
        "cdn.tse",
        "resultados.tse",
        "ele2026",
        "cd_pleito",
        "p000",
        "aux.json",
        "dados-de-urna",
        "ambiente",
        "ciclo",
        "hash",
        ".jez",
        "o00",
    ]
    for pat in needles:
        print(f"count[{pat}]={s.lower().count(pat.lower())}")

    # Quoted string literals that look relevant
    strs = set(re.findall(r"['\"]([^'\"]{6,160})['\"]", s))
    keys = [
        x
        for x in strs
        if any(
            k in x.lower()
            for k in (
                "urna",
                "log",
                "jez",
                "pleito",
                "aux",
                "hash",
                "secao",
                "zona",
                "municipio",
                "cdn.tse",
                "arquivo",
            )
        )
    ]
    print("interesting strings", len(keys))
    for x in sorted(keys)[:80]:
        print(x)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
