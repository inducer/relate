"""Real-engine security checks; run with --slow and optional Playwright browsers.

No Django live server, database, or authentication fixtures are needed: the HTTP
fixture serves the actual response builders' bytes and headers. Authorization is
covered by test_answer_resources.py. The attack shell deliberately bypasses the
sanitizer to test CSP independently, not to claim CSP blocks all navigation.
"""

from __future__ import annotations

import base64
import json
import secrets
import shutil
import struct
import threading
import zlib
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import nbformat
import pytest
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from course.answer_resources import _harden_response, _preview_response


if TYPE_CHECKING:
    from collections.abc import Iterator


pytestmark = pytest.mark.slow
_CHANNEL = "browser_security_channel_" + "a" * 32


def _png() -> str:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    image = (b"\x89PNG\r\n\x1a\n"
             + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
             + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
             + chunk(b"IEND", b""))
    return base64.b64encode(image).decode("ascii")


def _hostile_notebook(origin: str) -> bytes:
    endpoint = origin + "/attack"
    attack = f"""
<p id="safe-target">Visible saved output</p>
<a href="#safe-target">Safe fragment</a>
<script>window.notebookExecuted = true; top.location = '{endpoint}/script';</script>
<script src="{endpoint}/script.js"></script>
<img src="{endpoint}/image" srcset="{endpoint}/srcset 2x"
     onerror="window.notebookExecuted = true">
<svg onload="window.notebookExecuted = true"><image href="{endpoint}/svg"/></svg>
<math><mtext><table><mglyph><style><!--</style><img title="--><img
 src='{endpoint}/repair' onerror='window.notebookExecuted = true'>">
</table></mtext></math>
</div></body><head><meta http-equiv="refresh" content="0;url={endpoint}/meta">
<base href="{endpoint}/base"><link rel="stylesheet" href="{endpoint}/css"></head><body>
<form action="{endpoint}/form" target="_top"><input name="secret">
<button>Submit</button></form>
<iframe src="{endpoint}/frame"
 srcdoc="<script>top.location='{endpoint}/srcdoc'</script>"></iframe>
<object data="{endpoint}/object"></object>
<a href="{endpoint}/link" target="_top" ping="{endpoint}/ping">External link</a>
<a href="javascript:window.notebookExecuted=true">Script link</a>
<style>body, #grading-controls {{ display:none }}
body {{ background:url('{endpoint}/background') }}</style>
<div style="position:fixed;inset:0;z-index:2147483647" id="grading-controls">
Notebook cannot hide the real controls</div>
"""
    notebook = nbformat.v4.new_notebook(cells=[
        nbformat.v4.new_markdown_cell(attack + "\n![Remote](" + endpoint + "/md)"),
        nbformat.v4.new_code_cell(
            "raise RuntimeError('Notebook code must never execute')",
            outputs=[nbformat.v4.new_output("display_data", data={
                "text/html": attack,
                "application/javascript": "window.notebookExecuted = true",
            }), nbformat.v4.new_output("display_data", data={"image/png": _png()})]),
    ], metadata={"trusted": True})
    return json.dumps(notebook).encode()


@dataclass
class BrowserSite:
    origin: str = ""
    requests: list[tuple[str, dict[str, str]]] = field(default_factory=list)


