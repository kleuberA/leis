"""
supabase_storage.py — v3 (Flatten + Batch Insert)

Arquitetura ETL para persistência de leis no Supabase:
  1. Parseia a árvore JSON recursivamente
  2. Achata em arrays planos com temp_ids
  3. Insere em ordem hierárquica (pai antes do filho)
  4. Resolve FKs via mapeamento temp_id → id_real
  5. Artigos são inseridos em batch por performance
  6. Usa upsert onde possível para idempotência

Hierarquia: lei → partes → livros → titulos → subtitulos → capitulos → secoes → subsecoes → artigos
"""

import os
import json
import logging
import uuid
from typing import Dict, Any, Optional, List, Tuple
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# ─── Tipos para os arrays planos ────────────────────────────

TIPO_PARA_TABELA = {
    "parte": "partes",
    "livro": "livros",
    "titulo": "titulos",
    "subtitulo": "subtitulos",
    "capitulo": "capitulos",
    "secao": "secoes",
    "subsecao": "subsecoes",
}

# Coluna PK de cada tabela
TABELA_PK = {
    "partes": "id_parte",
    "livros": "id_livro",
    "titulos": "id_titulo",
    "subtitulos": "id_subtitulo",
    "capitulos": "id_capitulo",
    "secoes": "id_secao",
    "subsecoes": "id_subsecao",
}

# Colunas FK que cada tabela aceita (além de id_lei)
TABELA_FKS = {
    "partes": [],
    "livros": ["id_parte"],
    "titulos": ["id_parte", "id_livro"],
    "subtitulos": ["id_parte", "id_livro", "id_titulo"],
    "capitulos": ["id_parte", "id_livro", "id_titulo", "id_subtitulo"],
    "secoes": ["id_parte", "id_livro", "id_titulo", "id_capitulo"],
    "subsecoes": ["id_parte", "id_livro", "id_titulo", "id_capitulo", "id_secao"],
}

# Ordem de inserção (hierárquica)
ORDEM_INSERT = ["partes", "livros", "titulos", "subtitulos", "capitulos", "secoes", "subsecoes"]


class FlatNode:
    """Nó achatado com temp_id e referências para FKs via temp_ids."""
    def __init__(self, tabela: str, temp_id: str, data: dict, fk_temp_ids: dict):
        self.tabela = tabela
        self.temp_id = temp_id
        self.data = data              # dados básicos (nome, nome_completo, ordem)
        self.fk_temp_ids = fk_temp_ids  # ex: {"id_parte": "temp-abc123"}


