"""
parser.py — v4
Converte o texto limpo de uma lei brasileira em estrutura JSON hierárquica.

Correções v4:
  - CRÍTICO: extrair_incisos() agora preserva o texto preâmbulo do caput
  - CRÍTICO: extrair_alineas() agora preserva o texto preâmbulo do inciso
  - CRÍTICO: conteúdo do caput/parágrafo sempre tem schema consistente:
      { "texto": "...", "incisos": [...] }  quando há incisos
      { "texto": "..." }                    quando não há incisos
  - MÉDIO: _SPLIT_PARAGRAFO melhorado para não partir texto em referências internas
  - BAIXO: IDs normalizados (remove ordinal º/° do número para ID consistente)
  - Mantém compatibilidade total com hierarquia PARTE → LIVRO → TÍTULO → ... → ARTIGO
"""

import re
import json
import logging

logger = logging.getLogger(__name__)


# ===============================================================
# NORMALIZAÇÃO DE TEXTO BRUTO
# ===============================================================

def normalizar_texto(texto: str) -> str:
    texto = texto.replace("\r", "")
    texto = texto.replace("\xa0", " ")

    # Colapsa marcadores hierárquicos quebrados em duas linhas
    texto = re.sub(
        r"(T[IÍ]TULO|CAP[IÍ]TULO|SE[ÇC][ÃA]O|SUBSE[ÇC][ÃA]O|LIVRO|PARTE)"
        r"\s*\n\s*([IVXLCDM]+)",
        r"\1 \2",
        texto,
    )

    texto = re.sub(r"[ \t]+(Art\.\s+\d)", r"\n\1", texto)
    texto = re.sub(r"[ \t]+(§\s*\d+)", r"\n\1", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)

    if not texto.startswith("\n"):
        texto = "\n" + texto

    return texto


def limpar_texto_final(texto: str) -> str:
    """Limpeza aplicada ao texto DEPOIS que a estrutura foi extraída."""
    if not texto:
        return texto
    texto = texto.replace("\n", " ")
    texto = re.sub(r" {2,}", " ", texto)
    texto = re.sub(r"^\.\s*", "", texto)
    texto = re.sub(r"\s+\.\s*$", "", texto)
    texto = texto.replace("\x96", "-").replace("\u2013", "-").replace("\u2014", "-")
    return texto.strip()


def limpar_norma(texto: str) -> str:
    if not texto:
        return texto
    return re.sub(r"\s+", " ", texto).strip()


def _normalizar_id(numero: str) -> str:
    """Normaliza o número do artigo para uso em IDs (remove ordinais inconsistentes)."""
    if not numero:
        return numero
    # Remove º, °, o no final de números simples (ex: "1º" → "1", "5°" → "5")
    # Mas preserva sufixos alfabéticos e compostos (ex: "36-A", "4º-A")
    # return re.sub(r"([0-9])[°oº](?=-|$)", r"\1", numero)
    return re.sub(r"([0-9])[°oº]$", r"\1", numero)


# ===============================================================
# METADADOS LEGISLATIVOS
# ===============================================================

_PADRAO_META = re.compile(
    r"\("
    r"(Redação dada|Incluído|Incluída|Incluídos|Incluídas"
    r"|Revogado|Revogada|Revogados|Revogadas"
    r"|Vide|Renumerado)"
    r"[^)]*\)",
    re.IGNORECASE,
)

_PADRAO_NORMA = re.compile(
    r"(Lei(?:\s+Complementar)?|Decreto(?:-Lei)?|Emenda\s+Constitucional"
    r"|Medida\s+Provisória|Resolução|Portaria"
    r"|AD(?:In?|C|PF)\s+\d[\w.-]*"
    r"|Instrução\s+Normativa"
    r"|Ato\s+(?:Institucional|Normativo)"
    r"|Convênio"
    r")"
    r"[\s\w./º\-nº]*",
    re.IGNORECASE,
)

_PADRAO_ANO = re.compile(
    r"de\s+(\d{4})"
    r"|de\s+\d+[º°]?\.\d+\.(\d{4})"
)


def _extrair_ano(match: re.Match) -> str | None:
    return match.group(1) or match.group(2)


