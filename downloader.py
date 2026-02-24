"""
downloader.py — v2
Download multi-fonte de leis brasileiras com:
  - Catálogo YAML (config/leis.yaml): URL, fonte, encoding por lei
  - Adapters por fonte: Planalto, Senado, Câmara
  - Rate limiter por domínio (token bucket): respeita limite de RPM por fonte
  - Cache de HTML bruto: evita re-downloads desnecessários
  - Retry com backoff exponencial via tenacity
  - API simplificada: baixar_lei(codigo) ou baixar_lei_url(url, fonte)
"""

import hashlib
import logging
import time
import threading
from pathlib import Path
from typing import Optional

import requests
import yaml
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from adapters import get_adapter

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Configuração
# ─────────────────────────────────────────────────────────────

CACHE_DIR   = Path("cache/html")
CONFIG_PATH = Path(__file__).parent / "config" / "leis.yaml"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ─────────────────────────────────────────────────────────────
# Catálogo de leis (carregado uma vez, em memória)
# ─────────────────────────────────────────────────────────────

def _carregar_catalogo(path: Path = CONFIG_PATH) -> dict:
    """Carrega e retorna o catálogo de leis do YAML."""
    if not path.exists():
        logger.warning(f"Catálogo não encontrado: {path}. Usando configuração mínima.")
        return {"leis": {}, "fontes": {}}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


_CATALOGO: dict = _carregar_catalogo()
_LEIS:  dict = _CATALOGO.get("leis", {})
_FONTES: dict = _CATALOGO.get("fontes", {})


def listar_leis() -> dict[str, str]:
    """Retorna dicionário {codigo: nome} de todas as leis no catálogo."""
    return {cod: cfg.get("nome", cod) for cod, cfg in _LEIS.items()}


def info_lei(codigo: str) -> Optional[dict]:
    """Retorna a configuração de uma lei pelo código, ou None se não encontrada."""
    return _LEIS.get(str(codigo))


# ─────────────────────────────────────────────────────────────
# Rate limiter por domínio (token bucket thread-safe)
# ─────────────────────────────────────────────────────────────

class _RateLimiter:
    """
    Token bucket por domínio.
    Garante no máximo `rpm` requisições por minuto por domínio.
    Thread-safe para uso com asyncio/threads futuras.
    """

    def __init__(self):
        self._locks:  dict[str, threading.Lock]  = {}
        self._tokens: dict[str, float]            = {}
        self._ultimo: dict[str, float]            = {}
        self._rpm:    dict[str, int]              = {}
        self._meta_lock = threading.Lock()

    def _garantir_dominio(self, dominio: str, rpm: int) -> None:
        with self._meta_lock:
            if dominio not in self._locks:
                self._locks[dominio]  = threading.Lock()
                self._tokens[dominio] = float(rpm)   # começa cheio
                self._ultimo[dominio] = time.monotonic()
                self._rpm[dominio]    = rpm

    def aguardar(self, dominio: str, rpm: int = 20) -> None:
        """
        Bloqueia até que um token esteja disponível para o domínio.
        Chame antes de cada requisição HTTP.
        """
        self._garantir_dominio(dominio, rpm)

        with self._locks[dominio]:
            agora     = time.monotonic()
            decorrido = agora - self._ultimo[dominio]
            self._ultimo[dominio] = agora

            # Reabastece tokens proporcionalmente ao tempo passado
            taxa = self._rpm[dominio] / 60.0   # tokens por segundo
            self._tokens[dominio] = min(
                float(self._rpm[dominio]),
                self._tokens[dominio] + decorrido * taxa,
            )

            if self._tokens[dominio] >= 1.0:
                self._tokens[dominio] -= 1.0
            else:
                # Precisa esperar até ter 1 token
                espera = (1.0 - self._tokens[dominio]) / taxa
                logger.debug(f"Rate limit [{dominio}]: aguardando {espera:.2f}s")
                time.sleep(espera)
                self._tokens[dominio] = 0.0


_rate_limiter = _RateLimiter()


def _rpm_para_dominio(fonte: str) -> tuple[str, int]:
    """Retorna (dominio, rpm) para uma fonte a partir do catálogo."""
    cfg = _FONTES.get(fonte, {})
    dominio = cfg.get("dominio", fonte)
    rpm     = cfg.get("rate_limit_rpm", 20)
    return dominio, rpm


# ─────────────────────────────────────────────────────────────
# Cache helpers
# ─────────────────────────────────────────────────────────────

def _cache_path(url: str) -> Path:
    nome = hashlib.md5(url.encode()).hexdigest()
    return CACHE_DIR / f"{nome}.html"


def _carregar_cache(url: str) -> Optional[bytes]:
    path = _cache_path(url)
    if path.exists():
        logger.info(f"[cache] HIT: {url}")
        return path.read_bytes()
    return None


