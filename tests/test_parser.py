"""
tests/test_parser.py — v2
Suite de testes completa para o parser de leis brasileiras.

Schema do parser v4 (uploaded):
  conteudo = {
    "texto": "...",
    "incisos": [ {"tipo":"inciso", "numero":"I", "conteudo": {...}} ],
    "alineas": [ {"tipo":"alinea", "letra":"a", "texto":"..."} ],
    "metadados": [...]
  }
  — conteudo é SEMPRE dict (nunca lista direta)
"""

import sys, os, re, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from parser import (
    parse_lei, normalizar_texto, limpar_texto_final,
    extrair_metadados, extrair_incisos, extrair_alineas, extrair_paragrafos,
    _PAT_ANO, _PAT_NORMA
)
from tests.fixtures import (
    ART_SIMPLES, ART_INCISOS_TODOS_FORMATOS, ART_INCISOS_COM_ALINEAS,
    ART_PONTO_APOS_NUMERO, ART_SUFIXO_A, META_ANO_PADRAO,
    META_ANO_DATA_COMPLETA, META_REFERENCIA_INTERNA, META_ADIN_E_LEI_MINUSCULO,
    CAPITULO_QUEBRADO, PARAGRAFO_UNICO, ART_INCISO_SUFIXO,
    TEXTO_COM_NEWLINES, HIERARQUIA_LIVRO, LDB_RAW_PATH,
)


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _collect(obj, tipo, found=None):
    """Coleta recursivamente todos os nós de um tipo."""
    if found is None: found = []
    if isinstance(obj, dict):
        if obj.get("tipo") == tipo: found.append(obj)
        for v in obj.values():
            if isinstance(v, (dict, list)): _collect(v, tipo, found)
    elif isinstance(obj, list):
        for i in obj: _collect(i, tipo, found)
    return found


def _all_metas(obj):
    result = []
    if isinstance(obj, dict):
        result.extend(obj.get("metadados", []))
        result.extend(obj.get("alteracoes", []))
        for v in obj.values():
            if isinstance(v, (dict, list)): result.extend(_all_metas(v))
    elif isinstance(obj, list):
        for i in obj: result.extend(_all_metas(i))
    return result


def _all_texts(obj):
    """Coleta todos os valores de campos de texto."""
    result = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("texto", "norma", "ementa") and isinstance(v, str):
                result.append(v)
            elif isinstance(v, (dict, list)):
                result.extend(_all_texts(v))
    elif isinstance(obj, list):
        for i in obj: result.extend(_all_texts(i))
    return result


def _incisos_de(conteudo):
    """Extrai lista de incisos do conteudo (sempre dict agora)."""
    if isinstance(conteudo, dict):
        return conteudo.get("incisos", [])
    return []


def _parse_incisos_de(texto):
    """Retorna incisos de um texto simples."""
    resultado = extrair_incisos(texto)
    return _incisos_de(resultado)


# ═══════════════════════════════════════════════════════════════
# 1. NORMALIZAÇÃO
# ═══════════════════════════════════════════════════════════════

class TestNormalizacao(unittest.TestCase):

    def test_remove_carriage_return(self):
        resultado = normalizar_texto("a\r\nb")
        self.assertNotIn("\r", resultado)
        self.assertIn("a\nb", resultado)

    def test_normaliza_nbsp(self):
        self.assertNotIn("\xa0", normalizar_texto("texto\xa0aqui"))

    def test_colapsa_capitulo_quebrado(self):
        saida = normalizar_texto("CAPÍTULO\nIII\nDo Ensino")
        self.assertIn("CAPÍTULO III", saida)
        self.assertNotIn("CAPÍTULO\nIII", saida)

    def test_colapsa_titulo_quebrado(self):
        saida = normalizar_texto("TÍTULO\nI\nDa Educação")
        self.assertIn("TÍTULO I", saida)

    def test_colapsa_secao_quebrada(self):
        saida = normalizar_texto("SEÇÃO\nII\nDo Ensino")
        self.assertIn("SEÇÃO II", saida)

    def test_colapsa_livro_quebrado(self):
        saida = normalizar_texto("LIVRO\nI\nDas Obrigações")
        self.assertIn("LIVRO I", saida)


# ═══════════════════════════════════════════════════════════════
# 2. LIMPEZA DE TEXTO
# ═══════════════════════════════════════════════════════════════

