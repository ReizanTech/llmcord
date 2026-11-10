# Configuration

Every setting lives in `config.yaml`. A setting named `x` can instead be read
from the environment as `x_env: ENV_VAR_NAME`; `resolve_env` in
`rag/settings.py` turns the `_env` key into the resolved value.

## Hot reload: what takes effect when

This is the most common source of confusion, so it comes first.

| Setting | Takes effect |
| --- | --- |
| `bot_token`, `client_id`, `status_message` | Restart required (read once at import, `llmcord.py:37-48`) |
| `models` (default model), `providers` | Restart required for the default; `/model` switches at runtime |
| `system_prompt`, `max_text`, `max_images`, `max_messages`, `use_plain_responses`, `allow_dms`, `permissions` | Next message — `on_message` re-parses `config.yaml` every time (`llmcord.py:161`) |
| `rag.*` (all keys) | Restart, or `/kb reload: true` — see below |
| `rag.enabled` | Restart, or `/kb reload: true` |

`rag.*` is the exception to hot reloading: `load_knowledge_base` reads the
module-level `config`, which was parsed once at import (`llmcord.py:37`,
`136`). Editing `rag.top_k` on disk does **not** change the running bot until
`/kb reload: true` re-reads it — and even then it re-reads that same
import-time snapshot, so a changed `rag.*` value only applies after a restart.
Verified: changing `rag.top_k` in the file and calling the reload path leaves
`knowledge_base.settings.top_k` unchanged.

## Discord settings

| Setting | Default | Notes |
| --- | --- | --- |
| `bot_token` | — | Token from the Discord Developer Portal. Enable **MESSAGE CONTENT INTENT** for the bot. |
| `client_id` | — | Application id. Must belong to the **same** application as `bot_token`; otherwise the invite URL points at a different bot. |
| `status_message` | `github.com/jakobdylanc/llmcord` | Truncated to 128 characters (`llmcord.py:47`). |
| `max_text` | `100000` | Characters kept per message, including text attachments. |
| `max_images` | `5` | Images per message; forced to `0` unless the model name matches a vision tag. |
| `max_messages` | `25` | Reply-chain length; the oldest messages are dropped. |
| `use_plain_responses` | `false` | Plain text instead of embeds. Splits more often than embeds — see below. |
| `allow_dms` | `true` | When `false`, only admins may DM the bot. |

On message length: embeds are split at `4096 - len(" ⚪") = 4094` characters
(`llmcord.py:333`); plain responses at 4000 (`llmcord.py:331`). Plain
responses have the **smaller** limit, so they split more often — they do not
raise it.

## Permissions

```yaml
permissions:
  users:
    admin_ids: []
    allowed_ids: []
    blocked_ids: []
  roles: { allowed_ids: [], blocked_ids: [] }
  channels: { allowed_ids: [], blocked_ids: [] }
```

- Empty `allowed_ids` means "allow everyone" in that category. An empty
  `allowed_ids` for roles **and** users combined means all users are allowed.
- `admin_ids` bypass the **user and role** allow lists and can switch models
  with `/model` or manage the knowledge base with `/kb`. Admins do **not**
  bypass the channel allow list: `is_good_channel` checks
  `user_is_admin` only in its DM branch (`llmcord.py:178`), so an admin
  posting in a channel outside `channels.allowed_ids` gets no reply.
- Blocked entries win over allowed ones.
- Role and channel permissions do not apply to DMs.
- Channel matching also considers the parent channel and category id, so a
  category id in `channels.allowed_ids` covers its channels and threads.

## Providers

```yaml
providers:
  sovereign:
    base_url: https://backend.sovereigneg.com/v1
    api_key_env: SOVEREIGN_API_KEY
```

A provider is any OpenAI `/v1/chat/completions`-compatible endpoint. Optional
keys: `api_key`, `api_key_env`, `extra_headers`, `extra_query`, `extra_body`.
When a provider has no API key, the client is created with
`sk-no-key-required` (`llmcord.py:190`), which suits local servers.

