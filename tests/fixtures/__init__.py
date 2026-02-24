from pathlib import Path
# tests/fixtures/__init__.py
"""
Fixtures com trechos REAIS de leis brasileiras, cobrindo cada padrão problemático.
Cada fixture é uma string que pode ser passada diretamente ao parser.
"""

# ─────────────────────────────────────────────────────────────
# FIXTURE 1: Art. simples com parágrafo
# Fonte: LDB Art. 1º
# ─────────────────────────────────────────────────────────────
ART_SIMPLES = """\
TÍTULO I
Da Educação
Art. 1º A educação abrange os processos formativos que se desenvolvem na vida familiar.
§ 1º Esta Lei disciplina a educação escolar.
§ 2º A educação escolar deverá vincular-se ao mundo do trabalho.
"""

# ─────────────────────────────────────────────────────────────
# FIXTURE 2: Incisos — todos os 5 formatos de separador do Planalto
# ─────────────────────────────────────────────────────────────
ART_INCISOS_TODOS_FORMATOS = """\
TÍTULO I
Teste
Art. 3º O ensino será ministrado com base nos seguintes princípios:
I
- igualdade de condições para o acesso e permanência na escola;
II
- liberdade de aprender, ensinar, pesquisar e divulgar a cultura;
III - pluralismo de idéias e de concepções pedagógicas;
IV
- respeito à liberdade e apreço à tolerância;
V
- coexistência de instituições públicas e privadas de ensino;
VI
- gratuidade do ensino público em estabelecimentos oficiais;
VII - valorização do profissional da educação escolar;
VIII \x96 gestão democrática do ensino público, na forma desta Lei;
IX
- garantia de padrão de qualidade;
X
- valorização da experiência extra-escolar;
"""

# ─────────────────────────────────────────────────────────────
# FIXTURE 3: Inciso com alíneas
# Fonte: LDB Art. 4º, Inciso I
# ─────────────────────────────────────────────────────────────
ART_INCISOS_COM_ALINEAS = """\
TÍTULO I
Teste
Art. 4º O dever do Estado com educação escolar pública será efetivado mediante a garantia de:
I - educação básica obrigatória organizada da seguinte forma:
a) pré-escola;
b) ensino fundamental;
c) ensino médio;
II - educação infantil gratuita às crianças de até 5 anos de idade;
"""

# ─────────────────────────────────────────────────────────────
# FIXTURE 4: Artigo com número em formato 'Art. 15.' (ponto após número)
# Fonte: LDB Art. 15
# ─────────────────────────────────────────────────────────────
ART_PONTO_APOS_NUMERO = """\
TÍTULO I
Teste
Art. 15. Os sistemas de ensino assegurarão às unidades escolares públicas de educação básica progressivos graus de autonomia pedagógica e administrativa.
"""

# ─────────────────────────────────────────────────────────────
# FIXTURE 5: Artigo com sufixo -A
# Fonte: LDB Art. 4º-A
# ─────────────────────────────────────────────────────────────
ART_SUFIXO_A = """\
TÍTULO I
Teste
Art. 4º-A. É assegurado atendimento educacional, durante o período de internação, ao aluno da educação básica internado para tratamento de saúde.
(Incluído pela Lei nº 13.716, de 2018)
"""

# ─────────────────────────────────────────────────────────────
# FIXTURE 6: Metadados — formato padrão "de ANO"
# ─────────────────────────────────────────────────────────────
META_ANO_PADRAO = """\
TÍTULO I
Teste
Art. 10. Os Estados incumbir-se-ão de:
I - organizar, manter e desenvolver os órgãos e instituições oficiais dos seus sistemas de ensino;
(Redação dada pela Lei nº 12.796, de 2013)
"""

# ─────────────────────────────────────────────────────────────
# FIXTURE 7: Metadados — formato data completa "de 1º.12.2003"
# ─────────────────────────────────────────────────────────────
META_ANO_DATA_COMPLETA = """\
TÍTULO I
Teste
Art. 26. Os currículos da educação infantil do ensino fundamental e do ensino médio devem ter base nacional comum.
§ 3º A educação física, integrada à proposta pedagógica da escola, é componente curricular obrigatório da educação básica.
(Redação dada pela Lei nº 10.793, de 1º.12.2003)
"""

