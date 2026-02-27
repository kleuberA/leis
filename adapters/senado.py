"""
adapters/senado.py
Adapter para leis do Senado Federal — legis.senado.leg.br

Características do Senado:
  - Encoding: UTF-8
  - Texto da norma dentro de div.textoNorma ou div#textoNorma
  - Estrutura mais semântica que o Planalto
  - Cabeçalhos de navegação bem separados do corpo da lei
  - Algumas leis têm visualizador PDF embutido (não tratado aqui — usar URL .htm direta)
"""

from bs4 import BeautifulSoup
from .base import AdapterBase


class AdapterSenado(AdapterBase):

    nome_fonte = "senado"
    encoding_padrao = "utf-8"

    # Seletores em ordem de preferência
    _SELETORES_TEXTO = [
        "div.textoNorma",
        "div#textoNorma",
        "div.texto-norma",
        "div.conteudoTexto",
        "div#conteudo",
        "main",
        "article",
        "body",   # fallback
    ]

    def extrair_texto(self, html_bytes: bytes) -> str:
        html = self._decodificar(html_bytes)
        soup = BeautifulSoup(html, "lxml")

        self._remover_tags_ruido(soup)

        # Tenta cada seletor em ordem até encontrar conteúdo substantivo
        bloco = None
        for seletor in self._SELETORES_TEXTO:
            candidato = soup.select_one(seletor)
            if candidato and len(candidato.get_text(strip=True)) > 500:
                bloco = candidato
                break

        if bloco is None:
            bloco = soup.find("body") or soup
 
        texto = self._extrair_texto_formatado(bloco)
        return self._limpar_linhas(texto)