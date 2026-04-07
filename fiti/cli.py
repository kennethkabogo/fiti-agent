import argparse
import re
import sys
import zipfile
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


def _print_usage(client: APIClient) -> None:
    """Print accumulated token counts if any were recorded."""
    usage = client.get_usage()
    total = usage["input_tokens"] + usage["output_tokens"]
    if total > 0:
        print(colors.dim(
            f"Tokens: {usage['input_tokens']:,} in + {usage['output_tokens']:,} out = {total:,} total"
        ))


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


def cmd_export(args: argparse.Namespace) -> None:
    _validate_topic(args.topic)
    vault = TopicVault(args.topic)
    if not vault.exists():
        print(colors.red(f"Topic '{args.topic}' does not exist."))
        sys.exit(1)

    out = Path(args.output) if args.output else Path(f"{args.topic}.fiti.zip")
    if out.exists() and not args.force:
        print(colors.red(f"Output file already exists: {out}  (use --force to overwrite)"))
        sys.exit(1)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(vault.base_dir.rglob("*")):
            if p.is_symlink() or not p.is_file():
                continue
            zf.write(p, p.relative_to(vault.base_dir.parent))

    print(colors.green(f"Exported '{args.topic}' → {out}"))


def cmd_import(args: argparse.Namespace) -> None:
    archive = Path(args.archive)
    if not archive.exists():
        print(colors.red(f"Archive not found: {archive}"))
        sys.exit(1)
    if not zipfile.is_zipfile(archive):
        print(colors.red(f"Not a valid zip archive: {archive}"))
        sys.exit(1)

    topics_dir = Path.home() / ".fiti" / "topics"

    with zipfile.ZipFile(archive, "r") as zf:
        names = zf.namelist()
        # The archive must contain exactly one top-level directory (the topic name)
        roots = {n.split("/")[0] for n in names if n.strip()}
        if len(roots) != 1:
            print(colors.red("Archive must contain exactly one top-level topic directory."))
            sys.exit(1)
        topic_name = next(iter(roots))

        try:
            _validate_topic(topic_name)
        except SystemExit:
            print(colors.red(f"Archive topic name '{topic_name}' is not valid."))
            sys.exit(1)

        dest = topics_dir / topic_name
        if dest.exists() and not args.force:
            print(colors.red(
                f"Vault '{topic_name}' already exists. Use --force to overwrite."
            ))
            sys.exit(1)

        # Security: reject any entry with path traversal or absolute paths
        for entry in names:
            resolved = (topics_dir / entry).resolve()
            if not str(resolved).startswith(str(topics_dir.resolve())):
                print(colors.red(f"Unsafe path in archive: {entry}"))
                sys.exit(1)

        topics_dir.mkdir(parents=True, exist_ok=True)
        zf.extractall(topics_dir)

    print(colors.green(f"Imported vault '{topic_name}' from {archive}"))
    print(colors.dim(f"  Run `fiti use {topic_name}` to switch to it."))


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

    if args.dry_run:
        print(colors.bold(f"Dry run — {len(pending)} file(s) would be compiled:"))
        for f in pending:
            print(f"  {colors.dim('-')} {f.name}")
        return

    processed_dir = vault.raw_dir / "processed"
    processed_dir.mkdir(exist_ok=True)
    total = len(pending)

    try:
        with vault.locked():
            try:
                compiler = CompilerEngine(vault)
            except RuntimeError as e:
                print(colors.red(str(e)))
                sys.exit(1)

            for i, f in enumerate(pending, 1):
                print(f"{colors.dim(f'[{i}/{total}]')} Compiling {colors.bold(f.name)}...")
                try:
                    compiler.summarize_and_compile(f)
                    f.rename(processed_dir / f.name)
                    print(f"  {colors.green('done')}")
                except (RuntimeError, OSError) as e:
                    print(f"  {colors.red(f'failed: {e}')}")

            _print_usage(compiler.client)
    except RuntimeError as e:
        print(colors.red(str(e)))
        sys.exit(1)


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

    # Resolve any extra vaults from --topics
    extra_vaults = []
    if args.topics:
        for t in args.topics.split(','):
            t = t.strip()
            if not t or t == vault.name:
                continue
            _validate_topic(t)
            v = TopicVault(t)
            if not v.exists():
                print(colors.red(f"Topic '{t}' not found. Create it with `fiti new {t}`."))
                sys.exit(1)
            extra_vaults.append(v)

    mode = "report"
    if args.slides:
        mode = "slides"
    elif args.data:
        mode = "data"

    all_names = [vault.name] + [v.name for v in extra_vaults]
    output = Path(args.output) if args.output else None

    print(f"Querying {colors.bold(', '.join(all_names))} ({colors.dim(mode)})...")
    try:
        engine = QueryEngine(vault)
        outfile = engine.execute_query(
            args.question, mode, extra_vaults=extra_vaults, output_path=output
        )
        print(colors.green(f"Saved to: {outfile}"))
        _print_usage(engine.client)
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

    if args.dry_run:
        print(colors.dim("(Dry run — no LLM health check or index fixes applied)"))
        return

    print(f"\n{colors.dim('Running LLM Health Check...')}")
    result = linter.run_health_check(fix=args.fix)
    print(f"\n{result}")


