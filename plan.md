# Plan — RotaBrasilv3Claude

---

## Contexto do Portal

O portal é um sistema web (FastAPI + HTMX) que automatiza cotações de frete no **rotasbrasil.com.br**.
O `testUnit/diagnostico_scraper.py` é o **modelo base validado** — funciona perfeitamente para uma rota
e serve como referência de seletores DOM, lógica de formulário e extração de dados.
Qualquer mudança no site deve ser primeiro validada no diagnóstico antes de aplicar ao portal.

### Fluxo principal do portal (linha a linha)

```
Usuário preenche: nome, veículo, eixos, combustível, consumo, delay, Excel
  ↓
POST /cotacoes → lê o Excel (colunas obrigatórias: origem, destino)
  ↓
Para cada linha do Excel (sequencial):
  1. Monta ParametrosRota com dados da linha + parâmetros do portal
  1.1 Busca no cache (Xano) pela chave SHA-256
      → cache HIT  : usa resultado salvo, pula para 6
      → cache MISS : vai para 2
  2. Abre browser (uma vez por lote, persiste entre linhas)
  3. Preenche formulário: veículo → eixos → origem → destino → combustível → "todas"
  4. Clica BUSCAR (via JS) → aguarda div.routeResult.active sumir + reaparecer
  5. Espera delay configurado (evita detecção/bloqueio)
  6. Extrai campos — igual ao diagnóstico:
       tempo_viagem, rota_descricao, distancia_km, valor_pedagio,
       valor_combustivel, valor_total + 12 × Tipo_Carga_*
  7. Salva resultado no cache (Xano) com TTL configurável
  8. Emite evento SSE de progresso para o browser do usuário
  ↓
Fim do lote → GerarExcelUseCase:
  gera [nome_cotacao]_[YYYY-MM-DD]_[HH-MM].xlsx em /outputs/
  emite evento SSE "download_pronto"
  ↓
Usuário clica "Baixar Excel" → browser abre janela nativa de salvar
```

### Em caso de erro
- Erro por linha (site, timeout, captcha): registra `erro_mensagem`, continua para próxima linha
- Erro crítico (browser crash, exceção inesperada): para o lote, exibe detalhes no painel vermelho
- Mensagens de erro são técnicas e detalhadas para facilitar diagnóstico

---

## testUnit/diagnostico_scraper.py

### Função
Script standalone de diagnóstico/teste. Modelo base validado — executa **uma** consulta
no rotasbrasil.com.br, extrai todos os campos e salva em console + Excel + HTML + TXT.

```bash
# Executar do raiz do projeto:
.venv/Scripts/python testUnit/diagnostico_scraper.py
```

Outputs gerados dentro de `testUnit/`:
- `diagnostico_resultado.xlsx` — colunas prontas para mapeamento no sistema
- `diagnostico_resultado.html` — HTML bruto do painel de resultados
- `diagnostico_resultado.txt`  — texto puro do painel

### Fluxo de execução
```
Abre Chromium (headless=False, slow_mo=50)
  → goto rotasbrasil.com.br
  → Seleciona veículo (caminhão ID=2) + eixos (6)
  → Digita origem com autocomplete jQuery UI
  → Digita destino com autocomplete jQuery UI
  → Preenche combustível / consumo (page.type delay=50ms)
  → Seleciona tipo de carga: "todas"
  → Clica BUSCAR via JS
  → Aguarda div.routeResult.active (timeout 30s)
  → Extrai campos fixos (tempo, rota, distância, pedágio, combustível, total)
  → Extrai 12 tipos de carga em uma chamada JS de #tabelaDeFrete0
  → Salva Excel + HTML + TXT → abre Excel (Windows)
```

### Colunas de saída

| Coluna | Seletor DOM |
|---|---|
| Seq | sequencial |
| Origem | parâmetro |
| Destino | parâmetro |
| tempo_viagem | `div.color-primary-500` |
| rota_descricao | `.titulo` |
| distancia_km | `div.distance` |
| valor_pedagio | `span.vlPedagio` |
| combustivel | `span.vlCombustivel` |
| total Despesas | `div.results b` |
| Tipo_Carga_* (×12) | `#tabelaDeFrete0 .valorFreteMin` |

### 12 Tipos de Carga (valores de referência — Londrina→Curitiba, mar/2026)
```
Tipo_Carga_Granel Sólido:              R$ 3.530,40
Tipo_Carga_Granel Líquido:             R$ 3.623,66
Tipo_Carga_Frigorificada:              R$ 4.127,62
Tipo_Carga_Conteinerizada:             R$ 3.488,61
Tipo_Carga_Carga Geral:                R$ 3.511,62
Tipo_Carga_Neogranel:                  R$ 3.511,62
Tipo_Carga_Perigosa (granel sólido):   R$ 3.985,72
Tipo_Carga_Perigosa (granel líquido):  R$ 4.083,52
Tipo_Carga_Perigosa (frigorificada):   R$ 4.482,19
Tipo_Carga_Perigosa (conteinerizada):  R$ 3.747,86
Tipo_Carga_Perigosa (carga geral):     R$ 3.770,88
Tipo_Carga_Granel Pressurizada:        R$ 3.773,79
```
Os nomes das colunas são gerados dinamicamente lendo `#tabelaDeFrete0`.
Se o site alterar os tipos, o script se adapta sem mudança de código.

---

## Mudanças Aplicadas (2026-03-27)

### Scraper do portal alinhado ao diagnóstico
- `_digitar_humano` → `page.type(delay=50)` (era loop ~400ms/char)
- `slow_mo` 200 → 50
- Sempre seleciona `"todas"` — extrai 12 tipos de uma vez via `#tabelaDeFrete0`
- Bug múltiplas rotas corrigido: espera `div.routeResult.active` sumir antes de validar novo resultado
- `rota_descricao` extraído via `.titulo` (igual ao diagnóstico)
- Removido `CARGA_VALORES` e `_selecionar_tipo_carga`

### ResultadoRota
- Campo `valor_frete: Optional[str]` substituído por `fretes: dict`
- `from_dict` usa `.get("fretes", {})` — compatível com cache antigo

### Excel de saída
- Colunas sem prefixo `resultado_` (ex: `origem`, `destino`, `tempo_viagem`, ...)
- 12 colunas `Tipo_Carga_*` dinâmicas (azul no Excel)
- Colunas originais do Excel de entrada (verde no Excel)
- Download via botão no modal com janela nativa do browser

### Formulário (index.html)
- Removido campo "Tipo de Carga" (não é mais configurável)
- Exibe "Todos os 12 tipos extraídos automaticamente"

### Cache
- `tipo_carga` default mudou de `"Carga Geral"` para `"todas"` no `ParametrosRota`
- Entradas antigas no cache com tipo específico não serão reaproveitadas (stale)
