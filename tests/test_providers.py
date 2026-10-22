from __future__ import annotations

import os
import unittest
from typing import Optional
from unittest import mock

import support  # noqa: F401
from hax_web import WebError, codex, exa
from hax_web.providers import describe_providers, select_provider


class SelectionTests(unittest.TestCase):
    def use(
        self, environ: dict[str, str], exa_reason: Optional[str], codex_reason: Optional[str]
    ) -> None:
        for patch in (
            mock.patch.dict(os.environ, environ, clear=True),
            mock.patch.object(exa, "unavailable", return_value=exa_reason),
            mock.patch.object(codex, "unavailable", return_value=codex_reason),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_auto_detection_follows_registry_order(self) -> None:
        self.use({}, None, None)
        self.assertIs(select_provider(None), exa)

    def test_auto_detection_skips_unavailable_providers(self) -> None:
        self.use({}, "EXA_API_KEY is not set", None)
        self.assertIs(select_provider(None), codex)

    def test_environment_overrides_auto_detection(self) -> None:
        self.use({"HAX_WEB_PROVIDER": "codex"}, None, None)
        self.assertIs(select_provider(None), codex)

    def test_flag_overrides_environment(self) -> None:
        self.use({"HAX_WEB_PROVIDER": "codex"}, None, None)
        self.assertIs(select_provider("exa"), exa)

    def test_named_provider_is_selected_even_when_unavailable(self) -> None:
        self.use({"HAX_WEB_PROVIDER": "codex"}, None, "no login")
        self.assertIs(select_provider(None), codex)

    def test_unknown_environment_provider_is_rejected(self) -> None:
        self.use({"HAX_WEB_PROVIDER": "bing"}, None, None)
        with self.assertRaisesRegex(WebError, "unknown provider 'bing'"):
            select_provider(None)

    def test_no_available_provider_lists_each_reason(self) -> None:
        self.use({}, "EXA_API_KEY is not set", "no login")
        with self.assertRaisesRegex(WebError, "exa: EXA_API_KEY is not set; codex: no login"):
            select_provider(None)

    def test_description_shows_status_and_selection(self) -> None:
        cases = (
            ({}, "Selected: codex (auto-detected)"),
            ({"HAX_WEB_PROVIDER": "exa"}, "Selected: exa (from HAX_WEB_PROVIDER)"),
        )
        for environ, selection in cases:
            with self.subTest(selection=selection):
                self.use(environ, "EXA_API_KEY is not set", None)
                self.assertEqual(
                    describe_providers(),
                    f"exa    EXA_API_KEY is not set\ncodex  ready\n\n{selection}\n",
                )

    def test_description_reports_no_available_provider(self) -> None:
        self.use({}, "EXA_API_KEY is not set", "no login")
        self.assertTrue(describe_providers().endswith("\nNo provider is available.\n"))


if __name__ == "__main__":
    unittest.main()
