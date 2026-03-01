import json
import os
import re
from pathlib import Path

def generate_review_html(json_path: str, raw_path: str, output_path: str):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    with open(raw_path, 'r', encoding='utf-8') as f:
        raw_text = f.read()

    import html

    # Prepara o HTML
    html_template = """
<!DOCTYPE html>
<html lang="pt-br">
<head>
    <meta charset="UTF-8">
    <title>Revisão de Lei: [CODIGO]</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; display: flex; height: 100vh; background: #f4f7f6; }
        .pane { flex: 1; overflow-y: auto; padding: 20px; border-right: 1px solid #ddd; }
        .raw-pane { background: #fff; line-height: 1.6; white-space: pre-wrap; font-family: 'Courier New', Courier, monospace; font-size: 14px; }
        .json-pane { background: #1e1e1e; color: #d4d4d4; font-size: 13px; }
        h1 { font-size: 1.5rem; color: #2c3e50; margin-top: 0; }
        .header { position: sticky; top: 0; background: #fff; padding: 10px 0; border-bottom: 2px solid #3498db; margin-bottom: 15px; z-index: 10; }
        .item { margin-left: 20px; border-left: 1px solid #444; padding-left: 10px; margin-top: 5px; }
        .artigo { background: #2d2d2d; padding: 10px; border-radius: 4px; border-left: 4px solid #3498db; margin-bottom: 20px; }
        .artigo-num { color: #569cd6; font-weight: bold; font-size: 1.1em; }
        .status-tag { font-size: 10px; padding: 2px 6px; border-radius: 10px; margin-left: 10px; text-transform: uppercase; vertical-align: middle; }
        .status-ok { background: #28a745; color: white; }
        .status-warn { background: #ffc107; color: black; }
        .status-error { background: #dc3545; color: white; }
        .caput { font-style: italic; color: #ce9178; border-left: 2px solid #569cd6; padding-left: 8px; margin-bottom: 8px; }
        .paragrafo { border-left: 2px solid #ce9178; padding-left: 8px; margin-bottom: 8px; }
        .inciso { border-left: 2px solid #b5cea8; padding-left: 8px; margin-bottom: 5px; color: #dcdcaa; }
        .alinea { border-left: 1px dashed #608b4e; padding-left: 8px; margin-bottom: 3px; color: #9cdcfe; }
        .ementa { background: #eef; padding: 15px; border-radius: 8px; margin-bottom: 20px; border-left: 8px solid #3498db; color: #333; font-size: 0.95em; }
        .metadado { font-size: 0.8em; color: #808080; font-style: italic; margin-top: 2px; display: block; }
        .label-tipo { color: #569cd6; font-weight: bold; margin-right: 5px; }
        
        /* Novos estilos interativos */
        .nav-panel { position: sticky; bottom: 0; background: #2c3e50; color: white; padding: 10px; display: flex; justify-content: space-around; z-index: 100; box-shadow: 0 -2px 10px rgba(0,0,0,0.3); }
        .nav-btn { background: #3498db; color: white; border: none; padding: 8px 15px; border-radius: 4px; cursor: pointer; font-weight: bold; }
        .nav-btn:hover { background: #2980b9; }
        .artigo:has(input:checked) { opacity: 0.6; border-left-color: #2ecc71 !important; }
        .verify-check { float: right; margin-top: -5px; }
        .reparado-label { background: #9b59b6; color: white; font-size: 10px; padding: 2px 6px; border-radius: 10px; margin-left: 5px; }
    </style>
</head>
<body>
    <div class="pane raw-pane">
        <div class="header"><h1>Texto Original (Raw)</h1></div>
        [RAW_TEXT]
    </div>
    <div class="pane json-pane">
        <div class="header" style="background:#1e1e1e; color: white; border-bottom-color: #f1c40f;">
            <h1>Estrutura JSON Capturada</h1>
        </div>
        <div class="ementa"><strong>Ementa:</strong> [EMENTA]</div>
        <div id="structure-container">[STRUCTURE]</div>
        <div class="nav-panel">
            <button class="nav-btn" onclick="jumpToNextError()">⚠️ Próximo Erro / IA</button>
            <span id="stats-summary">Aguardando...</span>
            <button class="nav-btn" onclick="window.scrollTo(0,0)">↑ Topo</button>
        </div>
    </div>
    <script>
        function jumpToNextError() {
            const articles = Array.from(document.querySelectorAll('.artigo'));
            const currentY = window.scrollY;
            const next = articles.find(a => {
                const isError = a.style.borderLeftColor === 'rgb(231, 76, 60)' || a.style.borderLeftColor === 'rgb(241, 196, 15)'; // red or yellow
                return isError && a.offsetTop > currentY + 100;
            });
            if (next) next.scrollIntoView({ behavior: 'smooth', block: 'center' });
            else window.scrollTo({top: 0, behavior: 'smooth'});
        }

        function updateStats() {
            const total = document.querySelectorAll('.artigo').length;
            const verified = document.querySelectorAll('.verify-check input:checked').length;
            document.getElementById('stats-summary').innerText = `Verificados: ${verified} / ${total}`;
        }

        // Persistence
        document.addEventListener('change', (e) => {
            if (e.target.matches('.verify-check input')) {
                const id = e.target.closest('.artigo').id;
                localStorage.setItem('verified_' + id + '_[CODIGO]', e.target.checked);
                updateStats();
            }
        });

        window.onload = () => {
             document.querySelectorAll('.artigo').forEach(a => {
                 const checked = localStorage.getItem('verified_' + a.id + '_[CODIGO]') === 'true';
                 if (checked) a.querySelector('input').checked = true;
             });
             updateStats();
        };
    </script>
</body>
</html>
"""
    output_html = html_template.replace("[CODIGO]", str(data.get('lei', {}).get('codigo', '???')))
    output_html = output_html.replace("[RAW_TEXT]", html.escape(raw_text))
    output_html = output_html.replace("[EMENTA]", html.escape(data.get('lei', {}).get('ementa', 'Não identificada')))
    output_html = output_html.replace("[STRUCTURE]", render_structure(data.get('titulos', [])))

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(output_html)
    print(f"Relatório de revisão gerado em: {output_path}")

