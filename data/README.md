# Dados locais

Esta pasta guarda artefatos gerados em runtime e **não** entram no Git:

| Arquivo | Descrição |
| --- | --- |
| `urna_logs_<eleicao>.sqlite3` | Banco principal (seções, aux, logs, votos, modelos) |
| `*.sqlite3-wal` / `*-shm` | Journal do SQLite em modo WAL |
| `download.log` / `download.err.log` | Saída do downloader |

Gere o banco com:

```powershell
python download_logs_urna.py
```

O caminho padrão é `data/urna_logs_6257.sqlite3` (eleição 6257).
