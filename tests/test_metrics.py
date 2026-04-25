from __future__ import annotations


__copyright__ = "Copyright (C) 2025 Andreas Kloeckner"

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

import http.client
from unittest import mock

import pytest
from django.test import TestCase, override_settings
from django.urls import reverse


FAKE_TOKEN = "test-secret-token-123"

SAMPLE_METRICS = b"""# HELP granian_requests_total Total HTTP requests
# TYPE granian_requests_total counter
granian_requests_total 42
"""


class FakeHTTPResponse:
    """Minimal stub for http.client.HTTPResponse."""

    def __init__(self, status: int = 200, body: bytes = SAMPLE_METRICS,
                 content_type: str = "text/plain; version=0.0.4") -> None:
        self.status = status
        self._body = body
        self._content_type = content_type

    def read(self) -> bytes:
        return self._body

    def getheader(self, name: str, default: str | None = None) -> str | None:
        if name == "Content-Type":
            return self._content_type
        return default


class MetricsViewTest(TestCase):
    """Tests for relate.metrics.metrics view."""

    def _get(self, token: str | None = None, extra: dict | None = None):
        headers: dict = {}
        if token is not None:
            headers["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        if extra:
            headers.update(extra)
        return self.client.get(reverse("relate-metrics"), **headers)

    # {{{ token not configured → 404

    def test_no_token_configured_returns_404(self):
        # RELATE_METRICS_TOKEN is not in the test settings by default.
        resp = self._get()
        self.assertEqual(resp.status_code, 404)

    def test_empty_token_configured_returns_404(self):
        with override_settings(RELATE_METRICS_TOKEN=""):
            resp = self._get()
            self.assertEqual(resp.status_code, 404)

    # }}}

    # {{{ authentication checks

    @override_settings(RELATE_METRICS_TOKEN=FAKE_TOKEN)
    def test_no_auth_header_returns_401(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 401)
        self.assertIn("WWW-Authenticate", resp)

    @override_settings(RELATE_METRICS_TOKEN=FAKE_TOKEN)
    def test_wrong_scheme_returns_401(self):
        resp = self._get(extra={"HTTP_AUTHORIZATION": "Basic dXNlcjpwYXNz"})
        self.assertEqual(resp.status_code, 401)

    @override_settings(RELATE_METRICS_TOKEN=FAKE_TOKEN)
    def test_wrong_token_returns_403(self):
        resp = self._get(token="wrong-token")
        self.assertEqual(resp.status_code, 403)

    # }}}

    # {{{ successful proxy

    @override_settings(RELATE_METRICS_TOKEN=FAKE_TOKEN,
                       RELATE_GRANIAN_METRICS_PORT=19090)
    def test_correct_token_proxies_metrics(self):
        fake_conn = mock.MagicMock(spec=http.client.HTTPConnection)
        fake_conn.getresponse.return_value = FakeHTTPResponse()

        with mock.patch("http.client.HTTPConnection",
                        return_value=fake_conn) as mock_conn_cls:
            resp = self._get(token=FAKE_TOKEN)

        mock_conn_cls.assert_called_once_with("127.0.0.1", 19090, timeout=5)
        fake_conn.request.assert_called_once_with("GET", "/metrics")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, SAMPLE_METRICS)
        self.assertIn("text/plain", resp.get("Content-Type", ""))

    def test_default_port_9090(self):
        """When RELATE_GRANIAN_METRICS_PORT is absent the default is 9090."""
        fake_conn = mock.MagicMock(spec=http.client.HTTPConnection)
        fake_conn.getresponse.return_value = FakeHTTPResponse()

        with override_settings(RELATE_METRICS_TOKEN=FAKE_TOKEN):
            # RELATE_GRANIAN_METRICS_PORT is intentionally absent so the
            # view should fall back to the default port of 9090.
            with mock.patch("http.client.HTTPConnection",
                            return_value=fake_conn) as mock_conn_cls:
                resp = self._get(token=FAKE_TOKEN)

        mock_conn_cls.assert_called_once_with("127.0.0.1", 9090, timeout=5)
        self.assertEqual(resp.status_code, 200)

    # }}}

    # {{{ granian server unavailable

    @override_settings(RELATE_METRICS_TOKEN=FAKE_TOKEN)
    def test_granian_unavailable_returns_503(self):
        with mock.patch("http.client.HTTPConnection") as mock_conn_cls:
            mock_conn_cls.side_effect = OSError("Connection refused")
            resp = self._get(token=FAKE_TOKEN)

        self.assertEqual(resp.status_code, 503)

    @override_settings(RELATE_METRICS_TOKEN=FAKE_TOKEN)
    def test_granian_request_os_error_returns_503(self):
        fake_conn = mock.MagicMock(spec=http.client.HTTPConnection)
        fake_conn.request.side_effect = OSError("Connection refused")

        with mock.patch("http.client.HTTPConnection", return_value=fake_conn):
            resp = self._get(token=FAKE_TOKEN)

        self.assertEqual(resp.status_code, 503)

    # }}}


@pytest.mark.django_db
def test_metrics_url_resolves():
    """Smoke test that the URL reverses correctly."""
    url = reverse("relate-metrics")
    assert url == "/metrics"