def extrair_metadados(texto: str) -> tuple:
    metadados = []
    for match in _PADRAO_META.finditer(texto):
        trecho = match.group(0)
        trecho_lower = trecho.lower()
        tipo = None
        if "redação dada" in trecho_lower:
            tipo = "redacao"
        elif "incluíd" in trecho_lower:
            tipo = "incluido"
        elif "revogad" in trecho_lower:
            tipo = "revogado"
        elif "renumerado" in trecho_lower:
            tipo = "renumerado"
        elif "vide" in trecho_lower:
            tipo = "vide"
        norma_match = _PADRAO_NORMA.search(trecho)
        ano_match = _PADRAO_ANO.search(trecho)
        metadados.append({
            "tipo": tipo,
            "norma": limpar_norma(norma_match.group(0)) if norma_match else None,
            "ano": _extrair_ano(ano_match) if ano_match else None,
        })
    texto_limpo = _PADRAO_META.sub("", texto).strip()
    return texto_limpo, metadados


# ===============================================================
# ALÍNEAS
# ===============================================================

_SPLIT_ALINEA = re.compile(r"\n[ \t]*([a-z])\)[ \t]+")


def extrair_alineas(texto: str) -> dict:
    """
    Extrai alíneas de um texto.

    SEMPRE retorna um dict com schema consistente:
      { "texto": "...", "alineas": [...] }   quando há alíneas
      { "texto": "..." }                     quando não há alíneas

    O "texto" é o preâmbulo antes da primeira alínea (pode ser vazio "").
    """
    partes = _SPLIT_ALINEA.split(texto)

    # Extrai metadados e texto do preâmbulo (partes[0])
    preambulo_raw = partes[0].strip() if partes else ""
    texto_pre, meta_pre = extrair_metadados(preambulo_raw)
    texto_pre_limpo = limpar_texto_final(texto_pre)

    resultado: dict = {"texto": texto_pre_limpo}
    if meta_pre:
        resultado["metadados"] = meta_pre

    # Sem alíneas → retorna só o dict simples
    if len(partes) <= 1:
        return resultado

    # Processa alíneas
    alineas = []
    for i in range(1, len(partes), 2):
        letra = partes[i]
        conteudo = partes[i + 1].strip() if i + 1 < len(partes) else ""
        texto_sem_meta, meta = extrair_metadados(conteudo)
        item = {
            "tipo": "alinea",
            "letra": letra,
            "texto": limpar_texto_final(texto_sem_meta),
        }
        if meta:
            item["metadados"] = meta
        alineas.append(item)

    resultado["alineas"] = alineas
    return resultado


# ===============================================================
# INCISOS
#
# CORREÇÃO PRINCIPAL:
#   Antes: descartava partes[0] (o texto do caput/parágrafo antes dos incisos)
#   Agora: preserva partes[0] como "texto" no resultado
# ===============================================================

_SPLIT_INCISO = re.compile(
    r"\n[ \t]*"
    r"([IVXLCDM]{1,7}(?:-[A-Z])?)"
    r"[ \t]*\n?[ \t]*"
    r"[-\x96\u2013\u2014]"
    r"[ \t]*"
)


def extrair_incisos(texto: str) -> dict:
    """
    Extrai incisos de um texto.

    SEMPRE retorna um dict com schema consistente:
      { "texto": "...", "incisos": [...] }   quando há incisos
      { "texto": "...", "alineas": [...] }   quando não há incisos mas há alíneas
      { "texto": "..." }                     texto simples

    O campo "texto" é SEMPRE preservado — é o preâmbulo antes do primeiro inciso.
    """
    partes = _SPLIT_INCISO.split(texto)

    # Sem incisos → delega para alíneas (que também preserva texto)
    if len(partes) <= 1:
        return extrair_alineas(texto)

    # Preâmbulo: texto antes do primeiro inciso
    preambulo_raw = partes[0].strip()
    texto_pre, meta_pre = extrair_metadados(preambulo_raw)
    texto_pre_limpo = limpar_texto_final(texto_pre)

    resultado: dict = {"texto": texto_pre_limpo}
    if meta_pre:
        resultado["metadados"] = meta_pre

    # Processa cada inciso
    incisos = []
    for i in range(1, len(partes), 2):
        numero = partes[i]
        conteudo_raw = partes[i + 1].strip() if i + 1 < len(partes) else ""
        incisos.append({
            "tipo": "inciso",
            "numero": numero,
            "conteudo": extrair_alineas(conteudo_raw),
        })

    resultado["incisos"] = incisos
    return resultado


# ===============================================================
# PARÁGRAFOS
#
# CORREÇÃO: _SPLIT_PARAGRAFO melhorado para não partir em referências
# internas do tipo "§ 2º do art. X" (que não começam a linha).
# A âncora \n garante que só split em início de linha.
# ===============================================================

