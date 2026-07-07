"""U1 contract tests: evidence config fails loud and never egresses."""

import pytest

from doc_intel_analysts.evidence import config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in (
        "AI_GATEWAY_API_KEY",
        "VERCEL_OIDC_TOKEN",
        "EVIDENCE_EMBEDDING_ENDPOINT",
        "EVIDENCE_EMBEDDING_MODEL",
        "EVIDENCE_EMBEDDING_DIMENSIONS",
        "EVIDENCE_CLIP_MODEL",
        "EVIDENCE_CLIP_PRETRAINED",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "test-key")


def test_load_config_defaults_to_gateway(monkeypatch):
    cfg = config.load_config()
    assert cfg.gateway_base_url == "https://ai-gateway.vercel.sh/v1"
    assert cfg.gateway_api_key == "test-key"
    assert cfg.embedding_model == config.DEFAULT_EMBEDDING_MODEL


def test_guard_raises_when_embedding_points_elsewhere(monkeypatch):
    monkeypatch.setenv("EVIDENCE_EMBEDDING_ENDPOINT", "https://api.openai.com/v1")
    with pytest.raises(config.EvidenceConfigError, match="EVIDENCE_EMBEDDING_ENDPOINT"):
        config.load_config()


def test_guard_rejects_lookalike_gateway_host(monkeypatch):
    monkeypatch.setenv(
        "EVIDENCE_EMBEDDING_ENDPOINT", "https://ai-gateway.vercel.sh.evil.com/v1"
    )
    with pytest.raises(config.EvidenceConfigError, match="EVIDENCE_EMBEDDING_ENDPOINT"):
        config.load_config()


def test_guard_raises_without_any_gateway_credential(monkeypatch):
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    with pytest.raises(config.EvidenceConfigError, match="gateway credential"):
        config.load_config()


def test_store_path_is_outside_the_cognee_wipe_zone():
    cfg = config.load_config()
    assert ".evidence" in str(cfg.store_root)
    assert ".cognee" not in str(cfg.store_root)
    assert ".cognee" not in str(cfg.lance_root)
    assert ".cognee" not in str(cfg.parsed_root)
    assert cfg.parsed_root.is_relative_to(cfg.store_root)


def test_env_overrides_apply(monkeypatch):
    monkeypatch.setenv("EVIDENCE_EMBEDDING_MODEL", "text-embedding-3-large")
    monkeypatch.setenv("EVIDENCE_EMBEDDING_DIMENSIONS", "3072")
    cfg = config.load_config()
    assert cfg.embedding_model == "text-embedding-3-large"
    assert cfg.embedding_dimensions == 3072
