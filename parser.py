"""
parser.py — v8
Converte texto bruto de leis brasileiras em JSON hierárquico.

Leis cobertas e testadas:
  - LDB (9394):   TÍTULO → CAPÍTULO → SEÇÃO → ARTIGO
  - Código Penal: PARTE → TÍTULO → CAPÍTULO → ARTIGO
  - CPP:          LIVRO → TÍTULO → CAPÍTULO → SEÇÃO → ARTIGO
  - Qualquer lei sem hierarquia: ARTIGO direto

Correções v8:
  [BUG10] _extrair_nome capturava texto de artigos quando o HTML não separava
          o nome do capítulo/título/seção do primeiro artigo com \n isolado.
          Ex: "DA INSTRUÇÃO CRIMINAL Art. 394. O procedimento..."
          → Dois mecanismos de proteção adicionados:
            a) Cada parte coletada é truncada na primeira ocorrência de
               " Art. N" ou " § N" embutidos na linha (sub-string match).
            b) limpar_nome() pós-processa o resultado final com mesmo corte.
          [BUG10-SUB] limpar_texto_final recebia o nome resultante com
          metadados de redação embutidos que não eram removidos corretamente
          quando faziam parte da mesma linha que o texto do artigo.

Correções anteriores (mantidas):
  [BUG1] _SPLIT_ARTIGO sem re.IGNORECASE
  [BUG2] _SPLIT_TITULO exige marcador em linha própria
  [BUG3] "Livro IV\n." descartado como referência cruzada
  [BUG4] "Art. 167\n;" descartado na normalização
  [BUG5] "Art. 399\n.\n texto" normalizado corretamente
  [BUG6] § partido em 2 ou 3 linhas normalizado
  [BUG7] Ordinal 'o','º','°' partido em linha própria normalizado
  [BUG8] Nome de marcador em múltiplas linhas consecutivas
  [BUG9] Artigos em ordem correta (DFS pré-ordem)
"""

import re
import json
import logging
from collections import deque

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# FASE 1 — NORMALIZAÇÃO
# ═══════════════════════════════════════════════════════

def normalizar_texto(texto: str) -> str:
    texto = texto.replace("\r", "")
    texto = texto.replace("\xa0", " ")
    texto = texto.replace("║", "º")

    linhas = [re.sub(r"  +", " ", l) for l in texto.splitlines()]
    texto = "\n".join(linhas)

    # Metadados partidos
    texto = re.sub(r"\(([^\n)]{1,40})\n([^\n)]{1,80}\))", r"(\1 \2)", texto)

    # "Parágrafo\núnico"
    texto = re.sub(r"\nParágrafo\n\s*(único)", r"\nParágrafo único", texto, flags=re.IGNORECASE)

    # § partido em 3 linhas
    texto = re.sub(r"\n§\n(\d+)\n(o|º|°)\n", r"\n§ \1º\n", texto)
    texto = re.sub(r"\n§\n(\d+[°oº])", r"\n§ \1", texto)

    # § partido em 2 linhas
    texto = re.sub(r"\n§\n(\d+[°oº](?:-[A-Za-z])?\s)", r"\n§ \1", texto)

    # Ordinal partido após dígito
    texto = re.sub(r"(\d)\n(o)\n",    r"\1º\n", texto)
    texto = re.sub(r"(\d)\n([°º])\n", r"\1º\n", texto)
    texto = re.sub(r"(\d)\n(o)$",    r"\1º",   texto, flags=re.MULTILINE)
    texto = re.sub(r"(\d)\n([°º])$",  r"\1º",  texto, flags=re.MULTILINE)

    # Ordinal partido após Art.N
    texto = re.sub(r"(Art\.\s*\d+)\n([°oº])\n", r"\1\2\n", texto)

    def _fix_art_partido(texto):
        linhas = texto.splitlines()
        resultado = []
        i = 0
        while i < len(linhas):
            l = linhas[i]
            s = l.strip()
            m = re.match(r'^(Art\.?\s*\d+[°oº]?(?:-[A-Za-z])?)\s*$', s)
            if m and i + 1 < len(linhas):
                prox = linhas[i + 1].strip()
                if prox == '.':
                    k = i + 2
                    while k < len(linhas) and not linhas[k].strip():
                        k += 1
                    terceira = linhas[k].strip() if k < len(linhas) else ''
                    if terceira.startswith('Art'):
                        resultado.append(f"referência_interna: {s}.")
                        i += 2
                        continue
                    else:
                        resultado.append(m.group(1) + '.')
                        i += 2
                        continue
                elif prox == ';':
                    resultado.append(f"referência_interna: {s};")
                    i += 2
                    continue
                elif prox.startswith(','):
                    resultado.append(s + prox)
                    i += 2
                    continue
            resultado.append(l)
            i += 1
        return '\n'.join(resultado)

    texto = _fix_art_partido(texto)

    # Marcadores hierárquicos partidos
    texto = re.sub(
        r"(T[IÍ]TULO|CAP[IÍ]TULO|SE[ÇC][ÃA]O|SUBSE[ÇC][ÃA]O|LIVRO|PARTE)"
        r"\s*\n\s*([IVXLCDM][\w-]*)",
        r"\1 \2",
        texto,
        flags=re.IGNORECASE,
    )

    # [BUG3 FIX] Remove referências cruzadas "Livro IV\n.\n"
    texto = re.sub(
        r"\n([Ll]ivro|[Tt]ítulo|[Cc]apítulo)\s+[IVXLCDM]+[^\n]*\n\.\n",
        r"\n",
        texto,
    )

    # Colapsa 3+ linhas vazias → 2
    texto = re.sub(r"\n{3,}", "\n\n", texto)

    if not texto.startswith("\n"):
        texto = "\n" + texto

    return texto