@pytest.fixture(scope="module")
def notebook_site() -> Iterator[BrowserSite]:
    site = BrowserSite()
    responses: dict[str, HttpResponse] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            site.requests.append((self.path, dict(self.headers.items())))
            response = responses.get(urlsplit(self.path).path)
            if response is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(response.status_code)
            for name, value in response.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        def do_POST(self) -> None:
            self.do_GET()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    site.origin = f"http://127.0.0.1:{server.server_port}"
    request = RequestFactory().get("/preview", HTTP_HOST=urlsplit(site.origin).netloc)
    script_nonce, style_nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    with override_settings(RELATE_BASE_URL=site.origin):
        responses["/preview"] = _harden_response(_preview_response(
            request, _hostile_notebook(site.origin), _CHANNEL,
            script_nonce, style_nonce), script_nonce, style_nonce)
        # No automatic resize messages: isolates forged-message tests from the
        # trusted child's ResizeObserver rather than racing against it.
        responses["/quiet-preview"] = _harden_response(_preview_response(
            request, _hostile_notebook(site.origin), None,
            script_nonce, style_nonce), script_nonce, style_nonce)
    assert responses["/preview"].status_code == 200
    assert responses["/quiet-preview"].status_code == 200

    endpoint = site.origin + "/attack"
    shell = f"""<!doctype html><html><head>
<script nonce="{script_nonce}">
window.violations = [];
document.addEventListener('securitypolicyviolation', event => {{
  window.violations.push(event.effectiveDirective);
}});
window.trustedShellRan = true;
</script>
<base href="{endpoint}/base">
<link rel="stylesheet" href="{endpoint}/css">
<style>body {{ background:url('{endpoint}/background') }}</style>
</head><body>
<script>window.notebookExecuted = true;</script>
<script src="{endpoint}/script.js"></script>
<img src="{endpoint}/image" onerror="window.notebookExecuted = true">
<svg onload="window.notebookExecuted = true"></svg>
<iframe src="{endpoint}/frame"></iframe>
<object data="{endpoint}/object"></object>
<form action="{endpoint}/form"><button>Submit attack</button></form>
<div id="inline-style" style="position:fixed">CSP attack shell</div>
</body></html>"""
    responses["/shell"] = _harden_response(
        HttpResponse(shell), script_nonce, style_nonce)
    source = (Path(__file__).parents[1] / "frontend/js/rlUtils.js").read_text()
    source = source.split("export function enablePreviewForNotebookUpload()", 1)[1]
    source = "function enablePreviewForNotebookUpload()" + source.split("// }}}", 1)[0]
    responses["/frontend.js"] = HttpResponse(
        source + "\nenablePreviewForNotebookUpload();", content_type="text/javascript")
    for path, preview in [("/parent", "/preview"), ("/quiet-parent", "/quiet-preview")]:
        responses[path] = HttpResponse(f"""<!doctype html><html><head>
<link rel="icon" href="data:,">
</head><body>
<form id="grading-controls"><label>Grade <input value="7"></label>
<button type="button">Save grade</button></form>
<div class="relate-notebook-preview" data-preview-url="{preview}?channel={_CHANNEL}">
<p class="relate-notebook-status" data-loading="loading" data-ready="ready"
 data-error="error" data-unsupported="unsupported"></p>
<div class="relate-notebook-frame" data-title="Submitted notebook"></div>
<a class="relate-notebook-standalone" href="{preview}?channel={_CHANNEL}"
 rel="noopener noreferrer" hidden>Open preview</a>
</div><script src="/frontend.js"></script></body></html>""")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield site
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive(), "Preview HTTP server did not stop"


@pytest.fixture(scope="module", params=["chromium", "firefox", "webkit"])
def browser_engine(request: Any) -> Iterator[Any]:
    playwright = pytest.importorskip(
        "playwright.sync_api", reason="Optional Playwright package is not installed")
    with playwright.sync_playwright() as engines:
        engine = getattr(engines, request.param)
        options: dict[str, Any] = {"headless": True, "timeout": 20000}
        if (request.param == "chromium" and not Path(engine.executable_path).exists()
                and shutil.which("chromium")):
            options["executable_path"] = shutil.which("chromium")
        try:
            browser = engine.launch(**options)
        except playwright.Error as exc:
            # Do not hide test failures or unexpected crashes as availability skips.
            unavailable = ("Executable doesn't exist",
                           "Host system is missing dependencies",
                           "error while loading shared libraries")
            if any(message in str(exc) for message in unavailable):
                pytest.skip(f"{request.param} unavailable: {exc}")
            raise
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def browser_page(browser_engine: Any, notebook_site: BrowserSite) -> Iterator[Any]:
    context = browser_engine.new_context(viewport={"width": 1000, "height": 800})
    context.add_cookies([{"name": "lms-secret", "value": "notebook-must-not-read",
                         "url": notebook_site.origin}])
    page = context.new_page()
    page.set_default_timeout(10000)
    try:
        yield page
    finally:
        context.close()


def _realm_probe(frame: Any, *, embedded: bool) -> dict[str, Any]:
    # Automation runs this independently of notebook JS. It verifies the actual
    # realm's privileges; it is not evidence that CSP allowed this script to run.
    return frame.evaluate("""embedded => {
      const denied = fn => {try {fn(); return false;} catch (e) {
        return e.name === 'SecurityError';
      }};
      return {
        cookie: denied(() => document.cookie),
        localStorage: denied(() => localStorage.getItem('lms-secret')),
        sessionStorage: denied(() => sessionStorage.getItem('lms-secret')),
        parent: embedded ? denied(() => parent.document.body.innerHTML) : true,
        executed: window.notebookExecuted === true,
      };
    }""", embedded)


