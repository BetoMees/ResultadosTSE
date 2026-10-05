import json
import requests

d = requests.get(
    "https://resultados.tse.jus.br/oficial/ele2026/6257/dados/br/br-c0001-e006257-u.json",
    timeout=60,
).json()
print("v summary", {k: d["v"][k] for k in ("tv", "vv", "vb", "vn", "van", "vnom", "tvn", "pvv", "pvb", "pvn") if k in d["v"]})
carg = d["carg"][0]
candidates = []
for agr in carg.get("agr", []):
    for par in agr.get("par", []):
        for cand in par.get("cand", []):
            candidates.append(
                {
                    "n": cand.get("n"),
                    "nm": cand.get("nm"),
                    "sg": par.get("sg") or agr.get("com"),
                    "vap": cand.get("vap") or cand.get("tvtn") or cand.get("tvan"),
                    "pvap": cand.get("pvap"),
                    "st": cand.get("st"),
                    "seq": cand.get("seq"),
                    "keys": sorted(cand.keys()),
                }
            )
print("cand count", len(candidates))
print("cand keys", candidates[0]["keys"] if candidates else None)
for c in candidates[:15]:
    print(c["n"], c["nm"], c["sg"], c["vap"], c["pvap"], c["st"])
print(json.dumps(candidates[0], ensure_ascii=False, indent=2)[:800])
