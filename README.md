# Sistema de Cotações em Lote — Rota Brasil

Sistema para consultar rotas em lote no [rotasbrasil.com.br](https://rotasbrasil.com.br) via automação web, com cache no Xano e geração de planilha Excel com os resultados.

## Stack

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.11 + FastAPI |
| Automação | Playwright (Chromium headless) |
| Frontend | HTMX + Jinja2 + TailwindCSS + DaisyUI |
| Excel | pandas + openpyxl |
| Banco | Xano (REST API) |
| Deploy | PM2 + Nginx (VPS Linux) |

---

## Instalação local

### 1. Clone e crie o ambiente
```bash
git clone <repo> cotacoes
cd cotacoes
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Instala o browser do Playwright
```bash
playwright install chromium
playwright install-deps chromium   # instala dependências do SO (Linux)
```

### 3. Configure as variáveis de ambiente
```bash
cp .env.example .env
# Edite .env com sua URL do Xano e demais configurações
```

### 4. Rode em desenvolvimento
```bash
python main.py
# Acesse: http://localhost:8000
```

---

## Variáveis de ambiente (.env)

| Variável | Obrigatória | Descrição |
|---|---|---|
| `XANO_BASE_URL` | ✅ | URL base da sua instância Xano |
| `XANO_API_GROUP` | ✅ | Grupo de API no Xano (ex: `/api:abc123`) |
| `APP_ENV` | | `development` ou `production` |
| `APP_PORT` | | Porta HTTP (padrão: 8000) |
| `PLAYWRIGHT_HEADLESS` | | `true` em prod, `false` para debugar |
| `PLAYWRIGHT_TIMEOUT_MS` | | Timeout por operação (padrão: 30000) |
| `DELAY_PADRAO_SEGUNDOS` | | Delay padrão entre consultas (padrão: 15) |

---

## Formato do Excel de entrada

Colunas **obrigatórias**:
- `origem` — endereço de origem (ex: `Londrina, PR`)
- `destino` — endereço de destino (ex: `Curitiba, PR`)

Colunas **opcionais** (se ausentes, usa o valor configurado no formulário):
- `veiculo` — 1=Carro, 2=Caminhão, 3=Ônibus, 4=Moto
- `eixos` — número de eixos (ex: 6)
- `preco_combustivel` — R$ por litro (ex: 7.25)
- `consumo_km_l` — km por litro (ex: 2.5)
- `tipo_carga` — Carga Geral, Granel, Frigorificado, etc.

---

## Excel de saída

Nome gerado: `cotacao_NOME_YYYY-MM-DD_HH-MM.xlsx`

Colunas adicionadas:
| Coluna | Exemplo |
|---|---|
| `resultado_tempo_viagem` | `5 h 20 min` |
| `resultado_distancia_km` | `386,2 km` |
| `resultado_rota_descricao` | `via Rodovia Celso Garcia Cid...` |
| `resultado_valor_pedagio` | `R$ 207,00` |
| `resultado_valor_combustivel` | `R$ 1.119,91` |
| `resultado_valor_total` | `R$ 1.326,91` |
| `resultado_valor_frete` | `R$ 3.511,62` |
| `resultado_fonte` | `cache` ou `site` |
| `resultado_status` | `consultado`, `cache` ou `erro` |

---

## Tabelas no Xano

### `configuracao_site`
Cadastre ao menos um registro com:
- `nome`: `rotasbrasil`
- `url_base`: `https://rotasbrasil.com.br`
- `validade_cache_horas`: `720` (30 dias)
- `delay_padrao_segundos`: `15`
- `campos_input`: `{}` (JSON vazio por ora)
- `campos_resultado`: `{}` (JSON vazio por ora)

### Endpoints necessários no Xano
```
GET  /configuracao_site
GET  /configuracao_site/{id}
GET  /lote_cotacao
GET  /lote_cotacao/{id}
POST /lote_cotacao
PATCH /lote_cotacao/{id}
GET  /cache_consulta/buscar?chave_cache=X&config_id=Y
POST /cache_consulta
GET  /item_cotacao?lote_id=X
POST /item_cotacao
PATCH /item_cotacao/{id}
```

---

## Deploy na VPS ($5 Linux)

### 1. Instala dependências
```bash
sudo apt update && sudo apt install -y python3.11 python3.11-venv nodejs npm
npm install -g pm2
```

### 2. Instala Playwright e Chromium
```bash
pip install playwright
playwright install chromium
playwright install-deps chromium
```

### 3. Configura Nginx
```nginx
server {
    listen 80;
    server_name seu-dominio.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # Essencial para SSE funcionar via Nginx
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        chunked_transfer_encoding on;
    }
}
```

### 4. Inicia com PM2
```bash
pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

---

## Ajuste de seletores do scraper

Se o site mudar o layout e o scraper parar de extrair resultados:
1. Abra `app/infrastructure/scrapers/rotasbrasil_scraper.py`
2. Localize `SELETORES_RESULTADO` no topo do arquivo
3. Inspecione o DOM do site com F12 e atualize os seletores
4. O scraper loga o HTML do painel em `DEBUG` — use `PLAYWRIGHT_HEADLESS=false` para visualizar