class TestLimpezaTexto(unittest.TestCase):

    def test_newline_vira_espaco(self):
        resultado = limpar_texto_final("texto que foi\nquebrado pelo HTML\nno meio")
        self.assertNotIn("\n", resultado)
        self.assertIn("quebrado pelo HTML no meio", resultado)

    def test_remove_ponto_inicial(self):
        resultado = limpar_texto_final(". Os sistemas de ensino assegurarão")
        self.assertFalse(resultado.startswith("."))
        self.assertTrue(resultado.startswith("Os"))

    def test_remove_espaco_duplo(self):
        self.assertNotIn("  ", limpar_texto_final("texto  com   espaços"))

    def test_normaliza_endash(self):
        self.assertNotIn("\x96", limpar_texto_final("texto \x96 com endash"))

    def test_string_vazia(self):
        self.assertEqual(limpar_texto_final(""), "")

    def test_string_so_espaco(self):
        self.assertEqual(limpar_texto_final("   "), "")


# ═══════════════════════════════════════════════════════════════
# 3. METADADOS
# ═══════════════════════════════════════════════════════════════

class TestMetadados(unittest.TestCase):

    def test_ano_formato_padrao(self):
        m = _PAT_ANO.search("(Redação dada pela Lei nº 12.796, de 2013)")
        self.assertIsNotNone(m)
        ano = (m.group(1) or m.group(2)) if m else None
        self.assertEqual(ano, "2013")

    def test_ano_formato_data_completa(self):
        m = _PAT_ANO.search("(Redação dada pela Lei nº 10.793, de 1º.12.2003)")
        self.assertIsNotNone(m)
        ano = (m.group(1) or m.group(2)) if m else None
        self.assertEqual(ano, "2003")

    def test_norma_lei_maiusculo(self):
        self.assertIsNotNone(_PAT_NORMA.search("pela Lei nº 12.796, de 2013"))

    def test_norma_lei_minusculo(self):
        self.assertIsNotNone(_PAT_NORMA.search("pela lei nº 13.415, de 2017"))

    def test_norma_adin(self):
        self.assertIsNotNone(_PAT_NORMA.search("(Vide Adin 3324-7, de 2005)"))

    def test_norma_decreto(self):
        self.assertIsNotNone(_PAT_NORMA.search("(Vide Decreto nº 11.713, de 2023)"))

    def test_meta_tipo_redacao(self):
        _, metas = extrair_metadados("texto (Redação dada pela Lei nº 1, de 2020) fim")
        self.assertEqual(metas[0]["tipo"], "redacao")

    def test_meta_tipo_incluido(self):
        _, metas = extrair_metadados("texto (Incluído pela Lei nº 1, de 2020) fim")
        self.assertEqual(metas[0]["tipo"], "incluido")

    def test_meta_tipo_revogado(self):
        _, metas = extrair_metadados("texto (Revogado) fim")
        self.assertEqual(metas[0]["tipo"], "revogado")

    def test_meta_sem_norma_interna_e_legitimo(self):
        _, metas = extrair_metadados("texto (Vide parágrafo único do art. 2) fim")
        self.assertEqual(len(metas), 1)
        self.assertEqual(metas[0]["tipo"], "vide")
        self.assertIsNone(metas[0]["norma"])

    def test_meta_remove_anotacao_do_texto(self):
        texto_limpo, _ = extrair_metadados(
            "A educação (Redação dada pela Lei nº 1, de 2020) é direito."
        )
        self.assertNotIn("Redação dada", texto_limpo)

    def test_meta_multiplos(self):
        texto = "p (Redação dada pela Lei nº 1, de 2020) (Vide Decreto nº 2, de 2021)"
        _, metas = extrair_metadados(texto)
        self.assertEqual(len(metas), 2)
        tipos = {m["tipo"] for m in metas}
        self.assertIn("redacao", tipos)
        self.assertIn("vide", tipos)


# ═══════════════════════════════════════════════════════════════
# 4. ALÍNEAS
# ═══════════════════════════════════════════════════════════════

