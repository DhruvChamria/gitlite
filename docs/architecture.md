# Architecture

GitLite separates three states:

```text
H: HEAD snapshot -----------+-----------------------+
                            |                       |
                            v                       v
I: apply index delta to H --+-- staged diff     immutable objects
                            |
                            v
W: regular files on disk ---+-- working diff
```

`status` shows H→I in its first column and I→W in its second. Default `diff` deliberately compares H→W; `diff --staged` compares H→I.

## Content addressing

Blob IDs are SHA-1 hashes of raw bytes. Identical bytes share one object. A commit contains a complete path-to-blob snapshot:

```json
{
  "hash": "0123456789abcdef0123456789abcdef01234567",
  "parent": null,
  "timestamp": "2026-09-25T05:00:00.000000+00:00",
  "message": "initial notes",
  "files": {"notes.txt": "1111111111111111111111111111111111111111"}
}
```

The commit digest excludes `hash` and hashes UTF-8 bytes from `json.dumps(payload, sort_keys=True, separators=(",", ":"))`, using the default ASCII escaping. This preserves the original GitLite object format.

The index is a delta, for example `{"changed.txt": "<blob-id>", "removed.txt": null}`. Applying it to H produces I. A `null` value is a staged deletion; old indexes containing only strings remain readable.

## History model

Each commit stores one parent and HEAD stores one current commit ID. Checking out an older snapshot and committing creates another descendant of that selected snapshot. There are no named branches, but the other immutable commits remain available through `log --all`. Compression, deltas, garbage collection, branches, and merges are omitted so the object and safety model stays inspectable.

## Modules

- `cli.py` parses commands and renders user-facing results.
- `errors.py` defines expected domain failures.
- `models.py` defines immutable commits and results.
- `paths.py` handles discovery, portable names, collisions, exclusions, and link guards.
- `storage.py` validates objects, performs atomic file replacement, and owns the OS lock.
- `transactions.py` validates and rolls back the bounded commit/checkout journal.
- `repository.py` implements staging, snapshots, status, diff, checkout, history, and integrity checks.

Single metadata files are replaced atomically. Multi-file checkout cannot be globally atomic, so it uses a validated journal and explicit rollback instead.
