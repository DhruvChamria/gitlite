const PYODIDE_BASE = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";
const MODULES = [
  "__init__.py",
  "errors.py",
  "models.py",
  "paths.py",
  "storage.py",
  "transactions.py",
  "repository.py",
  "cli.py",
];

const terminal = document.querySelector("#terminal");
const commandForm = document.querySelector("#command-form");
const commandInput = document.querySelector("#command-input");
const commandButton = commandForm.querySelector("button");
const filenameInput = document.querySelector("#filename");
const contentInput = document.querySelector("#file-content");
const fileStatus = document.querySelector("#file-status");
const saveButton = document.querySelector("#save-file");
const resetButton = document.querySelector("#reset-workspace");
const clearButton = document.querySelector("#clear-output");
const tourButton = document.querySelector("#run-tour");
const runtimeStatus = document.querySelector("#runtime-status");
const runtimeDot = document.querySelector("#runtime-dot");
const interactiveControls = [commandInput, commandButton, filenameInput, contentInput, saveButton, resetButton, tourButton, ...document.querySelectorAll(".step")];

let pyodide;
let busy = false;

function appendOutput(text, className = "") {
  const line = document.createElement("p");
  line.className = className;
  line.textContent = text;
  terminal.append(line);
  terminal.scrollTop = terminal.scrollHeight;
}

function setEnabled(enabled) {
  interactiveControls.forEach((control) => { control.disabled = !enabled; });
}

function setBusy(value) {
  busy = value;
  setEnabled(!value && Boolean(pyodide));
}

async function loadSource() {
  pyodide.FS.mkdirTree("/app/gitlite");
  await Promise.all(MODULES.map(async (name) => {
    const response = await fetch(`gitlite/${name}`);
    if (!response.ok) throw new Error(`Could not load GitLite module ${name} (${response.status})`);
    pyodide.FS.writeFile(`/app/gitlite/${name}`, await response.text(), { encoding: "utf8" });
  }));
}

function bootstrapPython() {
  pyodide.runPython(`
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import sys

sys.path.insert(0, "/app")
importlib.invalidate_caches()
from gitlite.cli import main as gitlite_main
from gitlite.paths import validate_stored_path

WORKSPACE = Path("/workspace")

def reset_workspace():
    os.chdir("/")
    if WORKSPACE.exists():
        shutil.rmtree(WORKSPACE)
    WORKSPACE.mkdir()
    os.chdir(WORKSPACE)
    return "Browser workspace reset."

def browser_run(command):
    args = shlex.split(command)
    if not args or args[0] != "gitlite":
        return json.dumps({"code": 2, "stdout": "", "stderr": "Only commands beginning with 'gitlite' are allowed."})
    stdout = io.StringIO()
    stderr = io.StringIO()
    os.chdir(WORKSPACE)
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = gitlite_main(args[1:])
            except SystemExit as exc:
                code = int(exc.code or 0)
    except Exception as exc:
        code = 1
        print(f"browser runtime error: {exc}", file=stderr)
    return json.dumps({"code": int(code or 0), "stdout": stdout.getvalue(), "stderr": stderr.getvalue()})

def browser_write(name, content):
    normalized = str(name).replace("\\\\", "/")
    validate_stored_path(normalized)
    path = WORKSPACE.joinpath(*normalized.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(content), encoding="utf-8")
    return normalized

reset_workspace()
  `);
}

function pythonCall(expression, values = {}) {
  Object.entries(values).forEach(([name, value]) => pyodide.globals.set(name, value));
  return pyodide.runPython(expression);
}

function executeCommand(command, { echo = true } = {}) {
  if (!pyodide) return { code: 1, stdout: "", stderr: "Runtime is not ready." };
  if (echo) appendOutput(`$ ${command}`, "command");
  const raw = pythonCall("browser_run(_browser_command)", { _browser_command: command });
  const result = JSON.parse(raw);
  if (result.stdout.trim()) appendOutput(result.stdout.trimEnd(), result.code === 0 ? "" : "error");
  if (result.stderr.trim()) appendOutput(result.stderr.trimEnd(), "error");
  return result;
}

