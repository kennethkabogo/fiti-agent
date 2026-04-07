import json
import re
import time
import urllib.request
import urllib.error
from pathlib import Path
from fiti.api_client import APIClient
from fiti.compiler import CompilerEngine
from fiti.query import QueryEngine

TOOLS = [
    {
        "name": "list_vault_files",
        "description": "List files in a section of the active vault.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["raw", "summaries", "concepts", "queries"],
                    "description": "Which vault section to list.",
                }
            },
            "required": ["category"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a file inside the vault. Path must be relative to the vault root (e.g. 'wiki/summaries/foo_summary.md').",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path within the vault.",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "ingest_text",
        "description": "Write raw text content into the vault's raw/ directory so it can be compiled.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Text content to ingest."},
                "filename": {"type": "string", "description": "Filename to save as (e.g. 'note.md'). Must end in .md or .txt."},
            },
            "required": ["content", "filename"],
        },
    },
    {
        "name": "compile_pending",
        "description": "Run the LLM compiler on all pending raw files to generate summaries and update the index.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "query_vault",
        "description": "Query the vault knowledge base and save a response file.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Question to ask."},
                "mode": {
                    "type": "string",
                    "enum": ["report", "slides", "data"],
                    "description": "Output format.",
                },
            },
            "required": ["question", "mode"],
        },
    },
    {
        "name": "write_concept",
        "description": "Write a concept file directly to wiki/concepts/.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Concept title (used as filename)."},
                "content": {"type": "string", "description": "Markdown content."},
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "fetch_url",
        "description": "Fetch content from an HTTPS URL and ingest it as a raw file.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "HTTPS URL to fetch."},
                "filename": {"type": "string", "description": "Filename to save as (e.g. 'article.md')."},
            },
            "required": ["url", "filename"],
        },
    },
]

_MAX_READ_CHARS = 10_000
_MAX_INGEST_CHARS = 1_000_000
_FETCH_TIMEOUT = 10
_FETCH_MAX_BYTES = 1_000_000


