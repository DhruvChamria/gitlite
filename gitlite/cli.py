from __future__ import annotations

import argparse
import sys

from . import __version__
from .errors import GitLiteError, UsageError
from .repository import Repository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gitlite", description="Git-inspired local snapshots")
    parser.add_argument("--version", action="version", version=f"gitlite {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init", help="initialize the current directory")
    add = sub.add_parser("add", help="stage explicit files (metadata and cache paths are excluded)")
    add.add_argument("paths", nargs="+")
    remove = sub.add_parser("rm", help="stage removals while keeping working files")
    remove.add_argument("paths", nargs="+")
    unstage = sub.add_parser("unstage", help="remove paths from staging while keeping working files")
    unstage.add_argument("paths", nargs="+")
    commit = sub.add_parser("commit", help="commit the staged snapshot")
    commit.add_argument("legacy_message", nargs="?")
    commit.add_argument("-m", "--message")
    sub.add_parser("log", help="show current history")
    checkout = sub.add_parser("checkout", help="restore a full commit ID")
    checkout.add_argument("commit")
    sub.add_parser("recover", help="roll back one interrupted commit or checkout")
    diff = sub.add_parser("diff", help="show HEAD/worktree changes")
    diff.add_argument("path")
    sub.add_parser("status", help="show repository status")
    return parser


def run(args: argparse.Namespace) -> int:
    if args.command is None:
        build_parser().print_help()
        return 0
    if args.command == "init":
        print(Repository(discover=False).init())
        return 0
    repo = Repository()
    if args.command == "add":
        print("\n".join(repo.add(args.paths)))
    elif args.command == "rm":
        print("\n".join(repo.remove(args.paths)))
    elif args.command == "unstage":
        print("\n".join(repo.unstage(args.paths)))
    elif args.command == "commit":
        if bool(args.message) == bool(args.legacy_message):
            raise UsageError("Supply exactly one commit message: -m MESSAGE or legacy positional MESSAGE.")
        commit_id, parent = repo.commit(args.message or args.legacy_message)
        print(f"Committed as {commit_id}\nParent: {parent or 'none'}")
    elif args.command == "log":
        history = repo.log()
        if not history:
            print("No commits yet.")
        for item in history:
            print(f"commit {item['hash']}\nParent: {item['parent'] or 'none'}\nDate:   {item['timestamp']}\nMessage: {item['message']}\n")
    elif args.command == "checkout":
        print(f"Checked out commit {repo.checkout(args.commit)}")
    elif args.command == "recover":
        recovered, leftovers = repo.recover()
        if not recovered:
            print("No interrupted operation to recover.")
        else:
            print("Recovered interrupted operation by rolling back.")
            if leftovers:
                print("Preserved nonempty created directories: " + ", ".join(leftovers))
    elif args.command == "diff":
        print(repo.diff(args.path) or "No differences found.")
    elif args.command == "status":
        status = repo.status()
        print("=== GitLite Status ===")
        print(f"HEAD: {status.head or 'No commits yet'}")
        print("XY Path (X: HEAD/index, Y: index/worktree)")
        print("\n".join(status.rows) if status.rows else "Working tree clean.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        return run(parser.parse_args(argv))
    except UsageError as exc:
        parser.error(str(exc))
    except (GitLiteError, OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 2
