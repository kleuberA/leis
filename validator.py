"""
validator.py — v2
Valida a estrutura JSON gerada pelo parser v4 e produz relatório detalhado.

Atualizado para o novo schema consistente de conteúdo:
  { "texto": "...", "incisos": [...], "alineas": [...], "metadados": [...] }
"""

import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# HELPERS DE PERCURSO
# ═══════════════════════════════════════════════════════════════

def _coletar_artigos(no: dict | list, acumulador: list) -> None:
    if isinstance(no, list):
        for item in no:
            _coletar_artigos(item, acumulador)
        return

    if not isinstance(no, dict):
        return

    tipo = no.get("tipo")

    if tipo == "artigo":
        acumulador.append(no)
        return

    for chave in ("filhos", "artigos", "titulos", "capitulos", "secoes", "subsecoes"):
        if chave in no:
            _coletar_artigos(no[chave], acumulador)


def _caput_tem_texto(estrutura: list) -> bool:
    """
    Retorna True se o caput tem texto não-vazio.
    Compatível com o novo schema: conteudo é sempre um dict com "texto".
    """
    for bloco in estrutura:
        if bloco.get("tipo") == "caput":
            conteudo = bloco.get("conteudo")
            if isinstance(conteudo, dict):
                # Novo schema: sempre tem "texto"
                texto = conteudo.get("texto", "").strip()
                # Tem texto OU tem incisos diretos (artigo de lista pura)
                return bool(texto) or bool(conteudo.get("incisos"))
            elif isinstance(conteudo, list):
                # Schema legado: lista de incisos diretamente
                return len(conteudo) > 0
    return False


def _artigo_revogado(artigo: dict) -> bool:
    for alt in artigo.get("alteracoes", []):
        if alt.get("tipo") == "revogado":
            return True
    for bloco in artigo.get("estrutura", []):
        if bloco.get("tipo") == "caput":
            conteudo = bloco.get("conteudo", {})
            texto = ""
            if isinstance(conteudo, dict):
                texto = conteudo.get("texto", "")
            if "revogado" in texto.lower():
                return True
    return False


def _validar_conteudo(artigo_id: str, conteudo, relatorio: dict) -> None:
    """
    Valida o conteúdo de um bloco (caput ou parágrafo).
    Novo schema: conteudo é sempre dict com "texto" e opcionalmente "incisos"/"alineas".
    """
    if conteudo is None:
        relatorio["warnings"].append(f"{artigo_id}: conteúdo None encontrado")
        return

    if isinstance(conteudo, dict):
        # Valida incisos se houver
        for inciso in conteudo.get("incisos", []):
            if not isinstance(inciso, dict):
                continue
            if inciso.get("tipo") != "inciso":
                relatorio["warnings"].append(
                    f"{artigo_id}: item em 'incisos' sem tipo='inciso'"
                )
            sub = inciso.get("conteudo")
            if sub is None:
                relatorio["incisos_sem_conteudo"].append(artigo_id)
            elif isinstance(sub, dict):
                # Valida alíneas do inciso
                for alinea in sub.get("alineas", []):
                    if not isinstance(alinea, dict) or alinea.get("tipo") != "alinea":
                        relatorio["alineas_fora_de_lugar"].append(artigo_id)
        # Valida alíneas diretas no conteúdo (sem incisos)
        for alinea in conteudo.get("alineas", []):
            if not isinstance(alinea, dict) or alinea.get("tipo") != "alinea":
                relatorio["alineas_fora_de_lugar"].append(artigo_id)

    elif isinstance(conteudo, list):
        # Schema legado: lista direta — emite warning mas não falha
        relatorio["warnings"].append(
            f"{artigo_id}: conteúdo em formato legado (lista direta)"
        )


# ═══════════════════════════════════════════════════════════════
# ESTATÍSTICAS ADICIONAIS
# ═══════════════════════════════════════════════════════════════

def _contar_incisos_e_alineas(artigos: list) -> dict:
    """Conta incisos e alíneas totais na estrutura."""
    total_incisos = 0
    total_alineas = 0

    def _contar_no(conteudo):
        nonlocal total_incisos, total_alineas
        if not isinstance(conteudo, dict):
            return
        incisos = conteudo.get("incisos", [])
        total_incisos += len(incisos)
        for inc in incisos:
            sub = inc.get("conteudo", {})
            if isinstance(sub, dict):
                total_alineas += len(sub.get("alineas", []))
        total_alineas += len(conteudo.get("alineas", []))

    for artigo in artigos:
        for bloco in artigo.get("estrutura", []):
            _contar_no(bloco.get("conteudo"))

    return {"total_incisos": total_incisos, "total_alineas": total_alineas}


# ═══════════════════════════════════════════════════════════════
# VALIDAÇÃO PRINCIPAL
# ═══════════════════════════════════════════════════════════════

