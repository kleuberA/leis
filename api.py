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
import json
import logging
import re
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field

import settings
import pipeline
from downloader import listar_leis
from parser import iterar_artigos

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
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
    """Carrega o JSON estruturado de uma lei."""
    path = _data_path("struct", codigo)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "type": "not_found",
                "title": "Lei não processada",
                "detail": f"A lei '{codigo}' ainda não foi processada pelo pipeline. Execute POST /api/v1/pipeline/{codigo} primeiro.",
            },
        )
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


def _executar_pipeline_background(codigo: str):
    """Executa o pipeline como tarefa de background."""
    try:
        _pipeline_jobs[codigo] = PipelineStatus(
            codigo=codigo,
            status="processando",
            mensagem="Pipeline em execução...",
            iniciado_em=datetime.now().isoformat(),
        )
        resultado = pipeline.run(codigo=codigo, usar_cache=True)
        total_blocos = len(resultado.get("estrutura", {}).get("titulos", []))
        _pipeline_jobs[codigo] = PipelineStatus(
            codigo=codigo,
            status="concluido",
            mensagem=f"Pipeline concluído. {total_blocos} blocos detectados.",
            iniciado_em=_pipeline_jobs[codigo].iniciado_em,
            concluido_em=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Erro no pipeline para {codigo}: {e}")
        _pipeline_jobs[codigo] = PipelineStatus(
            codigo=codigo,
            status="erro",
            mensagem=f"Erro: {str(e)[:200]}",
            iniciado_em=_pipeline_jobs.get(codigo, PipelineStatus(codigo=codigo, status="erro")).iniciado_em,
            concluido_em=datetime.now().isoformat(),
        )


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
                "processada": _data_path("struct", cod).exists(),
            }
        return resultado
    except Exception as e:
        logger.error(f"Erro ao carregar catálogo: {e}")
        raise HTTPException(status_code=500, detail={
            "type": "internal_error",
            "title": "Erro interno",
            "detail": "Não foi possível carregar o catálogo de leis.",
        })


# ─── Lei Individual (resumo) ────────────────────────────────


@app.get("/api/v1/leis/{codigo}", response_model=LeiResumo, tags=["Leis"])
def get_lei_resumo(codigo: str):
    """Retorna um resumo de uma lei (metadados, contagens)."""
    data = _carregar_lei_json(codigo)
    artigos = _coletar_artigos_lista(data)
    return {
        "codigo": data.get("lei", {}).get("codigo", codigo),
        "nome": data.get("lei", {}).get("ementa", "Não identificada"),
        "total_artigos": len(artigos),
        "total_titulos": len(data.get("titulos", [])),
        "processada": True,
    }


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


@app.post("/api/v1/pipeline/{codigo}", response_model=PipelineResponse, tags=["Pipeline"])
def trigger_pipeline(
    codigo: str,
    background_tasks: BackgroundTasks,
    _auth: bool = Depends(verify_api_key),
):
    """
    Inicia o pipeline de processamento para uma lei (assíncrono).
    Use GET /api/v1/pipeline/{codigo}/status para acompanhar.
    Requer header X-API-Key.
    """
    catalogo = listar_leis()
    if codigo not in catalogo:
        raise HTTPException(status_code=404, detail={
            "type": "not_found",
            "title": "Lei não encontrada",
            "detail": f"A lei '{codigo}' não existe no catálogo.",
        })

    # Verifica se já está processando
    job = _pipeline_jobs.get(codigo)
    if job and job.status == "processando":
        return {
            "codigo": codigo,
            "status": "ja_processando",
            "mensagem": f"Pipeline para '{codigo}' já está em execução.",
        }

    # Inicia o pipeline em background
    _pipeline_jobs[codigo] = PipelineStatus(
        codigo=codigo,
        status="pendente",
        mensagem="Pipeline enfileirado.",
        iniciado_em=datetime.now().isoformat(),
    )
    background_tasks.add_task(_executar_pipeline_background, codigo)

    return {
        "codigo": codigo,
        "status": "iniciado",
        "mensagem": f"Pipeline iniciado para '{codigo}'. Acompanhe em GET /api/v1/pipeline/{codigo}/status",
    }


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


# ─── Startup ─────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT)