class FlatArticle:
    """Artigo achatado para batch insert."""
    def __init__(self, data: dict, fk_temp_ids: dict):
        self.data = data
        self.fk_temp_ids = fk_temp_ids


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
        # Detect which optional columns exist in artigos table
        self._artigos_has_estrutura = self._check_column_exists("artigos", "estrutura")
        self._artigos_has_alteracoes = self._check_column_exists("artigos", "alteracoes")
        if not self._artigos_has_estrutura or not self._artigos_has_alteracoes:
            logger.warning(
                "Colunas JSONB faltantes na tabela artigos. "
                "Execute no SQL Editor do Supabase:\n"
                "  ALTER TABLE public.artigos ADD COLUMN IF NOT EXISTS estrutura jsonb;\n"
                "  ALTER TABLE public.artigos ADD COLUMN IF NOT EXISTS alteracoes jsonb;"
            )

    def _check_column_exists(self, table: str, column: str) -> bool:
        """Verifica se uma coluna existe na tabela via SELECT."""
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.get(
                    f"{self.url}/rest/v1/{table}?select={column}&limit=0",
                    headers=self.headers
                )
                return r.status_code < 400
        except Exception:
            return False

    # ─── HTTP helpers ────────────────────────────────────────

    def _post(self, table: str, data: Any) -> Optional[Any]:
        """POST genérico. Aceita dict (single) ou list (batch)."""
        try:
            with httpx.Client(timeout=60.0) as client:
                r = client.post(
                    f"{self.url}/rest/v1/{table}",
                    headers=self.headers,
                    json=data
                )
                if r.status_code >= 400:
                    logger.error(f"Error inserting into {table}: {r.status_code} - {r.text}")
                    return None
                res = r.json()
                if isinstance(data, list):
                    return res  # lista de registros
                return res[0] if res else None
        except Exception as e:
            logger.error(f"Exception during post to {table}: {e}")
            return None

    def _post_batch(self, table: str, items: List[dict], batch_size: int = 200) -> Optional[List[dict]]:
        """Insere em lotes para evitar payloads grandes demais."""
        all_results = []
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            result = self._post(table, batch)
            if result is None:
                logger.error(f"Batch insert falhou em {table} (lote {i // batch_size + 1})")
                return None
            all_results.extend(result)
        return all_results

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

    def _update(self, table: str, filters: Dict[str, Any], data: Dict[str, Any]):
        try:
            with httpx.Client() as client:
                query = "&".join([f"{k}=eq.{v}" for k, v in filters.items()])
                r = client.patch(f"{self.url}/rest/v1/{table}?{query}", headers=self.headers, json=data)
                if r.status_code >= 400:
                    logger.error(f"Error updating {table}: {r.status_code} - {r.text}")
                r.raise_for_status()
        except Exception as e:
            logger.error(f"Exception during update to {table}: {e}")

    def _delete(self, table: str, filters: Dict[str, Any]):
        try:
            with httpx.Client() as client:
                query = "&".join([f"{k}=eq.{v}" for k, v in filters.items()])
                r = client.delete(f"{self.url}/rest/v1/{table}?{query}", headers=self.headers)
                if r.status_code >= 400:
                    logger.error(f"Error deleting from {table}: {r.status_code} - {r.text}")
        except Exception as e:
            logger.error(f"Exception during delete from {table}: {e}")

    # ─── ETAPA 0: Limpeza (para re-processamento) ───────────

    def _limpar_estrutura_lei(self, id_lei: int):
        """Remove artigos e estruturas intermediárias para re-população.
        Ordem inversa de dependência (filhos primeiro)."""
        for tab in ["artigos", "subsecoes", "secoes", "capitulos", "subtitulos", "titulos", "livros", "partes"]:
            self._delete(tab, {"id_lei": id_lei})
        logger.info(f"  Estrutura anterior da lei {id_lei} removida.")

    # ─── ETAPA 1: Flatten (Parse → Arrays Planos) ───────────

    def _flatten_tree(self, filhos: list, id_lei: int) -> Tuple[Dict[str, List[FlatNode]], List[FlatArticle]]:
        """
        Percorre a árvore recursivamente e gera arrays planos.
        Retorna:
          - nodes_by_table: {"partes": [FlatNode, ...], "livros": [...], ...}
          - articles: [FlatArticle, ...]
        """
        nodes_by_table: Dict[str, List[FlatNode]] = {t: [] for t in ORDEM_INSERT}
        articles: List[FlatArticle] = []
        ordem_counter = {"value": 0}

        def walk(nodo: dict, ctx: dict):
            """Recursão DFS. ctx contém os temp_ids dos pais."""
            tipo = nodo.get("tipo")

            if tipo == "artigo":
                # Acumula artigo com referências por temp_id
                from pipeline import concatenar_texto_artigo
                texto_concatenado = concatenar_texto_artigo(nodo)

                art_data = {
                    "id_lei": id_lei,
                    "numero": nodo.get("numero", ""),
                    "ordem": nodo.get("ordem", ordem_counter["value"]),
                    "texto": texto_concatenado,
                    "confianca": nodo.get("confianca"),
                    "reparado_ia": nodo.get("reparado_ia", False),
                }
                # JSONB columns: ALWAYS include the key when the column exists
                # (PostgREST requires all batch objects to have identical keys)
                if self._artigos_has_estrutura:
                    estrutura_raw = nodo.get("estrutura")
                    art_data["estrutura"] = json.dumps(estrutura_raw, ensure_ascii=False) if estrutura_raw else None
                if self._artigos_has_alteracoes:
                    alteracoes_raw = nodo.get("alteracoes")
                    art_data["alteracoes"] = json.dumps(alteracoes_raw, ensure_ascii=False) if alteracoes_raw else None
                # Copia FKs do contexto (os que possuem temp_ids)
                fk_temps = {}
                for fk_col in ["id_parte", "id_livro", "id_titulo", "id_subtitulo", "id_capitulo", "id_secao", "id_subsecao"]:
                    if fk_col in ctx:
                        fk_temps[fk_col] = ctx[fk_col]

                articles.append(FlatArticle(data=art_data, fk_temp_ids=fk_temps))
                return

            tabela = TIPO_PARA_TABELA.get(tipo)
            if not tabela:
                # Tipo desconhecido — tenta descer para os filhos mesmo assim
                for filho in nodo.get("filhos", []):
                    walk(filho, ctx)
                return

            # Gera temp_id único
            temp_id = str(uuid.uuid4())
            ordem_counter["value"] += 1

            nome = nodo.get("nome", nodo.get("numero", ""))
            numero = nodo.get("numero", "")
            nome_completo = (
                f"{tipo.upper()} {numero} - {nome}".strip()
                if nome and nome != numero
                else f"{tipo.upper()} {numero}".strip()
            )

            node_data = {
                "id_lei": id_lei,
                "nome": nome,
                "nome_completo": nome_completo,
                "ordem": ordem_counter["value"],
            }

            # Coleta FKs do contexto para esta tabela
            fk_temps = {}
            for fk_col in TABELA_FKS.get(tabela, []):
                if fk_col in ctx:
                    fk_temps[fk_col] = ctx[fk_col]

            nodes_by_table[tabela].append(FlatNode(
                tabela=tabela,
                temp_id=temp_id,
                data=node_data,
                fk_temp_ids=fk_temps,
            ))

            # Atualiza contexto para os filhos
            pk_col = TABELA_PK[tabela]  # ex: "id_parte"
            new_ctx = ctx.copy()
            new_ctx[pk_col] = temp_id  # Referência por temp_id

            # Desce para os filhos
            filhos_lista = nodo.get("filhos", [])
            if not filhos_lista and "artigos" in nodo:
                filhos_lista = nodo["artigos"]
            for filho in filhos_lista:
                walk(filho, new_ctx)

        # Inicia a travessia
        for raiz in filhos:
            walk(raiz, {})

        return nodes_by_table, articles

    # ─── ETAPA 2: Insert Ordenado + Mapeamento de IDs ───────

    def _insert_with_id_mapping(self, nodes_by_table: Dict[str, List[FlatNode]]) -> Optional[Dict[str, int]]:
        """
        Insere nível a nível na ordem hierárquica.
        Mantém um mapa global: temp_id → id_real do banco.
        
        Returns:
            Mapa {temp_id: id_real} ou None se falhar.
        """
        id_map: Dict[str, int] = {}  # temp_id → id_real

        for tabela in ORDEM_INSERT:
            nodes = nodes_by_table[tabela]
            if not nodes:
                continue

            pk_col = TABELA_PK[tabela]

            # Monta os registros com FKs resolvidas
            # PostgREST requires all objects to have the same keys
            fk_cols_for_table = TABELA_FKS.get(tabela, [])
            records = []
            for node in nodes:
                record = node.data.copy()

                # Ensure ALL FK columns for this table are present
                for fk_col in fk_cols_for_table:
                    temp_ref = node.fk_temp_ids.get(fk_col)
                    if temp_ref:
                        record[fk_col] = id_map.get(temp_ref)
                    else:
                        record[fk_col] = None

                records.append(record)

            # Batch insert
            logger.info(f"  Inserindo {len(records)} registros em '{tabela}'...")
            results = self._post_batch(tabela, records)

            if results is None:
                logger.error(f"  FALHA ao inserir em {tabela}!")
                return None

            # Mapeia temp_ids → IDs reais retornados
            if len(results) != len(nodes):
                logger.error(
                    f"  Mismatch: enviamos {len(nodes)} registros para {tabela}, "
                    f"mas recebemos {len(results)} de volta."
                )
                return None

            for i, node in enumerate(nodes):
                real_id = results[i].get(pk_col)
                if real_id is not None:
                    id_map[node.temp_id] = real_id
                else:
                    logger.warning(f"  Sem PK retornada para {tabela} index {i}")

        return id_map

    # ─── ETAPA 3: Batch Insert de Artigos ───────────────────

    def _insert_articles(self, articles: List[FlatArticle], id_map: Dict[str, int]) -> bool:
        """Insere todos os artigos em batch, resolvendo FKs via id_map.
        
        PostgREST requires all objects in a batch to have the same keys,
        so we normalize all records to include every possible FK column.
        """
        if not articles:
            logger.info("  Nenhum artigo para inserir.")
            return True

        # All possible FK columns for artigos
        ALL_FK_COLS = ["id_parte", "id_livro", "id_titulo", "id_subtitulo", "id_capitulo", "id_secao", "id_subsecao"]

        records = []
        for art in articles:
            record = art.data.copy()

            # Ensure ALL FK columns are present (None if not applicable)
            for fk_col in ALL_FK_COLS:
                temp_ref = art.fk_temp_ids.get(fk_col)
                if temp_ref:
                    record[fk_col] = id_map.get(temp_ref)
                else:
                    record[fk_col] = None

            records.append(record)

        logger.info(f"  Inserindo {len(records)} artigos em batch...")
        results = self._post_batch("artigos", records, batch_size=100)

        if results is None:
            logger.error("  FALHA ao inserir artigos!")
            return False

        logger.info(f"  ✅ {len(results)} artigos inseridos com sucesso.")
        return True

    # ─── Entrada Principal ──────────────────────────────────

    def salvar_lei_completa(self, estrutura: Dict[str, Any], url_origem: str, hash_html: str):
        """
        Salva toda a hierarquia no Supabase usando a estratégia:
        Flatten → Batch Insert Ordenado → Mapeamento de IDs.
        """
        info = estrutura.get("lei", {})

        # ── Detecção de Mudança ──
        lei_existente = self._get_by_url(url_origem)
        if lei_existente:
            if lei_existente.get("hash_html") == hash_html:
                logger.info(f"Sem mudanças detectadas para a lei {url_origem}")
                return True
            else:
                logger.warning(f"MUDANÇA DETECTADA! Re-processando {url_origem}")
                needs_review = True
        else:
            needs_review = False

        # ── ETAPA 1: Salvar/Atualizar Lei ──
        lei_data = {
            "nome": info.get("nome", "Sem Nome"),
            "tipo": self._mapear_tipo_lei(info.get("tipo", "Outro")),
            "ementa": info.get("ementa", ""),
            "data_publicacao": info.get("data_publicacao") or None,
            "orgao_emissor": info.get("orgao_emissor", "Planalto"),
            "url_origem": url_origem,
            "hash_html": hash_html,
            "status": "Em vigor",
            "confidence_avg": estrutura.get("confianca_media", 1.0),
            "needs_review": needs_review,
            "atualizado_em": "now()",
        }

        if lei_existente:
            id_lei = lei_existente["id_lei"]
            logger.info(f"  Lei existente encontrada (id={id_lei}). Limpando estrutura anterior...")
            self._limpar_estrutura_lei(id_lei)
            self._update("leis", {"id_lei": id_lei}, lei_data)
        else:
            lei_salva = self._post("leis", lei_data)
            if not lei_salva:
                logger.error("Falha ao inserir lei!")
                return False
            id_lei = lei_salva["id_lei"]

        logger.info(f"  Lei id={id_lei} salva. Iniciando flatten da árvore...")

        # ── ETAPA 2: Flatten ──
        filhos_raiz = estrutura.get("titulos", [])
        nodes_by_table, articles = self._flatten_tree(filhos_raiz, id_lei)

        # Log de contagens
        total_nodes = sum(len(v) for v in nodes_by_table.values())
        logger.info(f"  Flatten completo: {total_nodes} nós estruturais + {len(articles)} artigos")
        for tabela in ORDEM_INSERT:
            count = len(nodes_by_table[tabela])
            if count > 0:
                logger.info(f"    {tabela}: {count}")

        # ── ETAPA 3: Insert Ordenado com Mapeamento ──
        id_map = self._insert_with_id_mapping(nodes_by_table)
        if id_map is None:
            logger.error("  FALHA durante inserção hierárquica! Abortando.")
            return False

        logger.info(f"  Mapeamento de IDs concluído: {len(id_map)} temp_ids resolvidos.")

        # ── ETAPA 4: Insert Batch de Artigos ──
        success = self._insert_articles(articles, id_map)
        if not success:
            logger.error("  FALHA durante inserção de artigos!")
            return False

        logger.info(f"✅ Lei {id_lei} salva com sucesso no Supabase!")
        logger.info(f"   Resumo: {total_nodes} nós + {len(articles)} artigos")
        return True

    # ─── Helpers ─────────────────────────────────────────────

    def _mapear_tipo_lei(self, tipo: str) -> str:
        mapeamento = {
            "lei": "Lei Ordinária",
            "lcp": "Lei Complementar",
            "del": "Decreto-Lei",
            "mpv": "Medida Provisória",
            "const": "Constituição",
        }
        return mapeamento.get(tipo.lower(), "Outro")

    # ─── API Pública (para api.py) ───────────────────────────

    def list_leis(self) -> list:
        """Lista todas as leis do banco."""
        try:
            with httpx.Client() as client:
                r = client.get(
                    f"{self.url}/rest/v1/leis?select=*&order=atualizado_em.desc",
                    headers=self.headers
                )
                if r.status_code >= 400:
                    logger.error(f"Error listing laws from Supabase: {r.status_code} - {r.text}")
                    return []
                return r.json()
        except Exception as e:
            logger.error(f"Exception during list_leis: {e}")
            return []

    def update_lei(self, id_lei: int, data: Dict[str, Any]) -> bool:
        """Atualiza metadados de uma lei específica."""
        try:
            if "atualizado_em" not in data:
                data["atualizado_em"] = "now()"

            with httpx.Client() as client:
                r = client.patch(
                    f"{self.url}/rest/v1/leis?id_lei=eq.{id_lei}",
                    headers=self.headers,
                    json=data
                )
                if r.status_code >= 400:
                    logger.error(f"Error updating law {id_lei}: {r.status_code} - {r.text}")
                    return False
                return True
        except Exception as e:
            logger.error(f"Exception during law update: {e}")
            return False

    def obter_lei_completa(self, id_lei: int) -> Optional[dict]:
        """
        Recupera do Supabase todos os elementos e artigos de uma lei específica,
        reconstrói a árvore hierárquica e retorna no formato compatível com o frontend.
        """
        # 1. Buscar metadados da lei
        try:
            with httpx.Client() as client:
                r = client.get(f"{self.url}/rest/v1/leis?id_lei=eq.{id_lei}", headers=self.headers)
                r.raise_for_status()
                leis = r.json()
                if not leis:
                    return None
                lei_meta = leis[0]
        except Exception as e:
            logger.error(f"Erro ao buscar metadados da lei {id_lei}: {e}")
            return None

        # Helper para carregar todas as linhas paginadas
        def _fetch_all_rows(table: str) -> list:
            all_rows = []
            limit = 1000
            offset = 0
            with httpx.Client(timeout=30.0) as client:
                while True:
                    url = f"{self.url}/rest/v1/{table}?id_lei=eq.{id_lei}&order=ordem.asc&limit={limit}&offset={offset}"
                    r = client.get(url, headers=self.headers)
                    if r.status_code >= 400:
                        logger.error(f"Erro ao buscar {table} (status {r.status_code}): {r.text}")
                        break
                    rows = r.json()
                    if not rows:
                        break
                    all_rows.extend(rows)
                    if len(rows) < limit:
                        break
                    offset += limit
            return all_rows

        # 2. Buscar todas as tabelas estruturais e artigos
        tables = ["partes", "livros", "titulos", "subtitulos", "capitulos", "secoes", "subsecoes", "artigos"]
        data_by_table = {}
        for t in tables:
            data_by_table[t] = _fetch_all_rows(t)

        # 3. Mapear nome_completo / nome para extrair numero e nome limpo
        def _extrair_numero_nome(tipo: str, nome: str, nome_completo: str) -> Tuple[str, str]:
            tipo_upper = tipo.upper()
            if not nome_completo:
                return "", nome or ""
            if nome_completo.upper().startswith(tipo_upper):
                rest = nome_completo[len(tipo_upper):].strip()
                if " - " in rest:
                    parts = rest.split(" - ", 1)
                    return parts[0].strip(), parts[1].strip()
                else:
                    if not nome:
                        return "", rest
                    else:
                        return rest, nome
            return "", nome or nome_completo

        # 4. Criar dicionário de nós mapeados por (tipo, id)
        nodes = {}
        plural_to_singular = {
            "partes": "parte",
            "livros": "livro",
            "titulos": "titulo",
            "subtitulos": "subtitulo",
            "capitulos": "capitulo",
            "secoes": "secao",
            "subsecoes": "subsecao"
        }

        # Nós estruturais
        for plural, singular in plural_to_singular.items():
            pk_col = f"id_{singular}"
            for row in data_by_table[plural]:
                node_id = row[pk_col]
                numero, clean_nome = _extrair_numero_nome(singular, row.get("nome"), row.get("nome_completo"))
                node = {
                    "tipo": singular,
                    "numero": numero,
                    "nome": clean_nome,
                    "ordem": row.get("ordem", 0),
                    "filhos": []
                }
                nodes[(singular, node_id)] = (node, row)

        # Artigos
        for row in data_by_table["artigos"]:
            artigo_id = row["id_artigo"]
            
            # Parse json columns if needed
            estrutura_val = row.get("estrutura")
            if isinstance(estrutura_val, str):
                try:
                    estrutura_val = json.loads(estrutura_val)
                except Exception:
                    estrutura_val = None
            
            alteracoes_val = row.get("alteracoes")
            if isinstance(alteracoes_val, str):
                try:
                    alteracoes_val = json.loads(alteracoes_val)
                except Exception:
                    alteracoes_val = None

            node = {
                "id": str(artigo_id), # usar string id
                "tipo": "artigo",
                "numero": row.get("numero", ""),
                "ordem": row.get("ordem", 0),
                "estrutura": estrutura_val or [{"tipo": "caput", "conteudo": {"texto": row.get("texto", "")}}],
                "alteracoes": alteracoes_val or []
            }
            nodes[("artigo", artigo_id)] = (node, row)

        # 5. Resolver parentesco
        ancestor_cols = [
            ("subsecao", "id_subsecao"),
            ("secao", "id_secao"),
            ("capitulo", "id_capitulo"),
            ("subtitulo", "id_subtitulo"),
            ("titulo", "id_titulo"),
            ("livro", "id_livro"),
            ("parte", "id_parte")
        ]

        def _encontrar_pai(tipo: str, row: dict) -> Optional[Tuple[str, int]]:
            hierarchy_order = ["artigo", "subsecao", "secao", "capitulo", "subtitulo", "titulo", "livro", "parte"]
            try:
                type_idx = hierarchy_order.index(tipo)
            except ValueError:
                type_idx = 0

            for ancestor_type, col in ancestor_cols:
                try:
                    anc_idx = hierarchy_order.index(ancestor_type)
                except ValueError:
                    continue
                if anc_idx > type_idx:
                    parent_id = row.get(col)
                    if parent_id is not None:
                        return ancestor_type, parent_id
            return None

        root_nodes = []
        for key, (node, row) in nodes.items():
            tipo, node_id = key
            parent_key = _encontrar_pai(tipo, row)
            
            if parent_key and parent_key in nodes:
                parent_node, _ = nodes[parent_key]
                parent_node.setdefault("filhos", []).append(node)
            else:
                root_nodes.append(node)

        # Ordenar recursivamente
        def _sort_children(n: dict):
            if "filhos" in n and isinstance(n["filhos"], list):
                n["filhos"].sort(key=lambda x: x.get("ordem", 0))
                for child in n["filhos"]:
                    _sort_children(child)

        for n in root_nodes:
            _sort_children(n)

        # 6. Agrupar artigos avulsos na raiz (se houver)
        root_articles = [n for n in root_nodes if n["tipo"] == "artigo"]
        root_structural = [n for n in root_nodes if n["tipo"] != "artigo"]

        if root_articles:
            root_articles.sort(key=lambda x: x.get("ordem", 0))
            dummy_titulo = {
                "tipo": "titulo",
                "numero": "",
                "nome": "Disposições Gerais" if len(root_articles) > 1 else "",
                "filhos": root_articles
            }
            root_nodes = root_structural + [dummy_titulo]
        else:
            root_nodes = root_structural

        # 7. Separar em partes, livros, titulos
        partes_root = []
        livros_root = []
        titulos_root = []

        for node in root_nodes:
            t = node["tipo"]
            if t == "parte":
                partes_root.append(node)
            elif t == "livro":
                livros_root.append(node)
            else:
                titulos_root.append(node)

        partes_root.sort(key=lambda x: x.get("ordem", 0))
        livros_root.sort(key=lambda x: x.get("ordem", 0))
        titulos_root.sort(key=lambda x: x.get("ordem", 0))

        # 8. Retornar estrutura final no formato de LeiJson
        return {
            "lei": {
                "codigo": str(id_lei),
                "nome": lei_meta.get("nome", "Sem Nome"),
                "ementa": lei_meta.get("ementa", ""),
                "url": lei_meta.get("url_origem", "")
            },
            "partes": partes_root,
            "livros": livros_root,
            "titulos": titulos_root
        }


storage = SupabaseStorage()
