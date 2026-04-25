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

import hmac
import http.client
from typing import TYPE_CHECKING

from django.conf import settings
from django.http import Http404, HttpResponse


if TYPE_CHECKING:
    from django.http import HttpRequest


def metrics(request: HttpRequest) -> HttpResponse:
    """Proxy Granian's Prometheus metrics, protected by a bearer token.

    The endpoint is only active when :setting:`RELATE_METRICS_TOKEN` is
    configured in ``local_settings.py``.  Prometheus should be configured to
    send::

        Authorization: Bearer <RELATE_METRICS_TOKEN>

    Granian must be started with ``--metrics`` (or
    ``GRANIAN_METRICS=true``) so that its internal metrics server is running
    on ``127.0.0.1:<RELATE_GRANIAN_METRICS_PORT>`` (default port 9090).
    """

    token: str | None = getattr(settings, "RELATE_METRICS_TOKEN", None)
    if not token:
        raise Http404

    # Validate the bearer token.
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Bearer "):
        return HttpResponse(
            "Unauthorized",
            status=401,
            headers={"WWW-Authenticate": 'Bearer realm="RELATE metrics"'},
        )

    provided_token = auth_header[len("Bearer "):]
    if not hmac.compare_digest(provided_token, token):
        return HttpResponse(
            "Forbidden",
            status=403,
        )

    # Fetch metrics from Granian's internal metrics server.
    metrics_port: int = getattr(settings, "RELATE_GRANIAN_METRICS_PORT", 9090)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", metrics_port, timeout=5)
        try:
            conn.request("GET", "/metrics")
            resp = conn.getresponse()
            body = resp.read()
            content_type = resp.getheader("Content-Type", "text/plain; version=0.0.4")
        finally:
            conn.close()
    except OSError:
        return HttpResponse(
            "Metrics unavailable: could not connect to Granian metrics server.\n"
            "Ensure Granian is started with --metrics "
            f"(port {metrics_port}).\n",
            status=503,
            content_type="text/plain",
        )

    return HttpResponse(body, content_type=content_type, status=resp.status)
