import argparse
import re
import sys
from pathlib import Path

from fiti.state import StateManager
from fiti.vault import TopicVault
from fiti.compiler import CompilerEngine
from fiti.query import QueryEngine
from fiti.linter import LinterEngine
from fiti.api_client import APIClient
from fiti.config import get_config
from fiti import colors
import os

_TOPIC_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


def _validate_topic(topic: str) -> None:
    if not _TOPIC_RE.match(topic):
        print(colors.red(f"Invalid topic name '{topic}'. Use only letters, digits, hyphens, and underscores."))
        sys.exit(1)


def require_active_topic(state) -> TopicVault:
    topic = state.get_active_topic()
    if not topic:
        print(colors.yellow("No active topic. Run `fiti use <topic>` first."))
        sys.exit(1)
    vault = TopicVault(topic)
    if not vault.exists():
        print(colors.red(f"Topic vault '{topic}' does not exist. Run `fiti new {topic}` first."))
        sys.exit(1)
    return vault


# ── Vault management ───────────────────────────────────────────────────────

def cmd_new(args: argparse.Namespace) -> None:
    _validate_topic(args.topic)
    vault = TopicVault(args.topic)
    if vault.exists():
        print(colors.yellow(f"Topic '{args.topic}' already exists."))
        sys.exit(1)
    vault.ensure_structure()
    print(colors.green(f"Created new topic vault: {args.topic}"))


def cmd_use(args: argparse.Namespace) -> None:
    _validate_topic(args.topic)
    vault = TopicVault(args.topic)
    if not vault.exists():
        print(colors.yellow(f"Topic '{args.topic}' does not exist. Try `fiti new {args.topic}`."))
        sys.exit(1)
    state = StateManager()
    state.set_active_topic(args.topic)
    print(colors.green(f"Switched to topic: {args.topic}"))


def cmd_list(args: argparse.Namespace) -> None:
    topics_dir = Path.home() / ".fiti" / "topics"
    if not topics_dir.exists():
        print("No vaults found. Create one with `fiti new <topic>`.")
        return

    state = StateManager()
    active = state.get_active_topic()

    vaults = sorted(
        p for p in topics_dir.iterdir()
        if p.is_dir() and not p.is_symlink() and _TOPIC_RE.match(p.name)
    )
    if not vaults:
        print("No vaults found. Create one with `fiti new <topic>`.")
        return

    print(colors.bold("Vaults:"))
    for vdir in vaults:
        vault = TopicVault(vdir.name)
        s = vault.stats()
        marker = colors.green("* ") if vdir.name == active else "  "
        name = colors.bold(vdir.name) if vdir.name == active else vdir.name
        detail = colors.dim(
            f"  {s['pending']} pending, {s['summaries']} summaries, {s['concepts']} concepts"
        )
        print(f"  {marker}{name}{detail}")