def validar_estrutura(dados: dict | list) -> dict:
    if isinstance(dados, dict):
        arvore = dados.get("titulos", [])
        info_lei = dados.get("lei", {})
    else:
        arvore = dados
        info_lei = {}

    relatorio = {
        "lei": info_lei,
        "timestamp": datetime.now().isoformat(),
        "total_artigos": 0,
        "total_titulos": len(arvore),
        "artigos_por_titulo": {},
        "artigos_vazios": [],
        "artigos_sem_texto_caput": [],
        "artigos_revogados": [],
        "ids_duplicados": [],
        "incisos_sem_conteudo": [],
        "alineas_fora_de_lugar": [],
        "estatisticas": {},
        "warnings": [],
    }

    todos_artigos: list[dict] = []
    _coletar_artigos(arvore, todos_artigos)

    relatorio["total_artigos"] = len(todos_artigos)

    # Estatísticas adicionais
    relatorio["estatisticas"] = _contar_incisos_e_alineas(todos_artigos)

    # Artigos por título
    for titulo in arvore:
        arts_do_titulo: list[dict] = []
        _coletar_artigos(titulo, arts_do_titulo)
        chave = f"Título {titulo.get('numero', '?')} — {titulo.get('nome', '')}"
        relatorio["artigos_por_titulo"][chave] = len(arts_do_titulo)

    # Valida cada artigo
    ids_vistos: set[str] = set()
    ids_repetidos: set[str] = set()

    for artigo in todos_artigos:
        art_id = artigo.get("id", f"sem-id-{artigo.get('numero', '?')}")

        if art_id in ids_vistos:
            ids_repetidos.add(art_id)
        ids_vistos.add(art_id)

        estrutura = artigo.get("estrutura")

        if not estrutura:
            relatorio["artigos_vazios"].append(art_id)
            continue

        if not _caput_tem_texto(estrutura):
            relatorio["artigos_sem_texto_caput"].append(art_id)

        if _artigo_revogado(artigo):
            relatorio["artigos_revogados"].append(art_id)

        for bloco in estrutura:
            tipo_bloco = bloco.get("tipo")
            if tipo_bloco in ("caput", "paragrafo"):
                _validar_conteudo(art_id, bloco.get("conteudo"), relatorio)

    relatorio["ids_duplicados"] = sorted(ids_repetidos)

    for chave in ("artigos_vazios", "artigos_sem_texto_caput", "artigos_revogados",
                  "incisos_sem_conteudo", "alineas_fora_de_lugar"):
        relatorio[chave] = sorted(set(relatorio[chave]))

    return relatorio


# ═══════════════════════════════════════════════════════════════
# IMPRESSÃO DO RELATÓRIO
# ═══════════════════════════════════════════════════════════════

def imprimir_relatorio(r: dict) -> None:
    lei = r.get("lei", {})
    print("\n" + "═" * 50)
    print("  RELATÓRIO ESTRUTURAL")
    if lei:
        print(f"  Lei {lei.get('codigo', '?')}")
    print(f"  Gerado em: {r.get('timestamp', '?')}")
    print("═" * 50)

    print(f"\n📚 Total de artigos:    {r['total_artigos']}")
    print(f"📂 Total de títulos:    {r['total_titulos']}")

    est = r.get("estatisticas", {})
    if est:
        print(f"📋 Total de incisos:    {est.get('total_incisos', 0)}")
        print(f"📌 Total de alíneas:    {est.get('total_alineas', 0)}")

    print("\n📊 Artigos por título:")
    for titulo, qtd in r.get("artigos_por_titulo", {}).items():
        print(f"   {titulo}: {qtd}")

    print(f"\n{'─'*40}")
    _linha("🔴 IDs duplicados",          r["ids_duplicados"])
    _linha("🔴 Artigos vazios",           r["artigos_vazios"])
    _linha("🟠 Caput sem texto",          r["artigos_sem_texto_caput"])
    _linha("🟡 Artigos revogados",        r["artigos_revogados"])
    _linha("🟡 Incisos sem conteúdo",     r["incisos_sem_conteudo"])
    _linha("🟡 Alíneas fora de lugar",    r["alineas_fora_de_lugar"])

    if r.get("warnings"):
        print(f"\n⚠️  Warnings ({len(r['warnings'])}):")
        for w in r["warnings"][:10]:
            print(f"   • {w}")
        if len(r["warnings"]) > 10:
            print(f"   ... e mais {len(r['warnings']) - 10}")

    print("\n" + "═" * 50 + "\n")


def _linha(label: str, lista: list) -> None:
    status = "✅ Nenhum" if not lista else f"{len(lista)} encontrado(s)"
    print(f"{label}: {status}")
    if lista:
        for item in lista[:5]:
            print(f"   • {item}")
        if len(lista) > 5:
            print(f"   ... e mais {len(lista) - 5}")


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    entrada     = sys.argv[1] if len(sys.argv) > 1 else "ldb_struct.json"
    saida_relat = sys.argv[2] if len(sys.argv) > 2 else "relatorio_validacao.json"

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    with open(entrada, "r", encoding="utf-8") as f:
        dados = json.load(f)

    relatorio = validar_estrutura(dados)

    with open(saida_relat, "w", encoding="utf-8") as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=2)

    imprimir_relatorio(relatorio)
    print(f"Relatório salvo em '{saida_relat}'")