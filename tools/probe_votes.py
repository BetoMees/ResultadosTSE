import json
import requests

HOST = "https://resultados.tse.jus.br/oficial"
cands = [
    f"{HOST}/ele2026/6257/dados/br/br-c0001-e006257-u.json",
    f"{HOST}/ele2026/6257/dados/br/br-c0001-e006257-v.json",
    f"{HOST}/ele2026/6257/dados/br/br-c0001-e006257-r.json",
    f"{HOST}/ele2026/6257/dados/br/br-c0001-e006257-i.json",
    f"{HOST}/ele2026/6257/dados/br/br-c0001-e006257-f.json",
    f"{HOST}/ele2026/6257/dados/br/br-c0001-e006257-a.json",
    f"{HOST}/ele2026/6257/dados/br/br-c0001-e006257-ab.json",
    f"{HOST}/ele2026/6257/dados-simplificados/br/br-c0001-e006257-r.json",
    f"{HOST}/ele2026/6257/dados-simplificados/br/br-c0001-e006257-u.json",
    f"{HOST}/ele2026/6257/dados/br/br-e006257-v.json",
    f"{HOST}/ele2026/6257/dados/br/br-e006257-u.json",
    f"{HOST}/ele2026/6257/dados/br/br-e006257-r.json",
    f"{HOST}/ele2026/6257/dados/br/br-e006257-ab.json",
    f"{HOST}/ele2026/6257/config/ele-e006257-ele.json",
    f"{HOST}/ele2026/6257/config/cands-e006257-d.json",
]
for u in cands:
    r = requests.get(u, timeout=30)
    print(r.status_code, u.split("/")[-1], (r.text[:100].replace("\n", " ") if r.ok else ""))

# also try listing from SPA patterns in cache
import re
from pathlib import Path
text = Path(".cache/spa").joinpath("2844.674e403f7b371606.js").read_text(encoding="utf-8", errors="ignore")
for m in re.findall(r".{0,80}dados-simplificados.{0,120}|.{0,80}-e00.{0,80}", text)[:30]:
    print("SPA:", m[:180])
