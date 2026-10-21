from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from pydantic import TypeAdapter

from course.notebook_rendering import NOTEBOOK_MIME_TYPE
from course.page.upload import FileUploadForm, FileUploadQuestion, UploadableMimeType


if TYPE_CHECKING:
    from typing import Any

    from django.http import HttpRequest
    from pytest_django.fixtures import SettingsWrapper

    from course.page.base import PageContext


@pytest.fixture
def notebook_bytes() -> bytes:
    return json.dumps({"nbformat": 4, "nbformat_minor": 5, "metadata": {},
                       "cells": []}).encode()


@pytest.fixture
def page() -> FileUploadQuestion:
    return FileUploadQuestion.model_construct(
            id="upload", prompt="Upload a notebook", value=1,
            rubric="Check the submission", maximum_megabytes=1,
            mime_types=[NOTEBOOK_MIME_TYPE])


@pytest.fixture
def render_request() -> HttpRequest:
    request = RequestFactory().get("/")
    request.session = SessionStore()
    return request


@pytest.fixture
def page_context() -> PageContext:
    return cast("PageContext", cast("object", SimpleNamespace(
            course=SimpleNamespace(identifier="test-course"),
            flow_session=None, answer_resource_url=None)))


def upload_form(data: bytes, mime_type: str, allowed: list[str] | None = None,
        maximum_megabytes: float = 1) -> FileUploadForm:
    return FileUploadForm(maximum_megabytes, allowed or [NOTEBOOK_MIME_TYPE],
            data={}, files={"uploaded_file": SimpleUploadedFile(
                "untrusted-name.txt", data, content_type=mime_type)})


def legacy_answer(data: bytes, mime_type: str | None) -> dict[str, Any]:
    return {"base64_data": base64.b64encode(data).decode(), "mime_type": mime_type}


@pytest.mark.parametrize("mime_type", [NOTEBOOK_MIME_TYPE, "application/json",
    "application/octet-stream", "text/plain", "application/pdf"])
def test_notebook_only_uses_parser_not_browser_mime(
        notebook_bytes: bytes, mime_type: str) -> None:
    form = upload_form(notebook_bytes, mime_type)
    assert form.is_valid(), form.errors
    uploaded = form.cleaned_data["uploaded_file"]
    assert uploaded.content_type == NOTEBOOK_MIME_TYPE
    assert uploaded.read() == notebook_bytes


@pytest.mark.parametrize("mime_type", [NOTEBOOK_MIME_TYPE, "application/json",
    "application/octet-stream", "text/plain"])
def test_mixed_notebook_recognition(notebook_bytes: bytes, mime_type: str) -> None:
    form = upload_form(notebook_bytes, mime_type,
            [NOTEBOOK_MIME_TYPE, "text/plain", "application/octet-stream"])
    assert form.is_valid(), form.errors
    assert form.cleaned_data["uploaded_file"].content_type == NOTEBOOK_MIME_TYPE


@pytest.mark.parametrize("data", [b"not JSON", b"{}", b'{"nbformat": 3}',
                                  b"\xff"])
def test_invalid_notebook_only_rejected(data: bytes) -> None:
    form = upload_form(data, "application/octet-stream")
    assert not form.is_valid()
    assert "Invalid notebook" in str(form.errors)


def test_invalid_explicit_claim_rejected_even_with_octet_stream_allowed() -> None:
    form = upload_form(b"{}", NOTEBOOK_MIME_TYPE,
            [NOTEBOOK_MIME_TYPE, "application/octet-stream"])
    assert not form.is_valid()
    assert "Invalid notebook" in str(form.errors)


@pytest.mark.parametrize("mime_type", ["text/plain", "application/octet-stream"])
def test_generic_json_is_not_reinterpreted(mime_type: str) -> None:
    form = upload_form(b'{"ordinary": "JSON"}', mime_type,
            [NOTEBOOK_MIME_TYPE, mime_type])
    assert form.is_valid(), form.errors
    assert form.cleaned_data["uploaded_file"].content_type == mime_type