def _assert_no_attacks(page: Any, site: BrowserSite, start: int,
                       requests: list[str],
                       blocked: list[tuple[str, str]] | None = None) -> None:
    # Chromium emits request events even for CSP-blocked loads; Firefox does not.
    # Sanitized notebooks must not even attempt them. The unsanitized shell must
    # prove each reported attempt was blocked by policy before reaching the wire.
    attacks = [url for url in requests if "/attack" in url]
    if blocked is None:
        assert not attacks
    else:
        for url in attacks:
            assert any(failed_url == url and (failure == "csp"
                       or "BLOCKED_BY_CSP" in failure)
                       for failed_url, failure in blocked), (url, blocked)
    assert not [path for path, _headers in site.requests[start:] if "/attack" in path]
    assert len(page.context.pages) == 1, "Notebook opened a popup"


@pytest.mark.parametrize("embedded", [True, False], ids=["iframe", "direct-url"])
def test_hostile_notebook_browser(browser_page: Any, notebook_site: BrowserSite,
                                  embedded: bool) -> None:
    page = browser_page
    start = len(notebook_site.requests)
    requests: list[str] = []

    def record_request(request: Any) -> None:
        requests.append(request.url)

    page.on("request", record_request)
    navigations: list[str] = []

    def record_navigation(frame: Any) -> None:
        navigations.append(frame.url)

    page.on("framenavigated", record_navigation)
    path = "/parent" if embedded else "/preview?channel=" + _CHANNEL
    response = page.goto(notebook_site.origin + path)
    assert response is not None and response.status == 200
    if embedded:
        page.wait_for_function("""() => document.querySelector(
            '.relate-notebook-status').textContent === 'ready'""")
        frame = page.frames[1]
        iframe = page.locator("iframe")
        assert iframe.get_attribute("sandbox") == "allow-scripts"
        assert iframe.get_attribute("referrerpolicy") == "no-referrer"
        assert iframe.get_attribute("title") == "Submitted notebook"
        assert not page.locator(".relate-notebook-standalone").is_hidden()
        assert page.locator("#grading-controls").is_visible()
        assert page.locator("#grading-controls input").input_value() == "7"
        preview_headers = next(
            headers for url, headers in notebook_site.requests[start:]
            if url.startswith("/preview"))
        assert "notebook-must-not-read" in preview_headers.get("Cookie", "")
        assert not preview_headers.get("Referer")
        page.evaluate("enablePreviewForNotebookUpload()")
        assert page.locator("iframe").count() == 1
    else:
        frame = page.main_frame
        assert "sandbox allow-scripts" in response.headers["content-security-policy"]
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-content-type-options"] == "nosniff"
    assert _realm_probe(frame, embedded=embedded) == {
        "cookie": True, "localStorage": True, "sessionStorage": True,
        "parent": True, "executed": False,
    }
    assert frame.locator("#relate-notebook").is_visible()
    assert "Visible saved output" in frame.locator("body").inner_text()
    assert "were not reproduced by execution" in frame.locator("body").inner_text()
    assert frame.locator(
        "#relate-notebook script, #relate-notebook style, "
        "svg, math, meta[http-equiv], base, form, object, iframe").count() == 0
    assert frame.evaluate("""() => Array.from(
      document.querySelectorAll('#relate-notebook *'))
      .every(node => Array.from(node.attributes).every(attr =>
        !/^on/i.test(attr.name) && !['style', 'srcset', 'ping', 'target', 'nonce',
                                   'action', 'srcdoc'].includes(attr.name)))""")
    image = frame.locator('img[src^="data:image/png"]').first
    image.wait_for(state="visible")
    assert image.evaluate("image => image.complete && image.naturalWidth === 1")
    assert image.screenshot().startswith(b"\x89PNG\r\n\x1a\n")
    before = len(navigations)
    frame.locator('a[href="#safe-target"]').first.click()
    page.wait_for_timeout(400)
    assert frame.url.endswith("#safe-target")
    assert all(url.split("#", 1)[0] == frame.url.split("#", 1)[0]
               for url in navigations[before:])
    frame.get_by_text("External link", exact=True).first.click()
    frame.get_by_text("Script link", exact=True).first.click()
    page.wait_for_timeout(400)
    expected_url = notebook_site.origin + path + ("" if embedded else "#safe-target")
    assert page.url == expected_url
    if embedded:
        assert page.locator("#grading-controls button").is_visible()
    _assert_no_attacks(page, notebook_site, start, requests)