`config.yaml` ships entries for `openrouter`, `openai`, `x-ai`, `google`,
`azure-openai`, `lmstudio`, `ollama` and `vllm`.

## Models

```yaml
models:
  sovereign/qwen3.7-flash:vision:
    enable_thinking: true
    thinking_budget: 4096
```

- Format is `<provider>/<model>`, and the first entry is the default at
  startup (`llmcord.py:38`).
- Anything under a model entry is sent as `extra_body` to the provider, merged
  over the provider's own `extra_body` (`llmcord.py:197`).
- A `:vision` suffix is stripped before the model name is sent
  (`llmcord.py:185`) and marks the model as accepting images. Other names
  enable images when they contain a tag from `VISION_MODEL_TAGS`
  (`llmcord.py:26`): `chat-latest`, `claude`, `gemini`, `gemma`, `gpt-4`,
  `gpt-5`, `gpt-latest`, `grok-4`, `llama`, `vision`, `vl`.

## System prompt

Free text. `{date}` and `{time}` are replaced per message
(`llmcord.py:302`).

Two behaviours depend on it:

- **No `system_prompt` means no knowledge-base context.** The retrieval block
  is nested inside `if system_prompt := ...` (`llmcord.py:299`), so retrieved
  passages are dropped when the prompt is empty.
- The prompt is the place to describe the `<@ID>: message` prefix the bot adds
  to user messages (`llmcord.py:237`).

## RAG settings

```yaml
rag:
  enabled: true
  provider: sovereign
  knowledge_dir: knowledge_base
  storage_dir: storage
  embed_model: qwen3-embedding-8b
  embed_dim: 4096
  chunk_size: 800
  chunk_overlap: 120
  top_k: 5
  max_context_chars: 6000
  min_score: 0.45
```

| Key | Default | Effect |
| --- | --- | --- |
| `enabled` | `true` | `false` disables retrieval entirely. |
| `provider` | `sovereign` | Name of an entry under `providers`; embeddings use its `base_url` and key, so the secret is not duplicated. |
| `knowledge_dir` | `knowledge_base` | Scanned recursively for `*.md` by the builder. |
| `storage_dir` | `storage` | Where the index is persisted. |
| `embed_model` | `qwen3-embedding-8b` | Sent as `model_name` to the embedding endpoint. |
| `embed_dim` | `4096` | Checked after embedding; a mismatch aborts the build. |
| `chunk_size` / `chunk_overlap` | `800` / `120` | Characters, applied by `SentenceSplitter` after Markdown splitting. |
| `top_k` | `5` | Passages requested per message. |
| `max_context_chars` | `6000` | Cap on retrieved text appended to the system prompt. |
| `min_score` | `0.45` | Passages below this similarity are dropped. |

`min_score` compares against the retriever's score, which for
`SimpleVectorStore` is cosine similarity. A node whose score is `None` is
kept (`rag/knowledge.py:102`).

Raising `min_score` makes the bot answer "I don't know" more often; lowering
it injects weaker matches. `0.45` was chosen because off-topic questions
scored about `0.25` against this knowledge base while real questions scored
`0.51` and above.

## Example `.env`

```ini
DISCORD_BOT_TOKEN=...
DISCORD_CLIENT_ID=...
SOVEREIGN_API_KEY=...
```

`llmcord.py` calls `load_dotenv()` at import (`llmcord.py:19`) and
`build_knowledge_index.py` loads `.env` from its own directory
(`build_knowledge_index.py:22`), so both the bot and the builder see the same
secrets. Never commit `.env`; `.gitignore` excludes it.

## Related documents

- [ARCHITECTURE.md](ARCHITECTURE.md) — request flow and component map
- [KNOWLEDGE_BASE.md](KNOWLEDGE_BASE.md) — chunking, retrieval, updating the index
- [OPERATIONS.md](OPERATIONS.md) — install, run, Docker, troubleshooting