_SPLIT_PARAGRAFO = re.compile(
    r"\n(§\s*\d+[°oº]?\.?|Parágrafo\s+único\.?)"
)

_RE_STRIP_ART = re.compile(
    r"^Art\.\s+[\d]+[°oº]?(?:-[A-Za-z])?\.?\s*"
)


def extrair_paragrafos(texto_artigo: str) -> list:
    """
    Divide o texto do artigo em caput + parágrafos.

    Cada item tem "conteudo" com schema consistente vindo de extrair_incisos().
    """
    partes = _SPLIT_PARAGRAFO.split(texto_artigo)
    estrutura = []

    # Caput
    caput_raw = partes[0].strip()
    if caput_raw:
        caput_raw = _RE_STRIP_ART.sub("", caput_raw).strip()
        estrutura.append({
            "tipo": "caput",
            "conteudo": extrair_incisos(caput_raw),
        })

    # Parágrafos
    for i in range(1, len(partes), 2):
        marcador = partes[i].strip()
        conteudo = partes[i + 1].strip() if i + 1 < len(partes) else ""

        if "único" in marcador.lower():
            numero = "único"
        else:
            num_match = re.search(r"\d+", marcador)
            numero = num_match.group() if num_match else None

        estrutura.append({
            "tipo": "paragrafo",
            "numero": numero,
            "conteudo": extrair_incisos(conteudo),
        })

    return estrutura


# ===============================================================
# HIERARQUIA: TÍTULO -> CAPÍTULO -> SEÇÃO -> SUBSEÇÃO -> ARTIGO
# ===============================================================

_SPLIT_TITULO   = re.compile(r"\n(?=T[IÍ]TULO\s+[IVXLCDM])")
_SPLIT_LIVRO    = re.compile(r"\n(?=LIVRO\s+[IVXLCDM])")
_SPLIT_PARTE    = re.compile(r"\n(?=PARTE\s+(?:[IVXLCDM]+|GERAL|ESPECIAL))")
_SPLIT_CAPITULO = re.compile(r"\n(?=CAP[IÍ]TULO\s+[IVXLCDM])")
_SPLIT_SECAO    = re.compile(r"\n(?=SE[ÇC][ÃA]O\s+[IVXLCDM])")
_SPLIT_SUBSECAO = re.compile(r"\n(?=SUBSE[ÇC][ÃA]O\s+[IVXLCDM])")
_SPLIT_ARTIGO   = re.compile(r"\n(?=Art\.\s)")

_RE_TITULO   = re.compile(r"T[IÍ]TULO\s+([IVXLCDM]+)\s*(.*?)(?=\n|$)")
_RE_LIVRO    = re.compile(r"LIVRO\s+([IVXLCDM]+)\s*(.*?)(?=\n|$)")
_RE_PARTE    = re.compile(r"PARTE\s+((?:[IVXLCDM]+|GERAL|ESPECIAL))\s*(.*?)(?=\n|$)", re.IGNORECASE)
_RE_CAPITULO = re.compile(r"CAP[IÍ]TULO\s+([IVXLCDM]+)\s*(.*?)(?=\n|$)")
_RE_SECAO    = re.compile(r"SE[ÇC][ÃA]O\s+([IVXLCDM]+)\s*(.*?)(?=\n|$)")
_RE_SUBSECAO = re.compile(r"SUBSE[ÇC][ÃA]O\s+([IVXLCDM]+)\s*(.*?)(?=\n|$)")
_RE_ARTIGO   = re.compile(r"Art\.\s+([\d]+[°oº]?(?:-[A-Za-z])?)")


def _coletar_metadados(obj) -> list:
    resultado = []
    if isinstance(obj, dict):
        resultado.extend(obj.get("metadados", []))
        for v in obj.values():
            if isinstance(v, (dict, list)):
                resultado.extend(_coletar_metadados(v))
    elif isinstance(obj, list):
        for item in obj:
            resultado.extend(_coletar_metadados(item))
    return resultado


