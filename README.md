# GitLite

A Git-inspired version control system built from scratch in Python. Implements the core internals of how Git actually works - content-addressable blob storage, immutable commit objects with parent references, staging index, and unified diffs - without any external dependencies.

## How it works

```
Working directory
      │  git add
      ▼
  Index (staging)          ← index.json maps filename → blob hash
      │  git commit
      ▼
 Commit object             ← JSON with hash, timestamp, message, parent, files{}
      │
      ▼
 Blob store                ← .mygit/objects/blobs/<sha1> (raw file content)
```

Each file is stored exactly once by its SHA-1 hash - identical content across commits shares the same blob. Commits form a linked list via `parent` references, which is how `log` walks history.

## Commands

```bash
python main.py init                        # create .mygit/ directory
python main.py add <file> [file ...]       # stage one or more files
python main.py commit "message"            # snapshot staged files
python main.py log                         # walk commit history
python main.py checkout <commit-hash>      # restore files to a past commit
python main.py diff <file>                 # unified diff: HEAD vs working copy
python main.py status                      # show HEAD and staged files
```

## Getting Started

**Prerequisites:** Python 3.9+, no external packages needed.

```bash
git clone https://github.com/DhruvChamria/gitlite.git
cd gitlite

python main.py init
echo "hello" > test.txt
python main.py add test.txt
python main.py commit "first commit"
python main.py log
```

## Project Structure

```
gitlite/
├── main.py          # CLI entry point, command dispatch
├── repository.py    # Core VCS logic (init, add, commit, log, checkout, diff, status)
├── commit.py        # Commit dataclass + SHA-1 hash computation
└── utils.py         # sha1_bytes, JSON/text I/O, path helpers
```

At runtime, a `.mygit/` directory is created:

```
.mygit/
├── HEAD                        # stores current commit hash
├── index.json                  # staging area: { filename: blob_hash }
└── objects/
    ├── blobs/<sha1>             # raw file content, addressed by hash
    └── commits/<sha1>.json     # commit metadata + file snapshot
```

## Key Concepts Demonstrated

| Concept | Implementation |
|---|---|
| Content-addressable storage | `_save_blob` - files stored by SHA-1, deduped automatically |
| Immutable commit objects | `Commit.compute_hash()` - hash derived from content, not a counter |
| Linked commit history | Each commit stores `parent` hash; `log` walks the chain |
| Staging index | `index.json` accumulates adds; cleared after each commit |
| Unified diff | `difflib.unified_diff` comparing HEAD blob vs working file |
| Snapshot model | Each commit stores a full `{filename: blob_hash}` map, not deltas |
