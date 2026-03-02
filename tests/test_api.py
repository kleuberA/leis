"""
tests/test_api.py
Testes para a API REST de leis brasileiras.

Usa TestClient do FastAPI (httpx sob o capô) — sem necessidade de servidor rodando.
"""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

# Configura API_SECRET_KEY para testes antes de importar api
os.environ["API_SECRET_KEY"] = "test-secret-key-123"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"

from api import app


client = TestClient(app)

# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

TEST_API_KEY = "test-secret-key-123"
AUTH_HEADER = {"X-API-Key": TEST_API_KEY}


# ═══════════════════════════════════════════════════════════════
# 1. HEALTH CHECK
# ═══════════════════════════════════════════════════════════════

class TestHealth(unittest.TestCase):

    def test_health_retorna_200(self):
        r = client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)

    def test_health_contem_status_ok(self):
        r = client.get("/api/v1/health")
        data = r.json()
        self.assertEqual(data["status"], "ok")

    def test_health_contem_version(self):
        r = client.get("/api/v1/health")
        data = r.json()
        self.assertIn("version", data)

    def test_health_contem_timestamp(self):
        r = client.get("/api/v1/health")
        data = r.json()
        self.assertIn("timestamp", data)


# ═══════════════════════════════════════════════════════════════
# 2. CATÁLOGO
# ═══════════════════════════════════════════════════════════════

class TestCatalogo(unittest.TestCase):

    def test_catalogo_retorna_200(self):
        r = client.get("/api/v1/leis/catalogo")
        self.assertEqual(r.status_code, 200)

    def test_catalogo_contem_leis(self):
        r = client.get("/api/v1/leis/catalogo")
        data = r.json()
        self.assertIsInstance(data, dict)
        self.assertGreater(len(data), 0)

    def test_catalogo_tem_leis_basicas(self):
        r = client.get("/api/v1/leis/catalogo")
        data = r.json()
        for codigo in ["9394", "cp", "cf88"]:
            self.assertIn(codigo, data, f"Lei {codigo} não encontrada no catálogo")

    def test_catalogo_lei_tem_campos(self):
        r = client.get("/api/v1/leis/catalogo")
        data = r.json()
        lei = data.get("9394", {})
        self.assertIn("nome", lei)
        self.assertIn("tags", lei)
        self.assertIn("fonte", lei)

    def test_catalogo_filtro_por_tag(self):
        r = client.get("/api/v1/leis/catalogo?tag=penal")
        data = r.json()
        self.assertGreater(len(data), 0)
        for cod, info in data.items():
            self.assertIn("penal", info.get("tags", []))

    def test_catalogo_tag_inexistente_retorna_vazio(self):
        r = client.get("/api/v1/leis/catalogo?tag=tag_que_nao_existe_xyz")
        data = r.json()
        self.assertEqual(len(data), 0)


# ═══════════════════════════════════════════════════════════════
# 3. LEI INDIVIDUAL (RESUMO)
# ═══════════════════════════════════════════════════════════════

class TestLeiResumo(unittest.TestCase):
    """Testa endpoint GET /api/v1/leis/{codigo} — depende de struct existir."""

    def _skip_if_no_struct(self, codigo="9394"):
        from api import _data_path
        if not _data_path("struct", codigo).exists():
            self.skipTest(f"struct_{codigo}.json não disponível")

    def test_lei_existente_retorna_200(self):
        self._skip_if_no_struct()
        r = client.get("/api/v1/leis/9394")
        self.assertEqual(r.status_code, 200)

    def test_lei_existente_tem_campos(self):
        self._skip_if_no_struct()
        r = client.get("/api/v1/leis/9394")
        data = r.json()
        self.assertIn("codigo", data)
        self.assertIn("total_artigos", data)
        self.assertIn("total_titulos", data)

    def test_lei_inexistente_retorna_404(self):
        r = client.get("/api/v1/leis/lei_que_nao_existe")
        self.assertEqual(r.status_code, 404)


# ═══════════════════════════════════════════════════════════════
# 4. ARTIGOS (PAGINAÇÃO)
# ═══════════════════════════════════════════════════════════════

class TestArtigosPaginados(unittest.TestCase):

    def _skip_if_no_struct(self, codigo="9394"):
        from api import _data_path
        if not _data_path("struct", codigo).exists():
            self.skipTest(f"struct_{codigo}.json não disponível")

    def test_artigos_retorna_200(self):
        self._skip_if_no_struct()
        r = client.get("/api/v1/leis/9394/artigos")
        self.assertEqual(r.status_code, 200)

    def test_artigos_tem_paginacao(self):
        self._skip_if_no_struct()
        r = client.get("/api/v1/leis/9394/artigos?page=1&per_page=5")
        data = r.json()
        self.assertIn("artigos", data)
        self.assertIn("paginacao", data)
        self.assertLessEqual(len(data["artigos"]), 5)

    def test_artigos_paginacao_meta(self):
        self._skip_if_no_struct()
        r = client.get("/api/v1/leis/9394/artigos?page=1&per_page=10")
        meta = r.json()["paginacao"]
        self.assertEqual(meta["page"], 1)
        self.assertEqual(meta["per_page"], 10)
        self.assertGreater(meta["total"], 0)
        self.assertGreater(meta["total_pages"], 0)

    def test_artigos_campos_do_resumo(self):
        self._skip_if_no_struct()
        r = client.get("/api/v1/leis/9394/artigos?per_page=1")
        artigos = r.json()["artigos"]
        if artigos:
            art = artigos[0]
            self.assertIn("id", art)
            self.assertIn("numero", art)
            self.assertIn("confianca", art)
            self.assertIn("tem_estrutura", art)

    def test_artigos_pagina_2(self):
        self._skip_if_no_struct()
        r1 = client.get("/api/v1/leis/9394/artigos?page=1&per_page=5")
        r2 = client.get("/api/v1/leis/9394/artigos?page=2&per_page=5")
        arts1 = [a["id"] for a in r1.json()["artigos"]]
        arts2 = [a["id"] for a in r2.json()["artigos"]]
        # Páginas diferentes devem ter artigos diferentes
        self.assertNotEqual(arts1, arts2)


