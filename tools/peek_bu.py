"""Baixa 1 BU de amostra e inspeciona o formato."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import requests

from urna_tse.api import TseResultadosClient
from urna_tse.db import Database

db = Database(Path("data/urna_logs_6257.sqlite3"))
row = db.conn.execute(
    """
    SELECT s.uf, s.municipio_cd, s.zona, s.secao, c.hash, a.nome, s.modelo_urna
    FROM arquivos a
    JOIN cargas c ON c.id=a.carga_id
    JOIN secoes s ON s.id=a.secao_id
    WHERE a.tipo='bu' AND a.status='pending'
      AND EXISTS (
        SELECT 1 FROM arquivos l
        WHERE l.secao_id=a.secao_id AND l.tipo='log' AND l.status='ok' AND l.modelo_urna IS NOT NULL
      )
    LIMIT 1
    """
).fetchone()
print("sample", dict(row) if row else None)
if not row:
    raise SystemExit(0)

client = TseResultadosClient(min_interval=0.05)
# get bu nome from aux
aux = db.conn.execute(
    """
    SELECT a.nome FROM arquivos a
    JOIN secoes s ON s.id=a.secao_id
    WHERE s.uf=? AND s.municipio_cd=? AND s.zona=? AND s.secao=? AND a.tipo='bu'
    LIMIT 1
    """,
    (row["uf"], row["municipio_cd"], row["zona"], row["secao"]),
).fetchone()
print("bu nome", aux["nome"])
status, content, url = client.fetch_arquivo(
    "ele2026", "3220", row["uf"], row["municipio_cd"], row["zona"], row["secao"], row["hash"], aux["nome"]
)
print("http", status, "url", url, "size", len(content) if content else 0)
out = Path(".cache/sample_bu.bin")
out.write_bytes(content)
print("magic", content[:16], "hex", content[:32].hex())
# try decode as text
for enc in ("utf-8", "latin-1"):
    try:
        t = content.decode(enc)
        print("text?", enc, t[:200].replace("\n", " "))
    except Exception as e:
        print("not", enc, e)
# search for strings presidente / candidatos numbers
import re
textish = content.decode("latin-1", errors="ignore")
for m in re.finditer(r".{0,20}Presidente.{0,40}|vap|candidato|22|13", textish):
    s = m.group(0)
    if s.isprintable() or True:
        pass
# printable strings
strings = re.findall(rb"[\x20-\x7e]{4,}", content)
print("strings sample:")
for s in strings[:80]:
    print(" ", s.decode("ascii", errors="ignore"))
db.close()
