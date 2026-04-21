# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack

Python 3.11 + FastAPI + Uvicorn (1 worker) + Playwright/Chromium + Pandas/openpyxl + Jinja2/HTMX + Xano (external REST API as database).

## Common Commands

```bash
# Always use the venv Python
.venv/Scripts/python main.py                 # Dev server at http://localhost:8000
.venv/Scripts/python diagnostico_scraper.py  # Diagnóstico RotasBrasil (rota única, headless=False)
.venv/Scripts/python diagnostico_qualp.py    # Diagnóstico QualP (rota única, headless=False)
.venv/Scripts/python teste_eixos_qualp.py 9  # Teste isolado de ajuste de eixos no QualP
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/playwright install chromium
```

## Diagnósticos (scripts de teste visual)

Quando o usuário pedir para testar algo, **adicionar o passo ao script de diagnóstico correspondente** em vez de criar um teste separado. Os diagnósticos são a forma preferida de validar comportamento do scraper.

- `diagnostico_qualp.py` — testa o fluxo completo do QualP passo a passo com tempo por etapa e extração de: dados da rota, tabela frete ANTT (12 tipos), praças de pedágio (nome, tarifa, por eixo, rodovia/km)
- `diagnostico_scraper.py` — testa o fluxo completo do RotasBrasil
- `teste_eixos_qualp.py` — teste isolado para ajuste de eixos (aceita número via argumento)

Formato de saída dos diagnósticos:
```
[NN] Descrição do passo...    OK/ERRO  Xs  (detalhe)
```
Cada passo mostra tempo real — útil para identificar onde otimizar.

The server must **not** be started or stopped by Claude — the user manages the server process.

## Architecture

Clean Architecture with four layers:

**Domain** (`app/domain/`) — pure Python, no framework deps
- `ParametrosRota` / `ResultadoRota` — frozen dataclasses (value objects). `ParametrosRota` generates a SHA-256 cache key from its fields.
- `Cotacao` / `LoteCotacao` — stateful entities (AGUARDANDO → PROCESSANDO → CONCLUIDO/ERRO)
- `exceptions.py` — all custom domain exceptions

**Application** (`app/application/`)
- Interfaces: `CotacaoRepository` (abstract), `SiteScraper` (abstract with `iniciar_sessao / consultar / encerrar_sessao`)
- Use cases: `ProcessarLoteUseCase` (main loop), `BuscarCacheUseCase`, `SalvarResultadoUseCase`, `GerarExcelUseCase`

**Infrastructure** (`app/infrastructure/`)
- `XanoRepository` — httpx.AsyncClient calling Xano REST endpoints; TTL validation is client-side (Xano stores ms timestamps)
- `RotasBrasilScraper` — Playwright implementation of `SiteScraper`; humanized typing delays, jQuery UI autocomplete handling, reCAPTCHA detection
- `ExcelService` — pandas reads (.xlsx/.xls/.csv), openpyxl writes with column styling

**Presentation** (`app/presentation/`)
- FastAPI routers: `cotacoes.py` (upload, SSE stream, download), `historico.py`
- Jinja2 templates with HTMX (no JS build step)

## Request Flow

```
POST /cotacoes (file upload)
  → validate Excel (must have "origem" + "destino" columns)
  → create LoteCotacao + list of Cotacao in Xano
  → launch background task via run_in_executor (thread)
      thread creates its own asyncio.ProactorEventLoop (Windows Playwright requirement)
      for each row:
        BuscarCacheUseCase → if hit, use cached ResultadoRota
        else: RotasBrasilScraper.consultar() → SalvarResultadoUseCase
        emit SSE event → asyncio.run_coroutine_threadsafe → main loop queue
  → GerarExcelUseCase: merge original columns + result columns → /outputs/
  → emit "download_pronto" SSE event

GET /cotacoes/{id}/progresso  → SSE stream (AsyncIO queue per lote_id)
GET /cotacoes/{id}/download   → FileResponse from /outputs/
```

## Critical Constraints

- **1 worker only** (`workers=1` in uvicorn) — the SSE progress queue lives in memory; multiple workers would split queues across processes.
- **Windows + Playwright**: The background task thread calls `asyncio.run()` which auto-creates a `ProactorEventLoop`, solving the `NotImplementedError` from `SelectorEventLoop`. Do not change this threading pattern.
- **Scraper sequential**: One browser session per lote, one query at a time. The pattern is: fill form → click search → wait `delay_segundos` → extract → next row. The `div.routeResult.active` selector from the previous result stays in DOM — always wait for it to go hidden before treating the new result as loaded.
- **Components never call Xano directly** — only use cases and the repository do.

## Environment Variables

```env
XANO_BASE_URL=https://xxxx.b2.xano.io
XANO_API_GROUP=/api:XXXXXXXX
PLAYWRIGHT_HEADLESS=true
PLAYWRIGHT_TIMEOUT_MS=30000
PLAYWRIGHT_SLOW_MO_MS=0
DELAY_PADRAO_SEGUNDOS=15
APP_PORT=8000
```

See `.env.example` for full list. Copy to `.env` before running.

> **NUNCA delete, edite ou faça commit do `.env`** — ele está no `.gitignore` e fica APENAS no servidor de produção. Contém credenciais reais (Xano, secret key). Qualquer alteração de configuração deve ser feita diretamente no servidor via SSH.

## Xano Tables

`configuracao_site`, `lote_cotacao`, `item_cotacao`, `cache_consulta`. See `README.md` for full schemas. The Xano base URL + group combine into `settings.xano_url` (see `app/core/config.py`).

## Scraper Selectors (`rotasbrasil_scraper.py`)

Key selectors used for extraction (update here if the site changes):
`div.routeResult.active`, `div.color-primary-500` (tempo), `div.distance`, `span.vlPedagio`, `span.vlCombustivel`, `div.results b` (total), `div.valorFreteMin .valorFreteMinDados.text-right` (frete ANTT), `#countPedagiosRota0`.
Run `diagnostico_scraper.py` to re-map selectors after site changes.