class AgentExecutor:
    def __init__(self, vault, client: APIClient):
        self.vault = vault
        self.client = client
        self._dispatch = {
            "list_vault_files": self._list_vault_files,
            "read_file": self._read_file,
            "ingest_text": self._ingest_text,
            "compile_pending": self._compile_pending,
            "query_vault": self._query_vault,
            "write_concept": self._write_concept,
            "fetch_url": self._fetch_url,
        }

    @property
    def sessions_dir(self) -> Path:
        return self.vault.base_dir / "agent_sessions"

    def list_sessions(self) -> list:
        """Return summary of saved sessions, newest first."""
        if not self.sessions_dir.exists():
            return []
        sessions = []
        for f in sorted(self.sessions_dir.glob("*.json"), reverse=True):
            if f.is_symlink():
                continue
            try:
                data = json.loads(f.read_text())
                sessions.append({
                    "id": f.stem,
                    "goal": data.get("goal", ""),
                    "steps": len([m for m in data.get("messages", []) if m.get("role") == "assistant"]),
                })
            except (json.JSONDecodeError, OSError):
                pass
        return sessions

    def run(self, goal: str, max_iterations: int = 10, resume_id: str | None = None) -> str:
        system = (
            f"You are an autonomous agent managing the '{self.vault.name}' knowledge vault. "
            "Use the provided tools to accomplish the user's goal step by step. "
            "Think carefully before each tool call. When the goal is complete, "
            "provide a final summary of what was accomplished."
        )

        if resume_id:
            session_file = self.sessions_dir / f"{resume_id}.json"
            if session_file.exists() and not session_file.is_symlink():
                try:
                    data = json.loads(session_file.read_text())
                    messages = data["messages"]
                    messages.append({"role": "user", "content": goal})
                    print(f"  [agent] Resuming session {resume_id} ({len(messages)-1} prior messages)")
                except (json.JSONDecodeError, KeyError):
                    print(f"  [agent] Could not load session {resume_id!r}, starting fresh.")
                    messages = [{"role": "user", "content": goal}]
            else:
                print(f"  [agent] Session {resume_id!r} not found, starting fresh.")
                messages = [{"role": "user", "content": goal}]
        else:
            messages = [{"role": "user", "content": goal}]

        final_text = "Max iterations reached without completing the goal."

        for iteration in range(max_iterations):
            response = self.client.call_with_tools(messages, TOOLS, system=system)

            if response["text"]:
                print(f"  [agent] {response['text'][:200]}")

            if response["stop_reason"] == "end_turn":
                final_text = response["text"] or "(No response)"
                messages = response["raw_messages"]
                break

            tool_calls = response["tool_calls"]
            results = []
            for tc in tool_calls:
                name = tc["name"]
                args = tc["input"]
                print(f"  [tool] {name}({json.dumps(args, ensure_ascii=False)[:120]})")
                if name in self._dispatch:
                    result = self._dispatch[name](**args)
                else:
                    result = {"error": f"Unknown tool: {name}"}
                print(f"  [tool] -> {str(result)[:120]}")
                results.append(json.dumps(result))

            messages = self.client.inject_tool_results(response["raw_messages"], tool_calls, results)

        # Persist session
        self.sessions_dir.mkdir(exist_ok=True)
        session_id = str(int(time.time()))
        session_file = self.sessions_dir / f"{session_id}.json"
        try:
            session_file.write_text(json.dumps({
                "goal": goal,
                "messages": messages,
                "timestamp": int(time.time()),
            }, indent=2))
            session_file.chmod(0o600)
            print(f"  [agent] Session saved as {session_id}")
        except OSError:
            pass

        return final_text

    # ── Tool implementations ───────────────────────────────────────────────

    def _list_vault_files(self, category: str) -> dict:
        dirs = {
            "raw": self.vault.raw_dir,
            "summaries": self.vault.wiki_summaries_dir,
            "concepts": self.vault.wiki_concepts_dir,
            "queries": self.vault.wiki_queries_dir,
        }
        target = dirs.get(category)
        if target is None:
            return {"error": f"Unknown category: {category!r}"}
        if not target.exists():
            return {"files": []}
        files = [p.name for p in target.iterdir() if p.is_file() and not p.is_symlink()]
        return {"files": sorted(files)}

    def _read_file(self, path: str) -> dict:
        vault_root = self.vault.base_dir.resolve()
        candidate = self.vault.base_dir / path
        if candidate.is_symlink():
            return {"error": "Symlinks are not allowed."}
        try:
            full = candidate.resolve()
        except Exception:
            return {"error": "Invalid path."}
        if not full.is_relative_to(vault_root):
            return {"error": "Path traversal attempt blocked."}
        if not full.exists():
            return {"error": f"File not found: {path}"}
        try:
            content = full.read_text(errors="replace")
            if len(content) > _MAX_READ_CHARS:
                content = content[:_MAX_READ_CHARS] + f"\n... [truncated at {_MAX_READ_CHARS} chars]"
            return {"content": content}
        except OSError as e:
            return {"error": str(e)}

    def _ingest_text(self, content: str, filename: str) -> dict:
        if "/" in filename or "\\" in filename or filename.startswith(".."):
            return {"error": f"Invalid filename: {filename!r}"}
        suffix = Path(filename).suffix.lower()
        if suffix not in {".md", ".txt", ".rst", ".csv", ".json"}:
            return {"error": f"Unsupported file type: {suffix!r}"}
        if len(content) > _MAX_INGEST_CHARS:
            return {"error": f"Content exceeds {_MAX_INGEST_CHARS // 1000}KB limit."}
        self.vault.ensure_structure()
        dest = self.vault.raw_dir / filename
        dest.write_text(content)
        dest.chmod(0o600)
        return {"result": f"Ingested as raw/{filename}"}

    def _compile_pending(self) -> dict:
        pending = self.vault.list_raw_files()
        if not pending:
            return {"result": "No pending files to compile."}
        compiler = CompilerEngine(self.vault, self.client)
        processed_dir = self.vault.raw_dir / "processed"
        processed_dir.mkdir(exist_ok=True)
        compiled, failed = [], []
        for f in pending:
            try:
                compiler.summarize_and_compile(f)
                f.rename(processed_dir / f.name)
                compiled.append(f.name)
            except (RuntimeError, OSError) as e:
                failed.append(f"{f.name}: {e}")
        return {"compiled": compiled, "failed": failed}

    def _query_vault(self, question: str, mode: str = "report") -> dict:
        if mode not in {"report", "slides", "data"}:
            return {"error": f"Invalid mode: {mode!r}"}
        engine = QueryEngine(self.vault, self.client)
        try:
            outfile = engine.execute_query(question, mode)
            return {"result": f"Saved to {outfile.relative_to(self.vault.base_dir)}"}
        except (RuntimeError, OSError) as e:
            return {"error": str(e)}

    def _write_concept(self, title: str, content: str) -> dict:
        slug = re.sub(r'[^a-zA-Z0-9]+', '_', title.strip().lower()).strip('_') or "concept"
        self.vault.ensure_structure()
        dest = self.vault.wiki_concepts_dir / f"{slug}.md"
        if dest.is_symlink():
            return {"error": "Output path is a symlink."}
        dest.write_text(f"# {title}\n\n{content}")
        dest.chmod(0o600)
        return {"result": f"Concept written to wiki/concepts/{slug}.md"}

    def _fetch_url(self, url: str, filename: str) -> dict:
        if not url.startswith("https://"):
            return {"error": "Only HTTPS URLs are allowed."}
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "fiti-agent/1.0"},
            )
            with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
                raw = resp.read(_FETCH_MAX_BYTES)
            content = raw.decode("utf-8", errors="replace")
        except urllib.error.URLError as e:
            return {"error": f"Failed to fetch URL: {e.reason}"}
        except Exception as e:
            return {"error": f"Failed to fetch URL: {e}"}
        return self._ingest_text(content, filename)
