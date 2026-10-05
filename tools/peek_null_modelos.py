from pathlib import Path

from urna_tse.db import Database
from urna_tse.modelo import parse_modelo_from_jez

db = Database(Path("data/urna_logs_6257.sqlite3"))
print("por modelo_urna:")
for r in db.conn.execute(
    """
    SELECT COALESCE(modelo_urna, '(NULL)') m, COUNT(*) c,
           SUM(CASE WHEN content IS NULL THEN 1 ELSE 0 END) sem_blob,
           SUM(CASE WHEN content IS NOT NULL THEN 1 ELSE 0 END) com_blob
    FROM arquivos WHERE tipo='log' AND status='ok'
    GROUP BY 1 ORDER BY c DESC
    """
):
    print(f"  {r['m']}: {r['c']} (blob={r['com_blob']} sem_blob={r['sem_blob']})")

nulls = list(
    db.conn.execute(
        """
        SELECT id, secao_id, nome, size_bytes,
               content IS NOT NULL AS has_blob,
               log_text IS NOT NULL AS has_text,
               downloaded_at
        FROM arquivos
        WHERE tipo='log' AND status='ok' AND modelo_urna IS NULL
        LIMIT 5
        """
    )
)
print("\namostras NULL:")
for r in nulls:
    modelo = None
    if r["has_blob"]:
        blob = db.conn.execute("SELECT content FROM arquivos WHERE id=?", (r["id"],)).fetchone()["content"]
        modelo = parse_modelo_from_jez(blob)
    print(
        f"  id={r['id']} blob={r['has_blob']} text={r['has_text']} "
        f"size={r['size_bytes']} parsed={modelo} at={r['downloaded_at']}"
    )
print("total NULL", db.count("arquivos", "tipo='log' AND status='ok' AND modelo_urna IS NULL"))
db.close()
