"""
verify_storage.py -- Testa e verifica a logica de flatten + batch insert.

Uso:
  python verify_storage.py                    # Verifica integridade no banco
  python verify_storage.py --dry-run 9394     # Simula flatten sem salvar
  python verify_storage.py --save 9394        # Salva lei 9394 no banco
"""

import argparse
import json
import logging
import sys
import os
from pathlib import Path
from collections import Counter

# Fix Windows console encoding
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def dry_run_flatten(codigo: str):
    """Executa o flatten sem salvar -- apenas analisa a estrutura."""
    from supabase_storage import SupabaseStorage, ORDEM_INSERT

    storage = SupabaseStorage()

    # Carrega JSON
    for path in [
        Path(f"struct/struct_{codigo}.json"),
        Path(f"data/struct/struct_{codigo}.json"),
    ]:
        if path.exists():
            break
    else:
        print(f"[ERRO] Arquivo struct_{codigo}.json nao encontrado!")
        return

    print(f"[LOAD] Carregando: {path}")
    with open(path, "r", encoding="utf-8") as f:
        estrutura = json.load(f)

    filhos_raiz = estrutura.get("titulos", [])

    # Flatten
    print(f"\n[FLAT] Executando flatten...")
    nodes_by_table, articles = storage._flatten_tree(filhos_raiz, id_lei=0)

    # Relatorio
    print(f"\n{'='*55}")
    print(f"  RELATORIO DE FLATTEN (dry-run)")
    print(f"{'='*55}")

    total_nodes = 0
    for tabela in ORDEM_INSERT:
        count = len(nodes_by_table[tabela])
        if count > 0:
            print(f"  {tabela:15} {count:5} registros")
            total_nodes += count

    print(f"  {'-'*30}")
    print(f"  {'Nos estruturais':15} {total_nodes:5}")
    print(f"  {'Artigos':15} {len(articles):5}")
    print(f"  {'TOTAL':15} {total_nodes + len(articles):5}")

    # Verifica integridade dos temp_ids
    print(f"\n[FK] Verificacao de FKs...")
    all_temp_ids = set()
    for tabela in ORDEM_INSERT:
        for node in nodes_by_table[tabela]:
            all_temp_ids.add(node.temp_id)

    fk_errors = 0
    for tabela in ORDEM_INSERT:
        for node in nodes_by_table[tabela]:
            for fk_col, temp_ref in node.fk_temp_ids.items():
                if temp_ref not in all_temp_ids:
                    print(f"  [WARN] {tabela}: FK {fk_col} aponta para temp_id inexistente!")
                    fk_errors += 1

    for art in articles:
        for fk_col, temp_ref in art.fk_temp_ids.items():
            if temp_ref not in all_temp_ids:
                print(f"  [WARN] artigo: FK {fk_col} aponta para temp_id inexistente!")
                fk_errors += 1

    if fk_errors == 0:
        print(f"  [OK] Todas as referencias FK estao validas!")
    else:
        print(f"  [ERRO] {fk_errors} erros de FK encontrados!")

    # Amostra de artigos
    print(f"\n[SAMPLE] Amostra de artigos (primeiros 5):")
    for i, art in enumerate(articles[:5]):
        print(f"  Art. {art.data.get('numero', '?'):6} | ordem={art.data.get('ordem', '?')} | FKs: {list(art.fk_temp_ids.keys())}")
        if art.data.get('estrutura'):
            est = json.loads(art.data['estrutura'])
            print(f"         +-- estrutura: {len(est)} blocos")
        if art.data.get('alteracoes'):
            alt = json.loads(art.data['alteracoes'])
            print(f"         +-- alteracoes: {len(alt)} registros")


def verify_database():
    """Verifica a integridade dos dados no banco."""
    from supabase_storage import SupabaseStorage

    storage = SupabaseStorage()

    print(f"\n{'='*55}")
    print(f"  VERIFICACAO DO BANCO DE DADOS")
    print(f"{'='*55}")

    # Lista leis
    leis = storage.list_leis()
    print(f"\n  Leis no banco: {len(leis)}")

    for lei in leis:
        id_lei = lei.get("id_lei")
        nome = lei.get("nome", "?")[:40]
        print(f"\n  [LEI] Lei {id_lei}: {nome}")

        # Conta registros de cada tabela
        import httpx
        for tabela in ["partes", "livros", "titulos", "subtitulos", "capitulos", "secoes", "subsecoes", "artigos"]:
            try:
                with httpx.Client() as client:
                    r = client.get(
                        f"{storage.url}/rest/v1/{tabela}?id_lei=eq.{id_lei}&select=count",
                        headers={**storage.headers, "Prefer": "count=exact"}
                    )
                    count = r.headers.get("content-range", "0")
                    # content-range: 0-X/TOTAL
                    total = count.split("/")[-1] if "/" in count else "0"
                    if total != "0":
                        print(f"     {tabela:15} {total:>6} registros")
            except:
                pass


def save_lei(codigo: str):
    """Salva uma lei no banco usando a nova logica."""
    from supabase_storage import storage
    from downloader import calcular_fingerprint

    for path in [
        Path(f"struct/struct_{codigo}.json"),
        Path(f"data/struct/struct_{codigo}.json"),
    ]:
        if path.exists():
            break
    else:
        print(f"[ERRO] Arquivo struct_{codigo}.json nao encontrado!")
        return

    print(f"[LOAD] Carregando: {path}")
    with open(path, "r", encoding="utf-8") as f:
        estrutura = json.load(f)

    raw_path = Path(f"raw/raw_{codigo}.txt")
    if not raw_path.exists():
        raw_path = Path(f"data/raw/raw_{codigo}.txt")

    hash_txt = "manual"
    if raw_path.exists():
        hash_txt = calcular_fingerprint(raw_path.read_bytes())

    origem = estrutura.get("lei", {}).get("url", "manual")

    print(f"\n[SAVE] Salvando no Supabase...")
    sucesso = storage.salvar_lei_completa(estrutura, origem, hash_txt)

    if sucesso:
        print(f"\n[OK] Lei {codigo} salva com sucesso!")
    else:
        print(f"\n[ERRO] Falha ao salvar lei {codigo}!")
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="Verificação e teste da storage v3")
    ap.add_argument("--dry-run", metavar="CODIGO", help="Simula flatten sem salvar")
    ap.add_argument("--save", metavar="CODIGO", help="Salva lei no banco")
    ap.add_argument("--verify", action="store_true", help="Verifica dados no banco")

    args = ap.parse_args()

    if args.dry_run:
        dry_run_flatten(args.dry_run)
    elif args.save:
        save_lei(args.save)
    elif args.verify:
        verify_database()
    else:
        # Default: dry-run se houver struct, senão verify
        print("Uso: python verify_storage.py --dry-run <CODIGO> | --save <CODIGO> | --verify")
        print()
        dry_run_flatten("9394")


if __name__ == "__main__":
    main()
