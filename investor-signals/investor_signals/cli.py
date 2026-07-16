"""CLI entry point: `sync` and `serve`.

    python -m investor_signals sync   [--config config.yaml]
    python -m investor_signals serve  [--config config.yaml] [--host H] [--port P]
"""

from __future__ import annotations

import argparse
import sys

from .config import load_config


def _cmd_sync(args: argparse.Namespace) -> int:
    from .sync import run_sync

    config = load_config(args.config)
    print(
        f"Sync scope: mode={config.scope.mode} "
        f"owners={config.scope.owner_ids or '(resolve active)'} "
        f"window={config.scope.start_date}..{config.scope.end_date} "
        f"types={config.scope.object_types}"
    )
    report = run_sync(config)
    print(report.summary())
    if report.errors:
        print("\nErrors:", file=sys.stderr)
        for e in report.errors[:20]:
            print(f"  - {e}", file=sys.stderr)
    print(
        "\nReminder: this dataset targets outreach for private-fund placements. "
        "Before the app goes live for the sales team, run a quick compliance/legal "
        "sanity check given the regulatory context around investor solicitation — "
        "don't assume it's already been cleared."
    )
    return 0


def _cmd_seed(args: argparse.Namespace) -> int:
    from .seed import seed_store

    config = load_config(args.config)
    print(
        f"Seeding synthetic data: contacts={args.contacts} "
        f"mode={'real-extraction' if args.extract else 'offline (ground-truth)'} "
        f"store={config.store_path}"
    )
    report = seed_store(
        config,
        n_contacts=args.contacts,
        use_llm=args.extract,
        reset=not args.no_reset,
        seed=args.seed,
    )
    print(report.summary())
    if report.errors:
        print("\nErrors:", file=sys.stderr)
        for e in report.errors[:20]:
            print(f"  - {e}", file=sys.stderr)
    print("\nNow run:  python -m investor_signals serve")
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    from .import_xlsx import import_xlsx

    config = load_config(args.config)
    mode = "real-extraction" if args.extract else "offline heuristics"
    print(f"Importing {args.file} ({mode}) into {config.store_path}")
    report = import_xlsx(
        args.file, config, use_llm=args.extract, reset=not args.no_reset
    )
    print(report.summary())
    if report.errors:
        print("\nErrors:", file=sys.stderr)
        for e in report.errors[:20]:
            print(f"  - {e}", file=sys.stderr)
    print("\nNow run:  python -m investor_signals serve")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .app import create_app

    config = load_config(args.config)
    app = create_app(config)
    host = args.host or config.server_host
    port = args.port or config.server_port
    print(f"Serving on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="investor_signals",
        description="Moonfare investor-signal extraction (read-only against HubSpot).",
    )
    parser.add_argument(
        "--config", default=None, help="Path to config.yaml (default: repo-root config.yaml)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="Pull, extract, normalize, and persist signals.")
    p_sync.set_defaults(func=_cmd_sync)

    p_seed = sub.add_parser(
        "seed",
        help="Populate the store with synthetic calls/emails (MVP, no HubSpot).",
    )
    p_seed.add_argument("--contacts", type=int, default=12)
    p_seed.add_argument("--seed", type=int, default=42, help="RNG seed (deterministic)")
    p_seed.add_argument(
        "--extract",
        action="store_true",
        help="Run the real Claude extractor over synthetic bodies (needs a key). "
        "Default is offline, using synthetic ground-truth signals.",
    )
    p_seed.add_argument(
        "--no-reset",
        action="store_true",
        help="Append to the existing store instead of recreating it.",
    )
    p_seed.set_defaults(func=_cmd_seed)

    p_import = sub.add_parser(
        "import-xlsx",
        help="Import a HubSpot engagement .xlsx export into the store.",
    )
    p_import.add_argument("file", help="Path to the .xlsx export")
    p_import.add_argument(
        "--extract",
        action="store_true",
        help="Use the Claude extractor (needs a key). Default is offline heuristics.",
    )
    p_import.add_argument("--no-reset", action="store_true")
    p_import.set_defaults(func=_cmd_import)

    p_serve = sub.add_parser("serve", help="Run the local web app.")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, FileNotFoundError) as exc:
        # Expected operator errors (missing token, missing/invalid config) —
        # report cleanly instead of dumping a traceback.
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
