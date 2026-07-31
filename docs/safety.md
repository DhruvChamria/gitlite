# Safety and recovery

GitLite accepts explicit regular-file paths only. CLI paths are relative to the invocation directory and may use `..` only when the final path remains inside the nearest repository. Stored names use normalized `/` separators. Metadata names, control characters, Windows device names, trailing dots/spaces, portable case collisions, and file/directory collisions are rejected.

The hosted Browser Lab runs in Pyodide's in-memory filesystem. The pinned runtime is installed from the committed npm lockfile and bundled into the Pages artifact rather than executed from a third-party CDN. It cannot access visitor files, uses a single in-page command stream instead of an OS advisory lock, and skips physical-disk `fsync` because browser memory has no such durability boundary. Refreshing or resetting discards that sandbox. Native CLI behavior retains the OS lock and flushed atomic-write contract described below.

GitLite never follows symlinks, junctions, or reparse points in repository metadata or worktree paths. Status reports unsupported non-excluded entries with `!!`. Built-in scan exclusions are `.git`, `.mygit`, `.venv`, `venv`, `__pycache__`, `*.pyc`, and `*.pyo`. This is not a configurable ignore language. An already tracked cache path remains tracked.

## Checkout policy

Checkout requires an empty index and every currently tracked file to match HEAD. It validates the target commit and all blobs before the first worktree change. Untracked target collisions, obstructing ancestors, unsafe path transitions, and dirty or missing tracked files are refused. Unrelated untracked files are preserved. File/directory and case-only transitions may require an intermediate deletion snapshot.

There is no force option. This policy prevents GitLite from deciding that local bytes are disposable.

## Lock and journal lifecycle

Commands serialize through a permanent `.mygit/LOCK` advisory OS lock. New initialization first reserves `.mygit` exclusively, then creates and acquires the lock; an interrupted initialization remains visibly incomplete and is never auto-deleted. Inspect and move that exact incomplete directory aside before retrying.

Metadata and worktree replacements use flushed temporary siblings named `.gitlite-tmp-*` followed by atomic replacement. GitLite removes only its own temporaries during handled completion. Unknown residue from an interrupted process is reported and preserved.

Commit and checkout write `.mygit/transaction.json` before changing mutable state. A later command refuses to proceed until:

```console
gitlite recover
```

Recovery always rolls back. It verifies journal paths, commits, blobs, exact change maps, HEAD/index intermediate states, and every affected worktree file before modifying anything. If bytes match neither the recorded before nor after state, recovery stops and preserves both the user data and journal. `fsck` diagnoses a pending or malformed journal but never repairs it.

## Compatibility and diagnostics

Legacy commit hashes and string-only indexes remain valid. New `null` deletion entries are not understood by the old executable; do not use an older GitLite version to write a repository after staging a deletion with this release.

Run `gitlite fsck` to validate HEAD, index, commit and blob schemas and hashes, references, portable path rules, cycles, and pending operations. It retains unreachable valid objects and interruption residue. Preserve `.mygit` before manual repair or forensic work.

JSON metadata is limited to 16 MiB per file and 64 container levels. Inputs beyond those bounds are reported as corruption instead of risking unbounded parser or validation work. Initialization also refuses to create a repository beneath an existing parent repository.

## Guarantee boundary

Validation failures do not alter tracked state. Handled I/O failures attempt rollback, and process interruption is detected for explicit recovery. GitLite does not provide whole-tree atomic visibility, power-loss durability, hostile-writer protection, remote-filesystem guarantees, permissions or timestamp preservation, or cryptographic authenticity. Snapshots are regular-file bytes and names only and cannot replace independent backups.
