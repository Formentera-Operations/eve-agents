"""U1 contract tests: the egress guard refuses any non-gateway configuration."""

import pytest

from doc_intel_analysts.graph import config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in (
        "LLM_ENDPOINT", "LLM_API_KEY", "LLM_PROVIDER", "LLM_MODEL",
        "EMBEDDING_ENDPOINT", "EMBEDDING_API_KEY", "EMBEDDING_PROVIDER", "EMBEDDING_MODEL",
        "TELEMETRY_DISABLED", "AI_GATEWAY_API_KEY", "VERCEL_OIDC_TOKEN",
        "DATA_ROOT_DIRECTORY", "SYSTEM_ROOT_DIRECTORY", "ENABLE_BACKEND_ACCESS_CONTROL",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "test-key")


def test_configure_sets_full_gateway_env(monkeypatch):
    config.configure()
    import os

    assert os.environ["LLM_ENDPOINT"] == config.GATEWAY_BASE_URL
    assert os.environ["EMBEDDING_ENDPOINT"] == config.GATEWAY_BASE_URL
    assert os.environ["TELEMETRY_DISABLED"] == "1"
    assert os.environ["ENABLE_BACKEND_ACCESS_CONTROL"] == "false"
    assert config.DATA_ROOT.exists() and config.SYSTEM_ROOT.exists()
    assert ".cognee" in str(config.DATA_ROOT)


def test_guard_raises_when_embedding_points_elsewhere(monkeypatch):
    monkeypatch.setenv("EMBEDDING_ENDPOINT", "https://api.openai.com/v1")
    with pytest.raises(config.GraphConfigError, match="EMBEDDING_ENDPOINT"):
        config.configure()


def test_guard_raises_when_llm_points_elsewhere(monkeypatch):
    monkeypatch.setenv("LLM_ENDPOINT", "https://api.openai.com/v1")
    with pytest.raises(config.GraphConfigError, match="LLM_ENDPOINT"):
        config.configure()


def test_guard_raises_when_telemetry_enabled(monkeypatch):
    monkeypatch.setenv("TELEMETRY_DISABLED", "0")
    with pytest.raises(config.GraphConfigError, match="TELEMETRY"):
        config.configure()


def test_guard_raises_without_any_gateway_credential(monkeypatch):
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    with pytest.raises(config.GraphConfigError, match="gateway credential"):
        config.configure()
