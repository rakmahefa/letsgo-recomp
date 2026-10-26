#!/usr/bin/env python3
"""Prevent the frozen generator spec from excluding imports needed by Unicorn at startup."""
from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LasgenSpecTests(unittest.TestCase):
    def test_pkg_resources_is_included_not_excluded(self) -> None:
        spec = (ROOT / "tools" / "lasgen.spec").read_text(encoding="utf-8")
        excludes = re.search(r"\bexcludes\s*=\s*\[(.*?)\]", spec, re.S)
        self.assertIsNotNone(excludes, "lasgen.spec must declare explicit exclusions")
        self.assertNotRegex(
            excludes.group(1),
            r"""['"]pkg_resources['"]""",
            "pkg_resources is required by Unicorn's libunicorn loader and must not be excluded",
        )
        self.assertIn(
            "collect_submodules('pkg_resources')",
            spec,
            "dynamically imported pkg_resources submodules must be collected by PyInstaller",
        )
        self.assertIn(
            "collect_submodules('unicorn')",
            spec,
            "Unicorn architecture modules are loaded dynamically and must remain bundled",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
