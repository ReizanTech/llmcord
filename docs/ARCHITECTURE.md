# Architecture

How this bot works end to end: a Discord support bot that answers from a
Markdown knowledge base instead of the model's memory.

## What runs

| Process | Entry point | Purpose |
| --- | --- | --- |
| Bot | `llmcord.py` | Connects to Discord, answers messages |
| Index builder | `build_knowledge_index.py` | Embeds `knowledge_base/*.md` into `storage/` |
| Tests | `tests/test_rag.py` | Verifies the RAG layer without Discord or network |

The bot and the builder are separate: the bot **never** reads the Markdown
files or calls the embedding API. It only loads the persisted index from
`storage/`. That is why editing a `.md` file has no effect until the builder
runs again.

## Component map

```
llmcord.py                 Discord events, message chain, streaming replies
  ├── rag/settings.py      config parsing: RagSettings, get_config, resolve_env
  └── rag/knowledge.py     KnowledgeBase (load + retrieve), format_context, Source
build_knowledge_index.py   document loading, chunking, embedding, persistence
knowledge_base/*.md        the source of truth for support answers
storage/                   persisted vector index (generated, not committed)
config.yaml                settings for the bot and the `rag:` section
```

## Request flow

`on_message` in `llmcord.py` runs these steps in order:

1. **Accept or ignore** (`llmcord.py:155`) — ignore bot authors, and ignore
   non-DM messages that do not mention the bot.
2. **Authorise** (`llmcord.py:158-182`) — resolve the author's roles and the
   channel's ids, then apply `permissions.users` / `roles` / `channels`
   allow/block lists from `config.yaml`.
3. **Resolve the model** (`llmcord.py:184-199`) — split `curr_model` on the
   first `/` into provider and model, read that provider's `base_url` and
   `api_key`, and merge `extra_headers` / `extra_query` / `extra_body`.
4. **Build the conversation** (`llmcord.py:210-281`) — walk reply references
   backwards, up to `max_messages`, caching each message in `msg_nodes`.
5. **Retrieve** (`llmcord.py:285-297`) — if the knowledge base is available,
   embed the incoming text (minus the bot mention) and fetch up to `top_k`
   passages. Runs in a worker thread because retrieval blocks.
6. **Compose the system prompt** (`llmcord.py:299-321`) — substitute
   `{date}` / `{time}`, then append a `# Knowledge Base` section when passages
   were found.
7. **Stream the answer** (`llmcord.py:344-390`) — consume the completion as a
   stream and edit Discord messages in place, splitting when a message would
   exceed 4094 characters (embeds) or 4000 (plain responses).

## Where retrieval is wired in

Retrieval depends on `system_prompt` being non-empty. The context is appended
inside `if system_prompt := config.get("system_prompt"):` (`llmcord.py:299`),
so with no `system_prompt` in `config.yaml`, retrieved passages are discarded
and the bot answers from the model alone. Keep a system prompt when you rely
on the knowledge base.

The injected section also carries answering rules — cite passages as `[1]`,
`[2]`, match an exact `W`/`E` code, reproduce full `https://` links, and cover
every OS branch. Those rules live in the prompt, not in the knowledge base
file, so they apply to every document.

Retrieval uses the current message only. The surrounding reply chain is
conversation history for the model; it is not part of the search query.

## Degradation

The knowledge base is optional at runtime:

- Missing `storage/` → `KnowledgeBase.load` records an `unavailable_reason`
  and the bot answers without context (`rag/knowledge.py:139-143`).
- A retrieval exception → logged, a warning is shown to the user, the reply
  still happens (`llmcord.py:294-297`).
- `rag.enabled: false` → `RagSettings.from_config` returns `None`, and
  `knowledge_base` stays `None` (`llmcord.py:136-140`).

One configuration error is **not** caught: a missing provider API key raises
`ValueError` from `RagSettings.from_config`, which is called outside the
`try` in `load_knowledge_base` (`llmcord.py:136`). The exception propagates
out of `on_ready`, so the bot connects to Discord but the knowledge base never
loads. Check the log for `no API key for provider` after changing providers.

## Storage layout

`build_knowledge_index.py` persists five files into `storage/`:

| File | Written by | Needed to load |
| --- | --- | --- |
| `docstore.json` | docstore | yes |
| `index_store.json` | index struct | yes |
| `default__vector_store.json` | vector store | yes |
| `image__vector_store.json` | vector store | no (empty) |
| `graph_store.json` | storage context | no (empty) |

The vector-store filename is derived from the vector store's id, so the
builder detects it with `*vector_store.json` rather than a fixed name
(`build_knowledge_index.py:60-72`). Both the docstore and the vector store are
required: the vector store returns node ids only, and without the docstore the
retriever has no text to return.

## Concurrency

- `msg_nodes` is a global dict guarded by a per-message `asyncio.Lock`, capped
  at `MAX_MESSAGE_NODES = 500` (`llmcord.py:34`, `400-403`).
- Retrieval and index loading go through `asyncio.to_thread`, so neither
  blocks the event loop (`llmcord.py:142`, `292`).
- One bot instance only. Two instances on the same token produce duplicate
  replies; `run.bat` refuses to start a second one.

## Related documents

- [CONFIGURATION.md](CONFIGURATION.md) — every setting, its default, and whether it hot-reloads
- [KNOWLEDGE_BASE.md](KNOWLEDGE_BASE.md) — chunking, retrieval, and updating the index
- [OPERATIONS.md](OPERATIONS.md) — install, run, Docker, troubleshooting, tests
