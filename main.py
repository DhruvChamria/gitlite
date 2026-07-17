"""
GitLite CLI entry point.

A simplified Git-like version control system implemented in Python.
"""

import sys
from repository import Repository


def print_help() -> None:
    """Display supported commands."""
    help_text = """
GitLite - simplified Git-like version control system

Usage:
  python main.py init
  python main.py add <filename> [more_files...]
  python main.py commit "message"
  python main.py log
  python main.py checkout <commit-hash>
  python main.py diff <filename>
  python main.py status
"""
    print(help_text.strip())


def main() -> None:
    repo = Repository()

    if len(sys.argv) < 2:
        print_help()
        return

    command = sys.argv[1]

    try:
        if command == "init":
            repo.init()

        elif command == "add":
            if len(sys.argv) < 3:
                print("Usage: python main.py add <filename> [more_files...]")
                return
            for filename in sys.argv[2:]:
                repo.add(filename)

        elif command == "commit":
            if len(sys.argv) < 3:
                print('Usage: python main.py commit "message"')
                return
            message = sys.argv[2]
            repo.commit(message)

        elif command == "log":
            repo.log()

        elif command == "checkout":
            if len(sys.argv) < 3:
                print("Usage: python main.py checkout <commit-hash>")
                return
            repo.checkout(sys.argv[2])

        elif command == "diff":
            if len(sys.argv) < 3:
                print("Usage: python main.py diff <filename>")
                return
            repo.diff(sys.argv[2])

        elif command == "status":
            repo.status()

        else:
            print(f"Unknown command: {command}")
            print_help()

    except Exception as exc:
        print(f"Error: {exc}")


if __name__ == "__main__":
    main()