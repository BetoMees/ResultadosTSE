#!/usr/bin/env python3
"""Pretty-extract URL builders from dados-de-urna SPA chunks."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPA = ROOT / ".cache" / "spa"


def main() -> int:
    files = [Path(p) for p in sys.argv[1:]]
    if not files:
        files = sorted(SPA.glob("*.js"))
    if not files:
        print(
            f"Nenhum .js em {SPA}. Rode tools/scan_chunks.py antes "
            "ou passe caminhos: python tools/extract_urna_urls.py chunk.js …",
            file=sys.stderr,
        )
        return 1

    for path in files:
        if not path.exists():
            print("missing", path)
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        print(f"\n######## {path.name} len={len(text)} ########")
        for pat in [
            r".{0,120}arquivo-urna.{0,180}",
            r".{0,120}aux\.json.{0,180}",
            r".{0,120}logjez.{0,180}",
            r".{0,120}arquivoLog.{0,180}",
            r".{0,100}configuracao\(.{0,220}",
            r".{0,100}selecao\(.{0,220}",
            r".{0,80}cdPleito.{0,160}",
            r".{0,80}cd_pleito.{0,160}",
            r".{0,80}p000.{0,160}",
            r".{0,80}-cs\.json.{0,160}",
            r".{0,80}hashes.{0,160}",
            r"https?://[^\"'\s]{10,200}",
            r"[\"'][^\"']*arquivo-urna[^\"']*[\"']",
            r"[\"'][^\"']*\.json[^\"']*[\"']",
            r"[\"'][^\"']*\.jez[^\"']*[\"']",
            r"[\"'][^\"']*\.logjez[^\"']*[\"']",
            r"[\"'][^\"']*log-da-urna[^\"']*[\"']",
        ]:
            hits = re.findall(pat, text, flags=re.I)
            if not hits:
                continue
            print(f"\n-- {pat} ({len(hits)}) --")
            for h in hits[:12]:
                print(h.replace("\n", " ")[:240])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
