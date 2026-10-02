"""Metering: exactly-once under retries; honest quota boundaries."""
from tests.conftest import auth_headers


def test_same_request_twice_one_event(client, tenant):
    h = auth_headers(tenant, "idem-probe-1")
    body = {"input_tokens": 100, "output_tokens": 50}
    r1 = client.post("/v1/generate", json=body, headers=h)
    r2 = client.post("/v1/generate", json=body, headers=h)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r2.json()["replayed"] is True
    # The replayed response mirrors the original (minus the replay marker).
    j1 = {k: v for k, v in r1.json().items() if k != "replayed"}
    j2 = {k: v for k, v in r2.json().items() if k != "replayed"}
    assert j1 == j2
    usage = client.get("/v1/usage", headers={"X-Tenant-Key": tenant["api_key"]}).json()
    assert usage["api_calls"]["used"] == 1  # not 2


def test_quota_boundary_exact_then_over(client, tenant):
    key = tenant["api_key"]
    # Free plan: 1,000 calls/month. Burn 999 with distinct keys.
    for i in range(999):
        r = client.post("/v1/generate", json={},
                        headers={"X-Tenant-Key": key, "Idempotency-Key": f"b{i}"})
        assert r.status_code == 200, (i, r.text)
    # Request #1000 lands exactly on the limit -> allowed.
    r = client.post("/v1/generate", json={},
                    headers={"X-Tenant-Key": key, "Idempotency-Key": "b-exact"})
    assert r.status_code == 200, r.text
    # Request #1001 is over -> 429 with a clear message.
    r = client.post("/v1/generate", json={},
                    headers={"X-Tenant-Key": key, "Idempotency-Key": "b-over"})
    assert r.status_code == 429, r.text
    body = r.json()
    assert body["error"] == "quota_exceeded"
    assert "1,000" in body["message"] or "1000" in body["message"]


def test_missing_idempotency_key_is_400(client, tenant):
    r = client.post("/v1/generate", json={},
                    headers={"X-Tenant-Key": tenant["api_key"]})
    assert r.status_code == 400
    assert r.json()["error"] == "missing_idempotency_key"


def test_bad_input_is_4xx_not_500(client, tenant):
    r = client.post("/v1/generate", json={"input_tokens": -5},
                    headers=auth_headers(tenant, "bad1"))
    assert r.status_code == 422
    r = client.post("/v1/generate", json={"input_tokens": "lots"},
                    headers=auth_headers(tenant, "bad2"))
    assert r.status_code == 422
