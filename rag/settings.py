"""Config loading shared by the bot and the index builder.

`resolve_env` turns any `*_env` key into its resolved value, so
`api_key_env: SOVEREIGN_API_KEY` becomes `api_key: <secret from .env>`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def resolve_env(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            key.removesuffix("_env"): os.environ.get(value) if key.endswith("_env") else resolve_env(value)
            for key, value in node.items()
        }
    return node


def get_config(filename: str = "config.yaml") -> dict[str, Any]:
    with open(filename, encoding="utf-8") as file:
        return resolve_env(yaml.safe_load(file))


@dataclass(frozen=True)
class RagSettings:
    """Everything the knowledge base needs, resolved from the `rag:` section.

    The provider is reused rather than duplicated: `rag.provider` names an
    entry under `providers:`, so the embedding calls go to the same endpoint
    and key the chat model already uses.
    """

    knowledge_dir: Path
    storage_dir: Path
    base_url: str
    api_key: str
    embed_model: str = "qwen3-embedding-8b"
    embed_dim: int = 4096
    chunk_size: int = 800
    chunk_overlap: int = 120
    top_k: int = 5
    max_context_chars: int = 6000
    # Below this cosine similarity a passage is treated as irrelevant. Without
    # it, an off-topic question still pulls in top-k passages and the model
    # gets context that only confuses it.
    min_score: float = 0.45

    @classmethod
    def from_config(cls, config: dict[str, Any], root: Path) -> RagSettings | None:
        """Return settings, or None when RAG is disabled."""
        rag = config.get("rag") or {}
        if not rag.get("enabled", True):
            return None

        provider_name = rag.get("provider", "sovereign")
        provider = (config.get("providers") or {}).get(provider_name) or {}

        base_url = provider.get("base_url")
        if not base_url:
            raise ValueError(f"rag.provider '{provider_name}' has no base_url under providers:")

        api_key = provider.get("api_key")
        if not api_key:
            raise ValueError(
                f"no API key for provider '{provider_name}' — check its api_key_env in config.yaml "
                "and make sure the variable is set in .env"
            )

        return cls(
            knowledge_dir=root / rag.get("knowledge_dir", "knowledge_base"),
            storage_dir=root / rag.get("storage_dir", "storage"),
            base_url=base_url,
            api_key=api_key,
            embed_model=rag.get("embed_model", cls.embed_model),
            embed_dim=int(rag.get("embed_dim", cls.embed_dim)),
            chunk_size=int(rag.get("chunk_size", cls.chunk_size)),
            chunk_overlap=int(rag.get("chunk_overlap", cls.chunk_overlap)),
            top_k=int(rag.get("top_k", cls.top_k)),
            max_context_chars=int(rag.get("max_context_chars", cls.max_context_chars)),
            min_score=float(rag.get("min_score", cls.min_score)),
        )