class TestAlineas(unittest.TestCase):

    def _alineas_de(self, texto):
        resultado = extrair_alineas(texto)
        if isinstance(resultado, dict):
            return resultado.get("alineas", [])
        return resultado if isinstance(resultado, list) else []

    def test_extrai_alineas_corretas(self):
        texto = (
            "organizada da seguinte forma:\n"
            "a) pré-escola;\n"
            "b) ensino fundamental;\n"
            "c) ensino médio;\n"
        )
        alineas = self._alineas_de(texto)
        self.assertEqual(len(alineas), 3)
        self.assertEqual([a["letra"] for a in alineas], ["a", "b", "c"])

    def test_alinea_tipo_correto(self):
        texto = "forma:\na) pré-escola;\nb) ensino;\n"
        alineas = self._alineas_de(texto)
        for a in alineas:
            self.assertEqual(a["tipo"], "alinea")

    def test_sem_falso_positivo_e_no_meio(self):
        """'e)' no meio de frase não é alínea."""
        resultado = extrair_alineas("A lei prevê casos e) para situações gerais.")
        self.assertIsInstance(resultado, dict)
        self.assertEqual(resultado.get("alineas", []), [])

    def test_sem_falso_positivo_o_parenteses(self):
        resultado = extrair_alineas("Conforme disposto no regulamento próprio.")
        self.assertIsInstance(resultado, dict)

    def test_texto_sem_alineas_retorna_dict(self):
        resultado = extrair_alineas("texto simples sem alíneas")
        self.assertIsInstance(resultado, dict)
        self.assertIn("texto", resultado)


# ═══════════════════════════════════════════════════════════════
# 5. INCISOS — schema v4: sempre retorna dict {texto, incisos:[]}
# ═══════════════════════════════════════════════════════════════

class TestIncisos(unittest.TestCase):

    def test_formato_numeral_linha_propria_traco_linha_seguinte(self):
        """I\\n- texto"""
        texto = "princípios:\nI\n- igualdade;\nII\n- liberdade;"
        incisos = _parse_incisos_de(texto)
        self.assertEqual(len(incisos), 2)
        self.assertEqual(incisos[0]["numero"], "I")
        self.assertEqual(incisos[1]["numero"], "II")

    def test_formato_mesmo_linha_traco_ascii(self):
        """III - texto"""
        texto = "princípios:\nIII - pluralismo;\nIV - respeito;"
        incisos = _parse_incisos_de(texto)
        self.assertEqual(len(incisos), 2)
        self.assertEqual(incisos[0]["numero"], "III")

    def test_formato_endash_latin1(self):
        """VIII \\x96 texto"""
        texto = "princípios:\nVIII \x96 gestão democrática;"
        incisos = _parse_incisos_de(texto)
        self.assertEqual(len(incisos), 1)
        self.assertEqual(incisos[0]["numero"], "VIII")

    def test_formato_inciso_com_sufixo(self):
        """VII-A - texto"""
        texto = "Incumbências:\nVII - base;\nVII-A - sufixo;\nVIII - próximo;"
        incisos = _parse_incisos_de(texto)
        nums = [i["numero"] for i in incisos]
        self.assertIn("VII-A", nums)

    def test_sem_falso_positivo_sigla(self):
        texto = "O benefício é pago pelo INSS - Instituto.\nO censo pelo IBGE - Instituto."
        incisos = _parse_incisos_de(texto)
        self.assertEqual(len(incisos), 0)

    def test_todos_os_5_formatos_no_mesmo_artigo(self):
        result = parse_lei(ART_INCISOS_TODOS_FORMATOS, "test")
        arts = _collect(result, "artigo")
        self.assertEqual(len(arts), 1)
        caput_conteudo = arts[0]["estrutura"][0]["conteudo"]
        incisos = _incisos_de(caput_conteudo)
        self.assertGreaterEqual(len(incisos), 8)

    def test_sem_inciso_aninhado_dentro_de_outro(self):
        result = parse_lei(ART_INCISOS_TODOS_FORMATOS, "test")
        incisos = _collect(result, "inciso")
        for inc in incisos:
            conteudo = inc.get("conteudo", {})
            texto = conteudo.get("texto", "") if isinstance(conteudo, dict) else ""
            nested = re.findall(r"[IVXLCDM]{1,7}\s*[-\x96]", texto)
            self.assertEqual(nested, [],
                f"Inciso {inc['numero']} tem incisos aninhados: {nested}")

    def test_alineas_dentro_de_inciso(self):
        """Alíneas ficam dentro do conteudo do inciso."""
        result = parse_lei(ART_INCISOS_COM_ALINEAS, "test")
        incisos = _collect(result, "inciso")
        inc_I = next((i for i in incisos if i["numero"] == "I"), None)
        self.assertIsNotNone(inc_I)
        alineas = inc_I["conteudo"].get("alineas", [])
        self.assertGreaterEqual(len(alineas), 3)


