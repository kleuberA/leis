
from parser import _extrair_nome, _RE_NUM
import re

# Problematic text from the user's report
bloco_capitulo = """CAPÍTULO II
DOS CRIMES CONTRA O PRIVILÉGIO DE INVENÇÃO
Violação de privilégio de invenção
Art 187. (Revogado pela Lei nº 9.279, de 14.5.1996)
Falsa atribuição de privilégio
Art 188. (Revogado pela Lei nº 9.279, de 14.5.1996)
Usurpação ou indevida exploração de modelo ou desenho privilegiado
"""

re_capitulo = _RE_NUM["capitulo"]
nome = _extrair_nome(bloco_capitulo, re_capitulo)

print(f"Nome extraído: '{nome}'")

# Expected: "DOS CRIMES CONTRA O PRIVILÉGIO DE INVENÇÃO Violação de privilégio de invenção"
# Actual (bug): "DOS CRIMES CONTRA O PRIVILÉGIO DE INVENÇÃO Violação de privilégio de invenção Art 187. (Revogado pela Lei nº 9.279, de 14.5.1996) Falsa atribuição de privilégio Art 188. (Revogado pela Lei nº 9.279, de 14.5.1996) Usurpação ou indevida exploração de modelo ou desenho privilegiado"
