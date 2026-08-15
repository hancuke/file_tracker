"""Argparse CLI wrapper for FileTracker."""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="filetracker", description="Track physical file changes vs. a baseline."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--root", default=".", help="Root directory to track.")
        p.add_argument(
            "--exclude",
            nargs="*",
            default=None,
            help="Glob patterns to exclude (e.g. '*.pyc' '__pycache__').",
        )

    p_scan = sub.add_parser("scan", help="Show file changes vs. the baseline.")
    add_common(p_scan)

    p_commit = sub.add_parser("commit", help="Advance the baseline.")
    add_common(p_commit)
    p_commit.add_argument("-m", "--message", default="", help="Commit message.")

    p_undo = sub.add_parser("undo", help="Roll back the last commit.")
    add_common(p_undo)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from filetracker.tracker import FileTracker

    tracker = FileTracker(root=args.root, exclude=args.exclude)

    if args.command == "scan":
        cs = tracker.scan()
        print(
            f"Changes: {len(cs.added)} added, "
            f"{len(cs.modified)} modified, {len(cs.deleted)} deleted."
        )
        for c in cs:
            print(f"  [{c.status.value}] {c.path}")
        return 0

    if args.command == "commit":
        tracker.commit(message=args.message)
        print("Baseline advanced.")
        return 0

    if args.command == "undo":
        if tracker.undo():
            print("Baseline rolled back by one commit.")
        else:
            print("Nothing to undo.")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
