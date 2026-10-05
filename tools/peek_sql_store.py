from pathlib import Path

from urna_tse.db import Database

db = Database(Path("data/urna_logs_6257.sqlite3"))
print("tables", [r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1")])
print("votos_abr", db.count("votos_abr"), "votos_candidatos", db.count("votos_candidatos"))
print(
    "modelo arquivos",
    list(
        db.conn.execute(
            "SELECT COALESCE(modelo_urna,'(null)') m, COUNT(*) c FROM arquivos WHERE tipo='log' AND status='ok' GROUP BY 1 ORDER BY c DESC"
        )
    ),
)
print(
    "modelo secoes",
    list(
        db.conn.execute(
            "SELECT COALESCE(modelo_urna,'(null)') m, COUNT(*) c FROM secoes WHERE modelo_urna IS NOT NULL GROUP BY 1 ORDER BY c DESC LIMIT 10"
        )
    ),
)
print("cols arquivos", [r[1] for r in db.conn.execute("PRAGMA table_info(arquivos)")])
print("cols secoes", [r[1] for r in db.conn.execute("PRAGMA table_info(secoes)")])
db.close()
