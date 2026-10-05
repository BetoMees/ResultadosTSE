from pathlib import Path

from urna_tse.db import Database

db = Database(Path("data/urna_logs_6257.sqlite3"))
db.conn.execute("PRAGMA busy_timeout=60000")
# espelha modelo de arquivos -> secoes
cur = db.conn.execute(
    """
    UPDATE secoes
    SET modelo_urna = (
        SELECT a.modelo_urna FROM arquivos a
        WHERE a.secao_id = secoes.id AND a.tipo='log' AND a.status='ok'
          AND a.modelo_urna IS NOT NULL AND a.modelo_urna != '(ainda não extraído)'
        LIMIT 1
    )
    WHERE EXISTS (
        SELECT 1 FROM arquivos a
        WHERE a.secao_id = secoes.id AND a.tipo='log' AND a.status='ok'
          AND a.modelo_urna IS NOT NULL
    )
    """
)
db.commit()
print("secoes updated", cur.rowcount)
print("arquivos modelos:")
for r in db.conn.execute(
    "SELECT COALESCE(modelo_urna,'(null)') m, COUNT(*) c FROM arquivos WHERE tipo='log' AND status='ok' GROUP BY 1 ORDER BY c DESC"
):
    print(" ", r["m"], r["c"])
print("secoes modelos:")
for r in db.conn.execute(
    "SELECT COALESCE(modelo_urna,'(null)') m, COUNT(*) c FROM secoes GROUP BY 1 ORDER BY c DESC LIMIT 10"
):
    print(" ", r["m"], r["c"])
db.close()
