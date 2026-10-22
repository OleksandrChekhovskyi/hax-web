from __future__ import annotations

import os
import unittest
from typing import Optional
from unittest import mock

import support  # noqa: F401
from hax_web import WebError, codex, deepseek, exa
from hax_web.providers import PROVIDERS, describe_providers, select_provider


class SelectionTests(unittest.TestCase):
    def use(self, environ: dict[str, str], **reasons: Optional[str]) -> None:
        """Set the environment and make each provider available unless `reasons` names why not."""
        environ_patch = mock.patch.dict(os.environ, environ, clear=True)
        environ_patch.start()
        self.addCleanup(environ_patch.stop)
        for name, provider in PROVIDERS.items():
            patch = mock.patch.object(provider, "unavailable", return_value=reasons.get(name))
            patch.start()
            self.addCleanup(patch.stop)

    def test_auto_detection_follows_registry_order(self) -> None:
        self.use({})
        self.assertIs(select_provider(None), exa)

    def test_auto_detection_skips_unavailable_providers(self) -> None:
        self.use({}, exa="no key")
        self.assertIs(select_provider(None), deepseek)
        self.use({}, exa="no key", deepseek="no key")
        self.assertIs(select_provider(None), codex)

    def test_environment_overrides_auto_detection(self) -> None:
        self.use({"HAX_WEB_PROVIDER": "codex"})
        self.assertIs(select_provider(None), codex)

    def test_flag_overrides_environment(self) -> None:
        self.use({"HAX_WEB_PROVIDER": "codex"})
        self.assertIs(select_provider("exa"), exa)

    def test_named_provider_is_selected_even_when_unavailable(self) -> None:
        self.use({"HAX_WEB_PROVIDER": "codex"}, codex="no login")
        self.assertIs(select_provider(None), codex)

    def test_unknown_environment_provider_is_rejected(self) -> None:
        self.use({"HAX_WEB_PROVIDER": "bing"})
        with self.assertRaisesRegex(WebError, "unknown provider 'bing'"):
            select_provider(None)

    def test_no_available_provider_lists_each_reason(self) -> None:
        self.use({}, exa="no exa key", deepseek="no deepseek key", codex="no login")
        message = "exa: no exa key; deepseek: no deepseek key; codex: no login"
        with self.assertRaisesRegex(WebError, message):
            select_provider(None)

    def test_description_shows_status_and_selection(self) -> None:
        cases = (
            ({}, "Selected: codex (auto-detected)"),
            ({"HAX_WEB_PROVIDER": "exa"}, "Selected: exa (from HAX_WEB_PROVIDER)"),
        )
        for environ, selection in cases:
            with self.subTest(selection=selection):
                self.use(environ, exa="no exa key", deepseek="no deepseek key")
                self.assertEqual(
                    describe_providers(),
                    "exa       no exa key\n"
                    "deepseek  no deepseek key\n"
                    f"codex     ready\n\n{selection}\n",
                )

    def test_description_reports_no_available_provider(self) -> None:
        self.use({}, exa="no key", deepseek="no key", codex="no login")
        self.assertTrue(describe_providers().endswith("\nNo provider is available.\n"))


if __name__ == "__main__":
    unittest.main()
