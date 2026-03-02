from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import json
import logging
import yaml
from typing import Dict, List, Optional
from pydantic import BaseModel

import pipeline
from downloader import listar_leis

app = FastAPI(title="Leis API", description="API para processamento e curadoria de leis brasileiras")

# Configuração de CORS para permitir que o futuro frontend acesse a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Modelos Pydantic
class ArtigoUpdate(BaseModel):
    texto: Optional[str] = None
    estrutura: Optional[List[dict]] = None
    confianca: Optional[float] = None

class PipelineResponse(BaseModel):
    codigo: str
    status: str
    mensagem: str

# Endpoints

@app.get("/leis/catalogo")
def get_catalogo():
    """Lista todas as leis disponíveis no catálogo."""
    try:
        return listar_leis()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/leis/{codigo}")
def get_lei(codigo: str):
    """Retorna a estrutura JSON de uma lei específica."""
    path = Path(f"struct_{codigo}.json")
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Estrutura da lei {codigo} não encontrada. Execute o pipeline primeiro.")
    
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

@app.post("/pipeline/{codigo}", response_model=PipelineResponse)
def trigger_pipeline(codigo: str, background_tasks: BackgroundTasks):
    """Aciona o pipeline de processamento para uma lei."""
    # Verifica se a lei existe no catálogo
    catalogo = listar_leis()
    if codigo not in catalogo:
        raise HTTPException(status_code=404, detail=f"Lei {codigo} não encontrada no catálogo.")

    # Executa o pipeline de forma síncrona para simplificar o fluxo inicial de 100% precisão
    # Se for muito demorado, moveríamos para background_tasks
    try:
        resultado = pipeline.run(codigo=codigo, usar_cache=True)
        return {
            "codigo": codigo,
            "status": "sucesso",
            "mensagem": f"Pipeline concluído para a lei {codigo}. {len(resultado.get('estrutura', {}).get('titulos', []))} blocos detectados."
        }
    except Exception as e:
        logger.error(f"Erro no pipeline: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar pipeline: {str(e)}")

def find_article_mut(node, article_id):
    """Busca e permite mutação de um artigo na estrutura recursiva."""
    if isinstance(node, dict):
        if node.get("tipo") == "artigo" and node.get("id") == article_id:
            return node
        for key in ("titulos", "filhos", "artigos", "estrutura"):
            if key in node and isinstance(node[key], list):
                for item in node[key]:
                    found = find_article_mut(item, article_id)
                    if found: return found
    elif isinstance(node, list):
        for item in node:
            found = find_article_mut(item, article_id)
            if found: return found
    return None

@app.patch("/leis/{codigo}/artigos/{artigo_id}")
def update_artigo(codigo: str, artigo_id: str, update: ArtigoUpdate):
    """Atualiza um artigo específico na estrutura da lei (correção manual)."""
    path = Path(f"struct_{codigo}.json")
    if not path.exists():
        raise HTTPException(status_code=404, detail="JSON da lei não encontrado.")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    artigo = find_article_mut(data, artigo_id)
    if not artigo:
        raise HTTPException(status_code=404, detail=f"Artigo {artigo_id} não encontrado na lei {codigo}.")

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

    return {"status": "sucesso", "artigo_id": artigo_id}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
