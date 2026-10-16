from __future__ import annotations

import unittest

import support  # noqa: F401
from hax_web import WebError
from hax_web.urls import validate_public_url


class UrlTests(unittest.TestCase):
    def test_accepts_public_http_urls(self) -> None:
        url = "https://example.com/a?q=1"
        self.assertEqual(validate_public_url(url), url)

    def test_rejects_non_http_and_credentials(self) -> None:
        with self.assertRaisesRegex(WebError, "http"):
            validate_public_url("file:///etc/passwd")
        with self.assertRaisesRegex(WebError, "credentials"):
            validate_public_url("https://user:secret@example.com/")

    def test_rejects_private_urls(self) -> None:
        for url in (
            "http://localhost/",
            "http://service.internal/",
            "http://127.0.0.1/",
            "http://10.0.0.1/",
            "http://224.0.0.1/",
            "http://[::1]/",
            "http://[ff02::1]/",
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(WebError, "private"):
                    validate_public_url(url)

    def test_rejects_ambiguous_ipv4_urls(self) -> None:
        for url in (
            "http://127.1/",
            "http://127.0.1/",
            "http://0177.0.0.1/",
            "http://0x7f.0.0.1/",
            "http://2130706433/",
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(WebError, "ambiguous IPv4"):
                    validate_public_url(url)

    def test_rejects_encoded_private_hosts(self) -> None:
        with self.assertRaisesRegex(WebError, "percent-encoding"):
            validate_public_url("http://%31%32%37.0.0.1/")

    def test_normalizes_unicode_hosts_before_validation(self) -> None:
        with self.assertRaisesRegex(WebError, "private"):
            validate_public_url("http://１２７.０.０.１/")
        url = "https://例え.テスト/"
        self.assertEqual(validate_public_url(url), url)


if __name__ == "__main__":
    unittest.main()
