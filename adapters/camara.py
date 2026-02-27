"""
adapters/camara.py
Adapter para leis da Câmara dos Deputados — www.camara.leg.br

Características da Câmara:
  - Encoding: UTF-8
  - Texto em div.corpo-artigo ou div.conteudo-publicacao
  - Estrutura pode conter artigos numerados em <span> ou <p>
  - Cabeçalho e menu lateral separados do conteúdo principal
"""

from bs4 import BeautifulSoup
from .base import AdapterBase


class AdapterCamara(AdapterBase):

    nome_fonte = "camara"
    encoding_padrao = "utf-8"

    _SELETORES_TEXTO = [
        "div.corpo-artigo",
        "div.conteudo-publicacao",
        "div.texto-lei",
        "div#conteudo-principal",
        "div.conteudo",
        "main",
        "article",
        "body",   # fallback
    ]

    def extrair_texto(self, html_bytes: bytes) -> str:
        html = self._decodificar(html_bytes)
        soup = BeautifulSoup(html, "lxml")

        self._remover_tags_ruido(soup)

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