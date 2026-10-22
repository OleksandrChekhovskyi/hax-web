from __future__ import annotations

import io
import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

from support import ROOT
from hax_web import VERSION, cli, exa


class CliTests(unittest.TestCase):
    def test_json_output_is_normalized(self) -> None:
        result = {"query": "q", "results": []}
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {"AI_AGENT": "hax"}):
            with mock.patch.object(exa, "search", return_value=result):
                with mock.patch("sys.stdout", stdout):
                    cli.main(["search", "q", "--json", "--provider", "exa"])
        self.assertEqual(json.loads(stdout.getvalue()), result)

    def test_launcher_works_through_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            link = pathlib.Path(directory) / "hax-web"
            link.symlink_to(ROOT / "hax-web")
            result = subprocess.run(
                [str(link), "--version"],
                check=False,
                text=True,
                capture_output=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f"hax-web {VERSION}")

    def test_launcher_ignores_modules_in_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pathlib.Path(directory, "json.py").write_text("raise SystemExit('shadowed')\n")
            result = subprocess.run(
                [str(ROOT / "hax-web"), "--version"],
                check=False,
                text=True,
                capture_output=True,
                cwd=directory,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
