import io
import re
import zipfile
from pathlib import Path
import sqlite3

con = sqlite3.connect(Path("data/urna_logs_6257.sqlite3"))
row = con.execute(
    "SELECT content FROM arquivos WHERE tipo='log' AND status='ok' AND content IS NOT NULL LIMIT 1"
).fetchone()
z = zipfile.ZipFile(io.BytesIO(row[0]))
text = z.read(z.namelist()[0]).decode("latin-1", errors="replace")
keys = ("voto", "candidato", "presidente", "boletim", "total", "eleitor", "apurad", "branco", "nulo")
for line in text.splitlines():
    low = line.lower()
    if any(k in low for k in keys) and ("presidente" in low or "voto" in low or "boletim" in low or "branco" in low or "nulo" in low):
        if "assinatura" in low or "verifica" in low:
            continue
        print(line[:220])
print("---TAIL---")
for line in text.splitlines()[-80:]:
    print(line[:220])
