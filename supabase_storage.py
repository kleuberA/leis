import os
import logging
from typing import Dict, Any, Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

class SupabaseStorage:
    def __init__(self):
        self.url = SUPABASE_URL
        self.key = SUPABASE_KEY
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }

    def _post(self, table: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            with httpx.Client() as client:
                r = client.post(f"{self.url}/rest/v1/{table}", headers=self.headers, json=data)
                r.raise_for_status()
                res = r.json()
                return res[0] if res else None
        except Exception as e:
            logger.error(f"Error inserting into {table}: {e}")
            return None

    def _get_by_url(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            with httpx.Client() as client:
                r = client.get(f"{self.url}/rest/v1/leis?url_origem=eq.{url}", headers=self.headers)
                r.raise_for_status()
                res = r.json()
                return res[0] if res else None
        except Exception as e:
            logger.error(f"Error fetching law by URL: {e}")
            return None

    def salvar_lei_completa(self, estrutura: Dict[str, Any], url_origem: str, hash_html: str):
        """Salva toda a hierarquia no Supabase com detecção de mudança."""
        info = estrutura.get("lei", {})
        
        # Detecção de Mudança
        lei_existente = self._get_by_url(url_origem)
        if lei_existente:
            if lei_existente.get("hash_html") == hash_html:
                logger.info(f"Sem mudanças detectadas para a lei {url_origem}")
                return True
            else:
                logger.warning(f"MUDANÇA DETECTADA! Criando nova versão para {url_origem}")
                # Aqui poderíamos implementar logicamente o versionamento (ex: criar backup)
                # Por simplicidade e conforme pedido, vamos atualizar os dados existentes
                # ou marcar para revisão.
                needs_review = True
        else:
            needs_review = False

        # 1. Salvar/Atualizar Lei
        lei_data = {
            "nome": info.get("nome", "Sem Nome"),
            "tipo": self._mapear_tipo_lei(info.get("tipo", "Outro")),
            "ementa": info.get("ementa", ""),
            "data_publicacao": info.get("data_publicacao"),
            "orgao_emissor": info.get("orgao_emissor", "Planalto"),
            "url_origem": url_origem,
            "hash_html": hash_html,
            "status": "Em vigor",
            "confidence_avg": estrutura.get("confianca_media", 1.0),
            "needs_review": needs_review,
            "atualizado_em": "now()"
        }
        
        if lei_existente:
            # Update existing
            id_lei = lei_existente["id_lei"]
            # Para evitar duplicidade de artigos em re-processamento, idealmente limparíamos os artigos antigos
            # ou usaríamos um sistema de upsert robusto.
            # Vou assumir que queremos limpar para re-popular se mudou.
            self._limpar_estrutura_lei(id_lei)
            self._update("leis", {"id_lei": id_lei}, lei_data)
        else:
            lei_salva = self._post("leis", lei_data)
            if not lei_salva: return False
            id_lei = lei_salva["id_lei"]
        
        # 2. Salvar Hierarquia Recurssivamente (parser retorna 'titulos')
        self._salvar_filhos(estrutura.get("titulos", []), id_lei)
        
        return True

    def _update(self, table: str, filters: Dict[str, Any], data: Dict[str, Any]):
        try:
            with httpx.Client() as client:
                query = "&".join([f"{k}=eq.{v}" for k, v in filters.items()])
                r = client.patch(f"{self.url}/rest/v1/{table}?{query}", headers=self.headers, json=data)
                r.raise_for_status()
        except Exception as e:
            logger.error(f"Error updating {table}: {e}")

    def _limpar_estrutura_lei(self, id_lei: int):
        """Remove artigos e estruturas intermediárias para re-população."""
        # A ordem importa por causa de FKs
        for tab in ["artigos", "subsecoes", "secoes", "capitulos", "titulos", "livros", "partes"]:
            try:
                with httpx.Client() as client:
                    client.delete(f"{self.url}/rest/v1/{tab}?id_lei=eq.{id_lei}", headers=self.headers)
            except: pass

    def _mapear_tipo_lei(self, tipo: str) -> str:
        mapeamento = {
            "lei": "Lei Ordinária",
            "lcp": "Lei Complementar",
            "del": "Decreto-Lei",
            "mpv": "Medida Provisória",
            "const": "Constituição"
        }
        return mapeamento.get(tipo.lower(), "Outro")

    def _salvar_filhos(self, filhos: list, id_lei: int, ids_superiores: Dict[str, int] = None):
        if ids_superiores is None:
            ids_superiores = {}

        for item in filhos:
            tipo = item.get("tipo")
            
            if tipo == "artigo":
                from pipeline import concatenar_texto_artigo
                texto_concatenado = concatenar_texto_artigo(item)
                artigo_data = {
                    "id_lei": id_lei,
                    "numero": item.get("numero"),
                    "ordem": item.get("ordem"),
                    "texto": texto_concatenado,
                    "confianca": item.get("confianca"),
                    "reparado_ia": item.get("reparado_ia", False),
                    **ids_superiores
                }
                self._post("artigos", artigo_data)
            else:
                # É um nível hierárquico
                tabela = self._tipo_para_tabela(tipo)
                if not tabela: continue
                
                meta_data = {
                    "id_lei": id_lei,
                    "nome": item.get("numero", ""),
                    "nome_completo": item.get("nome", ""),
                    "ordem": item.get("ordem", 0),
                    **ids_superiores
                }
                
                salvo = self._post(tabela, meta_data)
                if salvo:
                    # Atualiza ids superiores para os netos
                    novos_ids = ids_superiores.copy()
                    novos_ids[f"id_{tipo}"] = salvo[f"id_{tipo}"]
                    
                    # Salva filhos ou artigos
                    netos = item.get("filhos", [])
                    if not netos and "artigos" in item:
                        netos = item["artigos"]
                        
                    self._salvar_filhos(netos, id_lei, novos_ids)

    def _tipo_para_tabela(self, tipo: str) -> Optional[str]:
        tabelas = {
            "parte": "partes",
            "livro": "livros",
            "titulo": "titulos",
            "capitulo": "capitulos",
            "secao": "secoes",
            "subsecao": "subsecoes"
        }
        return tabelas.get(tipo)

storage = SupabaseStorage()
