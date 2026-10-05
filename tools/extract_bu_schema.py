from pathlib import Path
import re

t = Path(".cache/spa/369.69540f212d9cd90f.js").read_text(encoding="utf-8", errors="ignore")
print("len", len(t))
for mm in re.finditer(r'"([^"]+)"\s*:\s*\{name:"([^"]+)",type:"([^"]+)"', t):
    path, name, typ = mm.group(1), mm.group(2), mm.group(3)
    blob = (name + typ + path).lower()
    if any(k in blob for k in ("voto", "cargo", "cand", "apurad", "eleicao", "qtd", "quant", "numero")):
        print(f"{path} | {name} | {typ}")
