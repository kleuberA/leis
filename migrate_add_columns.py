"""
migrate_add_columns.py — Adiciona colunas JSONB e constraints faltantes.

Executa diretamente via REST API do Supabase (sem necessidade de psql ou Supabase CLI).
Esse script é idempotente — verifica antes de adicionar.

Colunas adicionadas:
  - artigos.estrutura (jsonb)  — Estrutura interna do artigo (caput, incisos, alíneas...)
  - artigos.alteracoes (jsonb) — Histórico de alterações legislativas
  - artigos.reparado_ia (bool) — Flag de reparo por IA

Uso:
  python migrate_add_columns.py
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Nota: Para executar DDL no Supabase via API, usamos a função rpc
# Se o seu projeto tem a extensão pg_net ou acesso RPC, use isso.
# Caso contrário, execute manualmente no SQL Editor do Supabase Dashboard.

SQL_STATEMENTS = [
    # Adicionar coluna estrutura ao artigos
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'artigos' 
            AND column_name = 'estrutura'
        ) THEN
            ALTER TABLE public.artigos ADD COLUMN estrutura jsonb;
        END IF;
    END $$;
    """,
    # Adicionar coluna alteracoes ao artigos
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'artigos' 
            AND column_name = 'alteracoes'
        ) THEN
            ALTER TABLE public.artigos ADD COLUMN alteracoes jsonb;
        END IF;
    END $$;
    """,
    # Adicionar coluna reparado_ia ao artigos
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'artigos' 
            AND column_name = 'reparado_ia'
        ) THEN
            ALTER TABLE public.artigos ADD COLUMN reparado_ia boolean DEFAULT false;
        END IF;
    END $$;
    """,
]


def run_migration():
    """Tenta executar as migrations via endpoint RPC ou imprime SQL para execução manual."""
    
    print("=" * 60)
    print("  MIGRAÇÃO: Adicionando colunas ao banco")
    print("=" * 60)
    print()
    
    # Tenta via REST RPC (precisa da função `exec_sql` criada previamente)
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    
    # Primeiro, verifica se as colunas já existem consultando um artigo
    print("Verificando estado atual das colunas...")
    with httpx.Client() as client:
        r = client.get(
            f"{SUPABASE_URL}/rest/v1/artigos?select=*&limit=1",
            headers=headers
        )
        if r.status_code < 400:
            sample = r.json()
            if sample:
                cols = set(sample[0].keys())
                missing = []
                if "estrutura" not in cols:
                    missing.append("estrutura (jsonb)")
                if "alteracoes" not in cols:
                    missing.append("alteracoes (jsonb)")
                if "reparado_ia" not in cols:
                    missing.append("reparado_ia (boolean)")
                
                if not missing:
                    print("✅ Todas as colunas já existem! Nada a fazer.")
                    return
                else:
                    print(f"⚠️  Colunas faltantes: {', '.join(missing)}")
            else:
                print("  Tabela artigos está vazia. Continuando com migração...")
        else:
            print(f"  Erro ao verificar: {r.status_code}")
    
    # Como não temos acesso DDL via REST API padrão,
    # imprimimos o SQL para execução manual no Dashboard
    print()
    print("=" * 60)
    print("  EXECUTE O SQL ABAIXO NO SUPABASE SQL EDITOR:")
    print("  Dashboard -> SQL Editor -> New Query -> Cole e execute")
    print("=" * 60)
    print()
    
    migration_sql = """
-- ═══════════════════════════════════════════════════════════
-- MIGRAÇÃO: Adicionar colunas JSONB e melhorias
-- ═══════════════════════════════════════════════════════════

-- 1. Coluna 'estrutura' para guardar a estrutura interna do artigo
--    (caput, parágrafos, incisos, alíneas) como JSON
ALTER TABLE public.artigos 
  ADD COLUMN IF NOT EXISTS estrutura jsonb;

-- 2. Coluna 'alteracoes' para guardar o histórico de modificações
--    legislativas (redações dadas por outras leis, inclusões, etc.)
ALTER TABLE public.artigos 
  ADD COLUMN IF NOT EXISTS alteracoes jsonb;

-- 3. Flag indicando se o artigo foi reparado por IA
ALTER TABLE public.artigos 
  ADD COLUMN IF NOT EXISTS reparado_ia boolean DEFAULT false;

-- 4. Comentários para documentação
COMMENT ON COLUMN public.artigos.estrutura IS 
  'Estrutura interna do artigo: caput, parágrafos, incisos, alíneas em formato JSON';

COMMENT ON COLUMN public.artigos.alteracoes IS 
  'Histórico de alterações legislativas: redações dadas, inclusões, revogações';

COMMENT ON COLUMN public.artigos.reparado_ia IS 
  'Flag indicando se o artigo foi reparado automaticamente por IA';
"""
    
    print(migration_sql)
    print()
    print("=" * 60)
    print("  Após executar, rode novamente para verificar.")
    print("=" * 60)


if __name__ == "__main__":
    run_migration()