def _parse_artigos(bloco: str, codigo_lei: str, ordem_ref: list) -> list:
    artigos = []
    for art in _SPLIT_ARTIGO.split(bloco):
        art = art.strip()
        if not art.startswith("Art."):
            continue
        ordem_ref[0] += 1
        num_match = _RE_ARTIGO.match(art)
        numero = num_match.group(1) if num_match else None
        numero_id = _normalizar_id(numero) if numero else None
        id_unico = (
            f"lei-{codigo_lei}-art-{numero_id}"
            if numero_id
            else f"lei-{codigo_lei}-art-{ordem_ref[0]}"
        )
        estrutura = extrair_paragrafos(art)
        todas_meta = _coletar_metadados(estrutura)
        artigo = {
            "id": id_unico,
            "ordem": ordem_ref[0],
            "numero": numero,
            "tipo": "artigo",
            "estrutura": estrutura,
        }
        if todas_meta:
            artigo["alteracoes"] = todas_meta
        artigos.append(artigo)
    return artigos


def _parse_subsecoes(bloco: str, codigo_lei: str, ordem_ref: list) -> list:
    partes = _SPLIT_SUBSECAO.split(bloco)
    resultado = []
    for parte in partes:
        parte = parte.strip()
        m = _RE_SUBSECAO.match(parte)
        if m:
            resultado.append({
                "tipo": "subsecao",
                "numero": m.group(1),
                "nome": limpar_texto_final(m.group(2)),
                "artigos": _parse_artigos(parte, codigo_lei, ordem_ref),
            })
        else:
            resultado.extend(_parse_artigos(parte, codigo_lei, ordem_ref))
    return resultado


def _parse_secoes(bloco: str, codigo_lei: str, ordem_ref: list) -> list:
    partes = _SPLIT_SECAO.split(bloco)
    resultado = []
    for parte in partes:
        parte = parte.strip()
        m = _RE_SECAO.match(parte)
        if m:
            resultado.append({
                "tipo": "secao",
                "numero": m.group(1),
                "nome": limpar_texto_final(m.group(2)),
                "filhos": _parse_subsecoes(parte, codigo_lei, ordem_ref),
            })
        else:
            resultado.extend(_parse_subsecoes(parte, codigo_lei, ordem_ref))
    return resultado


def _parse_capitulos(bloco: str, codigo_lei: str, ordem_ref: list) -> list:
    partes = _SPLIT_CAPITULO.split(bloco)
    resultado = []
    for parte in partes:
        parte = parte.strip()
        m = _RE_CAPITULO.match(parte)
        if m:
            resultado.append({
                "tipo": "capitulo",
                "numero": m.group(1),
                "nome": limpar_texto_final(m.group(2)),
                "filhos": _parse_secoes(parte, codigo_lei, ordem_ref),
            })
        else:
            resultado.extend(_parse_secoes(parte, codigo_lei, ordem_ref))
    return resultado


def _parse_livros(bloco: str, codigo_lei: str, ordem_ref: list) -> list:
    partes = _SPLIT_LIVRO.split(bloco)
    resultado = []
    for parte in partes:
        parte = parte.strip()
        m = _RE_LIVRO.match(parte)
        if m:
            resultado.append({
                "tipo": "livro",
                "numero": m.group(1),
                "nome": limpar_texto_final(m.group(2)),
                "filhos": _parse_capitulos(parte, codigo_lei, ordem_ref),
            })
        else:
            resultado.extend(_parse_capitulos(parte, codigo_lei, ordem_ref))
    return resultado


def _parse_partes(bloco: str, codigo_lei: str, ordem_ref: list) -> list:
    partes = _SPLIT_PARTE.split(bloco)
    resultado = []
    for parte in partes:
        parte = parte.strip()
        m = _RE_PARTE.match(parte)
        if m:
            resultado.append({
                "tipo": "parte",
                "numero": m.group(1).upper(),
                "nome": limpar_texto_final(m.group(2)),
                "filhos": _parse_livros(parte, codigo_lei, ordem_ref),
            })
        else:
            resultado.extend(_parse_livros(parte, codigo_lei, ordem_ref))
    return resultado


# ===============================================================
# PARSER PRINCIPAL
# ===============================================================

