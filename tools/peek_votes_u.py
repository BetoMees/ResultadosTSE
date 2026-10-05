import json
import requests

u = "https://resultados.tse.jus.br/oficial/ele2026/6257/dados/br/br-c0001-e006257-u.json"
d = requests.get(u, timeout=60).json()
print("keys", sorted(d.keys()))
for k in ["pst", "s", "st", "ht", "dt", "tf", "c", "tf", "vvc", "tv", "cands"]:
    if k in d:
        print(k, d[k] if not isinstance(d[k], list) else f"list[{len(d[k])}]")
# print candidate-like structures
for key in d:
    val = d[key]
    if isinstance(val, list) and val and isinstance(val[0], dict):
        print("LIST", key, "sample keys", sorted(val[0].keys()), "n", len(val))
        print(json.dumps(val[0], ensure_ascii=False)[:500])
    elif isinstance(val, dict):
        print("DICT", key, sorted(val.keys())[:30])

# UF sample
u2 = "https://resultados.tse.jus.br/oficial/ele2026/6257/dados/sp/sp-c0001-e006257-u.json"
r = requests.get(u2, timeout=60)
print("sp", r.status_code)
if r.ok:
    d2 = r.json()
    print("sp keys", sorted(d2.keys())[:40])
    for key in d2:
        val = d2[key]
        if isinstance(val, list) and val and isinstance(val[0], dict) and any(k in val[0] for k in ("n", "nm", "vap", "pvap")):
            print("sp LIST", key, len(val), json.dumps(val[0], ensure_ascii=False)[:400])
            break
