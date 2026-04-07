import argparse
import re
import sys
from pathlib import Path
from fiti.state import StateManager
from fiti.vault import TopicVault
from fiti.compiler import CompilerEngine
from fiti.query import QueryEngine
from fiti.linter import LinterEngine
import os

_TOPIC_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


def _validate_topic(topic: str) -> None:
    if not _TOPIC_RE.match(topic):
        print(f"Invalid topic name '{topic}'. Use only letters, digits, hyphens, and underscores.")
        sys.exit(1)


def require_active_topic(state) -> TopicVault:
    topic = state.get_active_topic()
    if not topic:
        print("No active topic. Run `fiti use <topic>` first.")
        sys.exit(1)
    vault = TopicVault(topic)
    if not vault.exists():
        print(f"Topic vault '{topic}' does not exist. Run `fiti new {topic}` first.")
        sys.exit(1)
    return vault


def cmd_new(args: argparse.Namespace) -> None:
    _validate_topic(args.topic)
    vault = TopicVault(args.topic)
    if vault.exists():
        print(f"Topic '{args.topic}' already exists.")
        sys.exit(1)
    vault.ensure_structure()
    print(f"Created new topic vault: {args.topic}")


def cmd_use(args: argparse.Namespace) -> None:
    _validate_topic(args.topic)
    vault = TopicVault(args.topic)
    if not vault.exists():
        print(f"Topic '{args.topic}' does not exist. Do you want to try `fiti new {args.topic}`?")
        sys.exit(1)
    state = StateManager()
    state.set_active_topic(args.topic)
    print(f"Switched to topic: {args.topic}")


def cmd_status(args: argparse.Namespace) -> None:
    state = StateManager()
    topic = state.get_active_topic()
    if not topic:
        print("No active topic.")
        return
    vault = TopicVault(topic)
    if not vault.exists():
        print(f"Active topic '{topic}' is missing from filesystem.")
        return
    files = vault.list_raw_files()
    print(f"Active Topic: {topic}")
    print(f"Raw uncompiled files: {len(files)}")
    for f in files:
        print(f"  - {f.name}")


def cmd_ingest(args: argparse.Namespace) -> None:
    state = StateManager()
    vault = require_active_topic(state)
    target = Path(args.path)
    if not target.exists():
        print(f"File not found: {target}")
        sys.exit(1)
    dest = vault.ingest_file(target)
    print(f"Ingested {target.name} into {vault.name} raw directory.")


def cmd_compile(args: argparse.Namespace) -> None:
    state = StateManager()
    vault = require_active_topic(state)
    pending = vault.list_raw_files()

    if not pending:
        print("No raw files to compile.")
        return

    try:
        compiler = CompilerEngine(vault)
    except RuntimeError as e:
        print(e)
        sys.exit(1)

    processed_dir = vault.raw_dir / "processed"
    processed_dir.mkdir(exist_ok=True)

    for f in pending:
        print(f"Compiling {f.name}...")
        try:
            compiler.summarize_and_compile(f)
            f.rename(processed_dir / f.name)
            print(f"  -> Done.")
        except (RuntimeError, OSError) as e:
            print(f"  -> Failed: {e}")


def cmd_ask(args: argparse.Namespace) -> None:
    state = StateManager()
    vault = require_active_topic(state)

    mode = "report"
    if args.slides:
        mode = "slides"
    elif args.data:
        mode = "data"

    print(f"Querying topic: {vault.name} (mode: {mode})...")
    try:
        engine = QueryEngine(vault)
        outfile = engine.execute_query(args.question, mode)
        print(f"Saved response to: {outfile}")
    except (RuntimeError, OSError) as e:
        print(f"Query failed: {e}")
        sys.exit(1)


def check_pro_license():
    if not os.environ.get("FITI_PRO_KEY"):
        print("⭐️ FITI PRO FEATURE ⭐️")
        print("The automated memory linter is a premium feature. Please upgrade at fiti.sh/pro and set FITI_PRO_KEY.")
        sys.exit(1)


def cmd_lint(args: argparse.Namespace) -> None:
    check_pro_license()
    state = StateManager()
    vault = require_active_topic(state)

    print(f"Linting topic: {vault.name}...")
    try:
        linter = LinterEngine(vault)
    except RuntimeError as e:
        print(e)
        sys.exit(1)

    broken_links = linter.find_broken_links()
    if broken_links:
        print(f"Found {len(broken_links)} broken links:")
        for bl in broken_links:
            print(f"  - {bl}")
    else:
        print("No broken links found.")

    print("\nRunning LLM Health Check...")
    result = linter.run_health_check(fix=args.fix)
    print(f"\n{result}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fiti - Topic-Scoped LLM Knowledge CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="Create a new topic vault")
    p_new.add_argument("topic", help="Name of the new topic")
    p_new.set_defaults(func=cmd_new)

    p_use = sub.add_parser("use", help="Switch the active topic")
    p_use.add_argument("topic", help="Name of the topic to switch to")
    p_use.set_defaults(func=cmd_use)

    p_status = sub.add_parser("status", help="Show active topic and pending files")
    p_status.set_defaults(func=cmd_status)

    p_ingest = sub.add_parser("ingest", help="Add a raw document to the active topic")
    p_ingest.add_argument("path", help="Path to the file to ingest")
    p_ingest.set_defaults(func=cmd_ingest)

    p_compile = sub.add_parser("compile", help="Run LLM to process uncompiled raw docs")
    p_compile.set_defaults(func=cmd_compile)

    p_ask = sub.add_parser("ask", help="Ask a question against the active topic wiki")
    p_ask.add_argument("question", help="The question to ask")
    group = p_ask.add_mutually_exclusive_group()
    group.add_argument("--slides", action="store_true", help="Output answer as a Marp slide deck")
    group.add_argument("--data", action="store_true", help="Output answer as a matplotlib chart script")
    p_ask.set_defaults(func=cmd_ask)

    p_lint = sub.add_parser("lint", help="Run health check and find broken links (PRO)")
    p_lint.add_argument("--fix", action="store_true", help="Auto-fix structural issues in the Index")
    p_lint.set_defaults(func=cmd_lint)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