def cmd_delete(args: argparse.Namespace) -> None:
    _validate_topic(args.topic)
    vault = TopicVault(args.topic)
    if not vault.exists():
        print(colors.red(f"Topic '{args.topic}' does not exist."))
        sys.exit(1)

    if not args.yes:
        print(colors.yellow(
            f"This will permanently delete the vault '{args.topic}' and all its contents."
        ))
        try:
            confirm = input(f"Type the topic name to confirm: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)
        if confirm != args.topic:
            print("Aborted — name did not match.")
            sys.exit(1)

    import shutil
    shutil.rmtree(vault.base_dir)

    # Clear active topic if we just deleted it
    state = StateManager()
    if state.get_active_topic() == args.topic:
        state.set_active_topic("")

    print(colors.green(f"Deleted vault: {args.topic}"))


def cmd_status(args: argparse.Namespace) -> None:
    state = StateManager()
    topic = state.get_active_topic()
    if not topic:
        print("No active topic.")
        return
    vault = TopicVault(topic)
    if not vault.exists():
        print(colors.red(f"Active topic '{topic}' is missing from filesystem."))
        return
    files = vault.list_raw_files()
    s = vault.stats()
    print(f"Active Topic:        {colors.bold(topic)}")
    print(f"Pending files:       {colors.yellow(str(len(files))) if files else colors.dim('0')}")
    print(f"Summaries:           {s['summaries']}")
    print(f"Concepts:            {s['concepts']}")
    print(f"Saved queries:       {s['queries']}")
    if files:
        for f in files:
            print(f"  {colors.dim('-')} {f.name}")


def cmd_ingest(args: argparse.Namespace) -> None:
    state = StateManager()
    vault = require_active_topic(state)
    target = Path(args.path)
    if not target.exists():
        print(colors.red(f"File not found: {target}"))
        sys.exit(1)
    try:
        vault.ingest_file(target)
        print(colors.green(f"Ingested {target.name} into {vault.name} raw directory."))
    except ValueError as e:
        print(colors.red(f"Ingest failed: {e}"))
        sys.exit(1)


def cmd_compile(args: argparse.Namespace) -> None:
    state = StateManager()
    vault = require_active_topic(state)
    pending = vault.list_raw_files()

    if not pending:
        print(colors.dim("No raw files to compile."))
        return

    try:
        compiler = CompilerEngine(vault)
    except RuntimeError as e:
        print(colors.red(str(e)))
        sys.exit(1)

    processed_dir = vault.raw_dir / "processed"
    processed_dir.mkdir(exist_ok=True)
    total = len(pending)

    for i, f in enumerate(pending, 1):
        print(f"{colors.dim(f'[{i}/{total}]')} Compiling {colors.bold(f.name)}...")
        try:
            compiler.summarize_and_compile(f)
            f.rename(processed_dir / f.name)
            print(f"  {colors.green('done')}")
        except (RuntimeError, OSError) as e:
            print(f"  {colors.red(f'failed: {e}')}")


def cmd_search(args: argparse.Namespace) -> None:
    state = StateManager()
    vault = require_active_topic(state)

    keyword = args.keyword
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    vault_root = vault.base_dir

    search_dirs = []
    if args.all:
        search_dirs = [vault.raw_dir, vault.wiki_dir]
    else:
        search_dirs = [vault.wiki_dir]

    print(f"Searching {colors.bold(vault.name)} for {colors.cyan(repr(keyword))}...")

    total_matches = 0
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for p in sorted(search_dir.rglob("*.md")):
            if p.is_symlink():
                continue
            try:
                lines = p.read_text(errors="replace").splitlines()
            except OSError:
                continue
            for lineno, line in enumerate(lines, 1):
                if pattern.search(line):
                    rel = p.relative_to(vault_root)
                    snippet = line.strip()[:100]
                    highlighted = pattern.sub(lambda m: colors.yellow(m.group()), snippet)
                    print(f"  {colors.dim(str(rel))}:{colors.cyan(str(lineno))}  {highlighted}")
                    total_matches += 1

    if total_matches == 0:
        print(colors.dim("No matches found."))
    else:
        print(colors.dim(f"\n{total_matches} match{'es' if total_matches != 1 else ''} found."))


def cmd_ask(args: argparse.Namespace) -> None:
    state = StateManager()
    vault = require_active_topic(state)

    mode = "report"
    if args.slides:
        mode = "slides"
    elif args.data:
        mode = "data"

    print(f"Querying {colors.bold(vault.name)} ({colors.dim(mode)})...")
    try:
        engine = QueryEngine(vault)
        outfile = engine.execute_query(args.question, mode)
        print(colors.green(f"Saved to: {outfile}"))
    except (RuntimeError, OSError) as e:
        print(colors.red(f"Query failed: {e}"))
        sys.exit(1)


def cmd_config(args: argparse.Namespace) -> None:
    cfg = get_config()
    cfg_file = Path.home() / ".fiti" / "config.json"

    if cfg_file.exists():
        source = str(cfg_file)
    else:
        source = "defaults (no ~/.fiti/config.json found)"

    print(f"{colors.bold('Active configuration')} ({colors.dim(source)}):")
    for k, v in cfg.to_dict().items():
        print(f"  {k:<24} {v}")

    if not cfg_file.exists():
        print(colors.dim(
            "\nCreate ~/.fiti/config.json to override any of the above.\n"
            'Example: {"anthropic_model": "claude-opus-4-6", "retry_attempts": 5}'
        ))


def check_pro_license():
    if not os.environ.get("FITI_PRO_KEY"):
        print(colors.yellow("⭐  FITI PRO FEATURE ⭐"))
        print("The automated memory linter is a premium feature. "
              "Please upgrade at fiti.sh/pro and set FITI_PRO_KEY.")
        sys.exit(1)


def cmd_lint(args: argparse.Namespace) -> None:
    check_pro_license()
    state = StateManager()
    vault = require_active_topic(state)

    print(f"Linting {colors.bold(vault.name)}...")
    try:
        linter = LinterEngine(vault)
    except RuntimeError as e:
        print(colors.red(str(e)))
        sys.exit(1)

    broken_links = linter.find_broken_links()
    if broken_links:
        print(colors.yellow(f"Found {len(broken_links)} broken link(s):"))
        for bl in broken_links:
            print(f"  {colors.red('-')} {bl}")
    else:
        print(colors.green("No broken links found."))

    print(f"\n{colors.dim('Running LLM Health Check...')}")
    result = linter.run_health_check(fix=args.fix)
    print(f"\n{result}")


def cmd_agent(args: argparse.Namespace) -> None:
    state = StateManager()
    vault = require_active_topic(state)
    max_steps = args.max_steps if args.max_steps else get_config().max_agent_steps
    print(f"Agent on {colors.bold(vault.name)}  goal: {colors.cyan(args.goal)}\n")
    try:
        from fiti.agent import AgentExecutor
        client = APIClient()
        executor = AgentExecutor(vault, client)
        result = executor.run(args.goal, max_iterations=max_steps)
        print(f"\n{result}")
    except (RuntimeError, OSError) as e:
        print(colors.red(f"Agent failed: {e}"))
        sys.exit(1)


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Fiti — Topic-Scoped LLM Knowledge CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="Create a new topic vault")
    p_new.add_argument("topic")
    p_new.set_defaults(func=cmd_new)

    p_use = sub.add_parser("use", help="Switch the active topic")
    p_use.add_argument("topic")
    p_use.set_defaults(func=cmd_use)

    p_list = sub.add_parser("list", help="List all topic vaults")
    p_list.set_defaults(func=cmd_list)

    p_delete = sub.add_parser("delete", help="Delete a topic vault")
    p_delete.add_argument("topic")
    p_delete.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    p_delete.set_defaults(func=cmd_delete)

    p_status = sub.add_parser("status", help="Show active topic stats")
    p_status.set_defaults(func=cmd_status)

    p_ingest = sub.add_parser("ingest", help="Add a raw document to the active topic")
    p_ingest.add_argument("path", help="Path to the file to ingest")
    p_ingest.set_defaults(func=cmd_ingest)

    p_compile = sub.add_parser("compile", help="Run LLM to process uncompiled raw docs")
    p_compile.set_defaults(func=cmd_compile)

    p_search = sub.add_parser("search", help="Search the wiki for a keyword")
    p_search.add_argument("keyword", help="Keyword to search for")
    p_search.add_argument("--all", "-a", action="store_true",
                          help="Also search raw/ files (default: wiki only)")
    p_search.set_defaults(func=cmd_search)

    p_ask = sub.add_parser("ask", help="Ask a question against the active topic wiki")
    p_ask.add_argument("question")
    group = p_ask.add_mutually_exclusive_group()
    group.add_argument("--slides", action="store_true", help="Output as Marp slide deck")
    group.add_argument("--data", action="store_true", help="Output as matplotlib chart script")
    p_ask.set_defaults(func=cmd_ask)

    p_lint = sub.add_parser("lint", help="Run health check and find broken links (PRO)")
    p_lint.add_argument("--fix", action="store_true", help="Auto-fix and rebuild the Index")
    p_lint.set_defaults(func=cmd_lint)

    p_agent = sub.add_parser("agent", help="Run an autonomous multi-step workflow")
    p_agent.add_argument("goal", help="What you want the agent to accomplish")
    p_agent.add_argument("--max-steps", type=int, default=None, metavar="N",
                         help=f"Max tool-use iterations (default: config max_agent_steps)")
    p_agent.set_defaults(func=cmd_agent)

    p_config = sub.add_parser("config", help="Show active configuration")
    p_config.set_defaults(func=cmd_config)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
