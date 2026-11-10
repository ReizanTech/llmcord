# Operations

Install, run, and diagnose the bot.

## Requirements

- Python 3.13 (developed on 3.13.8)
- The packages in `requirements.txt`
- A Discord application with a bot token
- An OpenAI-compatible chat endpoint and an OpenAI-compatible embedding
  endpoint

`requirements.txt`:

```
discord.py>=2.6.0
httpx
openai
python-dotenv
pyyaml

# RAG support knowledge base
llama-index-core>=0.14.0
llama-index-embeddings-openai>=0.5.0
```

Versions installed and tested here: discord.py 2.7.1, openai 3.46.0,
llama-index-core 0.14.25, pyyaml 6.0.3, httpx 0.28.1.

## Install

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Then create `.env` next to `config.yaml`:

```ini
DISCORD_BOT_TOKEN=...
DISCORD_CLIENT_ID=...
SOVEREIGN_API_KEY=...
```

The token's application id and `DISCORD_CLIENT_ID` must be the same
application, or the invite URL points at a different bot. You can check:

```python
import base64, os, re
env = dict(re.match(r"^([A-Z0-9_]+)=(.*)$", l).groups()
           for l in open(".env", encoding="utf-8").read().splitlines()
           if re.match(r"^[A-Z0-9_]+=", l))
first = env["DISCORD_BOT_TOKEN"].split(".")[0]
first += "=" * (-len(first) % 4)
print(base64.urlsafe_b64decode(first).decode() == env["DISCORD_CLIENT_ID"])
```

## Build the index

Required once before the first run, and again after editing the knowledge
base:

```bash
.venv/Scripts/python.exe build_knowledge_index.py
```

Use `--rebuild` after deleting or renaming a `.md` file — an incremental build
keeps the removed file's chunks. See
[KNOWLEDGE_BASE.md](KNOWLEDGE_BASE.md).

The build needs network access to the embedding endpoint. Measured on the
current single-file knowledge base (33 chunks): about 4 s when re-embedding
everything and under a second when nothing changed, rising to roughly 20 s
when the embedding endpoint is slow.

## Run

The bot must be started from its own directory: `config.yaml` is opened by
relative path, so starting from a parent folder fails with
`FileNotFoundError: config.yaml`.

```bash
.venv/Scripts/python.exe llmcord.py
```

On Windows the repository includes helper scripts. They are local conveniences
and are **not** tracked by git (`.gitignore` excludes them):

| Script | Purpose |
| --- | --- |
| `run.bat` | Start in a visible window; refuses to start if an instance is already running |
| `run-bot.bat` | Start loop used by `run-hidden.vbs`; restarts the bot 5s after it exits |
| `run-hidden.vbs` | Start `run-bot.bat` with no window |
| `stop-bot.bat` | Kill the restart loop and the bot process |

Never run two instances on one token: each answers every message, so users
get duplicate replies.

Successful startup log:

```
INFO: logging in using static token
INFO: Shard ID None has connected to Gateway (Session ID: ...)
INFO: BOT INVITE URL: https://discord.com/oauth2/authorize?client_id=...&permissions=412317191168&scope=bot
INFO: Knowledge base ready: .../knowledge_base
```

If the last line is missing, the knowledge base did not load — see below.

## Docker

```bash
docker compose up
```

The image installs `requirements.txt`, then copies `llmcord.py`,
`config.yaml`, `build_knowledge_index.py`, `rag/` and `knowledge_base/`
(`Dockerfile`). Compose runs with `network_mode: host` and mounts the project
read-only at `/app` (`docker-compose.yaml`), which means:

- The container cannot write `storage/`. Build the index on the host first.
- The image is rebuilt only when you rebuild it; `docker compose up` alone
  reuses the existing image.

To build the index inside the container instead, run
`docker compose run --rm container python build_knowledge_index.py` with the
mount writable.

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests -q
```

12 tests, no Discord and no network. They cover settings parsing, the
missing/incomplete index paths, incremental rebuild, off-topic filtering,
context formatting, and citation numbering.

`pytest` is not in `requirements.txt`; install it separately:
`.venv/Scripts/python.exe -m pip install pytest`.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `401 Unauthorized` at login | Token revoked or reset | Reset the token in the Developer Portal and update `.env` |
| Invite URL names a different bot | `DISCORD_CLIENT_ID` belongs to another application | Set it to the token's application id |
| `Knowledge base unavailable (no index at ...)` | `storage/` missing | Run `build_knowledge_index.py` |
| `Knowledge base unavailable (index is empty ...)` | Index has no nodes | Run `build_knowledge_index.py --rebuild` |
| `no API key for provider '...'` in the log | `api_key_env` variable missing from `.env` | Add it; this error is **not** caught and stops the knowledge base from loading |
| Bot replies with no knowledge | `system_prompt` empty, or `rag.enabled: false` | Retrieval is discarded without a system prompt |
| Answers ignore a newly added file | Index not rebuilt, or `/kb reload` used instead | `/kb reload` re-reads `storage/` only; rebuild the index |
| Deleted section still answers | Incremental build kept its chunks | Rebuild with `--rebuild` |
| `embedding dimension N does not match embed_dim=...` | `rag.embed_model` changed without updating `embed_dim` | Set `embed_dim` to the new model's dimension, then `--rebuild` |
| Two replies per message | Two bot instances | `stop-bot.bat`, then start one |
| `FileNotFoundError: config.yaml` | Started from another directory | `cd` into the project first |

`/kb` (admins only) reports status:

```
/kb              # status
/kb reload:true  # re-read storage/ from disk
```

## Logs

`logging.basicConfig` writes to stderr at INFO level (`llmcord.py:21-24`).
`run.bat`/`run-bot.bat` redirect to `bot.log`, which `.gitignore` excludes.
Useful lines:

```
Message received (user ID: ..., conversation length: ...)
Retrieved N passage(s) for: <question>
HTTP Request: POST .../embeddings "HTTP/1.1 200 OK"
```

`Retrieved 0 passage(s)` on an on-topic question means the threshold or the
chunking needs attention, not that retrieval is broken.

## Related documents

- [ARCHITECTURE.md](ARCHITECTURE.md) — how a message becomes a reply
- [CONFIGURATION.md](CONFIGURATION.md) — every setting and its reload behaviour
- [KNOWLEDGE_BASE.md](KNOWLEDGE_BASE.md) — building and maintaining the index
