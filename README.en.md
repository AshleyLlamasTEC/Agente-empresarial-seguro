# Secure Enterprise Agent

A **100% local** AI agent to analyze and fix code in a **working copy**, with
verifiable controls and an audit log. No cloud, no production, no external
tooling.

```
                       +-------------------------------------------+
                       |             WORK MACHINE                  |
                       |                                           |
  Operator  <--------> |  agent/cli.py  <---- 127.0.0.1 ----> Ollama
   (human)   approves  |        |                                  |
                       |        +--> Sandbox (workspace only)       |
                       |        +--> Policy (whitelist)             |
                       |        +--> DLP (secret redaction)         |
                       |        +--> Hash-chained log (audit)       |
                       |                                           |
                       |  No VPN | No corporate net | No production |
                       +-------------------------------------------+
```

## What it does

- **`consulta` profile** (read-only): finds defects, explains code and proposes
  fixes. It cannot write files or run commands.
- **`desarrollo` profile** (read/write): applies changes **with your approval**
  and runs whitelisted commands.
- **`datos` profile** (local copy): queries a **local** database (SQLite or MySQL
  on `127.0.0.1`), read-only by default and with approval.
- **Rollback**: undoes a session's writes from the audit log backups, checking the
  hash before and after.

## Requirements

- Python 3.10+ (standard library only).
- [Ollama](https://ollama.com/download) with a local model:
  `ollama pull qwen2.5-coder:7b`

## Quick start

```bash
# 1. Compliance check (runs nothing)
python -m agent.cli doctor --profile consulta --workspace C:\work\project-copy

# 2. Read-only analysis
python -m agent.cli ask --profile consulta --workspace C:\work\project-copy \
  "Review the project, list defects and propose fixes"

# 3. Fix with approval on every change
python -m agent.cli ask --profile desarrollo --workspace C:\work\project-copy \
  "Fix the average() defect in app.js"

# 4. Verify the audit log was not altered
python -m agent.cli verify-audit --file C:\work\agent-audit\<file>.jsonl

# 5. Undo the last session's writes (from backups)
python -m agent.cli rollback --workspace C:\work\project-copy --list
python -m agent.cli rollback --workspace C:\work\project-copy
```

Without a task, `ask` goes interactive. `--dry-run` simulates everything without
writing, running or touching the database.

## First use: agent identity

The agent **starts blank**: no name, no knowledge of the user. Define it once:

```bash
python -m agent.cli setup
```

`setup` stores `identity.json` at the repo root. That file is private: it is in
`.gitignore` and is **not** uploaded. Only the empty template
`identity.example.json` ships in the repo. Default tone: **respectful and calm
(Zen)**.

## Useful flags

| Flag | Effect |
|---|---|
| `--dry-run` | Simulate: no writes, no commands, no database access |
| `--yes` | Skip human approval (recommended only with `--dry-run`) |
| `--no-write` | Disable file writing |
| `--no-db` | Disable database access |
| `--db-write` | Allow writes to the local database (with approval) |
| `--db-ddl` | Allow DDL (CREATE/DROP/ALTER) on the local database |
| `--model` | Ollama model to use for this session |

## Security controls

| # | Control | Implementation |
|---|---------|----------------|
| 1 | No cloud access | HTTP client only accepts `127.0.0.1`/`localhost` (`agent/ollama_client.py`) |
| 2 | No production access | Denylist for `ssh`, `curl`, `mysql`, `kubectl`, `aws`, `deploy`, `migrate`, etc. |
| 3 | Workspace confinement | Paths resolved and validated; `..`, absolute, UNC and `~` blocked (`agent/sandbox.py`) |
| 4 | No command chaining | `; & | $ > <` and newlines are forbidden (`agent/policy.py`) |
| 5 | Command whitelist | Only the profile's declared commands run |
| 6 | No installing dependencies | `npm install`, `pip install`, etc. blocked |
| 7 | No destructive commands | `rm`, `del`, `mv`, `git reset`, `git push` blocked |
| 8 | Credential protection | `.env`, `*.pem`, `*.key`, `id_rsa` cannot be read (`agent/dlp.py`) |
| 9 | Secret redaction | Passwords, tokens and keys are redacted before reaching the model |
| 10 | Human approval | Every write and command needs your `y/N` |
| 11 | Automatic backup | Each modified file is copied first (`audit/backups/`) |
| 12 | Sanitized environment | Commands receive only safe environment variables |
| 13 | Hash-chained log | Each record carries the previous hash; tampering breaks the chain |
| 14 | Deny by default | Anything not explicitly allowed is denied |
| 15 | Local-only database | Only `127.0.0.1`/`localhost`/`::1`; one statement, no comments, no DDL by default |
| 16 | Verified rollback | Restores backups inside the workspace and checks hashes |
| 17 | Private identity | `identity.json` stays local; starts blank |

## Structure

```
agent/                Core package (cli, config, identity, policy, sandbox, dlp,
                      db, rollback, ollama_client, tools, agent loop, audit)
profiles/             consulta.json, desarrollo.json, datos.json
identity.example.json Identity template (identity.json is private)
tests/                98 automated tests
docs/                 Policy, threats, install, checklist, mapping, models
opencode-integration/ Equivalent opencode profiles (optional)
examples/demo-proyecto/ Project with defects for safe testing
```

## Tests

```bash
python -m unittest discover -s tests -t . -v
```

## Audit documentation

Everything under `docs/` is written in Spanish (the operating environment's
language): security policy, threat model, controls mapping, install guide,
audit checklist, use manual and local-models guide.

## Honest limitations

This agent is **not an OS-level sandbox**. The whitelist reduces risk, but the
commands it runs (e.g. `npm test`) can execute arbitrary project code. Real
isolation must come from the environment: no VPN, no production credentials and
always a copy. See `docs/MODELO_DE_AMENAZAS.md`, "Riesgos residuales".
