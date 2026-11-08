"""RAG support: a Markdown knowledge base the bot retrieves from before replying."""

from rag.knowledge import KnowledgeBase, Source, format_context
from rag.settings import RagSettings, get_config, resolve_env

__all__ = [
    "KnowledgeBase",
    "RagSettings",
    "Source",
    "format_context",
    "get_config",
    "resolve_env",
]
