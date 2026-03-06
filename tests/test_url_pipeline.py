from fastapi.testclient import TestClient
from api import app
import pytest

client = TestClient(app)

def test_trigger_url_pipeline():
    print("\nRoutes in app:")
    for route in app.routes:
        methods = getattr(route, "methods", None)
        print(f"  {route.path} {methods}")

    # 1. Check health
    health = client.get("/api/v1/health")
    print(f"Health: {health.status_code}")
    print(health.json())

    # 2. Trigger URL
    url = "https://www.planalto.gov.br/ccivil_03/leis/l9394.htm"
    response = client.post(
        "/api/v1/pipeline/url",
        json={"url": url, "fonte": "planalto"},
        headers={"X-API-Key": "8303"}
    )
    
    if response.status_code not in [200, 201]:
        print(f"FAILED Trigger: {response.status_code}")
        try:
            print(response.json())
        except:
            print(response.text)
        
    assert response.status_code in [200, 201]
    data = response.json()
    assert "codigo" in data
    assert data["status"] in ["iniciado", "ja_processando"]

if __name__ == "__main__":
    test_trigger_url_pipeline()
    print("Test passed!")