def cmd_agent(args: argparse.Namespace) -> None:
    state = StateManager()
    vault = require_active_topic(state)

    from fiti.agent import AgentExecutor
    client = APIClient()
    executor = AgentExecutor(vault, client)

    if args.list_sessions or not args.goal:
        sessions = executor.list_sessions()
        if not sessions:
            print(colors.dim("No saved sessions for this vault."))
            if not args.goal:
                print(colors.yellow("Usage: fiti agent \"<goal>\"  or  fiti agent --resume <id>"))
        else:
            print(colors.bold("Saved agent sessions:"))
            for s in sessions:
                print(f"  {colors.cyan(s['id'])}  {s['steps']} steps  {colors.dim(s['goal'][:60])}")
            if not args.goal:
                print(colors.dim("\nResume one with: fiti agent \"<goal>\" --resume <id>"))
        return

    max_steps = args.max_steps if args.max_steps else get_config().max_agent_steps
    print(f"Agent on {colors.bold(vault.name)}  goal: {colors.cyan(args.goal)}\n")
    try:
        result = executor.run(args.goal, max_iterations=max_steps, resume_id=args.resume)
        print(f"\n{result}")
        _print_usage(client)
    except (RuntimeError, OSError) as e:
        print(colors.red(f"Agent failed: {e}"))
        sys.exit(1)


def cmd_watch(args: argparse.Namespace) -> None:
    import time as _time
    state = StateManager()
    vault = require_active_topic(state)

    target = Path(args.dir)
    if not target.exists() or not target.is_dir():
        print(colors.red(f"Directory not found: {target}"))
        sys.exit(1)

    interval = get_config().watch_interval
    print(
        f"Watching {colors.bold(str(target))} → vault {colors.bold(vault.name)}"
        f"  (interval: {interval}s, Ctrl-C to stop)"
    )
    if args.compile:
        print(colors.dim("  Auto-compile enabled."))

    seen = {p.name for p in target.iterdir() if p.is_file() and not p.is_symlink()}
    ingested_count = 0

    try:
        while True:
            _time.sleep(interval)
            current = {p.name for p in target.iterdir() if p.is_file() and not p.is_symlink()}
            new_files = current - seen
            for fname in sorted(new_files):
                fpath = target / fname
                try:
                    vault.ingest_file(fpath)
                    ingested_count += 1
                    print(colors.green(f"[watch] [{ingested_count} ingested] {fname}"))
                    if args.compile:
                        _watch_compile_one(vault, fname)
                except ValueError as e:
                    print(colors.yellow(f"[watch] Skipped {fname}: {e}"))
            seen = current
    except KeyboardInterrupt:
        summary = f"{ingested_count} file{'s' if ingested_count != 1 else ''} ingested"
        print(colors.dim(f"\nWatch stopped. {summary}."))


