import json
import requests

r = requests.get("https://resultados.tse.jus.br/oficial/comum/config/ele-c.json", timeout=60)
d = r.json()
print("top keys", d.keys())
print("arq templates:")
for a in d.get("arq", []):
    print(" ", a)
print("---pleitos---")
for pl in d.get("pl", []):
    print(pl.get("cd"), pl.get("dt"), pl.get("nm") or pl.get("ds"), "turnos?", list(pl.keys())[:20])
    for el in pl.get("e", []) or pl.get("eleicoes", []) or []:
        if not isinstance(el, dict):
            continue
        cds = str(el.get("cd") or el.get("cdabr") or "")
        if "6257" in cds or "presidente" in json.dumps(el, ensure_ascii=False).lower()[:500]:
            print("  ELE", json.dumps(el, ensure_ascii=False)[:800])