# ═══════════════════════════════════════════════════════════════
# 6. PARÁGRAFOS E CAPUT
# ═══════════════════════════════════════════════════════════════

class TestParagrafos(unittest.TestCase):

    def test_caput_extraido(self):
        result = parse_lei(ART_SIMPLES, "test")
        arts = _collect(result, "artigo")
        self.assertEqual(len(arts), 1)
        tipos = [b["tipo"] for b in arts[0]["estrutura"]]
        self.assertIn("caput", tipos)

    def test_paragrafos_numerados(self):
        result = parse_lei(ART_SIMPLES, "test")
        arts = _collect(result, "artigo")
        paragrafos = [b for b in arts[0]["estrutura"] if b["tipo"] == "paragrafo"]
        self.assertEqual(len(paragrafos), 2)
        numeros = [p["numero"] for p in paragrafos]
        self.assertIn("1", numeros)
        self.assertIn("2", numeros)

    def test_paragrafo_unico(self):
        result = parse_lei(PARAGRAFO_UNICO, "test")
        arts = _collect(result, "artigo")
        paragrafos = [b for b in arts[0]["estrutura"] if b["tipo"] == "paragrafo"]
        self.assertEqual(len(paragrafos), 1)
        self.assertEqual(paragrafos[0]["numero"], "único")

    def test_caput_sem_ponto_inicial(self):
        result = parse_lei(ART_PONTO_APOS_NUMERO, "test")
        arts = _collect(result, "artigo")
        caput = arts[0]["estrutura"][0]["conteudo"]
        texto = caput.get("texto", "") if isinstance(caput, dict) else ""
        self.assertFalse(texto.startswith("."), f"Caput com ponto: {repr(texto[:30])}")

    def test_caput_sem_newlines(self):
        result = parse_lei(TEXTO_COM_NEWLINES, "test")
        for t in _all_texts(result):
            self.assertNotIn("\n", t)

    def test_conteudo_e_sempre_dict(self):
        """Conteudo de caput/parágrafo deve SEMPRE ser dict (nunca lista)."""
        result = parse_lei(ART_INCISOS_TODOS_FORMATOS, "test")
        for art in _collect(result, "artigo"):
            for bloco in art.get("estrutura", []):
                conteudo = bloco.get("conteudo")
                self.assertIsInstance(conteudo, dict,
                    f"conteudo não é dict em {bloco.get('tipo')}: {type(conteudo)}")


# ═══════════════════════════════════════════════════════════════
# 7. NUMERAÇÃO DE ARTIGOS
# ═══════════════════════════════════════════════════════════════

class TestNumeracaoArtigos(unittest.TestCase):

    def test_artigo_com_ordinal(self):
        result = parse_lei(ART_SIMPLES, "test")
        arts = _collect(result, "artigo")
        self.assertEqual(arts[0]["numero"], "1º")

    def test_artigo_com_ponto_apos_numero(self):
        result = parse_lei(ART_PONTO_APOS_NUMERO, "test")
        arts = _collect(result, "artigo")
        self.assertEqual(arts[0]["numero"], "15")

    def test_artigo_com_sufixo_a(self):
        result = parse_lei(ART_SUFIXO_A, "test")
        arts = _collect(result, "artigo")
        self.assertEqual(arts[0]["numero"], "4º-A")

    def test_id_contem_codigo_lei(self):
        result = parse_lei(ART_SIMPLES, "9394")
        arts = _collect(result, "artigo")
        self.assertTrue(arts[0]["id"].startswith("lei-9394-"))

    def test_ids_unicos(self):
        result = parse_lei(META_ADIN_E_LEI_MINUSCULO, "test")
        arts = _collect(result, "artigo")
        ids = [a["id"] for a in arts]
        self.assertEqual(len(ids), len(set(ids)))

    def test_ordem_sequencial(self):
        result = parse_lei(META_ADIN_E_LEI_MINUSCULO, "test")
        arts = _collect(result, "artigo")
        ordens = [a["ordem"] for a in arts]
        self.assertEqual(ordens, sorted(ordens))
        self.assertEqual(ordens[0], 1)


# ═══════════════════════════════════════════════════════════════
# 8. HIERARQUIA
# ═══════════════════════════════════════════════════════════════

