
import json
with open("struct_10406.json", "r", encoding="utf-8") as f:
    d = json.load(f)

def find_art(node, num):
    if isinstance(node, dict):
        if node.get('tipo') == 'artigo' and node.get('numero') == num:
            return node
        for k in ['titulos', 'filhos']:
            if k in node:
                res = find_art(node[k], num)
                if res: return res
    elif isinstance(node, list):
        for item in node:
            res = find_art(item, num)
            if res: return res
    return None

art1 = find_art(d, "1")
print(f"Art 1 Rubrica: {art1.get('rubrica')}")
art5 = find_art(d, "5")
print(f"Art 5 Rubrica: {art5.get('rubrica')}")
