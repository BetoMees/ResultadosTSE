# Urna — logs e dashboard (TSE Resultados)

Baixa os **logs da urna** (*dados-de-urna / log-da-urna*) do portal público
[Resultados do TSE](https://resultados.tse.jus.br/oficial/app/index.html),
grava em **SQLite** local (com retomada) e exibe um **dashboard** com KPIs,
mapa e filtros por modelo de urna.

Eleição padrão: **6257** (Eleição Ordinária Federal – 2026, 1º turno).

## Estrutura

```
Urna/
├── download_logs_urna.py      # CLI do downloader
├── sync_votos_presidente.py   # Totais Presidente (BR/UF) via API de votos
├── sync_votos_secao_bu.py     # Votos por seção a partir do BU
├── serve_dashboard.py         # Sobe o site em :8765
├── urna_tse/                  # Cliente HTTP, DB, parse de modelo/BU
├── web/                       # FastAPI + frontend estático
├── tools/                     # Extração / peek / diagnóstico
├── data/                      # SQLite e logs (ignorados pelo Git)
├── requirements.txt
└── README.md
```

## Instalação

```powershell
cd <pasta-do-projeto>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Downloader

Descobrir seções + baixar `aux` + logs (todas as UFs):

```powershell
python download_logs_urna.py
```

Teste pequeno:

```powershell
python download_logs_urna.py --ufs ac --limit 20 --workers 2 --min-interval 0.2
```

Retomar / só estatísticas:

```powershell
python download_logs_urna.py
python download_logs_urna.py --stats-only
```

### Opções úteis

| Flag | Função |
| --- | --- |
| `--workers N` | Paralelismo HTTP (padrão 32; use 4–8 se houver 429) |
| `--min-interval S` | Espaçamento entre *inícios* de request (padrão 0.02) |
| `--batch-size N` | Alterna lotes aux+logs (padrão 2000; `0` = fases únicas) |
| `--aux-refresh-seconds` | Cooldown para reconsultar aux ok sem log |
| `--no-blob` | Não guarda o `.jez` no SQLite |
| `--extract-text` | Grava `logd.dat` em texto (DB muito maior) |
| `--skip-discover` / `--skip-aux` / `--skip-logs` | Roda só uma fase |
| `--db caminho` | Outro arquivo SQLite |

Acompanhar progresso:

```powershell
python download_logs_urna.py --stats-only
Get-Content data\download.err.log -Tail 30
```

### Rate limit (429)

A CDN do TSE pode bloquear temporariamente se o volume de requests for alto
(~1 `aux` + 1 arquivo por seção; centenas de milhares no país).

O cliente HTTP já trata isso:

- **HTTP 429 / 5xx**: espera longa antes de retentar (honra `Retry-After` se existir;
  senão backoff 30s → 60s → 120s… até 10 min), e aumenta o `min_interval`.
- **Download ZIP (2022)**: mesma lógica ao baixar cada UF; o painel mostra
  “rate limit / espera Ns”.
- Se o bloqueio persistir após várias tentativas, a UF/arquivo falha e o job
  pode ser **Continuado** depois.

Ainda assim, reduza `--workers` e aumente `--min-interval` (ex.: `0.1`–`0.25`)
se notar muitos 429.

Não existe endpoint “baixar tudo de uma vez” no portal Resultados. Pacotes ZIP
por UF (*Arquivos transmitidos para totalização*) costumam aparecer depois no
[Dados Abertos](https://dadosabertos.tse.jus.br/) em
`cdn.tse.jus.br/.../arqurnatot/` — ainda não publicados para 2026 no momento
deste README. Logs **Gedai** no Dados Abertos são outro produto (preparação).

## Dashboard e downloads

Site local com KPIs, gráficos e mapa. Na **Visão geral**, o card **Downloads por eleição**:

| Ano | Modo | Observação |
| --- | --- | --- |
| **2026** | Por região/seção (Resultados) | Pacote ZIP completo ainda não publicado |
| **2022** | ZIP por UF (Dados Abertos / CDN) | `arqurnatot` — importa `.logjez` |
| **2018** | Indisponível | TSE não publicou `arqurnatot` para 2018 |

Cada eleição usa um SQLite próprio em `data/` (ex.: `urna_logs_2022_1t.sqlite3`). O botão **Atualizar painel** refresca os números (sem auto-refresh).

```powershell
python sync_votos_presidente.py
python tools\extract_modelos.py
python serve_dashboard.py
```

Abra [http://127.0.0.1:8765](http://127.0.0.1:8765).

## API pública (Resultados)

| Etapa | Endpoint |
| --- | --- |
| Catálogo | `GET /oficial/comum/config/ele-c.json` |
| Seções por UF (CS) | `GET /oficial/{ciclo}/arquivo-urna/{pleito}/config/{uf}/{uf}-p{pleito:06d}-cs.json` |
| Hash/arquivos (aux) | `GET /oficial/{ciclo}/arquivo-urna/{pleito}/dados/{uf}/{mun}/{zona}/{secao}/…-aux.json` |
| Arquivo (log) | `GET /oficial/{ciclo}/arquivo-urna/{pleito}/dados/{uf}/{mun}/{zona}/{secao}/{hash}/{arquivo}` |

Para a eleição **6257**: `ciclo=ele2026`, `pleito=3220` (~517 mil seções no 1º turno).

## Schema SQLite (resumo)

| Tabela | Conteúdo |
| --- | --- |
| `meta` | `eleicao`, `pleito`, `ciclo`, host, … |
| `uf_config` | JSON CS por UF |
| `secoes` | UF → município → zona → seção (+ `modelo_urna`) |
| `aux` / `cargas` / `arquivos` | Metadados e BLOBs (`.jez`, status, sha256) |
| `votos_abr` / `votos_candidatos` | Totais Presidente |
| `votos_secao` | Votos válidos por seção (via BU) |

Status em `arquivos`: `pending`, `ok`, `missing`, `error`.

O banco local fica em `data/` e **não** é versionado (pode passar de dezenas de GB com BLOBs).

## O que usamos dos logs hoje

De cada `.jez` / `.logjez` o import abre o `logd.dat` e extrai só o
**modelo da urna** (`Identificação do Modelo de Urna: UE20xx` → coluna
`secoes.modelo_urna` / `arquivos.modelo_urna`).

Totais de Presidente (válidos, brancos, nulos, por UF) **não** vêm do log:
vêm dos CSV odsele (`votacao_candidato_munzona` + `detalhe_votacao_munzona`)
ou da API de votos (2026). A aba Modelos cruza o CSV de votação por seção
com o `modelo_urna` já extraído dos logs.

O log **não revela o candidato escolhido** (voto secreto). Só registra eventos
operacionais e confirmações por cargo.

## O que ainda pode ser extraído do log

Cada arquivo costuma ter milhares de linhas (`DATA HORA LEVEL SERIAL MÓDULO mensagem hash`).
Em vez de gravar o `log_text` inteiro (explode o SQLite), o caminho natural é
um **resumo por seção** no import. Abaixo, o que ainda não usamos e vale a pena.

### Alto valor

| Dado | Exemplo no log | Uso possível no painel |
| --- | --- | --- |
| Abertura / encerramento | `Urna pronta para receber votos` → `Inicio do Encerramento` | Duração da votação; seções que abriram/fecharam tarde |
| Fluxo de eleitores | `Eleitor foi habilitado` + timestamps | Ritmo por hora, picos, comparação entre UFs |
| Biometria do eleitor | sucesso / falha / `O eleitor não possui biometria` | Taxa biométrica por UF e por modelo de urna |
| Versão do software | `Versão da aplicação: 8.26.0.0 - Onça-pintada` | Inventário de firmware |
| Energia | `Urna operando com rede elétrica` / bateria | Seções em bateria vs rede |
| Mídia de carga | ID da mídia, computador, data/usuário da carga | Rastreio da preparação da urna |
| Local informado | município, zona, seção, local de votação | Conferir cadastro vs CS |
| Alertas e erros | linhas `ALERTA` / `ERRO` | Mapa de seções com incidente |

### Médio valor

| Dado | Exemplo no log | Uso possível |
| --- | --- | --- |
| Votos confirmados por cargo | `Voto confirmado para [Presidente]` (sem número) | Contagem de atos de voto por cargo na seção |
| Teclas especiais | `Tecla pressionada: BRANCO` (e correção) | Comportamento operacional, não resultado oficial |
| Biometria do mesário | pedido / falha / mesário não é eleitor da seção | Qualidade do fechamento da mesa |
| Tempo habilitação → confirmação | diferença entre timestamps VOTA | Proxy de tempo médio por eleitor |

### Baixo valor (ruído — em geral ignorar)

- Dezenas de verificações de assinatura `.vst` / `.vsc` no boot  
- Particionamento e formatação da mídia interna  
- Linhas de “gerando arquivo `.bu` / `.rdv` / `.hash`” no encerramento (só confirmam que gerou)

### O que o log não tem

| Pedido | Onde buscar em vez disso |
| --- | --- |
| Voto nominal (candidato) | Não existe no log (sigilo) |
| Totais brancos/nulos/válidos oficiais | CSV `detalhe_votacao_munzona` / API de votos / BU |
| Imagem do BU, RDV bruto | Arquivos `.imgbu` / `.rdv` do pacote (hoje não importamos) |

## Observações

- Só endpoints públicos oficiais; sem autenticação.
- O downloader é **resumável**: rode de novo para continuar.
- Seja respeitoso com a CDN (workers / intervalo).
