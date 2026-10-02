import os
import tempfile

# Isolated DB for the whole test session, set before the app is imported.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["BILLING_PROVIDER"] = "simulated"

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def tenant(client):
    r = client.post("/admin/tenants", json={"name": "test-tenant", "plan_id": "free"})
    assert r.status_code == 200, r.text
    return r.json()


def auth_headers(tenant, idem_key="k1"):
    return {"X-Tenant-Key": tenant["api_key"], "Idempotency-Key": idem_key}
