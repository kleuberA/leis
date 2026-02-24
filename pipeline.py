"""
pipeline.py — v2
Orquestra o pipeline completo: download → parse → cross-refs → validação.

Novidades v2:
  - Suporte a múltiplas leis por código do catálogo (config/leis.yaml)
  - Extração de cross-references em JSON separado
  - Modo batch: processa várias leis em sequência
  - Relatório de precisão com threshold configurável

Uso:
    python pipeline.py                         # LDB (padrão)
    python pipeline.py --lei 9394
    python pipeline.py --lei 10406             # Código Civil
    python pipeline.py --batch 9394 8078 clt  # Múltiplas leis
    python pipeline.py --url URL --codigo xyz  # URL avulsa
    python pipeline.py --listar               # Lista leis disponíveis
    python pipeline.py --sem-cache            # Força re-download
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from downloader import baixar_lei, baixar_lei_url, listar_leis, info_lei
from parser import parse_lei
from validator import validar_estrutura, imprimir_relatorio
from crossref import extrair_crossrefs_estrutura

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Threshold mínimo de qualidade para não falhar o pipeline
PRECISAO_MINIMA_ARTIGOS = 0.95    # 95% dos artigos devem ter estrutura


def run(
    codigo: str,
    url: str | None = None,
    fonte: str = "planalto",
    usar_cache: bool = True,
    extrair_refs: bool = True,
    saida_dir: Path | None = None,
) -> dict:
    """
    Executa o pipeline completo para uma lei.

    Args:
        codigo:      Código da lei (para IDs, nomes de arquivo, e lookup no catálogo).
        url:         URL direta (opcional). Se omitida, usa o catálogo.
        fonte:       Fonte para adapter quando url é fornecida diretamente.
        usar_cache:  Se True, usa HTML em cache quando disponível.
        extrair_refs: Se True, extrai cross-references e salva JSON.
        saida_dir:   Diretório de saída. Padrão: diretório atual.

    Returns:
        Dict com 'estrutura', 'relatorio', e opcionalmente 'crossrefs'.
    """
    base = saida_dir or Path(".")
    base.mkdir(parents=True, exist_ok=True)

    saida_txt   = base / f"raw_{codigo}.txt"
    saida_json  = base / f"struct_{codigo}.json"
    saida_relat = base / f"relatorio_{codigo}.json"
    saida_refs  = base / f"crossrefs_{codigo}.json"

    # Resolve nome da lei para logs
    cfg_lei  = info_lei(codigo) or {}
    nome_lei = cfg_lei.get("nome", f"Lei {codigo}")

    logger.info(f"{'═'*55}")
    logger.info(f"  Pipeline: {nome_lei}")
    logger.info(f"{'═'*55}")

    # ── ETAPA 1: Download ────────────────────────────────────────
    logger.info(f"[1/4] Download")
    if url:
        texto = baixar_lei_url(url, fonte=fonte, usar_cache=usar_cache)
    else:
        texto = baixar_lei(codigo, usar_cache=usar_cache)

    saida_txt.write_text(texto, encoding="utf-8")
    logger.info(f"      Texto salvo: {saida_txt} ({len(texto):,} chars)")

    # ── ETAPA 2: Parse ───────────────────────────────────────────
    logger.info(f"[2/4] Parse")
    estrutura = parse_lei(texto, codigo_lei=codigo)
    saida_json.write_text(
        json.dumps(estrutura, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"      JSON salvo: {saida_json}")

    # ── ETAPA 3: Cross-references ────────────────────────────────
    crossrefs = []
    if extrair_refs:
        logger.info(f"[3/4] Cross-references")
        crossrefs = extrair_crossrefs_estrutura(estrutura, codigo_lei=codigo)
        saida_refs.write_text(
            json.dumps(crossrefs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"      {len(crossrefs)} referências salvas: {saida_refs}")
    else:
        logger.info(f"[3/4] Cross-references (pulado)")

    # ── ETAPA 4: Validação + guarda de precisão ──────────────────
    logger.info(f"[4/4] Validação")
    relatorio = validar_estrutura(estrutura)
    saida_relat.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    imprimir_relatorio(relatorio)
    logger.info(f"      Relatório salvo: {saida_relat}")

    # Verifica threshold de qualidade
    total   = relatorio.get("total_artigos", 0)
    vazios  = len(relatorio.get("artigos_vazios", []))
    if total > 0:
        precisao = 1.0 - (vazios / total)
        if precisao < PRECISAO_MINIMA_ARTIGOS:
            logger.error(
                f"REGRESSÃO DE PRECISÃO: {precisao:.1%} < {PRECISAO_MINIMA_ARTIGOS:.0%} "
                f"({vazios}/{total} artigos vazios)"
            )
            sys.exit(2)
        else:
            logger.info(f"      Precisão estrutural: {precisao:.1%} ✓")

    return {"estrutura": estrutura, "relatorio": relatorio, "crossrefs": crossrefs}


def run_batch(
    codigos: list[str],
    usar_cache: bool = True,
    saida_dir: Path | None = None,
) -> list[dict]:
    """
    Processa múltiplas leis em sequência.
    Continua mesmo se uma lei falhar, reportando os erros no final.
    """
    resultados = []
    erros = []

    for i, codigo in enumerate(codigos, 1):
        logger.info(f"\n[{i}/{len(codigos)}] Processando lei: {codigo}")
        try:
            resultado = run(
                codigo=codigo,
                usar_cache=usar_cache,
                saida_dir=saida_dir,
            )
            resultados.append({"codigo": codigo, "status": "ok", **resultado})
        except KeyError as e:
            msg = f"Lei '{codigo}' não encontrada no catálogo"
            logger.error(msg)
            erros.append({"codigo": codigo, "erro": msg})
        except Exception as e:
            msg = str(e)
            logger.error(f"Falha ao processar lei {codigo}: {msg}")
            erros.append({"codigo": codigo, "erro": msg})

    # Sumário do batch
    logger.info(f"\n{'═'*55}")
    logger.info(f"  BATCH CONCLUÍDO: {len(resultados)} ok, {len(erros)} erro(s)")
    if erros:
        for e in erros:
            logger.error(f"  ✗ {e['codigo']}: {e['erro']}")
    logger.info(f"{'═'*55}")

    return resultados


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Pipeline de scraping de leis brasileiras v2"
    )

    grupo = ap.add_mutually_exclusive_group()
    grupo.add_argument("--lei",    help="Código de uma lei do catálogo (ex: 9394)")
    grupo.add_argument("--batch",  nargs="+", metavar="CODIGO",
                       help="Múltiplos códigos para processamento em lote")
    grupo.add_argument("--listar", action="store_true",
                       help="Lista todas as leis disponíveis no catálogo")

    ap.add_argument("--url",    help="URL direta (ignora catálogo, requer --codigo)")
    ap.add_argument("--codigo", help="Código da lei ao usar --url")
    ap.add_argument("--fonte",  default="planalto",
                    choices=["planalto", "senado", "camara"],
                    help="Fonte para --url (padrão: planalto)")
    ap.add_argument("--sem-cache", action="store_true",
                    help="Força re-download mesmo com cache disponível")
    ap.add_argument("--sem-refs", action="store_true",
                    help="Pula extração de cross-references")
    ap.add_argument("--saida", default=".",
                    help="Diretório de saída dos arquivos (padrão: .)")

    args = ap.parse_args()

    if args.listar:
        print("\nLeis disponíveis no catálogo:\n")
        for cod, nome in listar_leis().items():
            print(f"  {cod:12} {nome}")
        print()
        return

    saida_dir  = Path(args.saida)
    usar_cache = not args.sem_cache
    extrair    = not args.sem_refs

    if args.batch:
        run_batch(args.batch, usar_cache=usar_cache, saida_dir=saida_dir)

    elif args.url:
        if not args.codigo:
            ap.error("--url requer --codigo")
        run(
            codigo=args.codigo,
            url=args.url,
            fonte=args.fonte,
            usar_cache=usar_cache,
            extrair_refs=extrair,
            saida_dir=saida_dir,
        )

    elif args.lei:
        run(
            codigo=args.lei,
            usar_cache=usar_cache,
            extrair_refs=extrair,
            saida_dir=saida_dir,
        )

    else:
        # Padrão: LDB
        logger.info("Nenhuma lei especificada — usando padrão: LDB (9394)")
        run(
            codigo="9394",
            usar_cache=usar_cache,
            extrair_refs=extrair,
            saida_dir=saida_dir,
        )


if __name__ == "__main__":
    main()