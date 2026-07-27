# GitLite

GitLite is a small, Git-inspired local snapshot CLI for learning version-control internals; it is not Git-compatible.

It provides content-addressed blobs, immutable parent-linked snapshots, explicit staging and deletions, H/I/W status and diffs, conservative checkout with recovery, and repository integrity diagnostics. It has no third-party runtime dependencies.

## Install

GitLite requires Python 3.11 or newer.

```console
python -m pip install .
gitlite --version
```

From a source checkout, `python -m gitlite` and `python main.py` are equivalent entry points. For development, use `python -m pip install -e .`.

## Five-minute quick start

Run these commands in a disposable scratch directory, not in a project with irreplaceable uncommitted work:

```console
mkdir gitlite-scratch
cd gitlite-scratch
gitlite init
python -c "from pathlib import Path; Path('notes.txt').write_text('first note\n', encoding='utf-8')"
gitlite add notes.txt
gitlite diff --staged
gitlite commit -m "initial notes"
gitlite status
gitlite log
gitlite fsck
```

The complete reproducible walkthrough is available in [docs/demo.md](docs/demo.md), or run `python examples/demo.py`.

## Commands

| Command | Purpose |
|---|---|
| `gitlite init` | Initialize the current directory. |
| `gitlite add PATH [PATH ...]` | Stage exact file bytes or a tracked deletion. |
| `gitlite rm PATH [PATH ...]` | Stage removal while keeping working files. |
| `gitlite unstage PATH [PATH ...]` | Remove paths from staging while keeping working files. |
| `gitlite commit -m MESSAGE` | Commit the effective staged snapshot. Legacy `commit "message"` also works. |
| `gitlite status` | Show the current HEAD and two-column H/I/W state. |
| `gitlite diff [PATH]` | Compare HEAD with working files. |
| `gitlite diff [PATH] --staged` | Compare HEAD with the staged snapshot. |
| `gitlite log [--all]` | Walk current ancestry or list every stored snapshot. |
| `gitlite show [COMMIT]` | Inspect HEAD or one full commit ID. |
| `gitlite checkout COMMIT` | Safely switch to a full snapshot when tracked state is clean. |
| `gitlite recover` | Roll back one interrupted commit or checkout. |
| `gitlite fsck` | Diagnose metadata and object integrity without repair. |

Every subcommand supports `--help`. User and repository failures go to stderr with exit 1; command-line syntax failures use exit 2.

## Architecture

```text
Working tree (W)
      | gitlite add / rm / unstage
      v
Index delta -> effective staged snapshot (I)
      | gitlite commit
      v
HEAD snapshot (H) -> parent snapshot -> ...
      |                         |
      +---- commit objects -----+---- blob objects by SHA-1
```

The index is a delta over HEAD: blob IDs stage additions or changes and `null` stages deletions. Objects are immutable; HEAD, the index, and the operation journal are the small mutable pointers. See [architecture](docs/architecture.md), [safety and recovery](docs/safety.md), and the [approved implementation plan](docs/implementation-plan.md).

## Test

```console
python -m unittest discover -s tests -v
python examples/demo.py
git diff --check
```

CI is configured for Windows and Linux with Python 3.11 and 3.14. A checked-in workflow is configuration, not a claim that hosted jobs have run.

## Limits

GitLite intentionally has no branches, merges, remotes, recursive add, general ignore language, abbreviated IDs, force checkout, compression, permission tracking, or symlink tracking. It stores regular-file names and bytes, not permissions or timestamps. SHA-1 is retained for educational content addressing and format compatibility, not adversarial authenticity.

Use local filesystems. Cooperative locking does not protect against hostile external writers, network-filesystem behavior, process-wide atomic visibility, or power loss. Snapshots are not a substitute for independent backups. Read [docs/safety.md](docs/safety.md) before using checkout or recovery.
