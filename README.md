# 🏛️ Leis API — Backend de processamento de leis brasileiras

API REST para download, parsing, estruturação e consulta de leis brasileiras.

## ✨ Funcionalidades

- **Download multi-fonte** — Planalto, Senado, Câmara com rate limiting e cache
- **Parser hierárquico** — Extrai títulos, capítulos, seções, artigos, parágrafos, incisos, alíneas
- **IA adaptativa** — Recuperação automática de artigos que falham no regex via Gemini
- **Cross-references** — Extração de referências cruzadas entre artigos
- **Validação estrutural** — Relatório de qualidade com métricas de precisão
- **API REST** — FastAPI com paginação, busca textual e documentação interativa

## 📦 Leis disponíveis

| Código | Lei |
|--------|-----|
| `cf88` | Constituição Federal de 1988 |
| `cp` | Código Penal |
| `cpp` | Código de Processo Penal |
| `clt` | CLT — Consolidação das Leis do Trabalho |
| `9394` | LDB — Diretrizes e Bases da Educação |
| `8078` | Código de Defesa do Consumidor |
| `13709` | LGPD — Lei Geral de Proteção de Dados |
| ... | [+10 outras leis](config/leis.yaml) |

## 🚀 Rodando localmente

### Pré-requisitos

- Python 3.11+
- pip

### Instalação

```bash
# 1. Clone o repositório
git clone <url-do-repo>
cd lei

# 2. Crie um ambiente virtual
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/Mac
source .venv/bin/activate

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Configure as variáveis de ambiente
copy .env.example .env
# Edite o .env com suas chaves
```

### Rodando a API

```bash
# Iniciar o servidor
python api.py

# Ou com uvicorn (recomendado)
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

A API estará disponível em: **http://localhost:8000**

- **Documentação interativa (Swagger):** http://localhost:8000/api/v1/docs
- **Documentação alternativa (ReDoc):** http://localhost:8000/api/v1/redoc
- **Health check:** http://localhost:8000/api/v1/health

### Rodando com Docker

```bash
# Build e start
docker compose up --build

# Em background
docker compose up -d --build
```

## 📡 Endpoints da API

### Públicos (sem autenticação)

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| `GET` | `/api/v1/health` | Health check |
| `GET` | `/api/v1/leis/catalogo` | Lista leis (filtrável por `?tag=penal`) |
| `GET` | `/api/v1/leis/{codigo}` | Resumo de uma lei |
| `GET` | `/api/v1/leis/{codigo}/artigos` | Artigos paginados (`?page=1&per_page=20`) |
| `GET` | `/api/v1/leis/{codigo}/artigos/{id}` | Artigo completo |
| `GET` | `/api/v1/leis/{codigo}/busca` | Busca textual (`?q=homicídio`) |
| `GET` | `/api/v1/leis/{codigo}/crossrefs` | Referências cruzadas |
| `GET` | `/api/v1/leis/{codigo}/relatorio` | Relatório de validação |
| `GET` | `/api/v1/leis/{codigo}/estrutura` | JSON completo (cuidado: pode ser grande) |
| `GET` | `/api/v1/pipeline/{codigo}/status` | Status do pipeline |

### Protegidos (requer header `X-API-Key`)

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| `POST` | `/api/v1/pipeline/{codigo}` | Inicia processamento |
| `PATCH` | `/api/v1/leis/{codigo}/artigos/{id}` | Corrige artigo manualmente |

### Exemplo de uso

```bash
# Health check
curl http://localhost:8000/api/v1/health

# Listar leis
curl http://localhost:8000/api/v1/leis/catalogo

# Artigos da CLT com paginação
curl "http://localhost:8000/api/v1/leis/clt/artigos?page=1&per_page=10"

# Buscar por texto
curl "http://localhost:8000/api/v1/leis/cp/busca?q=homicídio"

# Iniciar pipeline (requer API key)
curl -X POST http://localhost:8000/api/v1/pipeline/9394 \
  -H "X-API-Key: sua_chave_aqui"
```

## 🧪 Testes

```bash
# Rodar todos os testes
python -m pytest tests/ -v

# Apenas testes do parser
python -m pytest tests/test_parser.py -v

# Apenas testes da API
python -m pytest tests/test_api.py -v
```

## 📁 Estrutura do projeto

```
lei/
├── api.py              # API REST (FastAPI)
├── pipeline.py         # Orquestrador do pipeline
├── parser.py           # Parser hierárquico de leis (v8)
├── downloader.py       # Download com cache e rate limiting
├── validator.py        # Validação estrutural
├── crossref.py         # Extração de referências cruzadas
├── smart_parser.py     # Recuperação via IA (Gemini)
├── review_viewer.py    # Gerador de relatório HTML
├── settings.py         # Configurações centralizadas
├── adapters/           # Adapters por fonte legislativa
│   ├── base.py         # Classe base abstrata
│   ├── planalto.py     # planalto.gov.br
│   ├── senado.py       # senado.leg.br
│   └── camara.py       # camara.leg.br
├── config/
│   └── leis.yaml       # Catálogo de leis
├── tests/
│   ├── test_parser.py  # Testes do parser
│   └── test_api.py     # Testes da API
├── data/               # Outputs processados (gitignored)
├── cache/              # Cache de HTML (gitignored)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

## ⚙️ Variáveis de ambiente

| Variável | Descrição | Obrigatório |
|----------|-----------|-------------|
| `GOOGLE_API_KEY` | Chave Google Gemini (SmartParser) | Não |
| `API_SECRET_KEY` | Chave de autenticação para endpoints protegidos | Sim (produção) |
| `CORS_ORIGINS` | Origens CORS permitidas (separar por vírgula) | Não |
| `API_HOST` | Host do servidor | Não (default: `0.0.0.0`) |
| `API_PORT` | Porta do servidor | Não (default: `8000`) |

## 🔧 Pipeline CLI

O pipeline também pode ser usado diretamente pela linha de comando:

```bash
# Processar uma lei
python pipeline.py --lei 9394

# Processar múltiplas leis
python pipeline.py --batch 9394 cp cpp clt

# Listar leis disponíveis
python pipeline.py --listar

# Forçar re-download (sem cache)
python pipeline.py --lei cf88 --sem-cache
```
