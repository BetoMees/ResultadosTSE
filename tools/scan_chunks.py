#!/usr/bin/env python3
"""Download TSE SPA JS chunks and search for urna/log URL patterns."""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

BASE = "https://resultados.tse.jus.br"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".cache" / "spa"
OUT.mkdir(parents=True, exist_ok=True)

NEEDLES = [
    "arquivo-urna",
    "logjez",
    "log-da-urna",
    "aux.json",
    "cd_pleito",
    "cdPleito",
    ".jez",
    "o00",
    "imgbu",
    "rdv",
    "boletim",
    "hash",
    "p000",
    "municipio",
    "secao",
    "zona",
]


def main() -> None:
    ngsw_path = OUT / "ngsw.json"
    urllib.request.urlretrieve(f"{BASE}/oficial/app/ngsw.json", ngsw_path)
    data = json.loads(ngsw_path.read_text(encoding="utf-8"))
    urls = []
    for ag in data.get("assetGroups", []):
        for u in ag.get("urls", []):
            if u.endswith(".js"):
                # ngsw uses /oficial/app/index.html/<file>
                file_part = u.split("/oficial/app/index.html/", 1)[-1]
                urls.append(file_part)

    print(f"js files: {len(urls)}")
    hits = []
    for i, rel in enumerate(urls, 1):
        local = OUT / rel.replace("/", "_")
        if not local.exists() or local.stat().st_size == 0:
            try:
                urllib.request.urlretrieve(f"{BASE}/oficial/app/{rel}", local)
            except Exception as exc:  # noqa: BLE001
                print("fail", rel, exc)
                continue
        text = local.read_text(encoding="utf-8", errors="ignore")
        found = [n for n in NEEDLES if n.lower() in text.lower()]
        if found:
            hits.append((rel, found, local))
            print(f"HIT {rel} -> {found}")

    print("---DETAILED---")
    for rel, found, local in hits:
        text = local.read_text(encoding="utf-8", errors="ignore")
        print(f"\n===== {rel} =====")
        for n in found:
            for m in re.finditer(rf".{{0,90}}{re.escape(n)}.{{0,140}}", text, flags=re.I):
                snippet = m.group(0).replace("\n", " ")
                print(n, ":", snippet[:260])


if __name__ == "__main__":
    main()
