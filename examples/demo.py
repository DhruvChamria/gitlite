from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile


SOURCE_ROOT = Path(__file__).resolve().parents[1]
MAIN = SOURCE_ROOT / "main.py"


def run(root: Path, *args: str, expected: int = 0) -> str:
    command = [sys.executable, str(MAIN), *args]
    print("$ gitlite " + " ".join(args))
    result = subprocess.run(command, cwd=root, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip())
    if result.returncode != expected:
        raise RuntimeError(f"command returned {result.returncode}, expected {expected}: {args}")
    return result.stdout


def commit_id(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("Committed as "):
            return line.removeprefix("Committed as ").strip()
    raise RuntimeError("commit output did not include a full ID")


def main() -> int:
    initial_notes = b"GitLite stores snapshots.\n"
    second_notes = b"GitLite stores immutable snapshots.\n"
    todo = b"Explain H, I, and W.\n"
    caller = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="gitlite-demo-") as temp:
        root = Path(temp)
        print(f"Demo repository: {root}")
        run(root, "init")
        (root / "notes.txt").write_bytes(initial_notes)
        run(root, "add", "notes.txt")
        run(root, "diff", "--staged")
        first = commit_id(run(root, "commit", "-m", "initial snapshot"))

        (root / "notes.txt").write_bytes(second_notes)
        (root / "todo.txt").write_bytes(todo)
        run(root, "status")
        run(root, "diff")
        run(root, "add", "notes.txt", "todo.txt")
        second = commit_id(run(root, "commit", "-m", "explain state model"))

        (root / "notes.txt").write_bytes(b"unsaved local edit\n")
        run(root, "checkout", first, expected=1)
        if (root / "notes.txt").read_bytes() != b"unsaved local edit\n":
            raise RuntimeError("refused checkout changed the working file")
        print("Restoring the demo's own known second-snapshot fixture bytes.")
        (root / "notes.txt").write_bytes(second_notes)
        run(root, "checkout", first)
        if (root / "notes.txt").read_bytes() != initial_notes or (root / "todo.txt").exists():
            raise RuntimeError("first snapshot was not restored exactly")

        run(root, "log", "--all")
        run(root, "show", second)
        run(root, "checkout", second)
        run(root, "rm", "todo.txt")
        run(root, "diff", "--staged")
        run(root, "unstage", "todo.txt")
        run(root, "fsck")
        print(f"Initial commit: {first}")
        print(f"Second commit:  {second}")
        print("The demo restored only data that it generated itself.")
    if Path.cwd() != caller:
        raise RuntimeError("demo changed the caller's working directory")
    print("Temporary demo repository cleaned up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
