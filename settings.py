"""
settings.py — Configurações centralizadas da aplicação.

Carrega valores do .env e fornece defaults seguros.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Diretórios ──────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "cache" / "html"
CONFIG_PATH = BASE_DIR / "config" / "leis.yaml"

# Cria diretórios de dados se não existirem
DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "raw").mkdir(exist_ok=True)
(DATA_DIR / "struct").mkdir(exist_ok=True)
(DATA_DIR / "crossrefs").mkdir(exist_ok=True)
(DATA_DIR / "relatorios").mkdir(exist_ok=True)

# ─── API ─────────────────────────────────────────────────────

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

# Chave de autenticação para endpoints protegidos (POST/PATCH)
API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")

# CORS — origens permitidas (separar por vírgula no .env)
_cors_raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]

# ─── Google AI / Ollama ───────────────────────────────────────

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.0-flash" if LLM_PROVIDER == "gemini" else "llama3")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# ─── Performance & Security ──────────────────────────────────

# Ativa cache em memória para leis muito acessadas (evita I/O JSON)
ENABLE_API_CACHE = os.getenv("ENABLE_API_CACHE", "true").lower() == "true"
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600")) # 1 hora

# Rate Limiting
ENABLE_RATE_LIMIT = os.getenv("ENABLE_RATE_LIMIT", "true").lower() == "true"
RATE_LIMIT_DEFAULT = os.getenv("RATE_LIMIT_DEFAULT", "20/minute")

# ─── Pipeline ────────────────────────────────────────────────

PRECISAO_MINIMA_ARTIGOS = float(os.getenv("PRECISAO_MINIMA", "0.95"))
