"""Build or refresh the knowledge base index used by the bot.

    python build_knowledge_index.py            # add/update changed .md files
    python build_knowledge_index.py --rebuild  # wipe the index and rebuild
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from rag.settings import RagSettings, get_config

ROOT = Path(__file__).resolve().parent

# Same as the bot: secrets come from .env next to config.yaml.
load_dotenv(ROOT / ".env")


def load_documents(knowledge_dir: Path):
    from llama_index.core import SimpleDirectoryReader

    if not knowledge_dir.exists():
        raise SystemExit(f"knowledge base folder not found: {knowledge_dir}")

    files = sorted(knowledge_dir.rglob("*.md"))
    if not files:
        raise SystemExit(f"no .md files in {knowledge_dir}")

    print(f"found {len(files)} .md file(s):")
    for path in files:
        print(f"  - {path.relative_to(knowledge_dir)}")

    return SimpleDirectoryReader(
        input_dir=str(knowledge_dir),
        recursive=True,
        required_exts=[".md"],
        # Stable ids, so the docstore recognises unchanged files instead of
        # re-embedding the whole knowledge base on every run.
        filename_as_id=True,
    ).load_data(show_progress=False)


def index_documents(documents, settings: RagSettings, embed_model=None) -> int:
    from llama_index.core import Settings, StorageContext, VectorStoreIndex, load_index_from_storage
    from llama_index.core.ingestion import IngestionPipeline
    from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
    from llama_index.core.storage.docstore import SimpleDocumentStore
    from llama_index.core.vector_stores import SimpleVectorStore

    from rag.knowledge import make_embed_model

    Settings.embed_model = embed_model or make_embed_model(settings, batch_size=16)

    storage_dir = settings.storage_dir
    # A persisted index needs the docstore, the index struct and the vector
    # store. LlamaIndex names the vector store file after its vector_store_id
    # (default: "default__vector_store.json"), so match it by suffix rather
    # than assuming a fixed name. A folder left behind by an interrupted or
    # partial build would otherwise crash the loader.
    has_index = (
        storage_dir.exists()
        and (storage_dir / "docstore.json").exists()
        and (storage_dir / "index_store.json").exists()
        and any(storage_dir.glob("*vector_store.json"))
    )
    if has_index:
        docstore = SimpleDocumentStore.from_persist_dir(str(storage_dir))
        vector_store = SimpleVectorStore.from_persist_dir(str(storage_dir))
        print("existing index found — updating incrementally")
    else:
        if storage_dir.exists():
            print("storage folder is incomplete — starting a fresh index")
        docstore = SimpleDocumentStore()
        vector_store = SimpleVectorStore()

    storage_context = StorageContext.from_defaults(
        persist_dir=str(storage_dir) if has_index else None,
        docstore=docstore,
        vector_store=vector_store,
    )

    pipeline = IngestionPipeline(
        transformations=[
            # Splits on headings and keeps the heading path in metadata.
            MarkdownNodeParser(),
            SentenceSplitter(
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
            ),
            # The pipeline does not embed on its own: the embedding model has
            # to be one of the transformations.
            Settings.embed_model,
        ],
        docstore=docstore,
        vector_store=vector_store,
    )

    started = time.time()
    new_nodes = pipeline.run(documents=documents, show_progress=True)
    elapsed = time.time() - started

    if new_nodes:
        print(f"embedded {len(new_nodes)} new chunk(s) in {elapsed:.1f}s")

        actual_dim = len(new_nodes[0].embedding or [])
        if actual_dim != settings.embed_dim:
            raise SystemExit(
                f"embedding dimension {actual_dim} does not match embed_dim={settings.embed_dim}.\n"
                "Update rag.embed_dim in config.yaml, or rerun with --rebuild if you changed models."
            )

        # The vector store and docstore already hold the nodes; this records
        # them in the index struct. The retriever filters vector hits by it,
        # so without it retrieval silently returns nothing.
        if storage_context.index_store.index_structs():
            index = load_index_from_storage(storage_context)
        else:
            index = VectorStoreIndex([], storage_context=storage_context)
        index.insert_nodes(list(new_nodes))
    else:
        print("no new or changed files — index is up to date")

    storage_context.persist(persist_dir=str(storage_dir))
    return len(new_nodes)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Build the bot's knowledge index")
    parser.add_argument("--rebuild", action="store_true", help="wipe the index and rebuild")
    parser.add_argument("--config", default="config.yaml", help="config file to read")
    args = parser.parse_args()

    settings = RagSettings.from_config(get_config(args.config), ROOT)
    if settings is None:
        raise SystemExit("rag.enabled is false in config.yaml")

    if args.rebuild and settings.storage_dir.exists():
        shutil.rmtree(settings.storage_dir)
        print("removed the old index (--rebuild)")

    documents = load_documents(settings.knowledge_dir)
    index_documents(documents, settings)
    print(f"index saved to: {settings.storage_dir}")


if __name__ == "__main__":
    main()
