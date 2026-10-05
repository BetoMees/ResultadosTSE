from pathlib import Path

from web.queries import apuracao, aux_status, connect, overview, tamanhos, ufs

c = connect(Path("data/urna_logs_6257.sqlite3"))
ov = overview(c)
print("secoes", ov["secoes"], "logs", ov["logs_ok"])
print("ufs", len(ufs(c)))
print("aux", aux_status(c))
print("apu", apuracao(c)["por_data"][:3])
print("tam", tamanhos(c)["n"], tamanhos(c)["avg"])
c.close()
print("ok")
