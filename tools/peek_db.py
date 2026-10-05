import sqlite3
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "data" / "urna_logs_6257.sqlite3"
print("exists", p.exists(), "size_mb", round(p.stat().st_size / 1024 / 1024, 1) if p.exists() else None)
con = sqlite3.connect(p)
print("meta", list(con.execute("SELECT key,value FROM meta")))
print("ufs", list(con.execute("SELECT uf,nome,n_secoes FROM uf_config ORDER BY uf")))
print("aux_st", list(con.execute("SELECT COALESCE(st,'') st, COUNT(*) c FROM aux GROUP BY st ORDER BY c DESC")))
print("arq", list(con.execute("SELECT tipo, status, COUNT(*) c FROM arquivos GROUP BY tipo,status")))
print(
    "sizes",
    list(
        con.execute(
            "SELECT COUNT(*) n, SUM(size_bytes) s, AVG(size_bytes) a FROM arquivos WHERE tipo='log' AND status='ok'"
        )
    ),
)
print("secoes_uf", list(con.execute("SELECT uf, COUNT(*) c FROM secoes GROUP BY uf ORDER BY c DESC")))
print(
    "apuracao",
    list(con.execute("SELECT data_apuracao, COUNT(*) c FROM secoes GROUP BY data_apuracao ORDER BY c DESC LIMIT 10")),
)
print("cargas", list(con.execute("SELECT COALESCE(st,'') st, COUNT(*) c FROM cargas GROUP BY st")))
print(
    "logs_by_uf",
    list(
        con.execute(
            """
            SELECT s.uf,
                   SUM(CASE WHEN a.status='ok' THEN 1 ELSE 0 END) ok,
                   COUNT(*) tot
            FROM arquivos a
            JOIN secoes s ON s.id=a.secao_id
            WHERE a.tipo='log'
            GROUP BY s.uf
            ORDER BY s.uf
            """
        )
    ),
)
