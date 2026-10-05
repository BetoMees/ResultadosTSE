from pathlib import Path

from urna_tse.db import Database

db = Database(Path("data/urna_logs_6257.sqlite3"))
print("stats", db.stats())
print("\npor UF (secoes / aux_ok / logs_ok / logs_pending):")
rows = db.conn.execute(
    """
    SELECT s.uf,
           COUNT(*) AS secoes,
           SUM(CASE WHEN a.http_status=200 THEN 1 ELSE 0 END) AS aux_ok,
           SUM(CASE WHEN ar.status='ok' THEN 1 ELSE 0 END) AS logs_ok,
           SUM(CASE WHEN ar.tipo='log' AND ar.status!='ok' THEN 1 ELSE 0 END) AS logs_pending,
           SUM(CASE WHEN ar.tipo='log' THEN 1 ELSE 0 END) AS logs_total
    FROM secoes s
    LEFT JOIN aux a ON a.secao_id=s.id
    LEFT JOIN arquivos ar ON ar.secao_id=s.id AND ar.tipo='log'
    GROUP BY s.uf
    ORDER BY s.uf
    """
)
for r in rows:
    print(
        f"  {r['uf']}: secoes={r['secoes']} aux={r['aux_ok'] or 0} "
        f"logs_ok={r['logs_ok'] or 0} logs_pend={r['logs_pending'] or 0} logs_tot={r['logs_total'] or 0}"
    )
db.close()