class TestHierarquia(unittest.TestCase):

    def test_titulo_extraido(self):
        result = parse_lei(ART_SIMPLES, "test")
        self.assertEqual(len(result["titulos"]), 1)

    def test_capitulo_extraido(self):
        texto = "\nTÍTULO I\nTeste\nCAPÍTULO I\nDo Ensino\nArt. 1º Teste.\n"
        result = parse_lei(texto, "test")
        caps = _collect(result, "capitulo")
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0]["numero"], "I")

    def test_capitulo_quebrado_em_linha(self):
        result = parse_lei(CAPITULO_QUEBRADO, "test")
        caps = _collect(result, "capitulo")
        self.assertGreater(len(caps), 0)
        self.assertEqual(caps[0]["numero"], "III")

    def test_livro_extraido(self):
        result = parse_lei(HIERARQUIA_LIVRO, "test")
        self.assertGreater(len(_collect(result, "livro")), 0)

    def test_parte_extraida(self):
        result = parse_lei(HIERARQUIA_LIVRO, "test")
        self.assertGreater(len(_collect(result, "parte")), 0)

    def test_artigos_dentro_de_livro(self):
        result = parse_lei(HIERARQUIA_LIVRO, "test")
        self.assertEqual(len(_collect(result, "artigo")), 2)

    def test_secao_extraida(self):
        texto = "\nTÍTULO I\nT\nCAPÍTULO I\nC\nSEÇÃO I\nS\nArt. 1º T.\n"
        result = parse_lei(texto, "test")
        self.assertEqual(len(_collect(result, "secao")), 1)

    def test_subsecao_extraida(self):
        texto = "\nTÍTULO I\nT\nCAPÍTULO I\nC\nSEÇÃO I\nS\nSUBSEÇÃO I\nSS\nArt. 1º T.\n"
        result = parse_lei(texto, "test")
        self.assertEqual(len(_collect(result, "subsecao")), 1)


# ═══════════════════════════════════════════════════════════════
# 9. INVARIANTES GLOBAIS DE TEXTO
# ═══════════════════════════════════════════════════════════════

class TestInvariantesTexto(unittest.TestCase):

    def _parse(self, fixture):
        return _all_texts(parse_lei(fixture, "test"))

    def test_art_simples_sem_newline(self):
        for t in self._parse(ART_SIMPLES):
            self.assertNotIn("\n", t)

    def test_art_incisos_sem_newline(self):
        for t in self._parse(ART_INCISOS_TODOS_FORMATOS):
            self.assertNotIn("\n", t)

    def test_art_alineas_sem_newline(self):
        for t in self._parse(ART_INCISOS_COM_ALINEAS):
            self.assertNotIn("\n", t)

    def test_art_ponto_sem_ponto_inicial(self):
        for t in self._parse(ART_PONTO_APOS_NUMERO):
            self.assertFalse(t.startswith("."), f"Começa com ponto: {repr(t[:40])}")

    def test_art_sufixo_sem_ponto_inicial(self):
        for t in self._parse(ART_SUFIXO_A):
            self.assertFalse(t.startswith("."))

    def test_meta_data_completa_sem_newline(self):
        for t in self._parse(META_ANO_DATA_COMPLETA):
            self.assertNotIn("\n", t)

    def test_hierarquia_livro_sem_newline(self):
        for t in self._parse(HIERARQUIA_LIVRO):
            self.assertNotIn("\n", t)

    def test_texto_newlines_corrigidos(self):
        for t in self._parse(TEXTO_COM_NEWLINES):
            self.assertNotIn("\n", t)


# ═══════════════════════════════════════════════════════════════
# 10. INTEGRAÇÃO — LDB COMPLETA (REGRESSÃO)
# ═══════════════════════════════════════════════════════════════

