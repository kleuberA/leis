"""
adapters/base.py
Classe base abstrata para todos os adapters de fontes legislativas.

Cada adapter concreto (Planalto, Senado, Câmara, etc.) deve herdar de
AdapterBase e implementar o método `extrair_texto`.

Métodos utilitários compartilhados:
  - _decodificar:              Converte bytes → str usando encoding da fonte
  - _remover_tags_ruido:       Remove tags que nunca contêm texto de lei
  - _limpar_linhas:            Normaliza espaços, quebras e linhas em branco
"""

from __future__ import annotations

import re
import unicodedata
from abc import ABC, abstractmethod

from bs4 import BeautifulSoup, Tag


class AdapterBase(ABC):
    """
    Interface comum para todos os adapters de fontes legislativas.

    Atributos de classe que cada subclasse deve definir:
        nome_fonte      (str): identificador da fonte, ex: "planalto"
        encoding_padrao (str): encoding padrão do HTML da fonte, ex: "latin-1"
    """

    nome_fonte:      str = "base"
    encoding_padrao: str = "utf-8"

    # Tags HTML que nunca fazem parte do texto legislativo
    _TAGS_RUIDO: tuple[str, ...] = (
        "script",
        "style",
        "noscript",
        "iframe",
        "nav",
        "header",
        "footer",
        "aside",
        "form",
        "button",
        "input",
        "select",
        "textarea",
        "meta",
        "link",
        "img",
        "svg",
        "figure",
    )

    # ─────────────────────────────────────────────────────────
    # Método abstrato — obrigatório em cada subclasse
    # ─────────────────────────────────────────────────────────

    @abstractmethod
    def extrair_texto(self, html_bytes: bytes) -> str:
        """
        Recebe o HTML bruto em bytes e retorna o texto limpo da lei.

        Args:
            html_bytes: Conteúdo HTML da página, como bytes.

        Returns:
            Texto puro, sem tags HTML, devidamente limpo e normalizado.
        """

    # ─────────────────────────────────────────────────────────
    # Utilitários protegidos (uso interno pelos adapters)
    # ─────────────────────────────────────────────────────────

    def _decodificar(self, html_bytes: bytes, encoding: str | None = None) -> str:
        """
        Decodifica bytes para str.

        Tenta, em ordem:
          1. O encoding fornecido como argumento
          2. O encoding_padrao da subclasse
          3. UTF-8 com substituição de caracteres inválidos

        Args:
            html_bytes: Conteúdo raw da página.
            encoding:   Encoding opcional para sobrepor o padrão da fonte.

        Returns:
            String HTML decodificada.
        """
        enc = encoding or self.encoding_padrao

        try:
            return html_bytes.decode(enc)
        except (UnicodeDecodeError, LookupError):
            pass

        # Fallback: utf-8 tolerante
        return html_bytes.decode("utf-8", errors="replace")

    def _remover_tags_ruido(self, soup: BeautifulSoup) -> None:
        """
        Remove in-place todas as tags que não carregam conteúdo legislativo.

        Modifica o objeto BeautifulSoup passado diretamente.

        Args:
            soup: Objeto BeautifulSoup a ser limpo.
        """
        for tag in soup.find_all(self._TAGS_RUIDO):
            tag.decompose()

        # Remove comentários HTML
        from bs4 import Comment
        for comentario in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comentario.extract()

    def _extrair_texto_formatado(self, entry_tag: Tag) -> str:
        """
        Extrai o texto de uma tag preservando quebras de linha em tags de bloco
        e mantendo a integridade de linhas para tags inline.

        Tags de bloco (p, div, br, li, etc.) geram quebras de linha.
        Tags inline (span, font, sup, b, etc.) são mescladas no fluxo.
        """
        # Elementos que definem quebra de linha (bloco)
        BLOCK_TAGS = {
            "p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
            "table", "blockquote", "pre"
        }

        fragmentos = []

        def _walk(tag):
            if isinstance(tag, str):
                # Se for texto, adiciona ao último fragmento ou cria um novo
                # Normaliza espaços internos
                txt = re.sub(r"\s+", " ", tag)
                if txt and txt != " ":
                    fragmentos.append(txt)
                return

            # Se for uma tag de bloco, garante que o fragmento anterior termina em newline
            is_block = tag.name.lower() in BLOCK_TAGS

            if is_block and fragmentos and fragmentos[-1] != "\n":
                # Se já tem texto mas não termina em newline, adiciona um
                # (Mas apenas se o último fragmento não for apenas espaço)
                fragmentos.append("\n")

            for child in tag.children:
                _walk(child)

            # Se for uma tag de bloco, garante que termina em newline
            if is_block and fragmentos and fragmentos[-1] != "\n":
                fragmentos.append("\n")

        _walk(entry_tag)

        # Une os fragmentos cuidando para não duplicar espaços entre texto e newlines
        resultado = []
        for f in fragmentos:
            if f == "\n":
                if resultado and resultado[-1] == " ":
                    resultado[-1] = "\n"
                elif not resultado or resultado[-1] != "\n":
                    resultado.append("\n")
            else:
                # Se o anterior for texto (não newline), garante um espaço se o atual não começar com pontuação
                if resultado and resultado[-1] != "\n" and resultado[-1] != " ":
                    # Verificação simples: se o atual não é pontuação colada, adiciona espaço
                    if not re.match(r"^[.,;:)\]º°o]", f):
                        resultado.append(" ")
                resultado.append(f)

        return "".join(resultado)

    def _limpar_linhas(self, texto: str) -> str:
        """
        Normaliza o texto bruto extraído do HTML:
          - Normaliza Unicode para NFC (acentos compostos)
          - Remove caracteres de controle indesejados (exceto \\n e \\t)
          - Substitui tabulações por espaços
          - Remove espaços em excesso no interior de cada linha
          - Remove espaços nas bordas de cada linha
          - Colapsa blocos de linhas em branco (máximo 2 consecutivas)
          - Remove linhas em branco no início e no final

        Args:
            texto: Texto bruto com possíveis ruídos de extração HTML.

        Returns:
            Texto limpo e normalizado.
        """
        # 1. Normalização Unicode
        texto = unicodedata.normalize("NFC", texto)

        # 2. Remove caracteres de controle, mantendo \n e espaço normal
        texto = re.sub(r"[\r\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", texto)

        # 3. Tabulações → espaço
        texto = texto.replace("\t", " ")

        # 4. Espaços múltiplos dentro da linha → um espaço
        linhas = []
        for linha in texto.split("\n"):
            linha = re.sub(r" {2,}", " ", linha).strip()
            linhas.append(linha)

        # 5. Colapsa linhas em branco consecutivas (máx. 2)
        texto_limpo_linhas: list[str] = []
        em_branco = 0
        for linha in linhas:
            if linha == "":
                em_branco += 1
                if em_branco <= 2:
                    texto_limpo_linhas.append("")
            else:
                em_branco = 0
                texto_limpo_linhas.append(linha)

        return "\n".join(texto_limpo_linhas).strip()

    # ─────────────────────────────────────────────────────────
    # Representação
    # ─────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"<Adapter fonte='{self.nome_fonte}' encoding='{self.encoding_padrao}'>"