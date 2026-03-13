"""
api.py — API REST para processamento e curadoria de leis brasileiras.

Endpoints:
  GET  /api/v1/health                          — Health check
  GET  /api/v1/leis/catalogo                   — Lista leis do catálogo
  GET  /api/v1/leis/{codigo}                   — Resumo de uma lei
  GET  /api/v1/leis/{codigo}/artigos           — Artigos com paginação
  GET  /api/v1/leis/{codigo}/artigos/{artigo_id} — Artigo individual
  GET  /api/v1/leis/{codigo}/busca             — Busca textual nos artigos
  GET  /api/v1/leis/{codigo}/crossrefs         — Referências cruzadas
  GET  /api/v1/leis/{codigo}/relatorio         — Relatório de validação
  POST /api/v1/pipeline/{codigo}               — Inicia pipeline (protegido)
  GET  /api/v1/pipeline/{codigo}/status        — Status do pipeline
  PATCH /api/v1/leis/{codigo}/artigos/{artigo_id} — Corrige artigo (protegido)
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Query, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pathlib import Path
import os
import json
import logging
import re
import queue
import asyncio
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from functools import lru_cache

import settings
import pipeline
from downloader import info_lei, atualizar_lei_catalogo
from parser import iterar_artigos

# Import storage safely - may fail if Supabase is not configured
try:
    from supabase_storage import storage
except Exception:
    storage = None

# ─── Cache em Memória ────────────────────────────────────────
# Cache para os JSONs estruturados das leis (ex: Código Civil é pesado)
@lru_cache(maxsize=10)
def _get_lei_cache(codigo: str, mtime: float):
    """
    Carrega o JSON e faz cache. 
    O mtime é usado como parte da chave para invalidar se o arquivo mudar.
    """
    path = _data_path("struct", codigo)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# ─── Logging ─────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ─── App ─────────────────────────────────────────────────────

app = FastAPI(
    title="Leis API",
    description="API para processamento, consulta e curadoria de leis brasileiras",
    version="1.0.0",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
)

# CORS — origens permitidas (separar por vírgula no .env)
_cors_raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173,http://localhost:8000")
CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Autenticação ────────────────────────────────────────────

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: Optional[str] = Security(api_key_header)):
    """Verifica a API key para endpoints protegidos."""
    if not settings.API_SECRET_KEY:
        # Se não configurou chave, permite acesso (desenvolvimento)
        return True
    if api_key != settings.API_SECRET_KEY:
        raise HTTPException(
            status_code=401,
            detail={
                "type": "authentication_error",
                "title": "Chave de API inválida",
                "detail": "O header X-API-Key é obrigatório e deve conter uma chave válida.",
            },
        )
    return True

# ─── Modelos Pydantic ────────────────────────────────────────


class ErrorResponse(BaseModel):
    type: str = Field(..., description="Tipo do erro")
    title: str = Field(..., description="Título curto do erro")
    detail: str = Field(..., description="Detalhes do erro")


class LeiResumo(BaseModel):
    codigo: str
    nome: str
    total_artigos: int
    total_titulos: int
    processada: bool


class ArtigoPaginado(BaseModel):
    id: str
    ordem: int
    numero: str
    confianca: float
    verificado_manual: bool = False
    reparado_ia: bool = False
    tem_estrutura: bool


class PaginacaoMeta(BaseModel):
    page: int
    per_page: int
    total: int
    total_pages: int


class ArtigosResponse(BaseModel):
    artigos: List[ArtigoPaginado]
    paginacao: PaginacaoMeta


class LeiCatalogoInput(BaseModel):
    codigo: str = Field(..., description="Código identificador da lei (ex: 9394, clt)")
    nome: str = Field(..., description="Nome completo da lei")
    url: str = Field(..., description="URL oficial da lei (preferencialmente compilada)")
    fonte: str = Field("planalto", description="Fonte (planalto, senado, camara)")
    encoding: str = Field("latin-1", description="Encoding esperado")
    tags: List[str] = Field(default_factory=list, description="Tags de agrupamento")


class ArtigoDetalhado(BaseModel):
    id: str
    ordem: int
    numero: str
    confianca: float
    verificado_manual: bool = False
    reparado_ia: bool = False
    estrutura: list
    alteracoes: list = []


class BuscaResult(BaseModel):
    artigo_id: str
    numero: str
    trecho: str
    confianca: float


class ArtigoUpdate(BaseModel):
    texto: Optional[str] = None
    estrutura: Optional[List[dict]] = None
    confianca: Optional[float] = None


class ParserOptions(BaseModel):
    tem_rubricas: bool = Field(False, description="Ativa extração de rubricas de artigos")
    rigor: str = Field("normal", description="Nível de rigor da normalização (normal, alto)")


class PipelineUrlRequest(BaseModel):
    url: str = Field(..., description="URL da lei")
    fonte: str = Field("planalto", description="Fonte da lei (planalto, senado, camara)")
    opcoes: Optional[ParserOptions] = None


class LeiMetadataUpdate(BaseModel):
    nome: Optional[str] = Field(None, description="Novo nome da lei")
    url: Optional[str] = Field(None, description="Nova URL da lei")
    tags: Optional[List[str]] = Field(None, description="Novas tags")
    fonte: Optional[str] = Field(None, description="Nova fonte (planalto, senado, camara)")


class PipelineResponse(BaseModel):
    codigo: str
    status: str
    mensagem: str


class PipelineStatus(BaseModel):
    codigo: str
    status: str  # "pendente", "processando", "concluido", "erro"
    mensagem: str = ""
    iniciado_em: Optional[str] = None
    concluido_em: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str


# ─── Estado do Pipeline (em memória — para produção usar Redis/DB) ───

_pipeline_jobs: dict[str, PipelineStatus] = {}
_pipeline_logs: dict[str, queue.Queue] = {}

# ─── Helpers ─────────────────────────────────────────────────


def _data_path(tipo: str, codigo: str) -> Path:
    """Retorna o caminho do arquivo de dados."""
    prefixos = {
        "raw": "raw",
        "struct": "struct",
        "crossrefs": "crossrefs",
        "relatorio": "relatorio",
    }
    prefixo = prefixos.get(tipo, tipo)

    # Primeiro tenta no data/ organizado
    organizado = settings.DATA_DIR / tipo / f"{prefixo}_{codigo}.json"
    if organizado.exists():
        return organizado

    # Fallback: arquivos legados no root
    legado = settings.BASE_DIR / f"{prefixo}_{codigo}.json"
    if legado.exists():
        return legado

    # Se não existe em nenhum, retorna o caminho organizado como destino
    return organizado


def _carregar_lei_json(codigo: str) -> dict:
    """Carrega o JSON estruturado de uma lei (com cache opcional)."""
    path = _data_path("struct", codigo)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "type": "not_found",
                "title": "Lei não processada",
                "detail": f"A lei '{codigo}' ainda não foi processada pelo pipeline.",
            },
        )
    
    if settings.ENABLE_API_CACHE:
        # Usa o timestamp de modificação para invalidar o cache automaticamente se o arquivo mudar
        mtime = os.path.getmtime(path)
        return _get_lei_cache(codigo, mtime)
    
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _coletar_artigos_lista(data: dict) -> list:
    """Coleta todos os artigos da estrutura em ordem de documento."""
    return list(iterar_artigos(data))


def _artigo_resumo(art: dict) -> dict:
    """Gera resumo de um artigo para a listagem paginada."""
    return {
        "id": art.get("id", ""),
        "ordem": art.get("ordem", 0),
        "numero": art.get("numero", ""),
        "confianca": art.get("confianca", 1.0),
        "verificado_manual": art.get("verificado_manual", False),
        "reparado_ia": art.get("reparado_ia", False),
        "tem_estrutura": bool(art.get("estrutura")),
    }


def _texto_artigo_completo(artigo: dict) -> str:
    """Extrai todo o texto visível de um artigo para busca."""
    partes = []

    def _extrair(obj):
        if isinstance(obj, dict):
            if "texto" in obj and isinstance(obj["texto"], str):
                partes.append(obj["texto"])
            for k in ("estrutura", "conteudo", "incisos", "alineas"):
                if k in obj:
                    _extrair(obj[k])
        elif isinstance(obj, list):
            for item in obj:
                _extrair(item)

    _extrair(artigo.get("estrutura", []))
    return " ".join(partes)


def find_article_mut(node, article_id):
    """Busca e permite mutação de um artigo na estrutura recursiva."""
    if isinstance(node, dict):
        if node.get("tipo") == "artigo" and node.get("id") == article_id:
            return node
        for key in ("titulos", "filhos", "artigos", "estrutura"):
            if key in node and isinstance(node[key], list):
                for item in node[key]:
                    found = find_article_mut(item, article_id)
                    if found:
                        return found
    elif isinstance(node, list):
        for item in node:
            found = find_article_mut(item, article_id)
            if found:
                return found
    return None


# ─── Background task ─────────────────────────────────────────


def _executar_pipeline_background(codigo: str, opcoes: dict = None, url: str = None, fonte: str = "planalto"):
    """Executa o pipeline e atualiza o status global, alimentando a fila de logs."""
    job = _pipeline_jobs.get(codigo)
    if not job: return

    log_queue = _pipeline_logs.get(codigo)
    
    def callback(msg):
        if log_queue:
            log_queue.put(msg)
        if job:
            job.mensagem = msg

    try:
        job.status = "processando"
        pipeline.run(
            codigo=codigo, 
            url=url,
            fonte=fonte,
            saida_dir=settings.DATA_DIR, 
            opcoes=opcoes,
            progress_callback=callback,
            persistir=False # Sempre manual via API agora
        )
        job.status = "concluido"
        job.mensagem = "Processamento finalizado. Pronto para salvar."
    except Exception as e:
        logger.error(f"Erro no pipeline background ({codigo}): {e}")
        job.status = "erro"
        job.mensagem = f"Erro no processamento: {str(e)}"
        if log_queue:
            log_queue.put(f"ERRO: {str(e)}")
    finally:
        if log_queue:
            log_queue.put(None) # Sinal de fim de stream


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════

# ─── Health ──────────────────────────────────────────────────


@app.get("/api/v1/health", response_model=HealthResponse, tags=["Sistema"])
def health_check():
    """Verifica se a API está funcionando."""
    return {
        "status": "ok",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
    }


# ─── Catálogo ────────────────────────────────────────────────


@app.get("/api/v1/leis/catalogo", tags=["Leis"])
def get_catalogo(tag: Optional[str] = Query(None, description="Filtrar por tag")):
    """Lista todas as leis disponíveis no catálogo, opcionalmente filtradas por tag."""
    try:
        import yaml

        config_path = settings.CONFIG_PATH
        with open(config_path, encoding="utf-8") as f:
            catalogo = yaml.safe_load(f)

        leis = catalogo.get("leis", {})
        resultado = {}
        for cod, cfg in leis.items():
            if tag and tag not in cfg.get("tags", []):
                continue
            resultado[cod] = {
                "nome": cfg.get("nome", cod),
                "tags": cfg.get("tags", []),
                "fonte": cfg.get("fonte", "planalto"),
                "url": cfg.get("url", ""),
                "processada": _data_path("struct", cod).exists(),
                "id_banco": (storage._get_by_url(cfg.get("url", "")) or {}).get("id_lei") if (cfg.get("url") and storage) else None
            }
        return resultado
    except Exception as e:
        logger.error(f"Erro ao carregar catálogo: {e}")
        raise HTTPException(status_code=500, detail={
            "type": "internal_error",
            "title": "Erro interno",
            "detail": "Não foi possível carregar o catálogo de leis.",
        })


@app.post("/api/v1/leis/catalogo", tags=["Leis"])
def add_to_catalogo(lei: LeiCatalogoInput, _auth: bool = Depends(verify_api_key)):
    """ Adiciona ou atualiza uma lei no catálogo (config/leis.yaml). """
    try:
        import yaml
        config_path = settings.CONFIG_PATH

        if not config_path.parent.exists():
            config_path.parent.mkdir(parents=True)

        if not config_path.exists():
            data = {"leis": {}, "fontes": {}}
        else:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {"leis": {}, "fontes": {}}

        if "leis" not in data:
            data["leis"] = {}

        data["leis"][lei.codigo] = {
            "nome": lei.nome,
            "url": lei.url,
            "fonte": lei.fonte,
            "encoding": lei.encoding,
            "tags": lei.tags
        }

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)

        logger.info(f"Lei {lei.codigo} adicionada/atualizada no catálogo por API.")
        return {"status": "sucesso", "codigo": lei.codigo}
        
    except Exception as e:
        logger.error(f"Erro ao atualizar catálogo: {e}")
        raise HTTPException(status_code=500, detail={
            "type": "internal_error",
            "title": "Erro ao atualizar catálogo",
            "detail": str(e)
        })


@app.patch("/api/v1/leis/{codigo}/metadata", tags=["Leis"])
async def patch_lei_metadata(
    codigo: str, 
    update: LeiMetadataUpdate,
    _auth: bool = Depends(verify_api_key)
):
    """
    Atualiza parcialmente os metadados de uma lei no catálogo (nome, tags, url, etc).
    """
    # Filtra apenas campos fornecidos
    dados = {k: v for k, v in update.model_dump().items() if v is not None}
    
    if not dados:
        raise HTTPException(status_code=400, detail="Nenhum dado para informar")

    sucesso = atualizar_lei_catalogo(codigo, dados)
    
    if not sucesso:
        raise HTTPException(status_code=404, detail=f"Lei '{codigo}' não encontrada no catálogo")

    return {
        "status": "sucesso",
        "mensagem": f"Metadados da lei '{codigo}' atualizados",
        "codigo": codigo,
        "campos_atualizados": list(dados.keys())
    }


# ─── Lei Individual (resumo) ────────────────────────────────


@app.get("/api/v1/leis/{codigo}", response_model=LeiResumo, tags=["Leis"])
def get_lei_resumo(codigo: str):
    """Retorna um resumo de uma lei (metadados, contagens)."""
    data = _carregar_lei_json(codigo)
    artigos = _coletar_artigos_lista(data)
    lei_info = data.get("lei", {})
    url = lei_info.get("url", "")
    id_banco = (storage._get_by_url(url) or {}).get("id_lei") if (url and storage) else None

    return {
        "codigo": lei_info.get("codigo", codigo),
        "nome": lei_info.get("ementa", "Não identificada"),
        "url": url,
        "total_artigos": len(artigos),
        "total_titulos": len(data.get("titulos", [])),
        "processada": True,
        "id_banco": str(id_banco) if id_banco else None
    }


@app.get("/api/v1/leis/{codigo}/estrutura", tags=["Leis"])
def get_lei_estrutura(codigo: str):
    """Retorna a estrutura completa da lei (JSON bruto)."""
    return _carregar_lei_json(codigo)


# ─── Artigos com Paginação ──────────────────────────────────


@app.get("/api/v1/leis/{codigo}/artigos", response_model=ArtigosResponse, tags=["Artigos"])
def get_artigos(
    codigo: str,
    page: int = Query(1, ge=1, description="Número da página"),
    per_page: int = Query(20, ge=1, le=100, description="Itens por página"),
):
    """Lista artigos de uma lei com paginação."""
    data = _carregar_lei_json(codigo)
    todos = _coletar_artigos_lista(data)
    total = len(todos)

    inicio = (page - 1) * per_page
    fim = inicio + per_page
    pagina = todos[inicio:fim]

    total_pages = (total + per_page - 1) // per_page

    return {
        "artigos": [_artigo_resumo(a) for a in pagina],
        "paginacao": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
    }


# ─── Artigo Individual ──────────────────────────────────────


@app.get("/api/v1/leis/{codigo}/artigos/{artigo_id}", response_model=ArtigoDetalhado, tags=["Artigos"])
def get_artigo(codigo: str, artigo_id: str):
    """Retorna o artigo completo com toda a estrutura."""
    data = _carregar_lei_json(codigo)
    artigo = find_article_mut(data, artigo_id)
    if not artigo:
        raise HTTPException(status_code=404, detail={
            "type": "not_found",
            "title": "Artigo não encontrado",
            "detail": f"O artigo '{artigo_id}' não foi encontrado na lei '{codigo}'.",
        })
    return {
        "id": artigo.get("id", ""),
        "ordem": artigo.get("ordem", 0),
        "numero": artigo.get("numero", ""),
        "confianca": artigo.get("confianca", 1.0),
        "verificado_manual": artigo.get("verificado_manual", False),
        "reparado_ia": artigo.get("reparado_ia", False),
        "estrutura": artigo.get("estrutura", []),
        "alteracoes": artigo.get("alteracoes", []),
    }


# ─── Busca Textual ──────────────────────────────────────────


@app.get("/api/v1/leis/{codigo}/busca", tags=["Artigos"])
def buscar_artigos(
    codigo: str,
    q: str = Query(..., min_length=3, description="Termo de busca"),
    limit: int = Query(20, ge=1, le=50, description="Máximo de resultados"),
):
    """Busca textual nos artigos de uma lei."""
    data = _carregar_lei_json(codigo)
    todos = _coletar_artigos_lista(data)

    termos = q.lower().split()
    resultados = []

    for art in todos:
        texto = _texto_artigo_completo(art).lower()
        if all(t in texto for t in termos):
            # Extrai trecho relevante
            idx = texto.find(termos[0])
            inicio = max(0, idx - 50)
            fim = min(len(texto), idx + 150)
            trecho = texto[inicio:fim].strip()
            if inicio > 0:
                trecho = "..." + trecho
            if fim < len(texto):
                trecho = trecho + "..."

            resultados.append({
                "artigo_id": art.get("id", ""),
                "numero": art.get("numero", ""),
                "trecho": trecho,
                "confianca": art.get("confianca", 1.0),
            })
            if len(resultados) >= limit:
                break

    return {"query": q, "total": len(resultados), "resultados": resultados}


# ─── Cross-references ───────────────────────────────────────


@app.get("/api/v1/leis/{codigo}/crossrefs", tags=["Análise"])
def get_crossrefs(codigo: str):
    """Retorna as referências cruzadas extraídas de uma lei."""
    path = _data_path("crossrefs", codigo)
    if not path.exists():
        raise HTTPException(status_code=404, detail={
            "type": "not_found",
            "title": "Cross-references não encontradas",
            "detail": f"Execute o pipeline para a lei '{codigo}' primeiro.",
        })
    with open(path, "r", encoding="utf-8") as f:
        refs = json.load(f)
    return {"codigo": codigo, "total": len(refs), "referencias": refs}


# ─── Relatório de Validação ──────────────────────────────────


@app.get("/api/v1/leis/{codigo}/relatorio", tags=["Análise"])
def get_relatorio(codigo: str):
    """Retorna o relatório de validação estrutural de uma lei."""
    path = _data_path("relatorio", codigo)
    if not path.exists():
        raise HTTPException(status_code=404, detail={
            "type": "not_found",
            "title": "Relatório não encontrado",
            "detail": f"Execute o pipeline para a lei '{codigo}' primeiro.",
        })
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ─── Pipeline (protegido) ───────────────────────────────────


@app.post("/api/v1/pipeline/url", response_model=PipelineResponse, tags=["Pipeline"])
def trigger_url_pipeline(
    request: PipelineUrlRequest,
    background_tasks: BackgroundTasks,
    _auth: bool = Depends(verify_api_key),
):
    """
    Inicia o pipeline a partir de uma URL direta.
    O código da lei será o MD5 da URL.
    """
    import hashlib
    url = request.url
    codigo = hashlib.md5(url.encode()).hexdigest()
    logger.info(f"Trigger URL: {url} -> {codigo}")

    # Verifica se já está processando
    job = _pipeline_jobs.get(codigo)
    if job and job.status == "processando":
        logger.info(f"Já processando: {codigo}")
        return {
            "codigo": codigo,
            "status": "ja_processando",
            "mensagem": f"A URL '{url}' já está sendo processada.",
        }

    # Baixa no foreground para garantir que a URL é válida e ter o raw
    try:
        from downloader import baixar_lei_url
        logger.info(f"Baixando URL: {url}")
        texto_limpo = baixar_lei_url(url, fonte=request.fonte, usar_cache=True)
        # Salva o raw em data/raw/
        raw_path = settings.DATA_DIR / "raw" / f"raw_{codigo}.txt"
        logger.info(f"Salvando raw em: {raw_path}")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(texto_limpo)
    except Exception as e:
        logger.error(f"Erro ao baixar URL {url}: {e}")
        raise HTTPException(status_code=400, detail={
            "type": "download_error",
            "title": "Erro de download",
            "detail": f"Não foi possível baixar a lei da URL: {str(e)}",
        })

    # Cria fila de logs
    _pipeline_logs[codigo] = queue.Queue()

    # Inicia o pipeline em background
    _pipeline_jobs[codigo] = PipelineStatus(
        codigo=codigo,
        status="pendente",
        mensagem="Download concluído. Iniciando processamento...",
        iniciado_em=datetime.now().isoformat(),
    )
    _pipeline_logs[codigo] = queue.Queue()
    
    opcoes_dict = request.opcoes.dict() if request.opcoes else None
    background_tasks.add_task(_executar_pipeline_background, codigo, opcoes_dict, url=url, fonte=request.fonte or "planalto")

    return {
        "codigo": codigo,
        "status": "iniciado",
        "mensagem": f"Processamento da URL iniciado. ID: {codigo}. Acompanhe via SSE.",
    }


@app.post("/api/v1/pipeline/{codigo}", response_model=PipelineResponse, tags=["Pipeline"])
def trigger_pipeline(
    codigo: str,
    background_tasks: BackgroundTasks,
    opcoes: Optional[ParserOptions] = None,
    _auth: bool = Depends(verify_api_key),
):
    """
    Inicia o pipeline de processamento para uma lei (assíncrono).
    Use GET /api/v1/pipeline/{codigo}/status para acompanhar.
    Requer header X-API-Key.
    """
    lei_cfg = info_lei(codigo)
    raw_path = settings.DATA_DIR / "raw" / f"raw_{codigo}.txt"
    
    if not lei_cfg and not raw_path.exists():
        raise HTTPException(status_code=404, detail={
            "type": "not_found",
            "title": "Lei não encontrada",
            "detail": f"A lei '{codigo}' não existe no catálogo e nenhum arquivo bruto foi encontrado.",
        })

    # Verifica se já está processando
    job = _pipeline_jobs.get(codigo)
    if job and job.status == "processando":
        return {
            "codigo": codigo,
            "status": "ja_processando",
            "mensagem": f"Pipeline para '{codigo}' já está em execução.",
        }

    # Cria fila de logs
    _pipeline_logs[codigo] = queue.Queue()

    # Tenta descobrir a URL e Fonte se for uma lei de URL (não no catálogo)
    url = None
    fonte = "planalto"
    
    if lei_cfg:
        url = lei_cfg.get("url")
        fonte = lei_cfg.get("fonte", "planalto")
    else:
        # Se não está no catálogo, tenta carregar do struct existente para pegar a URL
        path_struct = _data_path("struct", codigo)
        if path_struct.exists():
            try:
                with open(path_struct, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    url = data.get("lei", {}).get("url")
                    fonte = data.get("lei", {}).get("fonte", "planalto")
            except: pass

    # Inicia o pipeline em background
    _pipeline_jobs[codigo] = PipelineStatus(
        codigo=codigo,
        status="pendente",
        mensagem="Pipeline enfileirado.",
        iniciado_em=datetime.now().isoformat(),
    )
    # Extrai opções se existirem
    opcoes_dict = opcoes.dict() if opcoes else None
    background_tasks.add_task(_executar_pipeline_background, codigo, opcoes_dict, url=url, fonte=fonte)

    return {
        "codigo": codigo,
        "status": "iniciado",
        "mensagem": f"Pipeline iniciado para '{codigo}'. Acompanhe os logs via SSE.",
    }


@app.get("/api/v1/pipeline/{codigo}/events", tags=["Pipeline"])
async def pipeline_events(codigo: str):
    """Stream de logs do pipeline via Server-Sent Events (SSE)."""
    from fastapi.responses import StreamingResponse

    async def event_generator():
        q = _pipeline_logs.get(codigo)
        if not q:
            # Se não há fila, mas já foi processado, manda o status final
            if _data_path("struct", codigo).exists():
                yield "data: Processamento concluído anteriormente.\n\n"
                return
            yield "data: Nenhum pipeline ativo para este código.\n\n"
            return

        while True:
            try:
                # Usa loop assíncrono para não travar o worker
                msg = await asyncio.to_thread(q.get, timeout=5)
                if msg is None: break # Fim do pipeline
                yield f"data: {msg}\n\n"
            except queue.Empty:
                yield ": keep-alive\n\n" # SSE comment, not shown to client

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/v1/leis/{codigo}/save", tags=["Pipeline"])
def save_lei_to_db(codigo: str, _auth: bool = Depends(verify_api_key)):
    """Persiste a lei processada no Supabase (manual)."""
    from supabase_storage import storage
    from downloader import calcular_fingerprint
    
    path_struct = _data_path("struct", codigo)
    path_raw = settings.DATA_DIR / "raw" / f"raw_{codigo}.txt"
    
    if not path_struct.exists():
        raise HTTPException(status_code=404, detail="Lei não processada. Execute o pipeline primeiro.")
        
    with open(path_struct, "r", encoding="utf-8") as f:
        estrutura = json.load(f)
        
    hash_txt = "unknown"
    if path_raw.exists():
        hash_txt = calcular_fingerprint(path_raw.read_bytes())
        
    origem = estrutura.get("lei", {}).get("url", "manual")
    
    sucesso = storage.salvar_lei_completa(estrutura, origem, hash_txt)
    
    if sucesso:
        return {"status": "sucesso", "mensagem": "Lei persistida no Supabase com sucesso."}
    else:
        raise HTTPException(status_code=500, detail="Erro ao salvar no Supabase.")


@app.get("/api/v1/pipeline/{codigo}/status", response_model=PipelineStatus, tags=["Pipeline"])
def pipeline_status(codigo: str):
    """Verifica o status de processamento do pipeline."""
    job = _pipeline_jobs.get(codigo)
    if not job:
        # Verifica se já foi processado antes
        if _data_path("struct", codigo).exists():
            return PipelineStatus(
                codigo=codigo,
                status="concluido",
                mensagem="Lei já foi processada anteriormente.",
            )
        return PipelineStatus(
            codigo=codigo,
            status="nao_iniciado",
            mensagem="Pipeline nunca foi executado para esta lei.",
        )
    return job


# NOTE: Duplicate _executar_pipeline_background was removed.
# The correct version with log queue support is defined above (around line 309).


# ─── Correção Manual (protegido) ────────────────────────────


@app.patch("/api/v1/leis/{codigo}/artigos/{artigo_id}", tags=["Artigos"])
def update_artigo(
    codigo: str,
    artigo_id: str,
    update: ArtigoUpdate,
    _auth: bool = Depends(verify_api_key),
):
    """
    Atualiza um artigo específico (correção manual).
    Requer header X-API-Key.
    """
    path = _data_path("struct", codigo)
    if not path.exists():
        raise HTTPException(status_code=404, detail={
            "type": "not_found",
            "title": "Lei não processada",
            "detail": f"JSON da lei '{codigo}' não encontrado.",
        })

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    artigo = find_article_mut(data, artigo_id)
    if not artigo:
        raise HTTPException(status_code=404, detail={
            "type": "not_found",
            "title": "Artigo não encontrado",
            "detail": f"Artigo '{artigo_id}' não encontrado na lei '{codigo}'.",
        })

    # Aplica as correções
    if update.estrutura is not None:
        artigo["estrutura"] = update.estrutura
    if update.confianca is not None:
        artigo["confianca"] = update.confianca

    # Marca como verificado manualmente
    artigo["verificado_manual"] = True

    # Salva de volta
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return {"status": "sucesso", "artigo_id": artigo_id, "mensagem": "Artigo atualizado com sucesso."}


# ─── Estrutura completa (compatibilidade) ───────────────────


@app.get("/api/v1/leis/{codigo}/estrutura", tags=["Leis"])
def get_lei_estrutura(codigo: str):
    """
    Retorna a estrutura JSON completa de uma lei.
    ⚠️ Pode ser muito grande (>3 MB para leis extensas).
    Use /artigos com paginação quando possível.
    """
    return _carregar_lei_json(codigo)


@app.get("/api/v1/leis/{codigo}/raw", tags=["Leis"])
def get_lei_raw(codigo: str):
    """Retorna o texto bruto (raw) da lei."""
    path = _data_path("raw", codigo)
    # Ajuste para o nome de arquivo correto esperado por _data_path("raw", ...)
    # _data_path("raw", "cf88") retorna data/raw/raw_cf88.json? Não, pera. 
    # _data_path usa prefixo 'raw' e sufixo .json por padrão. 
    # Mas nossos arquivos raw são .txt.
    
    raw_path = settings.DATA_DIR / "raw" / f"raw_{codigo}.txt"
    if not raw_path.exists():
         raise HTTPException(status_code=404, detail={
            "type": "not_found",
            "title": "Texto bruto não encontrado",
            "detail": f"O arquivo bruto para a lei '{codigo}' não existe.",
        })
    with open(raw_path, "r", encoding="utf-8") as f:
        return {"codigo": codigo, "conteudo": f.read()}


# ─── Startup ─────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT)