def _salvar_cache(url: str, conteudo: bytes) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(url).write_bytes(conteudo)
    logger.debug(f"[cache] Salvo: {_cache_path(url)}")


# ─────────────────────────────────────────────────────────────
# Requisição HTTP com retry
# ─────────────────────────────────────────────────────────────

def _fazer_requisicao(url: str, timeout: int = 25) -> bytes:
    """
    Executa requisição HTTP com retry automático.
    O rate limiting é aplicado ANTES da chamada (pelo chamador).
    """

    @retry(
        retry=retry_if_exception_type((
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.HTTPError,
        )),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _get() -> bytes:
        logger.info(f"[http] GET {url}")
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.content

    return _get()


# ─────────────────────────────────────────────────────────────
# API pública — baixar por código do catálogo
# ─────────────────────────────────────────────────────────────

def baixar_lei(
    codigo: str,
    usar_cache: bool = True,
) -> str:
    """
    Baixa e extrai o texto limpo de uma lei pelo código do catálogo.

    Args:
        codigo:     Código da lei (ex: '9394', '10406', 'cp').
        usar_cache: Se True, usa HTML em disco se disponível.

    Returns:
        Texto limpo da lei, pronto para o parser.

    Raises:
        KeyError:  Se o código não estiver no catálogo.
        Exception: Em caso de falha no download após retries.
    """
    cfg = _LEIS.get(str(codigo))
    if cfg is None:
        leis_disponiveis = ", ".join(_LEIS.keys())
        raise KeyError(
            f"Lei '{codigo}' não encontrada no catálogo. "
            f"Disponíveis: {leis_disponiveis}"
        )

    url    = cfg["url"]
    fonte  = cfg.get("fonte", "planalto")

    logger.info(f"[download] Lei {codigo} — {cfg.get('nome', '')} [{fonte}]")
    return baixar_lei_url(url, fonte=fonte, usar_cache=usar_cache)


def baixar_lei_url(
    url: str,
    fonte: str = "planalto",
    usar_cache: bool = True,
) -> str:
    """
    Baixa e extrai o texto limpo de uma lei diretamente por URL.

    Args:
        url:        URL completa da lei.
        fonte:      Nome da fonte para selecionar o adapter correto.
        usar_cache: Se True, usa HTML em disco se disponível.

    Returns:
        Texto limpo da lei.
    """
    # 1. Cache
    html_bytes = _carregar_cache(url) if usar_cache else None

    # 2. Download com rate limit
    if html_bytes is None:
        dominio, rpm = _rpm_para_dominio(fonte)
        _rate_limiter.aguardar(dominio, rpm)

        cfg_fonte = _FONTES.get(fonte, {})
        timeout   = cfg_fonte.get("timeout_segundos", 25)

        html_bytes = _fazer_requisicao(url, timeout=timeout)

        if usar_cache:
            _salvar_cache(url, html_bytes)

    # 3. Extração de texto via adapter
    adapter = get_adapter(fonte)
    return adapter.extrair_texto(html_bytes)


# ─────────────────────────────────────────────────────────────
# Compatibilidade com a API antiga (pipeline.py existente)
# ─────────────────────────────────────────────────────────────

def baixar_lei_legacy(
    url: str,
    usar_cache: bool = True,
    encoding: str = "latin-1",
) -> str:
    """
    API de compatibilidade com o downloader v1.
    Usa o adapter Planalto independente da URL.
    Prefer usar baixar_lei(codigo) ou baixar_lei_url(url, fonte).
    """
    return baixar_lei_url(url, fonte="planalto", usar_cache=usar_cache)


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    ap = argparse.ArgumentParser(description="Downloader de leis brasileiras")
    ap.add_argument("--lei",    help="Código da lei no catálogo (ex: 9394)")
    ap.add_argument("--url",    help="URL direta da lei")
    ap.add_argument("--fonte",  default="planalto", help="Fonte: planalto|senado|camara")
    ap.add_argument("--saida",  default="raw_lei.txt", help="Arquivo de saída")
    ap.add_argument("--sem-cache", action="store_true")
    ap.add_argument("--listar", action="store_true", help="Lista leis disponíveis no catálogo")
    args = ap.parse_args()

    if args.listar:
        print("\nLeis disponíveis no catálogo:")
        for cod, nome in listar_leis().items():
            print(f"  {cod:10} {nome}")
        sys.exit(0)

    if args.lei:
        texto = baixar_lei(args.lei, usar_cache=not args.sem_cache)
        saida = args.saida if args.saida != "raw_lei.txt" else f"raw_{args.lei}.txt"
    elif args.url:
        texto = baixar_lei_url(args.url, fonte=args.fonte, usar_cache=not args.sem_cache)
        saida = args.saida
    else:
        print("Use --lei CODIGO ou --url URL. Use --listar para ver leis disponíveis.")
        sys.exit(1)

    Path(saida).write_text(texto, encoding="utf-8")
    print(f"Salvo em '{saida}' ({len(texto):,} caracteres)")