def test_ambiguous_unsupported_mime_requires_format_choice() -> None:
    form = upload_form(b'{"ordinary": "JSON"}', "application/json",
            [NOTEBOOK_MIME_TYPE, "text/plain"])
    assert not form.is_valid()
    assert "Please choose an allowed format" in str(form.errors)


def test_upload_budget_precedes_parser(
        notebook_bytes: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    validator = Mock(side_effect=AssertionError("Parser must not be called"))
    monkeypatch.setattr("course.page.upload.validate_notebook", validator)
    form = upload_form(notebook_bytes, NOTEBOOK_MIME_TYPE, maximum_megabytes=0)
    assert not form.is_valid()
    assert "Please keep file size under" in str(form.errors)
    validator.assert_not_called()


def test_notebook_mime_is_in_page_schema() -> None:
    assert TypeAdapter(UploadableMimeType).validate_python(
            NOTEBOOK_MIME_TYPE) == NOTEBOOK_MIME_TYPE


def test_accept_hint_includes_extension() -> None:
    form = FileUploadForm(1, [NOTEBOOK_MIME_TYPE])
    assert ".ipynb" in form.helper.layout.fields[0].attrs["accept"]
    assert NOTEBOOK_MIME_TYPE in form.helper.layout.fields[0].attrs["accept"]


def test_answer_uses_cleaned_file_and_explicit_extension(
        notebook_bytes: bytes, page: FileUploadQuestion, page_context: PageContext,
        settings: SettingsWrapper, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    settings.RELATE_BULK_STORAGE = FileSystemStorage(location=tmp_path)
    page.mime_types = [NOTEBOOK_MIME_TYPE, "text/plain"]
    form = upload_form(notebook_bytes, "application/json", page.mime_types)
    assert form.is_valid(), form.errors
    # Django can replace an upload during cleaning. Do not use the original File.
    original_files = {"uploaded_file": SimpleUploadedFile(
        "original.json", b"wrong file", content_type="application/json")}

    def unknown_extension(_mime_type: str) -> None:
        return None

    monkeypatch.setattr("mimetypes.guess_extension", unknown_extension)
    answer = page.answer_data(page_context, {}, form, original_files)
    assert answer["mime_type"] == NOTEBOOK_MIME_TYPE
    assert answer["storage_filename"].endswith(".ipynb")
    assert page.get_content_from_answer_data(answer) == (
            notebook_bytes, NOTEBOOK_MIME_TYPE)
    assert page.normalized_bytes_answer(page_context, {}, answer) == (
            ".ipynb", notebook_bytes)


@pytest.mark.parametrize("mime_type", [NOTEBOOK_MIME_TYPE, "application/json",
    "application/octet-stream", "text/plain", None])
def test_legacy_notebook_resources_and_normalization(
        notebook_bytes: bytes, page: FileUploadQuestion, page_context: PageContext,
        mime_type: str | None) -> None:
    answer = legacy_answer(notebook_bytes, mime_type)
    preview = page.render_answer_resource(page_context, {}, answer, "notebook-preview")
    assert preview is not None
    assert preview.kind == "notebook-preview"
    assert preview.content == notebook_bytes
    original = page.render_answer_resource(page_context, {}, answer, "original")
    assert original is not None
    assert original.content == notebook_bytes
    assert original.filename == "submission.ipynb"
    assert original.content_type == NOTEBOOK_MIME_TYPE
    assert page.normalized_bytes_answer(page_context, {}, answer) == (
            ".ipynb", notebook_bytes)
    assert page.render_answer_resource(page_context, {}, answer, "unknown") is None


def test_invalid_old_answer_still_downloadable(
        page: FileUploadQuestion, page_context: PageContext) -> None:
    answer = legacy_answer(b"invalid old notebook", NOTEBOOK_MIME_TYPE)
    resource = page.render_answer_resource(page_context, {}, answer, "original")
    assert resource is not None
    assert resource.content == b"invalid old notebook"


def test_mixed_formats_do_not_preview_generic_old_answers(
        notebook_bytes: bytes, page: FileUploadQuestion,
        page_context: PageContext) -> None:
    page.mime_types = [NOTEBOOK_MIME_TYPE, "application/octet-stream"]
    answer = legacy_answer(notebook_bytes, "application/octet-stream")
    assert page.render_answer_resource(
            page_context, {}, answer, "notebook-preview") is None


@pytest.mark.parametrize("mime_type", [NOTEBOOK_MIME_TYPE, "application/octet-stream"])
def test_notebook_parent_contains_urls_not_bytes(
        notebook_bytes: bytes, page: FileUploadQuestion, page_context: PageContext,
        mime_type: str, monkeypatch: pytest.MonkeyPatch,
        render_request: HttpRequest) -> None:
    answer = legacy_answer(notebook_bytes, mime_type)

    def resource_url(name: str) -> str:
        return f"/resources/{name}?channel=test"

    page_context.answer_resource_url = resource_url
    # The parent must not even read notebook content to build its UI.
    monkeypatch.setattr(FileUploadQuestion, "get_content_from_answer_data",
            Mock(side_effect=AssertionError("Parent must not read notebook bytes")))
    html = page.form_to_html(render_request, page_context,
            FileUploadForm(1, page.mime_types), answer)
    assert "/resources/notebook-preview?channel=test" in html
    assert "/resources/original?channel=test" in html
    assert "data:" not in html
    assert answer["base64_data"] not in html
    assert "<iframe" not in html
    assert 'rel="noopener noreferrer"' in html
    assert "were not reproduced by execution" in html
    assert "enablePreviewForNotebookUpload" in html


def test_unsaved_notebook_is_not_embedded(
        notebook_bytes: bytes, page: FileUploadQuestion, page_context: PageContext,
        render_request: HttpRequest) -> None:
    answer = legacy_answer(notebook_bytes, NOTEBOOK_MIME_TYPE)
    html = page.form_to_html(render_request, page_context,
            FileUploadForm(1, page.mime_types), answer)
    assert "until this answer has been saved" in html
    assert "data:" not in html
    assert "<iframe" not in html
    assert 'type="file"' in html


def test_pdf_parent_preview_unchanged(
        page: FileUploadQuestion, page_context: PageContext,
        render_request: HttpRequest) -> None:
    page.mime_types = ["application/pdf"]
    answer = legacy_answer(b"%PDF-test", "application/pdf")
    html = page.form_to_html(render_request, page_context,
            FileUploadForm(1, page.mime_types), answer)
    assert "data:application/pdf;base64," in html
    assert "enablePreviewForFileUpload" in html
    assert "enablePreviewForNotebookUpload" not in html


def test_non_notebook_upload_does_not_get_notebook_validation() -> None:
    form = upload_form(b"not a notebook", "application/json",
            ["application/octet-stream", "text/plain"])
    assert form.is_valid(), form.errors
    assert form.cleaned_data["uploaded_file"].content_type == "application/json"


def test_parent_resize_bridge() -> None:
    """Exercise the actual JS with a minimal DOM; browser isolation needs E2E tests."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the parent resize bridge")
    source = (Path(__file__).parents[1] / "frontend/js/rlUtils.js").read_text()
    source = source.replace("import jQuery from 'jquery';", "").replace("export ", "")
    harness = r"""
const assert = require('node:assert/strict');
function setup({sandbox = true, csp = true, channel = 'a'.repeat(43)} = {}) {
  const status = {dataset: {loading: 'loading', ready: 'ready', error: 'error',
                           unsupported: 'unsupported'}};
  const frames = [];
  const link = {hidden: true};
  const container = {dataset: {title: 'Notebook'},
                     appendChild: frame => frames.push(frame)};
  const preview = {dataset: {previewUrl: '/preview?channel=' + channel},
    querySelector: selector => ({'.relate-notebook-status': status,
      '.relate-notebook-frame': container,
      '.relate-notebook-standalone': link})[selector]};
  const timers = new Map();
  let nextTimer = 0;
  const listeners = new Map();
  global.window = {
    URL, location: {href: 'https://lms.test/grading', origin: 'https://lms.test'},
    SecurityPolicyViolationEvent: csp ? function() {} : undefined,
    setTimeout: (fn, delay) => {
      timers.set(++nextTimer, {fn, delay}); return nextTimer;
    },
    clearTimeout: id => timers.delete(id),
    addEventListener: (type, fn) => listeners.set(type, fn),
    removeEventListener: type => listeners.delete(type),
  };
  global.document = {
    querySelectorAll: () => [preview],
    createElement: () => ({...(sandbox ? {sandbox: {}} : {}), style: {}, attrs: {},
      contentWindow: {}, setAttribute(name, value) {this.attrs[name] = value;},
      remove() {this.removed = true;}}),
  };
  enablePreviewForNotebookUpload();
  return {status, frames, link, timers, listeners, channel,
    flush(delay) {
      for (const [id, timer] of [...timers]) {
        if (timer.delay === delay) {timers.delete(id); timer.fn();}
      }
    }};
}
for (const options of [{sandbox: false}, {csp: false}]) {
  const env = setup(options);
  assert.equal(env.frames.length, 0);
  assert.equal(env.status.textContent, 'unsupported');
  assert.equal(env.link.hidden, true);
}
const invalid = setup({channel: 'bad'});
assert.equal(invalid.frames.length, 0);
assert.equal(invalid.status.textContent, 'error');
const env = setup();
assert.equal(env.frames.length, 1);
const frame = env.frames[0];
assert.deepEqual(frame.attrs,
  {sandbox: 'allow-scripts', referrerpolicy: 'no-referrer'});
assert.equal(frame.title, 'Notebook');
assert.equal(frame.style.width, '100%');
assert.equal(frame.style.border, '0');
assert.equal(frame.style.height, '600px');
assert.equal(env.status.textContent, 'loading');
assert.equal(env.link.hidden, false);
enablePreviewForNotebookUpload();
assert.equal(env.frames.length, 1); // Idempotent initialization.
const message = env.listeners.get('message');
const valid = {type: 'relate-notebook-resize', channel: env.channel, height: 1200};
for (const event of [
  {source: {}, origin: 'null', data: valid},
  {source: frame.contentWindow, origin: 'https://lms.test', data: valid},
  ...[null, [], {}, {...valid, channel: 'b'.repeat(43)},
      {...valid, type: 'other'}, {...valid, height: '900'},
      {...valid, height: NaN}, {...valid, height: Infinity},
      {...valid, html: '<b>forged</b>'}].map(data => (
        {source: frame.contentWindow, origin: 'null', data}))]) {
  message(event);
}
assert.equal(env.status.textContent, 'loading');
assert.equal(frame.style.height, '600px');
function send(height) {
  message({source: frame.contentWindow, origin: 'null', data: {...valid, height}});
}
send(1200);
assert.equal(env.status.textContent, 'ready');
assert.equal(frame.style.height, '600px'); // Throttled, not synchronous.
send(90000);
assert.equal([...env.timers.values()].filter(timer => timer.delay === 100).length, 1);
env.flush(100);
assert.equal(frame.style.height, '6000px');
send(-100);
env.flush(100);
assert.equal(frame.style.height, '100px');
assert.equal([...env.timers.values()].some(timer => timer.delay === 30000), false);
const failure = setup();
failure.flush(30000);
assert.equal(failure.status.textContent, 'error');
assert.equal(failure.frames[0].removed, true);
assert.equal(failure.listeners.has('message'), false);
assert.equal(failure.link.hidden, false); // Standalone/download fallback remains.
console.log('Parent resize bridge assertions passed');
"""
    result = subprocess.run([node, "-e", source + harness], capture_output=True,
                            text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
