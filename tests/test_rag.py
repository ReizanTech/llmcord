"""Tests for the RAG support integration.

No Discord and no network: the embedding model is LlamaIndex's
`MockEmbedding`, and the index is built into `tmp_path` from real files.
"""

from __future__ import annotations

import pytest
from llama_index.core import Settings
from llama_index.core.embeddings import MockEmbedding

from rag import KnowledgeBase, RagSettings, format_context
from rag.knowledge import Source

EMBED_DIM = 8


@pytest.fixture(autouse=True)
def mock_embeddings(monkeypatch):
    """The embedding API is a network boundary — replaced, not called.

    Patches `_embed_model`, the dataclass field; the `embed_model` property
    getter would try to resolve a real OpenAI model.
    """
    monkeypatch.setattr(Settings, "_embed_model", MockEmbedding(embed_dim=EMBED_DIM))


@pytest.fixture
def settings(tmp_path):
    knowledge = tmp_path / "knowledge_base"
    knowledge.mkdir()
    (knowledge / "guide.md").write_text(
        "# Install\n\nRun GenPatcher.exe from the desktop.\n\n"
        "# Crashes\n\nDisable the antivirus before extracting the archive.\n",
        encoding="utf-8",
    )
    return RagSettings(
        knowledge_dir=knowledge,
        storage_dir=tmp_path / "storage",
        base_url="http://localhost/v1",
        api_key="test-key",
        embed_dim=EMBED_DIM,
    )


def build(settings) -> None:
    """Index through the real builder so the stores match production."""
    from llama_index.core import Settings

    from build_knowledge_index import index_documents, load_documents

    index_documents(load_documents(settings.knowledge_dir), settings, embed_model=Settings.embed_model)


def test_missing_index_reports_reason_instead_of_raising(settings):
    """The bot must still answer when the index was never built."""
    kb = KnowledgeBase.load(settings)

    assert kb.available is False
    assert "build_knowledge_index" in kb.unavailable_reason
    assert kb.retrieve("anything") == []


def test_retrieval_returns_text_after_reload(settings):
    """Regression: retrieval returned no nodes -> the bot answered with no context."""
    build(settings)

    kb = KnowledgeBase.load(settings, embed_model=Settings.embed_model)
    sources = kb.retrieve("antivirus", top_k=2)

    assert sources
    assert all(source.text for source in sources)
    assert sources[0].file_name == "guide.md"


def test_off_topic_question_yields_no_passages(settings):
    """A weak match must be dropped, not injected as misleading context."""
    build(settings)
    kb = KnowledgeBase.load(settings, embed_model=Settings.embed_model)

    # MockEmbedding returns identical vectors, so force the score down to
    # exercise the threshold itself rather than the embedding similarity.
    kb._settings = settings.__class__(**{**settings.__dict__, "min_score": 1.1})

    assert kb.retrieve("what is the best pizza place in Cairo?") == []


def test_settings_are_read_from_the_rag_section(tmp_path):
    config = {
        "providers": {"sovereign": {"base_url": "https://example/v1", "api_key": "k"}},
        "rag": {"enabled": True, "provider": "sovereign", "top_k": 3},
    }

    settings = RagSettings.from_config(config, tmp_path)

    assert settings is not None
    assert settings.base_url == "https://example/v1"
    assert settings.api_key == "k"
    assert settings.top_k == 3


def test_disabled_rag_returns_none():
    assert RagSettings.from_config({"rag": {"enabled": False}}, None) is None


def test_missing_provider_key_is_reported(tmp_path):
    config = {
        "providers": {"sovereign": {"base_url": "https://example/v1"}},
        "rag": {"enabled": True, "provider": "sovereign"},
    }

    with pytest.raises(ValueError, match="no API key"):
        RagSettings.from_config(config, tmp_path)


def test_context_is_capped_and_numbered():
    """Numbering is what the prompt tells the model to cite, so it must hold."""
    sources = [
        Source(file_name="a.md", header_path="/Install/", text="x" * 500),
        Source(file_name="b.md", header_path="", text="y" * 500),
    ]

    context = format_context(sources, max_chars=600)

    assert context.startswith("[1] (a.md › Install)")
    assert len(context) <= 640
    assert "[2]" not in context


def test_context_includes_every_passage_when_it_fits():
    sources = [
        Source(file_name="a.md", header_path="", text="first"),
        Source(file_name="b.md", header_path="", text="second"),
    ]

    context = format_context(sources, max_chars=6000)

    assert "[1] (a.md)" in context
    assert "[2] (b.md)" in context


def test_empty_sources_produce_no_context():
    assert format_context([], max_chars=6000) == ""
