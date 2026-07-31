import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { loadPyodide } from "pyodide";

const root = process.argv[2];
if (!root) throw new Error("usage: node browser_smoke.mjs <repository-root>");

const modules = [
  "__init__.py",
  "errors.py",
  "models.py",
  "paths.py",
  "storage.py",
  "transactions.py",
  "repository.py",
  "cli.py",
];

const pyodide = await loadPyodide();
pyodide.FS.mkdirTree("/app/gitlite");
for (const name of modules) {
  const source = await readFile(path.join(root, "gitlite", name), "utf8");
  pyodide.FS.writeFile(`/app/gitlite/${name}`, source, { encoding: "utf8" });
}

pyodide.runPython(`
import contextlib, importlib, io, json, os, shlex, sys
from pathlib import Path
sys.path.insert(0, "/app")
importlib.invalidate_caches()
from gitlite.cli import main as gitlite_main
Path("/workspace").mkdir()
os.chdir("/workspace")

def smoke_run(command):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            code = gitlite_main(shlex.split(command)[1:])
        except SystemExit as exc:
            code = int(exc.code or 0)
    return json.dumps({"code": int(code or 0), "stdout": stdout.getvalue(), "stderr": stderr.getvalue()})
`);

function run(command) {
  pyodide.globals.set("_smoke_command", command);
  return JSON.parse(pyodide.runPython("smoke_run(_smoke_command)"));
}

assert.equal(run("gitlite init").code, 0);
pyodide.runPython('Path("notes.txt").write_text("browser bytes\\n", encoding="utf-8")');
assert.equal(run("gitlite add notes.txt").code, 0);
const committed = run('gitlite commit -m "browser smoke"');
assert.equal(committed.code, 0, committed.stderr);
assert.match(committed.stdout, /Committed as [0-9a-f]{40}/);
assert.match(run("gitlite status").stdout, /Working tree clean/);
assert.match(run("gitlite fsck").stdout, /fsck OK: 1 commit\(s\), 1 blob\(s\)/);
console.log("Pyodide browser smoke passed.");
