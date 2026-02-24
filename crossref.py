"""
crossref.py
Extração de referências cruzadas entre artigos de leis brasileiras.

Detecta padrões como:
  "nos termos do art. 5º desta Lei"
  "conforme disposto no art. 37, § 1º, inciso III"
  "previsto no art. 4º-A"
  "na forma do art. 10 do Decreto nº 1.234"

Cada referência vira uma aresta REFERENCIA no grafo Neo4j:
  (artigo_origem)-[:REFERENCIA {paragrafo, inciso, lei_externa}]->(artigo_destino)
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Regex principal de cross-reference
# ─────────────────────────────────────────────────────────────

_RE_CROSSREF = re.compile(
    # Contexto verbal opcional (anchora a referência — reduz falsos positivos)
    r"(?:nos?\s+termos?\s+d[oa]s?|conforme\s+(?:o\s+)?disposto\s+n[oa]s?|"
    r"previsto\s+n[oa]s?|na\s+forma\s+d[oa]s?|nos?\s+moldes\s+d[oa]s?|"
    r"(?:a\s+que\s+se\s+refere|referidos?\s+n[oa]s?)\s+)?"
    r"art(?:igo)?s?\.?\s*"
    r"(\d+[°oº]?(?:-[A-Za-z])?)"                       # g1: número do artigo
    r"(?:[,\s]+(?:§\s*(\d+[°oº]?)|par[aá]grafo\s+(?:(\d+)|único)))?"
    r"(?:[,\s°oº]+inciso\s+([IVXLCDM]+))?"            # g4: inciso
    r"(?:[,\s]+al[\xed\xec]nea\s+[\x27\x22]?([a-z])[\x27\x22]?)?",
    re.IGNORECASE,
)# Detecta se a referência é para uma lei externa
_RE_LEI_EXTERNA = re.compile(
    r"(?:desta\s+Lei|desta\s+Lei\s+Complementar|"
    r"do\s+presente\s+diploma|"
    r"deste\s+(?:Código|Decreto|Estatuto))",
    re.IGNORECASE,
)

_RE_LEI_OUTRA = re.compile(
    r"d[ao]\s+Lei(?:\s+Complementar)?\s+n[°º]?\s*([\d.]+)",
    re.IGNORECASE,
)


def extrair_crossrefs(
    texto: str,
    artigo_origem_id: str,
    codigo_lei: str,
) -> list[dict]:
    """
    Extrai todas as referências cruzadas de um texto de artigo.

    Args:
        texto:            Texto limpo do artigo (caput + parágrafos + incisos).
        artigo_origem_id: ID canônico do artigo de origem (ex: 'lei-9394-art-5º').
        codigo_lei:       Código da lei atual (ex: '9394').

    Returns:
        Lista de dicts, cada um representando uma referência:
        {
            "origem":        "lei-9394-art-3º",
            "destino_art":   "5",          # número do artigo referenciado
            "destino_para":  "1",          # § (opcional)
            "destino_inc":   "III",        # inciso (opcional)
            "destino_alinea": "a",         # alínea (opcional)
            "lei_externa":   None,         # número da lei, se externa
            "trecho":        "nos termos do art. 5º, § 1º",
        }
    """
    refs = []

    for m in _RE_CROSSREF.finditer(texto):
        art_num  = m.group(1)
        if not art_num:
            continue

        para_num = m.group(2) or m.group(3)
        inc_num  = m.group(4)
        alinea   = m.group(5)

        trecho = m.group(0).strip()

        # Determina se é referência interna ou externa
        # Olha contexto ao redor do match (50 chars antes)
        inicio = max(0, m.start() - 60)
        contexto_antes = texto[inicio:m.start()]

        lei_externa = None
        lei_ext_m   = _RE_LEI_OUTRA.search(contexto_antes + trecho)
        if lei_ext_m:
            lei_externa = lei_ext_m.group(1)

        # Filtra referências ambíguas: "art. X" isolado sem contexto verbal nem §/inciso
        # é muito provável que seja numeração acidental (ex: "Art. 5. define...")
        _CTX_VERBAL = re.compile(
            r"(?:"
            r"nos?\s+termos?\s+d[oa]s?|"
            r"(?:conforme\s+)?disposto\s+n[oa]s?|"          # 'disposto no' e 'conforme disposto no'
            r"previsto\s+n[oa]s?|"
            r"na\s+forma\s+d[oa]s?|"
            r"nos\s+moldes\s+d[oa]s?|"
            r"a\s+que\s+se\s+refere[mn]?\s+(?:\w+\s+){0,3}d[oa]|"  # 'a que se refere ... do'
            r"referidos?\s+n[oa]s?"
            r")\s*$",
            re.IGNORECASE,
        )
        tem_contexto = bool(_CTX_VERBAL.search(contexto_antes))
        tem_detalhe  = bool(para_num or inc_num)

        if not tem_contexto and not tem_detalhe:
            continue

        refs.append({
            "origem":         artigo_origem_id,
            "destino_art":    art_num,
            "destino_para":   para_num,
            "destino_inc":    inc_num,
            "destino_alinea": alinea,
            "lei_externa":    lei_externa,
            "trecho":         trecho[:120],  # limita tamanho
        })

    return refs


def extrair_crossrefs_estrutura(estrutura: dict, codigo_lei: str) -> list[dict]:
    """
    Extrai cross-references de toda a estrutura JSON de uma lei.

    Args:
        estrutura:  Dict retornado por parse_lei().
        codigo_lei: Código da lei.

    Returns:
        Lista de todas as referências encontradas na lei.
    """
    todas_refs = []
    artigos = _coletar_artigos(estrutura)

    for artigo in artigos:
        texto_completo = _texto_artigo(artigo)
        if not texto_completo:
            continue

        refs = extrair_crossrefs(
            texto_completo,
            artigo_origem_id=artigo["id"],
            codigo_lei=codigo_lei,
        )
        todas_refs.extend(refs)

    logger.info(
        f"Lei {codigo_lei}: {len(todas_refs)} cross-references em {len(artigos)} artigos"
    )
    return todas_refs


def _coletar_artigos(obj) -> list[dict]:
    """Coleta todos os nós de artigo recursivamente."""
    result = []
    if isinstance(obj, dict):
        if obj.get("tipo") == "artigo":
            result.append(obj)
        for v in obj.values():
            if isinstance(v, (dict, list)):
                result.extend(_coletar_artigos(v))
    elif isinstance(obj, list):
        for item in obj:
            result.extend(_coletar_artigos(item))
    return result


def _texto_artigo(artigo: dict) -> str:
    """Extrai todo o texto visível de um artigo (caput + parágrafos + incisos)."""
    partes = []

    def _extrair(obj):
        if isinstance(obj, dict):
            if "texto" in obj and isinstance(obj["texto"], str):
                partes.append(obj["texto"])
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    _extrair(v)
        elif isinstance(obj, list):
            for item in obj:
                _extrair(item)

    _extrair(artigo.get("estrutura", []))
    return " ".join(partes)