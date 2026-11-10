"""Load a persisted LlamaIndex index and retrieve passages from it.

The bot must never die because the knowledge base is missing or stale, so
`KnowledgeBase.load` reports the problem through `unavailable_reason` and
retrieval returns an empty list. The chat keeps working without context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Source:
    """One retrieved passage, with what the bot needs to cite it."""

    file_name: str
    header_path: str
    text: str
    score: float | None = None

    @property
    def label(self) -> str:
        # Markdown headings can carry a trailing CR (files with CRLF line
        # endings), which would otherwise leak into the prompt.
        header = self.header_path.strip().strip("/").strip()
        return f"{self.file_name} › {header}" if header else self.file_name


def format_context(sources: list[Source], max_chars: int) -> str:
    """Render passages for the system prompt, newest-truncation safe.

    Each passage is numbered so the model can cite `[1]`, `[2]` instead of
    inventing file names.
    """
    if not sources:
        return ""

    blocks: list[str] = []
    used = 0
    for index, source in enumerate(sources, start=1):
        block = f"[{index}] ({source.label})\n{source.text.strip()}"
        if used + len(block) > max_chars:
            remaining = max_chars - used
            if remaining > 200:
                blocks.append(block[:remaining].rstrip() + " …")
            break
        blocks.append(block)
        used += len(block)

    return "\n\n".join(blocks)


class KnowledgeBase:
    """A loaded vector index plus the settings it was built with."""

    def __init__(self, index, settings, unavailable_reason: str | None = None) -> None:
        self._index = index
        self._settings = settings
        self.unavailable_reason = unavailable_reason

    @classmethod
    def load(cls, settings, embed_model=None) -> KnowledgeBase:
        """Load from disk without raising: a broken KB must not stop the bot."""
        try:
            index = _load_index(settings, embed_model)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed silently
            logger.warning("Knowledge base unavailable: %s", exc)
            return cls(None, settings, unavailable_reason=str(exc))
        return cls(index, settings)

    @property
    def available(self) -> bool:
        return self._index is not None

    @property
    def settings(self):
        return self._settings

    def retrieve(self, question: str, top_k: int | None = None) -> list[Source]:
        """Blocking — call through `asyncio.to_thread` from the event loop."""
        if self._index is None or not question.strip():
            return []

        nodes = self._index.as_retriever(
            similarity_top_k=top_k or self._settings.top_k
        ).retrieve(question)

        # Drop weak matches so an off-topic question gets no context at all
        # rather than the least-bad passages.
        min_score = self._settings.min_score
        return [
            Source(
                file_name=(node.metadata or {}).get("file_name", "?"),
                header_path=(node.metadata or {}).get("header_path", ""),
                text=node.get_content(),
                score=node.score,
            )
            for node in nodes
            if node.score is None or node.score >= min_score
        ]


def make_embed_model(settings, batch_size: int = 10):
    """The one place the embedding model is constructed.

    Tests pass `Settings.embed_model` in explicitly; production calls this
    with no argument and gets the configured provider.
    """
    from llama_index.embeddings.openai import OpenAIEmbedding

    return OpenAIEmbedding(
        model_name=settings.embed_model,
        api_base=settings.base_url,
        api_key=settings.api_key,
        embed_batch_size=batch_size,
        timeout=120.0,
        max_retries=3,
    )


def _load_index(settings, embed_model=None):
    """Build the index over the persisted stores.

    Both stores are required: the vector store returns node ids only, so
    without the docstore the retriever has no text to return.
    """
    from llama_index.core import (
        Settings,
        StorageContext,
        VectorStoreIndex,
        load_index_from_storage,
    )
    from llama_index.core.storage.docstore import SimpleDocumentStore
    from llama_index.core.vector_stores import SimpleVectorStore

    storage_dir: Path = settings.storage_dir
    if not storage_dir.exists():
        raise FileNotFoundError(
            f"no index at {storage_dir} — run: python build_knowledge_index.py"
        )

    Settings.embed_model = embed_model or make_embed_model(settings)

    storage_context = StorageContext.from_defaults(
        persist_dir=str(storage_dir),
        docstore=SimpleDocumentStore.from_persist_dir(str(storage_dir)),
        vector_store=SimpleVectorStore.from_persist_dir(str(storage_dir)),
    )
    index = load_index_from_storage(storage_context)
    if not index.index_struct.nodes_dict:
        raise ValueError("index is empty — rebuild it with --rebuild")
    return index