function saveFile(name = filenameInput.value, content = contentInput.value, { announce = true } = {}) {
  try {
    const saved = pythonCall("browser_write(_browser_name, _browser_content)", {
      _browser_name: name,
      _browser_content: content,
    });
    filenameInput.value = saved;
    fileStatus.textContent = `Saved ${saved} in the browser working tree.`;
    if (announce) appendOutput(`wrote ${saved}`, "success");
    return true;
  } catch (error) {
    fileStatus.textContent = `Could not save: ${error.message}`;
    appendOutput(`file error: ${error.message}`, "error");
    return false;
  }
}

function resetWorkspace({ announce = true } = {}) {
  const message = pythonCall("reset_workspace()");
  if (announce) appendOutput(message, "success");
  fileStatus.textContent = "The editor writes only to the browser sandbox.";
}

async function runTour() {
  if (busy) return;
  setBusy(true);
  terminal.replaceChildren();
  appendOutput("Guided demo: immutable snapshots and conservative checkout", "success");
  try {
    resetWorkspace({ announce: false });
    executeCommand("gitlite init");
    saveFile("notes.txt", "GitLite stores snapshots.\n", { announce: true });
    executeCommand("gitlite add notes.txt");
    executeCommand("gitlite diff --staged");
    const first = executeCommand('gitlite commit -m "initial browser snapshot"');
    const firstId = first.stdout.match(/Committed as ([0-9a-f]{40})/)?.[1];

    saveFile("notes.txt", "GitLite stores immutable snapshots.\n", { announce: true });
    saveFile("todo.txt", "Explain H, I, and W.\n", { announce: true });
    executeCommand("gitlite status");
    executeCommand("gitlite add notes.txt todo.txt");
    const second = executeCommand('gitlite commit -m "explain state model"');
    const secondId = second.stdout.match(/Committed as ([0-9a-f]{40})/)?.[1];

    saveFile("notes.txt", "unsaved local edit\n", { announce: true });
    executeCommand(`gitlite checkout ${firstId}`);
    appendOutput("Checkout refused the local edit, so the demo restores only its own known fixture.", "success");
    saveFile("notes.txt", "GitLite stores immutable snapshots.\n", { announce: false });
    executeCommand(`gitlite checkout ${firstId}`);
    executeCommand("gitlite log --all");
    executeCommand(`gitlite show ${secondId}`);
    executeCommand("gitlite fsck");
    filenameInput.value = "notes.txt";
    contentInput.value = "GitLite stores snapshots.\n";
  } catch (error) {
    appendOutput(`tour error: ${error.message}`, "error");
  } finally {
    setBusy(false);
    commandInput.focus();
  }
}

async function initialize() {
  setEnabled(false);
  try {
    pyodide = await loadPyodide({ indexURL: PYODIDE_BASE });
    await loadSource();
    bootstrapPython();
    terminal.replaceChildren();
    appendOutput("GitLite 0.1.0 ready in an isolated CPython 3.14 browser runtime.", "success");
    appendOutput("Run the guided demo or enter a GitLite command below.", "muted-line");
    runtimeStatus.textContent = "Browser runtime ready";
    runtimeDot.className = "status-dot ready";
    setEnabled(true);
    commandInput.focus();
  } catch (error) {
    runtimeStatus.textContent = "Runtime failed to load";
    runtimeDot.className = "status-dot error";
    terminal.replaceChildren();
    appendOutput(`startup error: ${error.message}`, "error");
    appendOutput("Check your network connection; Pyodide is loaded from its versioned CDN.", "muted-line");
  }
}

commandForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const command = commandInput.value.trim();
  if (command) executeCommand(command);
});

saveButton.addEventListener("click", () => saveFile());
resetButton.addEventListener("click", () => resetWorkspace());
clearButton.addEventListener("click", () => terminal.replaceChildren());
tourButton.addEventListener("click", runTour);

document.querySelectorAll(".step").forEach((step) => {
  step.addEventListener("click", () => {
    if (step.dataset.action === "seed") {
      saveFile("notes.txt", contentInput.value);
    } else {
      executeCommand(step.dataset.command);
    }
  });
});

window.addEventListener("DOMContentLoaded", initialize);