@pytest.mark.parametrize("embedded", [True, False], ids=["iframe", "direct-url"])
def test_preview_csp_without_sanitizer(browser_page: Any, notebook_site: BrowserSite,
                                      embedded: bool) -> None:
    page = browser_page
    start = len(notebook_site.requests)
    requests: list[str] = []
    blocked: list[tuple[str, str]] = []

    def record_request(request: Any) -> None:
        requests.append(request.url)

    def record_failure(request: Any) -> None:
        blocked.append((request.url, request.failure or ""))

    page.on("request", record_request)
    page.on("requestfailed", record_failure)
    if embedded:
        page.goto(notebook_site.origin + "/quiet-parent")
        page.locator("iframe").evaluate("frame => frame.src = '/shell'")
        page.wait_for_function("""() => document.querySelector('iframe')
            .src.endsWith('/shell')""")
        frame = page.frames[1]
        frame.wait_for_function("() => window.trustedShellRan === true")
    else:
        page.goto(notebook_site.origin + "/shell")
        frame = page.main_frame
    assert frame.evaluate("window.trustedShellRan") is True
    assert _realm_probe(frame, embedded=embedded)["executed"] is False
    assert frame.locator("#inline-style").evaluate(
        "node => getComputedStyle(node).position") == "static"
    assert frame.evaluate("document.baseURI") == notebook_site.origin + "/shell"
    frame.evaluate("""async origin => {
      await fetch(origin + '/attack/fetch').catch(() => {});
      const xhr = new XMLHttpRequest();
      xhr.open('GET', origin + '/attack/xhr');
      try { xhr.send(); } catch (_) {}
      navigator.sendBeacon(origin + '/attack/beacon', 'secret');
      document.querySelector('form').requestSubmit();
    }""", notebook_site.origin)
    if embedded:
        assert frame.evaluate("""origin => {
          try { top.location.href = origin + '/attack/top'; return false; }
          catch (e) { return e.name === 'SecurityError'; }
        }""", notebook_site.origin)
    page.wait_for_timeout(500)
    violations = frame.evaluate("window.violations")
    for directive in ["script-src-elem", "script-src-attr", "style-src-elem",
                      "style-src-attr", "img-src", "connect-src", "base-uri"]:
        assert directive in violations, (directive, violations)
    assert frame.url == notebook_site.origin + "/shell"
    _assert_no_attacks(page, notebook_site, start, requests, blocked)


def test_browser_resize_message_boundary(browser_page: Any,
                                         notebook_site: BrowserSite) -> None:
    page = browser_page
    page.goto(notebook_site.origin + "/quiet-parent")
    frame = page.frames[1]
    frame.wait_for_selector("#relate-notebook")
    iframe = page.locator("iframe")
    status = page.locator(".relate-notebook-status")
    assert status.inner_text() == "loading"
    valid = {"type": "relate-notebook-resize", "channel": _CHANNEL, "height": 1200}
    # Real postMessage sources: a parent and a separate opaque sibling must not
    # impersonate this preview, even if they know its channel.
    page.evaluate("data => window.postMessage(data, '*')", valid)
    page.evaluate("""data => {
      const sibling = document.createElement('iframe');
      sibling.id = 'forger'; sibling.sandbox = 'allow-scripts';
      sibling.srcdoc = '<script>parent.postMessage(' + JSON.stringify(data) +
                        ', "*")<\\/script>';
      document.body.appendChild(sibling);
    }""", valid)
    invalid = [None, [], {}, {**valid, "channel": "wrong"},
               {**valid, "type": "other"}, {**valid, "height": "1200"},
               {**valid, "html": "<style>#grading-controls{display:none}</style>"}]
    frame.evaluate("""({messages, valid}) => {
      for (const data of messages) parent.postMessage(data, '*');
      for (const height of [NaN, Infinity, -Infinity]) parent.postMessage({
        ...valid, height}, '*');
    }""", {"messages": invalid, "valid": valid})
    # Synthetic origin mismatch supplements, rather than replaces, real sources.
    page.evaluate("""data => {
      // Firefox rejects an opaque WindowProxy in MessageEventInit.source.
      const event = new Event('message');
      Object.defineProperties(event, {
        source: {value: document.querySelector('iframe').contentWindow},
        origin: {value: location.origin}, data: {value: data}
      });
      window.dispatchEvent(event);
    }""", valid)
    page.wait_for_timeout(250)
    assert status.inner_text() == "loading"
    assert iframe.first.evaluate("frame => frame.style.height") == "600px"
    page.locator("#forger").evaluate("frame => frame.remove()")
    for height, expected in [(90000, "6000px"), (-100, "100px"), (1200.2, "1201px")]:
        frame.evaluate("data => parent.postMessage(data, '*')",
                       {**valid, "height": height})
        page.wait_for_function("""expected => document.querySelector('iframe')
            .style.height === expected""", arg=expected)
    assert status.inner_text() == "ready"
    assert page.locator("#grading-controls").is_visible()
    assert page.locator("#grading-controls input").input_value() == "7"
