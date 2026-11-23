"""Shared fixtures.

Chat-flow tests were written against the four-pillar engine (IMPLEMENTATION_PLAN.md:
'ENGINE=pillars keeps the old behaviour for tests/comparison'), so the suites that
assert the legacy reply path pin ENGINE=pillars. Tests for the core engine's chat
path set ENGINE=core explicitly.
"""
import pytest

from app.config import settings

# Modules that exercise the legacy pillars/chat-analysis path.
_PILLARS_MODULES = {
    "test_chat_llm_first",
    "test_consult_flow",
    "test_jyotish",
    "test_precision",
    "test_trust_safety",
}


@pytest.fixture(autouse=True)
def _legacy_engine(monkeypatch, request):
    if request.module.__name__.rsplit(".", 1)[-1] in _PILLARS_MODULES:
        monkeypatch.setattr(settings, "ENGINE", "pillars")