# ═══════════════════════════════════════════════════════
# FASE 2 — LIMPEZA DE TEXTO FINAL
# ═══════════════════════════════════════════════════════

def limpar_texto_final(texto: str) -> str:
    if not texto:
        return texto
    texto = texto.replace("\n", " ")
    texto = re.sub(r" {2,}", " ", texto)
    texto = re.sub(r"^[°oº]\s*[-–]\s+", "", texto)
    texto = re.sub(r"^[°oº]\s+", "", texto)
    texto = re.sub(r"^\s*[-–]\s+", "", texto)
    texto = re.sub(r"^\.\s+", "", texto)
    texto = texto.replace("\x96", "-").replace("\u2013", "-").replace("\u2014", "-")
    texto = re.sub(r"\s+([.,;])\s*$", r"\1", texto)
    return texto.strip()


def limpar_norma(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip() if s else s


def _id_num(numero: str) -> str:
    if not numero:
        return numero
    return re.sub(r"([0-9])[°oº]$", r"\1", numero)


# ═══════════════════════════════════════════════════════
# [BUG10 FIX] — Regex para detectar Art./§ embutidos em nomes
#
# Quando o HTML não separa o nome do marcador hierárquico do primeiro
# artigo com uma linha vazia, a normalização mantém ambos na mesma linha.
# _extrair_nome não consegue identificar a fronteira porque _RE_ESTRUTURAL
# usa match() (início da string) — e a linha começa com o nome, não com Art.
#
# Solução: após coletar cada parte do nome, truncar na primeira ocorrência
# de " Art. N" ou " § N" embutidos. Aplicar também como pós-processamento
# no resultado final em limpar_nome().
# ═══════════════════════════════════════════════════════

# Detecta "Art. N" ou "§ N" precedidos de espaço (embutidos no meio de uma linha)
# Não usa re.IGNORECASE aqui: "Art." normativo é sempre maiúsculo (BUG1).
_RE_ARTIGO_OU_PARA_EMBUTIDO = re.compile(
    r"\s+(?:Art\.?\s*\d|§\s*\d)"
)


def _truncar_na_fronteira_artigo(texto: str) -> str:
    """
    Remove tudo a partir da primeira ocorrência de ' Art. N' ou ' § N'
    embutidos no meio de uma string (não no início).

    Ex: "DA INSTRUÇÃO CRIMINAL Art. 394. texto..." → "DA INSTRUÇÃO CRIMINAL"
    Ex: "DOS CRIMES § 1º texto..."                → "DOS CRIMES"
    Ex: "DA INSTRUÇÃO CRIMINAL"                   → inalterado
    """
    m = _RE_ARTIGO_OU_PARA_EMBUTIDO.search(texto)
    if m:
        return texto[:m.start()].strip()
    return texto


def limpar_nome(nome: str) -> str:
    """
    Aplica limpeza específica para nomes de marcadores hierárquicos:
    1. limpar_texto_final (espaços, dashes, etc.)
    2. Trunca na fronteira de Art./§ embutidos (BUG10)
    """
    nome = limpar_texto_final(nome)
    nome = _truncar_na_fronteira_artigo(nome)
    return nome


# ═══════════════════════════════════════════════════════
# FASE 3 — METADADOS LEGISLATIVOS
# ═══════════════════════════════════════════════════════

_PAT_META = re.compile(
    r"\("
    r"(Redação dada|Incluído|Incluída|Incluídos|Incluídas"
    r"|Revogado|Revogada|Revogados|Revogadas"
    r"|Vide|Renumerado|Vigência|Acrescido|Acrescida"
    r"|Suprimido|Suprimida|Alterado|Alterada|VETADO)"
    r"[^)]*\)",
    re.IGNORECASE,
)
_PAT_NORMA = re.compile(
    r"(Lei(?:\s+Complementar)?|Decreto(?:-Lei)?|Emenda\s+Constitucional"
    r"|Medida\s+Provisória|Resolução|Portaria|Instrução\s+Normativa"
    r"|Ato\s+(?:Institucional|Normativo)|Convênio|Adin|ADPF)"
    r"[\s\w./º\-nº]*",
    re.IGNORECASE,
)
_PAT_ANO = re.compile(r"de\s+(\d{4})|de\s+\d+[º°]?\.\d+\.(\d{4})")


def extrair_metadados(texto: str) -> tuple:
    metas = []
    for m in _PAT_META.finditer(texto):
        t = m.group(0)
        tl = t.lower()
        tipo = (
            "redacao"    if "redação dada" in tl else
            "incluido"   if "incluíd"      in tl else
            "revogado"   if "revogad"      in tl else
            "renumerado" if "renumerado"   in tl else
            "vide"       if "vide"         in tl else
            "vigencia"   if "vigência"     in tl else
            "vetado"     if "vetado"       in tl else
            "acrescido"  if "acrescid"     in tl else
            None
        )
        norma_m = _PAT_NORMA.search(t)
        ano_m   = _PAT_ANO.search(t)
        metas.append({
            "tipo":  tipo,
            "norma": limpar_norma(norma_m.group(0)) if norma_m else None,
            "ano":   (ano_m.group(1) or ano_m.group(2)) if ano_m else None,
        })
    texto_limpo = _PAT_META.sub("", texto).strip()
    if not texto_limpo and metas:
        tipo_unico = metas[0].get("tipo")
        if tipo_unico == "vetado":
            texto_limpo = "(VETADO)"
        elif tipo_unico == "revogado" and not metas[0].get("norma"):
            texto_limpo = "(Revogado)"
    return texto_limpo, metas


# ═══════════════════════════════════════════════════════
# FASE 4 — ALÍNEAS, INCISOS, PARÁGRAFOS
# ═══════════════════════════════════════════════════════

_SPLIT_ALINEA = re.compile(r"\n[ \t]*([a-z])\)[ \t]+")


def extrair_alineas(texto: str) -> dict:
    partes = _SPLIT_ALINEA.split(texto)
    t0, m0 = extrair_metadados((partes[0] or "").strip())
    r: dict = {"texto": limpar_texto_final(t0)}
    if m0:
        r["metadados"] = m0
    if len(partes) <= 1:
        return r
    als = []
    for i in range(1, len(partes), 2):
        letra = partes[i]
        corp  = partes[i + 1].strip() if i + 1 < len(partes) else ""
        tc, mc = extrair_metadados(corp)
        item = {"tipo": "alinea", "letra": letra, "texto": limpar_texto_final(tc)}
        if mc:
            item["metadados"] = mc
        als.append(item)
    r["alineas"] = als
    return r


_SPLIT_INCISO = re.compile(
    r"\n[ \t]*([IVXLCDM]{1,7}(?:-[A-Z])?)"
    r"[ \t]*\n?[ \t]*"
    r"[-\x96\u2013\u2014][ \t]*",
)


def extrair_incisos(texto: str) -> dict:
    partes = _SPLIT_INCISO.split(texto)
    if len(partes) <= 1:
        return extrair_alineas(texto)
    t0, m0 = extrair_metadados((partes[0] or "").strip())
    r: dict = {"texto": limpar_texto_final(t0)}
    if m0:
        r["metadados"] = m0
    incs = []
    for i in range(1, len(partes), 2):
        num  = partes[i]
        corp = partes[i + 1].strip() if i + 1 < len(partes) else ""
        incs.append({
            "tipo":     "inciso",
            "numero":   num,
            "conteudo": extrair_alineas(corp),
        })
    r["incisos"] = incs
    return r


_SPLIT_PARAGRAFO = re.compile(
    r"\n"
    r"("
    r"§\s*\d+[°oº]?(?:-[A-Za-z])?(?:\s*[-–.]\s*)?"
    r"|"
    r"Parágrafo\s+único\s*(?:[-–.]\s*)?"
    r")",
    re.IGNORECASE,
)

_RE_STRIP_ART = re.compile(
    r"^Art\.?\s*\d+[°oº]?(?:-[A-Za-z])?(?:\s*[-–.]\s*|\s+)"
)


def extrair_paragrafos(txt_art: str) -> list:
    partes = _SPLIT_PARAGRAFO.split(txt_art)
    estrutura = []

    raw = partes[0].strip()
    if raw:
        raw = _RE_STRIP_ART.sub("", raw).strip()
        raw = re.sub(r"^[-–]\s+", "", raw)
        estrutura.append({
            "tipo":     "caput",
            "conteudo": extrair_incisos(raw),
        })

    for i in range(1, len(partes), 2):
        marcador = partes[i].strip()
        corp     = partes[i + 1].strip() if i + 1 < len(partes) else ""
        corp = re.sub(r"^[-–]\s+", "", corp)
        corp = re.sub(r"^\.\s+", "", corp)

        if re.search(r"único", marcador, re.IGNORECASE):
            numero = "único"
        else:
            m = re.search(r"(\d+[°oº║]?(?:-[A-Za-z])?)", marcador)
            numero = m.group(1) if m else None
            if numero:
                numero = re.sub(r"[°oº║]", "", numero)

        estrutura.append({
            "tipo":     "paragrafo",
            "numero":   numero,
            "conteudo": extrair_incisos(corp),
        })

    return estrutura


# ═══════════════════════════════════════════════════════
# FASE 5 — PARSE DE ARTIGOS
# ═══════════════════════════════════════════════════════

_SPLIT_ARTIGO = re.compile(r"\n(?=Art\.?\s*\d)")   # SEM IGNORECASE
_RE_ART_NUM   = re.compile(r"Art\.?\s*(\d+[°oº]?(?:-[A-Za-z])?)")


def _coletar_metas(obj) -> list:
    result = []
    if isinstance(obj, dict):
        result.extend(obj.get("metadados", []))
        for v in obj.values():
            if isinstance(v, (dict, list)):
                result.extend(_coletar_metas(v))
    elif isinstance(obj, list):
        for item in obj:
            result.extend(_coletar_metas(item))
    return result


def _parse_artigos(bloco: str, lei: str, ordem: list) -> list:
    artigos = []
    for txt in _SPLIT_ARTIGO.split(bloco):
        txt = txt.strip()

        if not txt.startswith("Art"):
            continue

        if txt.startswith("referência_interna:"):
            continue

        m = _RE_ART_NUM.match(txt)
        if not m:
            continue
        numero = m.group(1)

        resto = txt[m.end():m.end() + 3].strip()
        if re.match(r"^[,;]", resto):
            logger.debug(f"Ref. cruzada descartada: {txt[:40]!r}")
            continue

        ordem[0] += 1
        id_art = f"lei-{lei}-art-{_id_num(numero)}" if _id_num(numero) else f"lei-{lei}-art-{ordem[0]}"

        # Cálculo de Confiança do Artigo
        confianca = 1.0
        if not txt.startswith("Art"): confianca -= 0.3
        if len(txt) < 10: confianca -= 0.5
        if "referência_interna" in txt: confianca -= 0.2

        estrutura = extrair_paragrafos(txt)
        metas     = _coletar_metas(estrutura)

        # Se não tem caput com texto, baixa confiança
        tem_caput = any(b.get("tipo") == "caput" and b.get("conteudo", {}).get("texto") for b in estrutura)
        if not tem_caput: confianca -= 0.4

        art: dict = {
            "id":        id_art,
            "ordem":     ordem[0],
            "numero":    numero,
            "tipo":      "artigo",
            "confianca": round(max(0.1, confianca), 2),
            "texto_bruto": txt,  # [NOVO] Guardamos o texto original para reparo via IA
            "estrutura": estrutura,
        }
        if metas:
            art["alteracoes"] = metas
        artigos.append(art)
    return artigos


# ═══════════════════════════════════════════════════════
# FASE 6 — HIERARQUIA ESTRUTURAL
# ═══════════════════════════════════════════════════════

_SPLIT_PARTE = re.compile(
    r"\n(?=PARTE\s+(?:[IVXLCDM]+|GERAL|ESPECIAL)\s*(?:\n|$))",
    re.IGNORECASE,
)
_SPLIT_LIVRO = re.compile(
    r"\n(?=LIVRO\s+[IVXLCDM]+\s*(?:\n|$))",
    re.IGNORECASE,
)
_SPLIT_TITULO = re.compile(
    r"\n(?=T[IÍ]TULO\s+[IVXLCDM]+(?:-[A-Za-z])?\s*(?:\n|$))",
    re.IGNORECASE,
)
_SPLIT_CAPITULO = re.compile(
    r"\n(?=CAP[IÍ]TULO\s+[IVXLCDM]+(?:-[A-Za-z])?\s*(?:\n|$))",
    re.IGNORECASE,
)
_SPLIT_SECAO = re.compile(
    r"\n(?=SE[ÇC][ÃA]O\s+[IVXLCDM]+(?:-[A-Za-z])?\s*(?:\n|$))",
    re.IGNORECASE,
)
_SPLIT_SUBSECAO = re.compile(
    r"\n(?=SUBSE[ÇC][ÃA]O\s+[IVXLCDM]+(?:-[A-Za-z])?\s*(?:\n|$))",
    re.IGNORECASE,
)

_RE_NUM = {
    "parte":    re.compile(r"PARTE\s+((?:[IVXLCDM]+|GERAL|ESPECIAL))", re.IGNORECASE),
    "livro":    re.compile(r"LIVRO\s+([IVXLCDM]+)",   re.IGNORECASE),
    "titulo":   re.compile(r"T[IÍ]TULO\s+([IVXLCDM]+(?:-[A-Za-z])?)", re.IGNORECASE),
    "capitulo": re.compile(r"CAP[IÍ]TULO\s+([IVXLCDM]+(?:-[A-Za-z])?)", re.IGNORECASE),
    "secao":    re.compile(r"SE[ÇC][ÃA]O\s+([IVXLCDM]+(?:-[A-Za-z])?)", re.IGNORECASE),
    "subsecao": re.compile(r"SUBSE[ÇC][ÃA]O\s+([IVXLCDM]+(?:-[A-Za-z])?)", re.IGNORECASE),
}

_RE_ESTRUTURAL = re.compile(
    r"^(?:T[IÍ]TULO|CAP[IÍ]TULO|SE[ÇC][ÃA]O|SUBSE[ÇC][ÃA]O"
    r"|LIVRO|PARTE|Art\.?\s*\d|§\s*\d|[IVXLCDM]{1,7}\s*[-–])",
    re.IGNORECASE,
)


def _extrair_nome(bloco: str, re_num: re.Pattern) -> str:
    """
    Extrai nome de um marcador hierárquico de forma robusta.

    - Pula linhas vazias após o marcador
    - Coleta linhas consecutivas não-vazias até encontrar outro marcador ou artigo
    - Une múltiplas linhas (ex: CPP Título XI tem nome em 2 linhas)
    - Para ao encontrar 2 linhas vazias seguidas após ter coletado o nome
    - [BUG10 FIX] Trunca cada parte coletada na fronteira de Art./§ embutidos,
      caso o HTML não separe o nome do primeiro artigo com linha própria.
    """
    linhas = bloco.splitlines()
    encontrou = False
    partes = []
    vazias_apos_nome = 0

    for linha in linhas:
        s = linha.strip()

        if not encontrou:
            if re_num.match(s):
                encontrou = True
            continue

        if not s:
            if partes:
                vazias_apos_nome += 1
                if vazias_apos_nome >= 2:
                    break
            continue
        else:
            vazias_apos_nome = 0

        if _RE_ESTRUTURAL.match(s):
            break

        # Metadado puro → pular
        if s.startswith("(") and s.endswith(")"):
            continue

        # [BUG10 FIX] Trunca na fronteira de Art./§ embutidos na linha
        # Isso captura casos onde o HTML não tem \n entre o nome e o artigo
        s_truncado = _truncar_na_fronteira_artigo(s)
        if s_truncado:
            partes.append(s_truncado)
        # Se após truncar o nome ficou vazio, ignoramos a linha
        # Se havia conteúdo de artigo embutido, paramos (nome já coletado)
        if s_truncado != s:
            # A linha tinha Art./§ embutido — fronteira encontrada, parar coleta
            break

    # [BUG10 FIX] Pós-processamento final: garante que o nome resultante
    # não contenha nenhum fragmento de artigo que tenha escapado
    nome_raw = limpar_texto_final(" ".join(partes))
    return _truncar_na_fronteira_artigo(nome_raw)


def _parse_subsecoes(bloco, lei, ordem):
    resultado = []
    for parte in _SPLIT_SUBSECAO.split(bloco):
        parte = parte.strip()
        m = _RE_NUM["subsecao"].match(parte)
        if m:
            resultado.append({
                "tipo":    "subsecao",
                "numero":  m.group(1),
                "nome":    _extrair_nome(parte, _RE_NUM["subsecao"]),
                "confianca": 1.0 if _extrair_nome(parte, _RE_NUM["subsecao"]) else 0.7,
                "artigos": _parse_artigos(parte, lei, ordem),
            })
        else:
            resultado.extend(_parse_artigos(parte, lei, ordem))
    return resultado


def _parse_secoes(bloco, lei, ordem):
    resultado = []
    for parte in _SPLIT_SECAO.split(bloco):
        parte = parte.strip()
        m = _RE_NUM["secao"].match(parte)
        if m:
            resultado.append({
                "tipo":   "secao",
                "numero": m.group(1),
                "nome":   _extrair_nome(parte, _RE_NUM["secao"]),
                "filhos": _parse_subsecoes(parte, lei, ordem),
            })
        else:
            resultado.extend(_parse_subsecoes(parte, lei, ordem))
    return resultado


def _parse_capitulos(bloco, lei, ordem):
    resultado = []
    for parte in _SPLIT_CAPITULO.split(bloco):
        parte = parte.strip()
        m = _RE_NUM["capitulo"].match(parte)
        if m:
            resultado.append({
                "tipo":   "capitulo",
                "numero": m.group(1),
                "nome":   _extrair_nome(parte, _RE_NUM["capitulo"]),
                "filhos": _parse_secoes(parte, lei, ordem),
            })
        else:
            resultado.extend(_parse_secoes(parte, lei, ordem))
    return resultado


def _parse_titulos(bloco, lei, ordem):
    resultado = []
    for parte in _SPLIT_TITULO.split(bloco):
        parte = parte.strip()
        m = _RE_NUM["titulo"].match(parte)
        if m:
            resultado.append({
                "tipo":   "titulo",
                "numero": m.group(1),
                "nome":   _extrair_nome(parte, _RE_NUM["titulo"]),
                "filhos": _parse_capitulos(parte, lei, ordem),
            })
        else:
            resultado.extend(_parse_capitulos(parte, lei, ordem))
    return resultado


def _parse_livros(bloco, lei, ordem):
    """
    [BUG3 FIX] Filtra "Livro IV\n." como referência cruzada.
    """
    resultado = []
    for parte in _SPLIT_LIVRO.split(bloco):
        parte = parte.strip()
        m = _RE_NUM["livro"].match(parte)
        if m:
            primeira = ""
            for l in parte.splitlines()[1:]:
                s = l.strip()
                if s:
                    primeira = s
                    break
            if re.match(r"^[.,;]$", primeira):
                resultado.extend(_parse_titulos(parte, lei, ordem))
                continue
            resultado.append({
                "tipo":   "livro",
                "numero": m.group(1),
                "nome":   _extrair_nome(parte, _RE_NUM["livro"]),
                "filhos": _parse_titulos(parte, lei, ordem),
            })
        else:
            resultado.extend(_parse_titulos(parte, lei, ordem))
    return resultado


def _parse_partes(bloco, lei, ordem):
    resultado = []
    for parte in _SPLIT_PARTE.split(bloco):
        parte = parte.strip()
        m = _RE_NUM["parte"].match(parte)
        if m:
            numero = m.group(1).upper()
            nome   = _extrair_nome(parte, _RE_NUM["parte"])
            tem_livro = bool(_SPLIT_LIVRO.search(parte))
            filhos = _parse_livros(parte, lei, ordem) if tem_livro else _parse_titulos(parte, lei, ordem)
            resultado.append({
                "tipo":   "parte",
                "numero": numero,
                "nome":   nome,
                "filhos": filhos,
            })
        else:
            tem_livro = bool(_SPLIT_LIVRO.search(parte))
            if tem_livro:
                resultado.extend(_parse_livros(parte, lei, ordem))
            else:
                resultado.extend(_parse_titulos(parte, lei, ordem))
    return resultado


# ═══════════════════════════════════════════════════════
# FASE 7 — AUTO-DETECÇÃO DE RAIZ
# ═══════════════════════════════════════════════════════

def _detectar_raiz(texto: str) -> str:
    candidatos = {}
    padroes = [
        ("parte",    re.compile(r"\nPARTE\s+(?:[IVXLCDM]+|GERAL|ESPECIAL)\s*(?:\n|$)", re.IGNORECASE)),
        ("livro",    re.compile(r"\nLIVRO\s+[IVXLCDM]+\s*(?:\n|$)", re.IGNORECASE)),
        ("titulo",   re.compile(r"\nT[IÍ]TULO\s+[IVXLCDM]+(?:-[A-Za-z])?\s*(?:\n|$)", re.IGNORECASE)),
        ("capitulo", re.compile(r"\nCAP[IÍ]TULO\s+[IVXLCDM]+(?:-[A-Za-z])?\s*(?:\n|$)", re.IGNORECASE)),
    ]
    for nome, pat in padroes:
        m = pat.search(texto)
        if m:
            candidatos[nome] = m.start()

    if not candidatos:
        return "artigo"

    if "livro" in candidatos:
        reais = 0
        for m in re.finditer(r"\nLIVRO\s+[IVXLCDM]+\s*\n", texto, re.IGNORECASE):
            for linha in texto[m.end():].splitlines():
                s = linha.strip()
                if s:
                    if not re.match(r"^[.,;]$", s):
                        reais += 1
                    break
        if reais == 0:
            del candidatos["livro"]

    return min(candidatos, key=candidatos.get) if candidatos else "artigo"


# ═══════════════════════════════════════════════════════
# PARSE PRINCIPAL
# ═══════════════════════════════════════════════════════

def parse_lei(texto: str, codigo_lei: str = "0000") -> dict:
    """
    Converte texto bruto de uma lei em JSON hierárquico.
    A hierarquia é auto-detectada (PARTE > LIVRO > TÍTULO > CAPÍTULO > SEÇÃO).
    """
    texto = normalizar_texto(texto)

    m_ementa = re.search(
        r"(Estabelece|Dispõe|Define|Institui|Regulamenta|Cria|Altera)[^.]+\.",
        texto,
    )
    ementa = limpar_texto_final(m_ementa.group(0)) if m_ementa else ""

    resultado = {
        "lei":     {"codigo": codigo_lei, "ementa": ementa},
        "titulos": [],
    }

    ordem = [0]
    raiz = _detectar_raiz(texto)
    logger.info(f"Lei {codigo_lei}: raiz = {raiz}")

    if raiz == "parte":
        resultado["titulos"] = _parse_partes(texto, codigo_lei, ordem)
    elif raiz == "livro":
        resultado["titulos"] = _parse_livros(texto, codigo_lei, ordem)
    elif raiz == "titulo":
        resultado["titulos"] = _parse_titulos(texto, codigo_lei, ordem)
    elif raiz == "capitulo":
        for parte in _SPLIT_CAPITULO.split(texto)[1:]:
            parte = parte.strip()
            m = _RE_NUM["capitulo"].match(parte)
            if m:
                resultado["titulos"].append({
                    "tipo":   "capitulo",
                    "numero": m.group(1),
                    "nome":   _extrair_nome(parte, _RE_NUM["capitulo"]),
                    "filhos": _parse_secoes(parte, codigo_lei, ordem),
                })
    else:
        resultado["titulos"] = _parse_artigos(texto, codigo_lei, ordem)

    logger.info(
        f"Lei {codigo_lei}: {ordem[0]} artigos, "
        f"{len(resultado['titulos'])} blocos [{raiz}]"
    )
    return resultado


# ═══════════════════════════════════════════════════════
# UTILIDADE: iteração de artigos em ordem de documento (DFS)
# ═══════════════════════════════════════════════════════

def iterar_artigos(resultado: dict):
    """
    Itera artigos em ordem de documento usando DFS pré-ordem.
    """
    def _dfs(node):
        if isinstance(node, dict):
            if node.get("tipo") == "artigo":
                yield node
            else:
                for chave in ("titulos", "filhos", "artigos", "estrutura"):
                    if chave in node and isinstance(node[chave], list):
                        for item in node[chave]:
                            yield from _dfs(item)
        elif isinstance(node, list):
            for item in node:
                yield from _dfs(item)

    yield from _dfs(resultado)


def _iterar_artigos_mut(resultado: dict):
    """
    Itera artigos em ordem de documento de forma mutável (permite editar o dict).
    """
    yield from iterar_artigos(resultado)


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    entrada = sys.argv[1] if len(sys.argv) > 1 else "rawldb.txt"
    saida   = sys.argv[2] if len(sys.argv) > 2 else "struct.json"
    codigo  = sys.argv[3] if len(sys.argv) > 3 else "0000"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    with open(entrada, "r", encoding="utf-8") as f:
        txt = f.read()

    resultado = parse_lei(txt, codigo_lei=codigo)

    with open(saida, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    print(f"Salvo em '{saida}'")