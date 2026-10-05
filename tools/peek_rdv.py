"""Baixa 1 RDV e tenta extrair votos de Presidente."""
from __future__ import annotations

import re
from pathlib import Path

from urna_tse.api import TseResultadosClient
from urna_tse.db import Database

db = Database(Path("data/urna_logs_6257.sqlite3"))
row = db.conn.execute(
    """
    SELECT s.uf, s.municipio_cd, s.zona, s.secao, c.hash, a.nome, s.modelo_urna, s.id AS secao_id
    FROM arquivos a
    JOIN cargas c ON c.id=a.carga_id
    JOIN secoes s ON s.id=a.secao_id
    WHERE a.tipo='rdv' AND a.status='pending'
      AND EXISTS (
        SELECT 1 FROM arquivos l
        WHERE l.secao_id=a.secao_id AND l.tipo='log' AND l.status='ok'
          AND l.modelo_urna IN ('UE2022','UE2020','UE2015','UE2013')
      )
    LIMIT 1
    """
).fetchone()
print(dict(row))
client = TseResultadosClient(min_interval=0.05)
status, content, url = client.fetch_arquivo(
    "ele2026", "3220", row["uf"], row["municipio_cd"], row["zona"], row["secao"], row["hash"], row["nome"]
)
print("rdv", status, len(content), content[:20])
Path(".cache/sample_rdv.bin").write_bytes(content)
strings = re.findall(rb"[\x20-\x7e]{3,}", content)
print("strings", [s.decode() for s in strings[:50]])

# Also try imgbu
img = db.conn.execute(
    """
    SELECT a.nome FROM arquivos a WHERE a.secao_id=? AND a.tipo LIKE '%img%' OR (a.secao_id=? AND a.nome LIKE '%imgbu%')
    """,
    (row["secao_id"], row["secao_id"]),
).fetchall()
print("img files", [dict(r) for r in db.conn.execute("SELECT tipo, nome FROM arquivos WHERE secao_id=?", (row["secao_id"],))])
db.close()
