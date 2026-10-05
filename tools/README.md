# Ferramentas auxiliares

Scripts de inspeção, extração e diagnóstico sobre o SQLite / API do TSE.

| Script | Uso |
| --- | --- |
| `extract_modelos.py` | Extrai modelo da UE a partir dos logs baixados |
| `mirror_modelos_secoes.py` | Espelha `arquivos.modelo_urna` → `secoes` |
| `peek_*.py` / `probe_*.py` | Inspeção pontual do banco ou payloads |
| `extract_urna_urls.py` / `analyze_spa.py` | Engenharia reversa leve do SPA Resultados |
| `extract_bu_schema.py` / `debug_bu_walk.py` | Schema ASN.1 / walk do boletim de urna |

A maioria espera o DB em `data/urna_logs_6257.sqlite3`. Rode a partir da raiz do projeto:

```powershell
python tools\extract_modelos.py
```