def parse_lei(texto: str, codigo_lei: str = "0000") -> dict:
    """
    Converte texto limpo de uma lei em estrutura JSON hierárquica completa.

    Schema do conteúdo de caput/parágrafo (SEMPRE consistente):
      {
        "texto": "Texto introdutório do caput ou parágrafo",   # sempre presente
        "metadados": [...],                                     # se houver
        "incisos": [                                            # se houver incisos
          {
            "tipo": "inciso",
            "numero": "I",
            "conteudo": {
              "texto": "...",         # texto do inciso
              "alineas": [...]        # se houver alíneas
            }
          }
        ],
        "alineas": [...]              # se houver alíneas diretas (sem incisos)
      }
    """
    texto = normalizar_texto(texto)

    ementa_match = re.search(
        r"(Estabelece|Dispõe|Define|Institui|Regulamenta|Cria|Altera)[^.]+\.",
        texto,
    )
    ementa = limpar_texto_final(ementa_match.group(0)) if ementa_match else ""

    estrutura_final = {
        "lei": {"codigo": codigo_lei, "ementa": ementa},
        "titulos": [],
    }

    ordem_ref = [0]

    _pos = {}
    for name, pat in [
        ("parte",    re.compile(r"\nPARTE\s+(?:[IVXLCDM]+|GERAL|ESPECIAL)", re.I)),
        ("livro",    re.compile(r"\nLIVRO\s+[IVXLCDM]")),
        ("titulo",   re.compile(r"\nT[IÍ]TULO\s+[IVXLCDM]")),
        ("capitulo", re.compile(r"\nCAP[IÍ]TULO\s+[IVXLCDM]")),
    ]:
        m = pat.search(texto)
        if m:
            _pos[name] = m.start()

    root = min(_pos, key=_pos.get) if _pos else "artigo"

    if root == "parte":
        blocos = _SPLIT_PARTE.split(texto)
        for bloco in blocos[1:]:
            bloco = bloco.strip()
            m = _RE_PARTE.match(bloco)
            if m:
                estrutura_final["titulos"].append({
                    "tipo": "parte",
                    "numero": m.group(1).upper(),
                    "nome": limpar_texto_final(m.group(2)),
                    "filhos": _parse_livros(bloco, codigo_lei, ordem_ref),
                })
            else:
                estrutura_final["titulos"].extend(
                    _parse_livros(bloco, codigo_lei, ordem_ref)
                )

    elif root == "livro":
        blocos = _SPLIT_LIVRO.split(texto)
        for bloco in blocos[1:]:
            bloco = bloco.strip()
            m = _RE_LIVRO.match(bloco)
            if m:
                estrutura_final["titulos"].append({
                    "tipo": "livro",
                    "numero": m.group(1),
                    "nome": limpar_texto_final(m.group(2)),
                    "filhos": _parse_capitulos(bloco, codigo_lei, ordem_ref),
                })

    elif root == "titulo":
        blocos = _SPLIT_TITULO.split(texto)
        for bloco in blocos[1:]:
            bloco = bloco.strip()
            m = _RE_TITULO.match(bloco)
            if m:
                estrutura_final["titulos"].append({
                    "tipo": "titulo",
                    "numero": m.group(1),
                    "nome": limpar_texto_final(m.group(2)),
                    "filhos": _parse_partes(bloco, codigo_lei, ordem_ref),
                })
            else:
                logger.warning(f"Bloco não reconhecido como TÍTULO: {bloco[:80]!r}")

    elif root == "capitulo":
        blocos = _SPLIT_CAPITULO.split(texto)
        for bloco in blocos[1:]:
            bloco = bloco.strip()
            m = _RE_CAPITULO.match(bloco)
            if m:
                estrutura_final["titulos"].append({
                    "tipo": "capitulo",
                    "numero": m.group(1),
                    "nome": limpar_texto_final(m.group(2)),
                    "filhos": _parse_secoes(bloco, codigo_lei, ordem_ref),
                })

    else:
        estrutura_final["titulos"].extend(
            _parse_artigos(texto, codigo_lei, ordem_ref)
        )

    logger.info(
        f"Lei {codigo_lei}: {ordem_ref[0]} artigos, "
        f"{len(estrutura_final['titulos'])} blocos raiz [{root}]"
    )
    return estrutura_final


# ===============================================================
# CLI
# ===============================================================

if __name__ == "__main__":
    import sys

    entrada = sys.argv[1] if len(sys.argv) > 1 else "rawldb.txt"
    saida   = sys.argv[2] if len(sys.argv) > 2 else "ldb_struct.json"
    codigo  = sys.argv[3] if len(sys.argv) > 3 else "9394"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    with open(entrada, "r", encoding="utf-8") as f:
        texto = f.read()

    estrutura = parse_lei(texto, codigo_lei=codigo)

    with open(saida, "w", encoding="utf-8") as f:
        json.dump(estrutura, f, ensure_ascii=False, indent=2)

    print(f"Estrutura salva em '{saida}'")