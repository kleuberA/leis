"""
adapters/planalto.py
Adapter para leis do Portal da Legislação — www.planalto.gov.br

Características do Planalto:
  - Encoding: latin-1 (ISO-8859-1), mesmo em páginas recentes
  - Estrutura HTML: texto dentro de <body>, sem classe específica consistente
  - Parágrafos em <p>, alguns em <font>, alguns em texto bruto
  - Notas de rodapé em tabelas que devem ser removidas
  - Cabeçalho com logo do governo que gera ruído se não filtrado
"""

import re
from bs4 import BeautifulSoup
from .base import AdapterBase


class AdapterPlanalto(AdapterBase):

    nome_fonte = "planalto"
    encoding_padrao = "latin-1"

    def extrair_texto(self, html_bytes: bytes) -> str:
        html = self._decodificar(html_bytes)
        soup = BeautifulSoup(html, "lxml")

        self._remover_tags_ruido(soup)
        self._remover_elementos_navegacao(soup)

        corpo = soup.find("body") or soup
        texto = corpo.get_text(separator="\n")
        return self._limpar_linhas(texto)

    def _remover_elementos_navegacao(self, soup: BeautifulSoup) -> None:
        """
        Remove elementos específicos do Planalto que não fazem parte da lei:
          - Tabela de rodapé com notas e links de navegação
          - Banner do governo (div com imagem de topo)
          - Links "Texto compilado" / "Voltar"
        """
        # Remove tabelas de rodapé com "Presidência da República"
        for table in soup.find_all("table"):
            texto_table = table.get_text()
            if any(k in texto_table for k in [
                "Presidência da República",
                "Casa Civil",
                "Subchefia para Assuntos Jurídicos",
                "Este texto não substitui",
            ]):
                table.decompose()

        # Remove divs de navegação (geralmente contêm só links)
        for div in soup.find_all("div"):
            links = div.find_all("a")
            texto_div = div.get_text(strip=True)
            # Div que é quase só links e texto curto → provavelmente nav
            if links and len(links) >= 3 and len(texto_div) < 300:
                div.decompose()