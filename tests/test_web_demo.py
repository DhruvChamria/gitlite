import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WebDemoTests(unittest.TestCase):
    def test_static_demo_references_real_package_and_bundled_runtime(self):
        html = (ROOT / "web-demo/index.html").read_text(encoding="utf-8")
        script = (ROOT / "web-demo/app.js").read_text(encoding="utf-8")
        self.assertIn('src="pyodide/pyodide.js"', html)
        self.assertNotIn("cdn.jsdelivr.net", html)
        self.assertIn('const PYODIDE_BASE = "./pyodide/"', script)
        self.assertIn('fetch(`gitlite/${name}`)', script)
        self.assertIn("from gitlite.cli import main as gitlite_main", script)
        self.assertIn("Only commands beginning with 'gitlite' are allowed.", script)
        self.assertNotIn("innerHTML", script)

    def test_pages_workflow_stages_demo_and_package(self):
        workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
        self.assertIn("cp -R web-demo/. _site/", workflow)
        self.assertIn("cp gitlite/*.py _site/gitlite/", workflow)
        self.assertIn("npm ci --ignore-scripts", workflow)
        self.assertIn("cp -R node_modules/pyodide _site/pyodide", workflow)
        self.assertIn("tests/browser_smoke.mjs", workflow)
        self.assertIn("pages: write", workflow)
        self.assertIn("id-token: write", workflow)

    def test_browser_runtime_is_exactly_locked(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
        self.assertTrue(package["private"])
        self.assertEqual(package["devDependencies"]["pyodide"], "314.0.7")
        locked = lock["packages"]["node_modules/pyodide"]
        self.assertEqual(locked["version"], "314.0.7")
        self.assertTrue(locked["integrity"].startswith("sha512-"))

    def test_all_official_actions_are_immutably_pinned(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            workflow = path.read_text(encoding="utf-8")
            action_refs = re.findall(r"uses: (actions/[^@\s]+)@([^\s]+)", workflow)
            self.assertTrue(action_refs, path.name)
            for action, reference in action_refs:
                self.assertRegex(reference, r"^[0-9a-f]{40}$", action)


if __name__ == "__main__":
    unittest.main()