class TestIntegracaoLDB(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(LDB_RAW_PATH):
            cls._skip = True
            return
        cls._skip = False
        with open(LDB_RAW_PATH, encoding="utf-8") as f:
            texto = f.read()
        cls.result  = parse_lei(texto, "9394")
        cls.artigos = _collect(cls.result, "artigo")
        cls.incisos = _collect(cls.result, "inciso")
        cls.alineas = _collect(cls.result, "alinea")
        cls.metas   = _all_metas(cls.result)
        cls.textos  = _all_texts(cls.result)

    def _skip_if_no_file(self):
        if self._skip:
            self.skipTest(f"Arquivo não encontrado: {LDB_RAW_PATH}")

    # ── Contagens ───────────────────────────────────────────────
    def test_total_artigos(self):
        self._skip_if_no_file()
        self.assertEqual(len(self.artigos), 120)

    def test_total_titulos(self):
        self._skip_if_no_file()
        self.assertEqual(len(self.result["titulos"]), 9)

    def test_total_incisos(self):
        self._skip_if_no_file()
        self.assertGreaterEqual(len(self.incisos), 300)

    def test_total_alineas(self):
        self._skip_if_no_file()
        self.assertGreaterEqual(len(self.alineas), 18)

    # ── IDs ─────────────────────────────────────────────────────
    def test_sem_ids_duplicados(self):
        self._skip_if_no_file()
        ids = [a["id"] for a in self.artigos]
        dups = [i for i in ids if ids.count(i) > 1]
        self.assertEqual(dups, [])

    def test_todos_ids_com_codigo_lei(self):
        self._skip_if_no_file()
        for art in self.artigos:
            self.assertTrue(art["id"].startswith("lei-9394-"))

    # ── Qualidade de texto ───────────────────────────────────────
    def test_zero_newlines_em_textos(self):
        self._skip_if_no_file()
        com_nl = [t for t in self.textos if "\n" in t]
        self.assertEqual(len(com_nl), 0, f"{len(com_nl)} textos com \\n")

    def test_zero_pontos_iniciais(self):
        self._skip_if_no_file()
        com_pt = [t for t in self.textos if t.startswith(".")]
        self.assertEqual(len(com_pt), 0, f"{len(com_pt)} textos com ponto inicial")

    def test_zero_nbsp(self):
        self._skip_if_no_file()
        com_nb = [t for t in self.textos if "\xa0" in t]
        self.assertEqual(len(com_nb), 0)

    def test_conteudo_sempre_dict_na_ldb(self):
        """Nenhum bloco pode ter conteúdo em formato lista (schema legado)."""
        self._skip_if_no_file()
        problemas = []
        for art in self.artigos:
            for bloco in art.get("estrutura", []):
                c = bloco.get("conteudo")
                if isinstance(c, list):
                    problemas.append(f"{art['id']} {bloco['tipo']}")
        self.assertEqual(problemas, [], f"Conteúdo em lista: {problemas[:3]}")

    # ── Metadados ────────────────────────────────────────────────
    def test_metadados_sem_ano_abaixo_5pct(self):
        self._skip_if_no_file()
        total = len(self.metas)
        sem_ano = len([m for m in self.metas if not m.get("ano")])
        self.assertLess(sem_ano / total * 100, 5.0,
            f"Sem ano: {sem_ano}/{total} ({sem_ano/total*100:.1f}%)")

    def test_metadados_sem_norma_abaixo_5pct(self):
        self._skip_if_no_file()
        total = len(self.metas)
        relevantes = [m for m in self.metas
            if not (m.get("tipo") in ("revogado","vide") and not m.get("norma"))]
        sem_norma = len([m for m in relevantes if not m.get("norma")])
        self.assertLess(sem_norma / total * 100, 3.0)

    # ── Sem incisos aninhados ─────────────────────────────────────
    def test_sem_incisos_aninhados(self):
        self._skip_if_no_file()
        problemas = []
        for inc in self.incisos:
            texto = inc.get("conteudo", {}).get("texto", "")
            nested = re.findall(r"\n[IVXLCDM]{1,7}\s*[-\x96]", texto)
            if nested:
                problemas.append((inc["numero"], nested))
        self.assertEqual(problemas, [], f"Aninhados: {problemas[:3]}")

    # ── Artigos específicos ───────────────────────────────────────
    def test_art3_tem_incisos_suficientes(self):
        self._skip_if_no_file()
        art3 = next((a for a in self.artigos if a["numero"] == "3º"), None)
        self.assertIsNotNone(art3)
        incisos = _collect(art3, "inciso")
        self.assertGreaterEqual(len(incisos), 13)

    def test_art4_tem_alineas(self):
        self._skip_if_no_file()
        art4 = next((a for a in self.artigos if a["numero"] == "4º"), None)
        self.assertIsNotNone(art4)
        self.assertGreaterEqual(len(_collect(art4, "alinea")), 3)

    def test_art15_caput_sem_ponto(self):
        self._skip_if_no_file()
        art15 = next((a for a in self.artigos if a["numero"] == "15"), None)
        self.assertIsNotNone(art15)
        texto = art15["estrutura"][0]["conteudo"].get("texto", "")
        self.assertFalse(texto.startswith("."))

    def test_art4a_numero_correto(self):
        self._skip_if_no_file()
        art = next((a for a in self.artigos if a["numero"] == "4º-A"), None)
        self.assertIsNotNone(art)
        self.assertEqual(art["id"], "lei-9394-art-4º-A")

    # ── Guarda de regressão ───────────────────────────────────────
    def test_precisao_estrutural_minima(self):
        """REGRESSÃO: artigos vazios não podem superar 5%."""
        self._skip_if_no_file()
        vazios = [a for a in self.artigos if not a.get("estrutura")]
        self.assertLess(len(vazios) / len(self.artigos) * 100, 5.0)


# ═══════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(__import__("__main__"))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


# ═══════════════════════════════════════════════════════════════
# 11. CROSS-REFERENCES
# ═══════════════════════════════════════════════════════════════

class TestCrossRefs(unittest.TestCase):
    """Testa extração de referências cruzadas entre artigos."""

    def setUp(self):
        # Importa aqui para não quebrar testes se crossref não existir
        import importlib
        spec = importlib.util.find_spec("crossref")
        if spec is None:
            self.skipTest("Módulo crossref não encontrado")
        from crossref import extrair_crossrefs, extrair_crossrefs_estrutura
        self._extrair = extrair_crossrefs
        self._extrair_struct = extrair_crossrefs_estrutura

    def test_captura_nos_termos_do(self):
        refs = self._extrair(
            "nos termos do art. 1º desta Lei, o acesso é garantido",
            "lei-test-art-5", "test"
        )
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["destino_art"], "1º")

    def test_captura_conforme_disposto_no(self):
        refs = self._extrair(
            "conforme disposto no art. 9º, § 3º, inciso II desta Lei",
            "lei-test-art-10", "test"
        )
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["destino_art"], "9º")
        self.assertEqual(refs[0]["destino_para"], "3º")  # inclui ordinal quando presente no texto
        self.assertEqual(refs[0]["destino_inc"], "II")

    def test_captura_disposto_no(self):
        """'disposto no' sem 'conforme' deve ser capturado."""
        refs = self._extrair(
            "Além do disposto no art. 59 desta Lei, os sistemas",
            "lei-test-art-60B", "test"
        )
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["destino_art"], "59")

    def test_captura_previsto_no(self):
        refs = self._extrair(
            "ressalvado o previsto no art. 213 da Constituição Federal",
            "lei-test-art-7", "test"
        )
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["destino_art"], "213")

    def test_captura_a_que_se_refere(self):
        refs = self._extrair(
            "A formação dos profissionais a que se refere o inciso III do art. 61",
            "lei-test-art-62A", "test"
        )
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["destino_art"], "61")

    def test_captura_sufixo_A(self):
        """Referência a art. com sufixo -A deve ser capturada."""
        refs = self._extrair(
            "previsto no art. 4º-A desta Lei",
            "lei-test-art-5", "test"
        )
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["destino_art"], "4º-A")

    def test_nao_captura_sem_contexto_verbal(self):
        """'art. X' sem contexto verbal e sem §/inciso não deve gerar ref."""
        refs = self._extrair(
            "a garantia de educação, nos termos gerais do sistema público",
            "lei-test-art-1", "test"
        )
        self.assertEqual(len(refs), 0)

    def test_nao_captura_texto_sem_referencia(self):
        refs = self._extrair(
            "texto simples sobre educação sem nenhuma referência a artigos",
            "lei-test-art-2", "test"
        )
        self.assertEqual(len(refs), 0)

    def test_origem_preenchida(self):
        refs = self._extrair(
            "nos termos do art. 5º desta Lei",
            "lei-9394-art-1º", "9394"
        )
        self.assertEqual(refs[0]["origem"], "lei-9394-art-1º")

    def test_trecho_limitado_a_120_chars(self):
        texto_longo = "nos termos do art. 5º desta Lei, " + "x" * 200
        refs = self._extrair(texto_longo, "lei-test-art-1", "test")
        if refs:
            self.assertLessEqual(len(refs[0]["trecho"]), 120)

    @unittest.skipUnless(os.path.exists("/home/claude/struct_9394_v3.json"), "JSON não disponível")
    def test_ldb_tem_crossrefs(self):
        """A LDB deve ter pelo menos 4 cross-references detectáveis."""
        import json
        data = json.load(open("/home/claude/struct_9394_v3.json"))
        refs = self._extrair_struct(data, "9394")
        self.assertGreaterEqual(len(refs), 4, "LDB deve ter ao menos 4 cross-references")

    @unittest.skipUnless(os.path.exists("/home/claude/struct_9394_v3.json"), "JSON não disponível")
    def test_crossrefs_tem_campos_obrigatorios(self):
        """Cada cross-reference deve ter os campos esperados."""
        import json
        data = json.load(open("/home/claude/struct_9394_v3.json"))
        refs = self._extrair_struct(data, "9394")
        campos = {"origem", "destino_art", "destino_para", "destino_inc", "destino_alinea", "lei_externa", "trecho"}
        for ref in refs:
            self.assertEqual(set(ref.keys()), campos, f"Campos faltando em: {ref}")


