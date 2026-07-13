"""U3 auth tests: bearer-token gate on the eve↔analysts seam (hosted mode).

Security-review properties under test:
1. ANALYSTS_API_TOKEN set -> every route except /health requires
   `Authorization: Bearer <token>`; 401 on missing/mismatch; the presented
   credential never appears in logs or response bodies.
2. FastAPI's auto-mounted /docs, /redoc and /openapi.json are gated too
   (pure ASGI middleware runs before routing).
3. ANALYSTS_REQUIRE_AUTH=1 without a token refuses to start (fail closed).
Token unset without the flag = auth disabled entirely (local dev unchanged).

The middleware reads ANALYSTS_API_TOKEN at request time, so monkeypatching
the env per test works against the module-level app.
"""

import logging
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from doc_intel_analysts import service

TOKEN = "seam-token-for-tests"


@pytest.fixture
def client() -> TestClient:
    return TestClient(service.app)


@pytest.fixture
def with_token(monkeypatch) -> None:
    monkeypatch.setenv("ANALYSTS_API_TOKEN", TOKEN)


@pytest.fixture
def without_token(monkeypatch) -> None:
    monkeypatch.delenv("ANALYSTS_API_TOKEN", raising=False)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_correct_token_reaches_a_real_route(client, with_token):
    res = client.get("/openapi.json", headers=_bearer(TOKEN))
    assert res.status_code == 200
    assert res.json()["info"]["title"] == "doc-intel-analysts"


def test_correct_token_passes_auth_on_business_route(client, with_token):
    # Invalid body: 422 (reached validation), never 401 (stopped by auth).
    res = client.post("/analyze", json={}, headers=_bearer(TOKEN))
    assert res.status_code == 422


def test_missing_header_is_401(client, with_token):
    assert client.post("/analyze", json={}).status_code == 401
    assert client.get("/openapi.json").status_code == 401


def test_wrong_token_is_401(client, with_token):
    res = client.post("/analyze", json={}, headers=_bearer("wrong-" + TOKEN))
    assert res.status_code == 401


def test_wrong_scheme_is_401(client, with_token):
    res = client.get("/openapi.json", headers={"Authorization": f"Basic {TOKEN}"})
    assert res.status_code == 401


def test_token_unset_leaves_service_open(client, without_token):
    assert client.get("/openapi.json").status_code == 200
    assert client.post("/analyze", json={}).status_code == 422


def test_health_is_open_with_and_without_token(client, with_token):
    assert client.get("/health").status_code == 200
    assert client.get("/health").json() == {"ok": True}


def test_health_is_open_when_auth_disabled(client, without_token):
    assert client.get("/health").status_code == 200


def test_docs_surfaces_not_public_when_token_set(client, with_token):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code in (401, 404), path


def test_401_leaks_no_token_material(client, with_token, caplog):
    presented = "attacker-presented-credential"
    with caplog.at_level(logging.DEBUG):
        res = client.post("/analyze", json={}, headers=_bearer(presented))
    assert res.status_code == 401
    assert presented not in res.text
    assert TOKEN not in res.text
    assert presented not in caplog.text
    assert TOKEN not in caplog.text


def test_require_auth_without_token_refuses_to_start():
    env = {k: v for k, v in os.environ.items() if k != "ANALYSTS_API_TOKEN"}
    env["ANALYSTS_REQUIRE_AUTH"] = "1"
    proc = subprocess.run(
        [sys.executable, "-c", "import doc_intel_analysts.service"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "ANALYSTS_API_TOKEN" in proc.stderr


def test_require_auth_with_token_starts():
    env = dict(os.environ)
    env["ANALYSTS_REQUIRE_AUTH"] = "1"
    env["ANALYSTS_API_TOKEN"] = TOKEN
    proc = subprocess.run(
        [sys.executable, "-c", "import doc_intel_analysts.service"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
