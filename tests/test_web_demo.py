from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WebDemoTests(unittest.TestCase):
    def test_static_demo_references_real_package_and_pinned_runtime(self):
        html = (ROOT / "web-demo/index.html").read_text(encoding="utf-8")
        script = (ROOT / "web-demo/app.js").read_text(encoding="utf-8")
        self.assertIn("pyodide/v314.0.7/full/pyodide.js", html)
        self.assertIn('const PYODIDE_BASE = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/"', script)
        self.assertIn('fetch(`gitlite/${name}`)', script)
        self.assertIn("from gitlite.cli import main as gitlite_main", script)
        self.assertIn("Only commands beginning with 'gitlite' are allowed.", script)
        self.assertNotIn("innerHTML", script)

    def test_pages_workflow_stages_demo_and_package(self):
        workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
        self.assertIn("cp -R web-demo/. _site/", workflow)
        self.assertIn("cp gitlite/*.py _site/gitlite/", workflow)
        self.assertIn("pyodide@314.0.7", workflow)
        self.assertIn("tests/browser_smoke.mjs", workflow)
        self.assertIn("actions/upload-pages-artifact@v4", workflow)
        self.assertIn("actions/deploy-pages@v4", workflow)
        self.assertIn("pages: write", workflow)
        self.assertIn("id-token: write", workflow)


if __name__ == "__main__":
    unittest.main()