# ═══════════════════════════════════════════════════════════════
# 12. DOWNLOADER — catálogo e adapters (sem rede)
# ═══════════════════════════════════════════════════════════════

class TestDownloaderCatalogo(unittest.TestCase):
    """Testa catálogo e adapters sem fazer requisições HTTP."""

    def setUp(self):
        import importlib.util
        if importlib.util.find_spec("downloader") is None:
            self.skipTest("Módulo downloader não encontrado")
        from downloader import listar_leis, info_lei
        self._listar = listar_leis
        self._info = info_lei

    def test_catalogo_tem_leis_basicas(self):
        leis = self._listar()
        for codigo in ["9394", "10406", "8078", "cp"]:
            self.assertIn(codigo, leis, f"Lei {codigo} não encontrada no catálogo")

    def test_info_lei_9394(self):
        cfg = self._info("9394")
        self.assertIsNotNone(cfg)
        self.assertIn("url", cfg)
        self.assertIn("fonte", cfg)
        self.assertIn("encoding", cfg)
        self.assertEqual(cfg["fonte"], "planalto")

    def test_info_lei_inexistente_retorna_none(self):
        cfg = self._info("99999999")
        self.assertIsNone(cfg)

    def test_catalogo_minimo_10_leis(self):
        leis = self._listar()
        self.assertGreaterEqual(len(leis), 10, "Catálogo deve ter ao menos 10 leis")


