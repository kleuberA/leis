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
from validator import validar_estrutura, imprimir_relatorio, precisa_revisao
from crossref import extrair_crossrefs_estrutura
from smart_parser import smart_parser
from supabase_storage import storage
from downloader import calcular_fingerprint

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
    opcoes: dict | None = None,
    progress_callback: callable = None,
    persistir: bool = False,
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
        opcoes:      Opções de parse (ex: tem_rubricas, rigor).
        progress_callback: Função para reportar progresso real-time.
        persistir:   Se True, salva no Supabase automaticamente.

    Returns:
        Dict com 'estrutura', 'relatorio', e opcionalmente 'crossrefs'.
    """
    base = saida_dir or Path(".")
    base.mkdir(parents=True, exist_ok=True)

    # Organização em subpastas conforme api.py
    (base / "raw").mkdir(exist_ok=True)
    (base / "struct").mkdir(exist_ok=True)
    (base / "relatorio").mkdir(exist_ok=True)
    (base / "crossrefs").mkdir(exist_ok=True)

    saida_txt   = base / "raw" / f"raw_{codigo}.txt"
    saida_json  = base / "struct" / f"struct_{codigo}.json"
    saida_relat = base / "relatorio" / f"relatorio_{codigo}.json"
    saida_refs  = base / "crossrefs" / f"crossrefs_{codigo}.json"

    def log(msg, level=logging.INFO):
        logger.log(level, msg)
        if progress_callback:
            progress_callback(msg)

    cfg_lei  = info_lei(codigo)
    nome_lei = cfg_lei.get("nome", codigo) if cfg_lei else codigo

    log(f"{'═'*55}")
    log(f"  Pipeline: {nome_lei}")
    log(f"{'═'*55}")

    # ── ETAPA 1: Download ────────────────────────────────────────
    log(f"[1/4] Navegando até a lei...")
    
    # Obtém o conteúdo bruto e calcula fingerprint
    if url:
        log(f"      Lei encontrada no site: {url}")
        texto = baixar_lei_url(url, fonte=fonte, usar_cache=usar_cache)
    else:
        log(f"      Lei encontrada no catálogo: {codigo}")
        texto = baixar_lei(codigo, usar_cache=usar_cache)

    log(f"      Download concluído ({len(texto):,} caracteres).")
    saida_txt.write_text(texto, encoding="utf-8")
    hash_txt = calcular_fingerprint(texto.encode("utf-8"))
    log(f"      Fingerprint: {hash_txt[:16]}...")

    # ── ETAPA 2: Parse ───────────────────────────────────────────
    log(f"[2/4] Iniciando parsing da estrutura...")
    
    url_lei = url or (cfg_lei.get("url") if cfg_lei else None)
    estrutura = parse_lei(texto, codigo_lei=codigo, url=url_lei, opcoes=opcoes)
    log(f"      Parse concluído.")
    
    # ── ETAPA 2.1: Supabase Storage ──────────────────────────────
    if persistir:
        log(f"[2.1] Armazenamento (Supabase)")
        storage.salvar_lei_completa(estrutura, url_lei or "manual", hash_txt)
    else:
        log(f"[2.1] Armazenamento automático desativado.")

    saida_json.write_text(
        json.dumps(estrutura, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

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
        log(f"[3/4] Extraindo referências cruzadas...")
        crossrefs = extrair_crossrefs_estrutura(estrutura, codigo_lei=codigo)
        saida_refs.write_text(
            json.dumps(crossrefs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log(f"      {len(crossrefs)} referências encontradas.")
    else:
        log(f"[3/4] Cross-references ignoradas.")

    # ── ETAPA 4: Validação + guarda de precisão ──────────────────
    log(f"[4/4] Validando integridade...")
    relatorio = validar_estrutura(estrutura)
    precisa_rev = precisa_revisao(relatorio)
    
    # Atualiza status no Supabase se precisar de revisão
    if persistir and precisa_rev:
        log("      Atenção: Lei marcada para REVISÃO HUMANA no banco.", level=logging.WARNING)
        storage._update("leis", {"id_lei": estrutura.get("lei", {}).get("id_lei", 0)}, {"needs_review": True})

    saida_relat.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    imprimir_relatorio(relatorio)
    log(f"      Relatório gerado em JSON.")

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


def concatenar_texto_artigo(artigo: dict) -> str:
    """
    Concatena caput + incisos + alineas + paragrafos em um único bloco de texto,
    preservando a estrutura para leitura humana.
    """
    partes = []
    
    for bloco in artigo.get("estrutura", []):
        tipo = bloco.get("tipo")
        conteudo = bloco.get("conteudo", {})
        
        if not isinstance(conteudo, dict):
            continue
            
        texto_bloco = conteudo.get("texto", "").strip()
        
        if tipo == "caput":
            if texto_bloco:
                partes.append(texto_bloco)
        elif tipo == "paragrafo":
            num = bloco.get("numero", "")
            prefixo = f"§ {num}" if num != "único" else "Parágrafo único."
            if texto_bloco:
                partes.append(f"{prefixo} {texto_bloco}")
            else:
                partes.append(prefixo)
        
        # Incisos (podem estar no caput ou no parágrafo no schema atual)
        for inciso in conteudo.get("incisos", []):
            num_inc = inciso.get("numero", "")
            cont_inc = inciso.get("conteudo", {})
            texto_inc = cont_inc.get("texto", "").strip()
            partes.append(f"{num_inc} - {texto_inc}")
            
            # Alíneas do inciso
            for alinea in cont_inc.get("alineas", []):
                letra = alinea.get("letra", "")
                texto_al = alinea.get("texto", "").strip()
                partes.append(f"  {letra}) {texto_al}")
                
        # Alíneas diretas do bloco (raro, mas possível)
        for alinea in conteudo.get("alineas", []):
            letra = alinea.get("letra", "")
            texto_al = alinea.get("texto", "").strip()
            partes.append(f"{letra}) {texto_al}")

    return "\n".join(partes)


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
        
        estrutura = parse_lei(texto, codigo_lei=sugestao_codigo, url=url)
        
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
    ap.add_argument("--rubricas", action="store_true",
                    help="Ativa a extração de rubricas de artigos")
    ap.add_argument("--rigor", choices=["normal", "alto"], default="normal",
                    help="Define o rigor da normalização (padrão: normal)")

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
    opcoes = {
        "tem_rubricas": args.rubricas,
        "rigor": args.rigor
    }

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
            opcoes=opcoes,
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
            opcoes=opcoes,
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
            opcoes=opcoes,
        )


if __name__ == "__main__":
    main()