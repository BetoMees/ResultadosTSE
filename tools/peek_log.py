import io
import re
import sqlite3
import zipfile
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "data" / "urna_logs_6257.sqlite3"
con = sqlite3.connect(p)
row = con.execute(
    "SELECT id, nome, size_bytes, content FROM arquivos WHERE tipo='log' AND status='ok' AND content IS NOT NULL LIMIT 1"
).fetchone()
print("sample", row[0], row[1], row[2])
z = zipfile.ZipFile(io.BytesIO(row[3]))
print("zip", z.namelist())
text = z.read(z.namelist()[0]).decode("latin-1", errors="replace")
lines = text.splitlines()
print("n_lines", len(lines))
for i, line in enumerate(lines[:60]):
    print(f"{i}: {line[:220]}")
print("---KEYS---")
keys = ("modelo", "ue20", "versa", "firm", "urna", "candidato", "voto", "boletim", "biometr", "aplicat")
for line in lines:
    low = line.lower()
    if any(k in low for k in keys):
        print(line[:240])
