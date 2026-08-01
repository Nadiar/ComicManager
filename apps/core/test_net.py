"""Cover downloads must not reach local files or LAN hosts."""

import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request

from django.test import SimpleTestCase, TestCase

from apps.core import cover_cache
from apps.core.net import UnsafeURLError, _CheckedRedirectHandler, check_url, host_matches


class CheckUrlTests(SimpleTestCase):

    def test_rejects_non_http_schemes(self):
        for url in ("file:///proc/self/environ", "ftp://example.com/a.jpg", "gopher://x", ""):
            with self.assertRaises(UnsafeURLError, msg=url):
                check_url(url)

    def test_rejects_local_and_private_addresses(self):
        for url in ("http://127.0.0.1/", "http://localhost:8000/", "http://[::1]/",
                    "http://192.168.1.10/x.jpg", "http://10.0.0.1/", "http://169.254.169.254/"):
            with self.assertRaises(UnsafeURLError, msg=url):
                check_url(url)

    def test_accepts_public_address(self):
        check_url("https://93.184.216.34/cover.jpg")

    def test_redirect_to_private_address_refused(self):
        handler = _CheckedRedirectHandler()
        req = Request("https://93.184.216.34/a.jpg")
        with self.assertRaises(UnsafeURLError):
            handler.redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1/secret")

    def test_host_matches(self):
        self.assertTrue(host_matches("https://inducks.org/hr.php?x", "inducks.org"))
        self.assertTrue(host_matches("https://www.inducks.org/x", "inducks.org"))
        self.assertFalse(host_matches("https://inducks.org.evil.com/x", "inducks.org"))
        self.assertFalse(host_matches("https://evilinducks.org/x", "inducks.org"))


class CoverProxyTests(TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(cover_cache, "COVER_CACHE_DIR", Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)

    def test_cv_cover_does_not_read_local_files(self):
        resp = self.client.get("/comics/cv-cover/1/?url=file:///proc/self/environ")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_inducks_login_not_sent_to_other_hosts(self):
        from apps.core.models import Setting
        Setting.objects.update_or_create(key="inducks_username", defaults={"value": "u", "label": "u"})
        Setting.objects.update_or_create(key="inducks_password", defaults={"value": "p", "label": "p"})
        with patch.object(cover_cache, "safe_fetch", return_value=b"img") as fetch:
            cover_cache.get_inducks_cover("x", "https://example.com/hr.php")
            self.assertNotIn("Authorization", fetch.call_args[0][1])
            cover_cache.get_inducks_cover("y", "https://inducks.org/hr.php?image=a")
            self.assertIn("Authorization", fetch.call_args[0][1])
