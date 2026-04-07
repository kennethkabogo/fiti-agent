# Fiti

A Topic-Scoped LLM Knowledge CLI.

Organize your knowledge into explicit, namespaced **vaults**. Ingest raw notes, documents, and links — Fiti uses an LLM to automatically maintain a structured wiki inside each vault, ready to query.

---

## How it works

```mermaid
flowchart LR
    A[Raw files\nnotes / docs / links] -->|fiti ingest| B[(Vault\nraw/)]
    B -->|fiti compile| C[LLM]
    C --> D[(Vault\nwiki/)]
    D -->|fiti ask| E[LLM]
    E --> F[Report / Slides / Chart]
```

---

## Vault structure

Each vault lives at `~/.fiti/topics/<name>/`:

```mermaid
graph TD
    V["~/.fiti/topics/&lt;name&gt;/"]
    V --> R[raw/]
    V --> W[wiki/]
    V --> AS[assets/]
    R --> RP[processed/]
    W --> IDX[INDEX.md]
    W --> C[concepts/]
    W --> S[summaries/]
    W --> Q[queries/]
```

---

## Installation

```bash
pip install .
```

Requires Python 3.11+. No third-party dependencies — pure stdlib.

Set at least one API key:

```bash
export GEMINI_API_KEY=...       # preferred
export ANTHROPIC_API_KEY=...    # fallback
```

---

## Usage

```mermaid
sequenceDiagram
    actor You
    participant CLI as fiti CLI
    participant Vault
    participant LLM

    You->>CLI: fiti new python
    CLI->>Vault: create vault structure

    You->>CLI: fiti use python
    CLI->>Vault: set active topic

    You->>CLI: fiti ingest notes.md
    CLI->>Vault: copy to raw/

    You->>CLI: fiti compile
    CLI->>Vault: read raw files
    CLI->>LLM: summarize + update index
    LLM-->>Vault: write summaries + INDEX.md
    CLI->>Vault: move files to raw/processed/

    You->>CLI: fiti ask "What are the key concepts?"
    CLI->>Vault: gather wiki context
    CLI->>LLM: query with context
    LLM-->>CLI: response
    CLI->>Vault: save to wiki/queries/
```

### Commands

| Command | Description |
|---|---|
| `fiti new <topic>` | Create a new topic vault |
| `fiti use <topic>` | Switch the active topic |
| `fiti status` | Show active topic and pending files |
| `fiti ingest <file>` | Add a raw document to the active topic |
| `fiti compile` | Process uncompiled files with an LLM |
| `fiti ask "<question>"` | Query the wiki and save a response |
| `fiti ask --slides "<question>"` | Output as a Marp slide deck |
| `fiti ask --data "<question>"` | Output as a matplotlib chart script |
| `fiti lint` | Find broken wiki links *(PRO)* |
| `fiti lint --fix` | Auto-fix and rebuild the index *(PRO)* |

---

## Example

```bash
fiti new python
fiti use python

fiti ingest ~/notes/decorators.md
fiti ingest ~/notes/async_patterns.md

fiti compile
# -> Summaries written to wiki/summaries/
# -> INDEX.md updated with new concepts

fiti ask "Explain the difference between @staticmethod and @classmethod"
# -> Saved to wiki/queries/explain_the_difference_be_<ts>.md

fiti ask --slides "Give me an overview of async patterns"
# -> Saved as a Marp presentation
```

---

## Architecture

```mermaid
classDiagram
    class APIClient {
        +gemini_api_key
        +anthropic_api_key
        +call_gemini(prompt) str
        +call_anthropic(prompt, max_tokens) str
        +call(prompt, max_tokens) str
    }
    class CompilerEngine {
        +vault TopicVault
        +summarize_and_compile(file_path)
    }
    class QueryEngine {
        +vault TopicVault
        +execute_query(question, mode) Path
    }
    class LinterEngine {
        +vault TopicVault
        +find_broken_links() List
        +run_health_check(fix) str
    }
    class TopicVault {
        +name str
        +base_dir Path
        +ensure_structure()
        +list_raw_files() List
        +ingest_file(file_path) Path
    }
    class StateManager {
        +state_file Path
        +get_active_topic() str
        +set_active_topic(topic)
    }

    CompilerEngine --> APIClient : uses
    QueryEngine --> APIClient : uses
    LinterEngine --> APIClient : uses
    CompilerEngine --> TopicVault : reads/writes
    QueryEngine --> TopicVault : reads/writes
    LinterEngine --> TopicVault : reads/writes
```

---

## LLM providers

Fiti prefers Gemini when both keys are set. All API calls use secure headers — no keys in URLs.

| Provider | Model | Set via |
|---|---|---|
| Google Gemini | `gemini-2.5-flash` | `GEMINI_API_KEY` |
| Anthropic Claude | `claude-3-5-sonnet-20241022` | `ANTHROPIC_API_KEY` |

---

## PRO features

The `lint` command requires a PRO license key:

```bash
export FITI_PRO_KEY=...
fiti lint
fiti lint --fix
```