# ─────────────────────────────────────────────────────────────
# FIXTURE 8: Metadados — referências internas (sem norma externa)
# ─────────────────────────────────────────────────────────────
META_REFERENCIA_INTERNA = """\
TÍTULO I
Teste
Art. 7º-A. Ao aluno regularmente matriculado em instituição de ensino pública ou privada, de qualquer nível, é assegurado atendimento educacional.
(Vide parágrafo único do art. 2)
"""

# ─────────────────────────────────────────────────────────────
# FIXTURE 9: Metadados — Adin e 'lei' minúsculo
# ─────────────────────────────────────────────────────────────
META_ADIN_E_LEI_MINUSCULO = """\
TÍTULO I
Teste
Art. 1. Teste de lei.
(Vide Adin 3324-7, de 2005)
Art. 2. Teste de redação.
(Redação dada pela lei nº 13.415, de 2017)
"""

# ─────────────────────────────────────────────────────────────
# FIXTURE 10: Marcador hierárquico quebrado em duas linhas
# Fonte: LDB — CAPÍTULO\nIII encontrado no raw
# ─────────────────────────────────────────────────────────────
CAPITULO_QUEBRADO = """\
TÍTULO I
Teste
CAPÍTULO
III
Do Ensino Médio
Art. 35. O ensino médio, etapa final da educação básica, com duração mínima de três anos.
"""

# ─────────────────────────────────────────────────────────────
# FIXTURE 11: Hierarquia completa com Parágrafo único
# ─────────────────────────────────────────────────────────────
PARAGRAFO_UNICO = """\
TÍTULO I
Teste
Art. 5º O acesso à educação básica obrigatória é direito público subjetivo.
Parágrafo único. O poder público, na esfera de sua competência, deverá recensear os alunos.
"""

# ─────────────────────────────────────────────────────────────
# FIXTURE 12: Inciso com numeral sufixo (VII-A)
# Fonte: LDB Art. 9º VII-A
# ─────────────────────────────────────────────────────────────
ART_INCISO_SUFIXO = """\
TÍTULO I
Teste
Art. 9º A União incumbir-se-á de:
VII - baixar normas gerais sobre cursos de graduação e pós-graduação;
VII-A - assegurar, em colaboração com os sistemas de ensino, o processo nacional de avaliação;
VIII - assegurar processo nacional de avaliação das instituições de educação superior;
"""

# ─────────────────────────────────────────────────────────────
# FIXTURE 13: \n dentro de texto (texto corrido quebrado pelo HTML)
# ─────────────────────────────────────────────────────────────
TEXTO_COM_NEWLINES = """\
TÍTULO I
Teste
Art. 2º A educação, dever da família e do Estado, inspirada nos princípios de
liberdade e nos ideais de solidariedade humana, tem por finalidade o pleno desenvolvimento
do educando, seu preparo para o exercício da cidadania e sua qualificação para o
trabalho.
"""

# ─────────────────────────────────────────────────────────────
# FIXTURE 14: Hierarquia com LIVRO (Código Civil)
# ─────────────────────────────────────────────────────────────
HIERARQUIA_LIVRO = """\
PARTE ESPECIAL
LIVRO I
Do Direito das Obrigações
TÍTULO I
Das Modalidades das Obrigações
CAPÍTULO I
Das Obrigações de Dar
Art. 233. A obrigação de dar coisa certa abrange os acessórios dela embora não mencionados.
Art. 234. Se, no caso do artigo antecedente, a coisa se perder, sem culpa do devedor, antes da tradição, ou pendente a condição suspensiva, fica resolvida a obrigação para ambas as partes.
"""

# ─────────────────────────────────────────────────────────────
# FIXTURE 15: LDB completa — para testes de integração
# (carregada do arquivo real, não definida aqui)
# ─────────────────────────────────────────────────────────────


BASE_DIR = Path(__file__).resolve().parent
LDB_RAW_PATH = BASE_DIR.parent.parent / "raw_9394.txt"