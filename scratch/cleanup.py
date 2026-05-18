"""Cleanup script - removes partially inserted law data."""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from supabase_storage import storage

leis = storage.list_leis()
for lei in leis:
    id_lei = lei.get('id_lei')
    nome = lei.get('nome', '?')
    print(f"Cleaning lei {id_lei}: {nome}")
    storage._limpar_estrutura_lei(id_lei)
    storage._delete('leis', {'id_lei': id_lei})

print("Cleanup complete.")
