# Reproducible demonstration

Run:

```console
python examples/demo.py
```

The script creates and cleans its own `<temp-dir>`, invokes the source wrapper with the active interpreter, generates bytes with Python, and checks every exit code. Key transcript excerpts are:

```text
Demo repository: <temp-dir>
$ gitlite init
Initialized empty GitLite repository in <temp-dir>/.mygit
$ gitlite add notes.txt
Staged notes.txt as blob <blob-id>
$ gitlite diff --staged
--- /dev/null
+++ b/notes.txt
@@ ...
+GitLite stores snapshots.
$ gitlite commit -m initial snapshot
Committed as <first-commit>
Parent: none
...
$ gitlite checkout <first-commit>
error: Checkout refused modified or missing tracked files: notes.txt
Restoring the demo's own known second-snapshot fixture bytes.
$ gitlite checkout <first-commit>
Checked out commit <first-commit>
...
$ gitlite log --all
commit <second-commit>
...
commit <first-commit> (HEAD)
...
$ gitlite show <second-commit>
commit <second-commit>
Parent: <first-commit>
Date:   <timestamp>
Message: explain state model
notes.txt <blob-id>
todo.txt <blob-id>
...
$ gitlite fsck
fsck OK: 2 commit(s), 3 blob(s).
Initial commit: <first-commit>
Second commit:  <second-commit>
The demo restored only data that it generated itself.
Temporary demo repository cleaned up.
```

The full output also shows H/I/W status, HEAD/worktree and staged diffs, removal staging that keeps the working file, unstaging, target-file removal during checkout, and hash-addressed object storage. Hashes, timestamps, and the temporary path vary by run.

## Two-minute interview walkthrough

1. Start with the three states: H is the current immutable snapshot, I is H plus the mutable index delta, and W is the filesystem. Point to the two status columns and the two diff modes.
2. Show that blob bytes and canonical commit payloads determine object IDs. Identical bytes deduplicate, while HEAD and the index are small mutable references.
3. Run the dirty checkout attempt. GitLite validates the full target and refuses to guess whether local bytes are disposable.
4. Restore the demo fixture, check out the older commit, and show that the target-only file disappears while unrelated files would remain.
5. Explain that atomic replacement protects one file, while the journal provides explicit rollback for a multi-file operation interrupted between replacements.
6. Finish with `log --all`, which retains alternate descendants, and `fsck`, which diagnoses rather than silently repairs or deletes.

Three useful talking points are the difference between immutable objects and mutable pointers, the H/I/W staging model, and why atomic single-file replacement still requires bounded multi-file recovery.
