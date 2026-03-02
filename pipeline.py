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
from parser import parse_lei, _iterar_artigos_mut
from validator import validar_estrutura, imprimir_relatorio
from crossref import extrair_crossrefs_estrutura
from smart_parser import smart_parser

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

    # ── ETAPA 2.5: Smart Repair (IA) ─────────────────────────────
    if smart_parser.enabled:
        logger.info(f"[2.5] Smart Repair (IA)")
        reparados = 0
        for art in _iterar_artigos_mut(estrutura):
            if art.get("confianca", 1.0) < 0.7:
                texto_bruto = art.get("texto_bruto")
                if not texto_bruto: continue
                
                novo_art = smart_parser.recuperar_artigo(texto_bruto, art.get("numero", ""))
                if novo_art:
                    # Atualiza o nó mantendo ID e Ordem originais
                    art["numero"]    = novo_art.get("numero", art["numero"])
                    art["estrutura"] = novo_art.get("estrutura", art["estrutura"])
                    art["confianca"] = novo_art.get("confianca_ia", 0.9)
                    art["reparado_ia"] = True
                    reparados += 1
                    
        if reparados:
            logger.info(f"      {reparados} artigos reparados via IA.")
            saida_json.write_text(json.dumps(estrutura, ensure_ascii=False, indent=2), encoding="utf-8")

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
            msg = f"REGRESSÃO DE PRECISÃO: {precisao:.1%} < {PRECISAO_MINIMA_ARTIGOS:.0%} ({vazios}/{total} artigos vazios)"
            logger.error(msg)
            # No CLI antigo matamos o processo, na API lançamos ou avisamos
            if __name__ == "__main__":
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


def suggest_config(url: str, nome: str = "") -> dict:
    """Gera uma sugestão de configuração para o leis.yaml a partir da URL."""
    from downloader import baixar_lei_url
    from parser import parse_lei
    
    print(f"🔍 Analisando URL para sugestão de config: {url}")
    try:
        texto = baixar_lei_url(url, usar_cache=True)
        # Tenta inferir o código do final da URL
        sugestao_codigo = Path(url).stem.replace("l", "").replace("compilado", "").replace("compilada", "")
        if not sugestao_codigo: sugestao_codigo = "nova_lei"
        
        estrutura = parse_lei(texto, codigo_lei=sugestao_codigo)
        
        # Infeção básica de tags
        tags = []
        if "penal" in nome.lower() or "crime" in nome.lower(): tags.append("penal")
        if "civil" in nome.lower(): tags.append("civil")
        
        config = {
            sugestao_codigo: {
                "nome": nome or estrutura.get("lei", {}).get("ementa", "Nova Lei")[:60] + "...",
                "url": url,
                "fonte": "planalto" if "planalto.gov.br" in url else "auto",
                "encoding": "latin-1" if "planalto.gov.br" in url else "utf-8",
                "tags": tags
            }
        }
        return config
    except Exception as e:
        print(f"❌ Erro ao sugerir config: {e}")
        return {}


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
    grupo.add_argument("--suggest", nargs=2, metavar=("URL", "NOME"),
                       help="Sugerir configuração para uma nova lei")

    ap.add_argument("--url",    help="URL direta (ignora catálogo, requer --codigo)")
    ap.add_argument("--codigo", help="Código da lei ao usar --url")
    ap.add_argument("--fonte",  default="planalto",
                    choices=["planalto", "senado", "camara"],
                    help="Fonte para --url (padrão: planalto)")
    ap.add_argument("--sem-cache", action="store_true",
                    help="Força re-download mesmo com cache disponível")
    ap.add_argument("--sem-refs", action="store_true",
                    help="Pula extração de cross-references")
    ap.add_argument("--review", action="store_true",
                    help="Gera relatório de revisão HTML após o processamento")
    ap.add_argument("--saida", default=".",
                    help="Diretório de saída dos arquivos (padrão: .)")

    args = ap.parse_args()

    if args.listar:
        print("\nLeis disponíveis no catálogo:\n")
        from downloader import listar_leis
        for cod, nome in listar_leis().items():
            print(f"  {cod:12} {nome}")
        print()
        return

    if args.suggest:
        import yaml
        sugestao = suggest_config(args.suggest[0], args.suggest[1])
        print("\n--- SUGESTÃO PARA config/leis.yaml ---")
        print(yaml.dump(sugestao, allow_unicode=True, default_flow_style=False))
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
        if args.review:
            from review_viewer import generate_review_html
            generate_review_html(f"struct_{args.codigo}.json", f"raw_{args.codigo}.txt", f"review_{args.codigo}.html")
    elif args.lei:
        run(
            codigo=args.lei,
            usar_cache=usar_cache,
            extrair_refs=extrair,
            saida_dir=saida_dir,
        )
        if args.review:
            from review_viewer import generate_review_html
            generate_review_html(f"struct_{args.lei}.json", f"raw_{args.lei}.txt", f"review_{args.lei}.html")
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