# ═══════════════════════════════════════════════════════════════
# 5. ARTIGO INDIVIDUAL
# ═══════════════════════════════════════════════════════════════

class TestArtigoIndividual(unittest.TestCase):

    def _skip_if_no_struct(self, codigo="9394"):
        from api import _data_path
        if not _data_path("struct", codigo).exists():
            self.skipTest(f"struct_{codigo}.json não disponível")

    def test_artigo_existente(self):
        self._skip_if_no_struct()
        r = client.get("/api/v1/leis/9394/artigos/lei-9394-art-1")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("estrutura", data)
        self.assertIn("numero", data)

    def test_artigo_inexistente_retorna_404(self):
        self._skip_if_no_struct()
        r = client.get("/api/v1/leis/9394/artigos/lei-9394-art-999999")
        self.assertEqual(r.status_code, 404)


# ═══════════════════════════════════════════════════════════════
# 6. BUSCA
# ═══════════════════════════════════════════════════════════════

class TestBusca(unittest.TestCase):

    def _skip_if_no_struct(self, codigo="9394"):
        from api import _data_path
        if not _data_path("struct", codigo).exists():
            self.skipTest(f"struct_{codigo}.json não disponível")

    def test_busca_retorna_200(self):
        self._skip_if_no_struct()
        r = client.get("/api/v1/leis/9394/busca?q=educação")
        self.assertEqual(r.status_code, 200)

    def test_busca_encontra_resultados(self):
        self._skip_if_no_struct()
        r = client.get("/api/v1/leis/9394/busca?q=educação")
        data = r.json()
        self.assertIn("resultados", data)
        self.assertGreater(len(data["resultados"]), 0)

    def test_busca_com_limite(self):
        self._skip_if_no_struct()
        r = client.get("/api/v1/leis/9394/busca?q=educação&limit=3")
        data = r.json()
        self.assertLessEqual(len(data["resultados"]), 3)

    def test_busca_termo_curto_retorna_422(self):
        self._skip_if_no_struct()
        r = client.get("/api/v1/leis/9394/busca?q=ab")
        self.assertEqual(r.status_code, 422)


# ═══════════════════════════════════════════════════════════════
# 7. AUTENTICAÇÃO
# ═══════════════════════════════════════════════════════════════

class TestAutenticacao(unittest.TestCase):

    def test_pipeline_sem_api_key_retorna_401(self):
        r = client.post("/api/v1/pipeline/9394")
        self.assertEqual(r.status_code, 401)

    def test_pipeline_com_api_key_errada_retorna_401(self):
        r = client.post("/api/v1/pipeline/9394", headers={"X-API-Key": "chave-errada"})
        self.assertEqual(r.status_code, 401)

    def test_patch_sem_api_key_retorna_401(self):
        r = client.patch(
            "/api/v1/leis/9394/artigos/lei-9394-art-1",
            json={"confianca": 1.0},
        )
        self.assertEqual(r.status_code, 401)


# ═══════════════════════════════════════════════════════════════
# 8. PIPELINE (com auth)
# ═══════════════════════════════════════════════════════════════

class TestPipeline(unittest.TestCase):

    def test_pipeline_lei_inexistente_retorna_404(self):
        r = client.post(
            "/api/v1/pipeline/lei_inexistente_xyz",
            headers=AUTH_HEADER,
        )
        self.assertEqual(r.status_code, 404)

    def test_pipeline_status_nao_iniciado(self):
        r = client.get("/api/v1/pipeline/lei_que_nunca_rodou/status")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn(data["status"], ["nao_iniciado", "concluido"])


# ═══════════════════════════════════════════════════════════════
# 9. CROSSREFS E RELATÓRIO
# ═══════════════════════════════════════════════════════════════

class TestCrossrefsRelatorio(unittest.TestCase):

    def _skip_if_no_file(self, tipo, codigo="9394"):
        from api import _data_path
        if not _data_path(tipo, codigo).exists():
            self.skipTest(f"{tipo}_{codigo}.json não disponível")

    def test_crossrefs_retorna_200(self):
        self._skip_if_no_file("crossrefs")
        r = client.get("/api/v1/leis/9394/crossrefs")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("total", data)
        self.assertIn("referencias", data)

    def test_relatorio_retorna_200(self):
        self._skip_if_no_file("relatorio")
        r = client.get("/api/v1/leis/9394/relatorio")
        self.assertEqual(r.status_code, 200)

    def test_crossrefs_inexistente_retorna_404(self):
        r = client.get("/api/v1/leis/lei_sem_crossrefs_xyz/crossrefs")
        self.assertEqual(r.status_code, 404)


# ═══════════════════════════════════════════════════════════════
# 10. ESTRUTURA COMPLETA
# ═══════════════════════════════════════════════════════════════

class TestEstruturaCompleta(unittest.TestCase):

    def _skip_if_no_struct(self, codigo="9394"):
        from api import _data_path
        if not _data_path("struct", codigo).exists():
            self.skipTest(f"struct_{codigo}.json não disponível")

    def test_estrutura_retorna_200(self):
        self._skip_if_no_struct()
        r = client.get("/api/v1/leis/9394/estrutura")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("lei", data)
        self.assertIn("titulos", data)


# ═══════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