def render_conteudo(conteudo):
    html = ""
    texto = conteudo.get("texto", "")
    if texto:
        html += f"{texto}"
        
    metadados = conteudo.get("metadados", [])
    for meta in metadados:
        html += f'<span class="metadado">({meta.get("tipo", "alteração")}: {meta.get("norma", "")} {meta.get("ano", "")})</span>'

    incisos = conteudo.get("incisos", [])
    for inc in incisos:
        html += f'<div class="item inciso"><span class="label-tipo">{inc.get("numero", "I")} -</span> '
        html += render_conteudo(inc.get("conteudo", {}))
        html += '</div>'

    alineas = conteudo.get("alineas", [])
    for al in alineas:
        html += f'<div class="item alinea"><span class="label-tipo">{al.get("letra", "a")})</span> '
        html += f'{al.get("texto", "")}'
        # Alíneas podem ter metadados também
        al_meta = al.get("metadados", [])
        for meta in al_meta:
            html += f'<span class="metadado">({meta.get("tipo", "alteração")}: {meta.get("norma", "")} {meta.get("ano", "")})</span>'
        html += '</div>'
        
    return html

def render_structure(items, level=0):
    html = ""
    for item in items:
        tipo = item.get("tipo", "unknown")
        if tipo == "artigo":
            conf = item.get("confianca", 1.0)
            color = "#3498db"
            if conf < 0.5: color = "#e74c3c"
            elif conf < 0.8: color = "#f1c40f"
            
            html += f'<div class="artigo" id="{item.get("id", "art-"+str(item.get("ordem")))}" style="border-left-color: {color};">'
            html += f'<span class="artigo-num">Art. {item.get("numero", "?")}</span>'
            html += f'<span style="font-size: 0.8em; margin-left: 10px; color: {color}">[Conf: {int(conf*100)}%]</span>'
            
            # Simple health check tag
            status_class = "status-ok" if item.get("estrutura") else "status-error"
            status_text = "OK" if item.get("estrutura") else "VAZIO"
            
            html += f'<div class="verify-check"><input type="checkbox"> <span style="font-size:10px">Verificado</span></div>'
            html += f'<span class="status-tag {status_class}">{status_text}</span>'
            if item.get("reparado_ia"):
                html += f'<span class="reparado-label">IA REPAIRED</span>'
            
            for bloco in item.get("estrutura", []):
                if bloco.get("tipo") == "caput":
                    html += f'<div class="item caput">'
                    html += render_conteudo(bloco.get("conteudo", {}))
                    html += '</div>'
                elif bloco.get("tipo") == "paragrafo":
                    num = bloco.get("numero", "único")
                    if num == "único" or num == "unico":
                        marcador = "Parágrafo único."
                    else:
                        marcador = f"§ {num}."
                    html += f'<div class="item paragrafo"><strong>{marcador}</strong> '
                    html += render_conteudo(bloco.get("conteudo", {}))
                    html += '</div>'
            
            html += '</div>'
        else:
            html += f'<div class="item" style="margin-top: 25px; border-left: 2px solid #f1c40f; padding-left: 15px;">'
            html += f'<h2 style="color: #f1c40f; margin: 0; font-size: 1.2rem;">{tipo.upper()} {item.get("numero", "")}</h2>'
            if item.get("nome"):
                html += f'<div style="color: #fff; margin-bottom: 10px; font-weight: bold;">{item.get("nome", "")}</div>'
            
            filhos = item.get("filhos", [])
            artigos = item.get("artigos", [])
            
            if filhos:
                html += render_structure(filhos, level + 1)
            if artigos:
                html += render_structure(artigos, level + 1)
                
            html += '</div>'
    return html

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Uso: python review_viewer.py <struct.json> <raw.txt> [output.html]")
    else:
        j = sys.argv[1]
        r = sys.argv[2]
        o = sys.argv[3] if len(sys.argv) > 3 else "review_" + Path(j).stem + ".html"
        generate_review_html(j, r, o)