class TestAdapters(unittest.TestCase):
    """Testa adapters com HTML sintético — sem rede."""

    def setUp(self):
        import importlib.util
        if importlib.util.find_spec("adapters") is None:
            self.skipTest("Módulo adapters não encontrado")
        from adapters import get_adapter, listar_fontes
        self._get = get_adapter
        self._listar = listar_fontes

    def test_fontes_disponiveis(self):
        fontes = self._listar()
        for fonte in ["planalto", "senado", "camara"]:
            self.assertIn(fonte, fontes)

    def test_fonte_invalida_levanta_valueerror(self):
        with self.assertRaises(ValueError):
            self._get("fonte_inexistente")

    def test_planalto_extrai_texto_simples(self):
        html = b"<html><body><p>Art. 1 O ensino sera ministrado.</p></body></html>"
        adapter = self._get("planalto")
        texto = adapter.extrair_texto(html)
        self.assertIn("Art. 1", texto)
        self.assertNotIn("<p>", texto)

    def test_planalto_remove_scripts(self):
        html = b"<html><body><script>alert('x')</script><p>Lei teste.</p></body></html>"
        adapter = self._get("planalto")
        texto = adapter.extrair_texto(html)
        self.assertNotIn("alert", texto)
        self.assertIn("Lei teste", texto)

    def test_planalto_decode_latin1(self):
        # § e ã em latin-1
        html_bytes = "<html><body><p>§ 1º Parágrafo.</p></body></html>".encode("latin-1")
        adapter = self._get("planalto")
        texto = adapter.extrair_texto(html_bytes)
        self.assertIn("§", texto)

    def test_senado_usa_seletor_textonorma(self):
        html = (
            b'<html><body>'
            b'<nav>Menu</nav>'
            b'<div class="textoNorma"><p>Art. 1 Texto da norma.</p></div>'
            b'<footer>Rodape</footer>'
            b'</body></html>'
        )
        adapter = self._get("senado")
        texto = adapter.extrair_texto(html)
        self.assertIn("Art. 1 Texto da norma", texto)

    def test_sem_linhas_vazias_no_output(self):
        html = b"<html><body><p>linha 1</p><p></p><p>linha 2</p></body></html>"
        adapter = self._get("planalto")
        texto = adapter.extrair_texto(html)
        linhas = texto.splitlines()
        vazias = [l for l in linhas if not l.strip()]
        self.assertEqual(vazias, [], "Output não deve ter linhas vazias")