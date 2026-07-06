"""Contract tests for programmatic SubAgent generation."""

import os

os.environ.setdefault("AI_GATEWAY_API_KEY", "test-placeholder")

from doc_intel_analysts.agent import DEFAULT_MODEL, build_subagents, load_analyst_classes


def test_subagents_generated_from_knowledge_table():
    classes = load_analyst_classes()
    subs = build_subagents(classes)
    assert len(subs) == len(classes) == 7
    assert all(s["name"] and s["description"] and s["system_prompt"] for s in subs)


def test_per_class_model_override_applies():
    subs = build_subagents(load_analyst_classes())
    by_name = {s["name"]: s for s in subs}
    assert by_name["logs-analyst"]["model"].model_name == "anthropic/claude-haiku-4.5"
    # every class without an override stays on the default
    for name, sub in by_name.items():
        if name != "logs-analyst":
            assert sub["model"].model_name == DEFAULT_MODEL


def test_override_is_data_driven_not_hardcoded():
    classes = load_analyst_classes()
    for cls in classes:
        cls.pop("model", None)
    subs = build_subagents(classes)
    assert all(s["model"].model_name == DEFAULT_MODEL for s in subs)