def _watch_compile_one(vault: TopicVault, ingested_name: str) -> None:
    """Compile only the freshly ingested file."""
    pending = [f for f in vault.list_raw_files() if f.name == ingested_name]
    if not pending:
        return
    try:
        compiler = CompilerEngine(vault)
        processed_dir = vault.raw_dir / "processed"
        processed_dir.mkdir(exist_ok=True)
        f = pending[0]
        print(f"  Compiling {colors.bold(f.name)}...")
        compiler.summarize_and_compile(f)
        f.rename(processed_dir / f.name)
        print(f"  {colors.green('done')}")
    except (RuntimeError, OSError) as e:
        print(f"  {colors.red(f'compile failed: {e}')}")


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
    p_compile.add_argument("--dry-run", action="store_true",
                           help="Show what would be compiled without calling the LLM")
    p_compile.set_defaults(func=cmd_compile)

    p_search = sub.add_parser("search", help="Search the wiki for a keyword")
    p_search.add_argument("keyword", help="Keyword to search for")
    p_search.add_argument("--all", "-a", action="store_true",
                          help="Also search raw/ files (default: wiki only)")
    p_search.set_defaults(func=cmd_search)

    p_ask = sub.add_parser("ask", help="Ask a question against the active topic wiki")
    p_ask.add_argument("question")
    p_ask.add_argument("--topics", metavar="T1,T2",
                       help="Comma-separated extra vault names to include as context")
    p_ask.add_argument("--output", "-o", metavar="FILE",
                       help="Save output to this path instead of wiki/queries/")
    group = p_ask.add_mutually_exclusive_group()
    group.add_argument("--slides", action="store_true", help="Output as Marp slide deck")
    group.add_argument("--data", action="store_true", help="Output as matplotlib chart script")
    p_ask.set_defaults(func=cmd_ask)

    p_lint = sub.add_parser("lint", help="Run health check and find broken links (PRO)")
    p_lint.add_argument("--fix", action="store_true", help="Auto-fix and rebuild the Index")
    p_lint.add_argument("--dry-run", action="store_true",
                        help="Find broken links only, skip LLM health check and writes")
    p_lint.set_defaults(func=cmd_lint)

    p_agent = sub.add_parser("agent", help="Run an autonomous multi-step workflow")
    p_agent.add_argument("goal", nargs="?", default="",
                         help="What you want the agent to accomplish")
    p_agent.add_argument("--max-steps", type=int, default=None, metavar="N",
                         help="Max tool-use iterations (default: config max_agent_steps)")
    p_agent.add_argument("--resume", metavar="SESSION_ID",
                         help="Resume a previous agent session by its ID")
    p_agent.add_argument("--list-sessions", action="store_true",
                         help="List saved agent sessions for the active vault")
    p_agent.set_defaults(func=cmd_agent)

    p_export = sub.add_parser("export", help="Export a vault to a zip archive")
    p_export.add_argument("topic")
    p_export.add_argument("--output", "-o", metavar="FILE",
                          help="Output path (default: <topic>.fiti.zip)")
    p_export.add_argument("--force", "-f", action="store_true",
                          help="Overwrite output file if it exists")
    p_export.set_defaults(func=cmd_export)

    p_import = sub.add_parser("import", help="Import a vault from a zip archive")
    p_import.add_argument("archive", help="Path to .fiti.zip archive")
    p_import.add_argument("--force", "-f", action="store_true",
                          help="Overwrite existing vault if it already exists")
    p_import.set_defaults(func=cmd_import)

    p_watch = sub.add_parser("watch", help="Monitor a directory and auto-ingest new files")
    p_watch.add_argument("dir", help="Directory to watch")
    p_watch.add_argument("--compile", "-c", action="store_true",
                         help="Auto-compile each ingested file immediately")
    p_watch.set_defaults(func=cmd_watch)

    p_config = sub.add_parser("config", help="Show active configuration")
    p_config.set_defaults(func=cmd_config)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
