# Knowledge Base

The bot answers from `knowledge_base/*.md`. This document covers how the
Markdown becomes retrievable passages, how a question selects them, and how to
update the index.

## Two separate steps

1. **Build** — `build_knowledge_index.py` reads the Markdown, splits it,
   embeds every chunk, and writes the index to `storage/`.
2. **Serve** — `llmcord.py` loads `storage/` at startup and searches it.

The bot does not read `.md` files and does not call the embedding API to build
anything. Editing a file changes nothing until step 1 runs again. Likewise,
`/kb reload: true` only re-runs step 2: it re-reads `storage/`, it does not
re-chunk or re-embed. Verified: adding a new `.md` file and then reloading
leaves the new file invisible.

## Build

```bash
python build_knowledge_index.py            # incremental
python build_knowledge_index.py --rebuild  # wipe storage/ and start over
```

Flags: `--rebuild`, `--config <path>` (default `config.yaml`).

The build prints the files it found, the number of chunks embedded, and where
the index was saved.

### Incremental vs full rebuild

Incremental is the default and is safe for **adding** or **editing** files.
It is not safe for **deleting** them: a deleted file's chunks stay in the
index and keep being returned. Verified: removing `b.md` and running an
incremental build still retrieved `b.md`.

After deleting or renaming a file, use `--rebuild`.

### The dimension guard

After embedding, the builder compares the actual vector length against
`rag.embed_dim` and aborts on a mismatch:

```
embedding dimension N does not match embed_dim=4096.
Update rag.embed_dim in config.yaml, or rerun with --rebuild if you changed models.
```

This catches a changed embedding model before it produces an index whose
vectors cannot be compared with each other.

### Incomplete storage

The builder requires `docstore.json`, `index_store.json` and at least one
`*vector_store.json`. If `storage/` exists but is missing any of them — an
interrupted build, a partially copied folder — it prints
`storage folder is incomplete — starting a fresh index` and rebuilds instead
of crashing.

## Chunking

Two parsers run in order (`build_knowledge_index.py:88-92`):

1. `MarkdownNodeParser` splits on headings and records the heading path in
   `metadata["header_path"]`.
2. `SentenceSplitter` splits any oversize section at
   `chunk_size` / `chunk_overlap` characters.

The embedding model is the pipeline's third transformation; the pipeline does
not embed on its own.

Two consequences for writing documents:

- Headings are chunk boundaries. A section that answers one question should
  sit under its own `###` heading.
- A section longer than `chunk_size` is split, and the split parts compete
  independently at retrieval time. If a step list and its download links land
  in different chunks, a retrieved chunk can contain the steps without the
  links. Raise `chunk_size` or keep sections compact.

`filename_as_id=True` gives documents stable ids, so an unchanged file is not
re-embedded on the next incremental run.

## Retrieval

For each message (`rag/knowledge.py:82-103`):

1. If the index is unavailable or the question is blank, return no passages.
2. Ask the retriever for `top_k` nearest chunks.
3. Drop chunks scoring below `min_score`; keep chunks whose score is `None`.
4. Wrap survivors in `Source(file_name, header_path, text, score)`.

The query is the incoming message with the bot mention removed
(`llmcord.py:289`). Reply-chain history is not searched.

`SimpleVectorStore` scores are cosine similarities. With this knowledge base,
on-topic questions scored about `0.51`–`0.79`, and an off-topic question
("best pizza place in Cairo") scored about `0.25`, which is why `min_score`
defaults to `0.45`.

## Prompt injection

Retrieved passages are numbered and appended under `# Knowledge Base`
(`llmcord.py:304-319`):

```
[1] (file.md › Section › Subsection)
passage text
```

The model is told to cite `[1]`, `[2]`, to match an exact `W`/`E` code, to
reproduce full `https://` links, and to cover every OS branch. The cap is
`max_context_chars`; `format_context` truncates the last passage that would
overflow and appends `…`, and only does so when more than 200 characters of
room remain (`rag/knowledge.py:43-51`).

The whole block is skipped when `system_prompt` is empty — see
[CONFIGURATION.md](CONFIGURATION.md).

## Writing documents

The current knowledge base is
`knowledge_base/GenPatcher_Support_Legionnaire_Generals.md`: 32 sections
covering the FAQ, issues, and the `W0xx` / `E0xx` code explanations.

Guidance that follows from how retrieval works:

- Put the exact code in the heading (`### E101: PowerShell version is not
  supported.`) — codes are strong retrieval terms.
- Keep the source's wording for menu names, file names and versions; the
  prompt tells the model to preserve them.
- Keep the links in the same section as the steps they belong to.
- Write one question per heading, in the language users ask in. Adding the
  user's likely phrasing as search terms inside the section improves matching
  for non-English questions.

## Checking retrieval

The tests cover the retrieval layer without Discord or network:

```bash
python -m pytest tests -q
```

They use `MockEmbedding` and a temporary index, so they verify wiring and
thresholds rather than embedding quality. To check a real question against
the real index:

```python
from pathlib import Path

from rag import KnowledgeBase, RagSettings, get_config

settings = RagSettings.from_config(get_config("config.yaml"), Path("."))
kb = KnowledgeBase.load(settings)
for source in kb.retrieve("ما حل الخطأ E101"):
    print(f"{source.score:.3f} {source.label}")
```

A blank result for an on-topic question usually means `min_score` is too high
or the section was split badly. A blank result for an off-topic question is
correct behaviour.

## Related documents

- [ARCHITECTURE.md](ARCHITECTURE.md) — request flow and degradation paths
- [CONFIGURATION.md](CONFIGURATION.md) — the `rag:` keys and hot reload
- [OPERATIONS.md](OPERATIONS.md) — install, run, troubleshooting
