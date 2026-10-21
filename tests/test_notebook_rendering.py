from __future__ import annotations

import base64
import json
import struct
import zlib
from copy import deepcopy
from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING, cast

import html5lib
import nbformat
import pytest

from course import notebook_rendering as rendering
from course.notebook_rendering import (
    NOTEBOOK_MIME_TYPE,
    NotebookValidationError,
    render_notebook,
    validate_notebook,
)


if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from xml.etree.ElementTree import Element

    from nbformat import NotebookNode


def _bytes(notebook: NotebookNode) -> bytes:
    # Unlike nbformat.writes, this does not normalize or validate test inputs.
    return json.dumps(notebook, ensure_ascii=False).encode("utf-8")


def _notebook(*cells: NotebookNode) -> NotebookNode:
    return nbformat.v4.new_notebook(cells=list(cells))


def _output(bundle: dict[str, object]) -> NotebookNode:
    return nbformat.v4.new_output("display_data", data=bundle)


def _tree(body: str) -> Element:
    return cast("Element", html5lib.parseFragment(
        body, treebuilder="etree", namespaceHTMLElements=False))


def _text(body: str) -> str:
    return "".join(_tree(body).itertext())


@pytest.fixture
def png() -> str:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    data = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
            + chunk(b"IEND", b""))
    return base64.b64encode(data).decode("ascii")


@pytest.fixture
def jpeg() -> str:
    # A real one-pixel JPEG; Pillow is not needed by the rendering service/tests.
    return (
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
        "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwh"
        "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAAR"
        "CAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAA"
        "AgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
        "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWG"
        "h4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl"
        "5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
        "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYk"
        "NOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
        "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk"
        "5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDi6KKK+ZP3E//Z"
    )


def _assert_inert(body: str) -> None:
    tree = _tree(body)
    ids = {node.attrib.get("id") for node in tree.iter()}
    for node in tree.iter():
        if node is tree:
            continue
        assert node.tag in rendering._BODY_TAGS
        for name, value in node.attrib.items():
            assert not name.lower().startswith("on")
            assert name not in {
                "style", "nonce", "srcset", "ping", "target", "download", "action",
                "formaction", "background", "poster", "srcdoc", "xlink:href",
            }
            if name == "href":
                assert node.tag == "a" and value.startswith("#") and value[1:] in ids
            if name == "src":
                assert node.tag == "img" and rendering._valid_image_url(value)


def test_mime_type() -> None:
    assert NOTEBOOK_MIME_TYPE == "application/x-ipynb+json"


@pytest.mark.parametrize("minor", range(6))
def test_supported_versions(minor: int) -> None:
    notebook = _notebook(nbformat.v4.new_code_cell("answer = 42"))
    notebook.nbformat_minor = minor
    if minor < 5:
        del notebook.cells[0]["id"]
    original = _bytes(notebook)
    validated = validate_notebook(original)
    assert isinstance(validated, nbformat.NotebookNode)
    assert validated == notebook
    assert validated.nbformat_minor == minor
    assert "answer" in _text(render_notebook(original).body_html)
    assert original == _bytes(notebook)


@pytest.mark.parametrize("data", [
    b"", b"\xff", b"not json", b"[]", b"null", b"{}",
    b'{"nbformat":4,"nbformat_minor":5,"metadata":{},"cells":[],"x":NaN}',
    b'{"nbformat":4,"nbformat_minor":5,"metadata":{},"cells":[],"x":Infinity}',
    b'{"nbformat":4,"nbformat":3,"nbformat_minor":5,"metadata":{},"cells":[]}',
    b"[" * 2000 + b"]" * 2000,
])
def test_invalid_json_or_structure(data: bytes) -> None:
    with pytest.raises(NotebookValidationError):
        validate_notebook(data)
    with pytest.raises(NotebookValidationError):
        render_notebook(data)


@pytest.mark.parametrize(("major", "minor"), [
    (3, 0), (5, 0), (4, -1), (4, 6), (4, 100), (4, True), (4, "5"), (4.0, 5),
])
def test_unsupported_versions(major: object, minor: object) -> None:
    notebook = _notebook()
    notebook.nbformat = major
    notebook.nbformat_minor = minor
    with pytest.raises(NotebookValidationError, match=r"supported|minor"):
        validate_notebook(_bytes(notebook))


_INVALID_MUTATIONS: tuple[Callable[[NotebookNode], object], ...] = (
    lambda nb: nb.pop("cells"),
    lambda nb: nb.update(cells={}),
    lambda nb: nb.cells.append("not a cell"),
    lambda nb: nb.cells[0].pop("source"),
    lambda nb: nb.cells[0].update(source=12),
    lambda nb: nb.cells[0].update(cell_type="future-cell"),
    lambda nb: nb.cells[0].update(outputs=[{"output_type": "future-output"}]),
    lambda nb: nb.cells[0].update(metadata={"tags": "hide-me"}),
    lambda nb: nb.cells[0].update(id="bad id"),
    lambda nb: nb.cells[0].update(id=[]),
)


@pytest.mark.parametrize("mutation", _INVALID_MUTATIONS)
def test_no_silent_structural_repairs(
        mutation: Callable[[NotebookNode], object]) -> None:
    notebook = _notebook(nbformat.v4.new_code_cell("visible"))
    mutation(notebook)
    with pytest.raises(NotebookValidationError):
        validate_notebook(_bytes(notebook))


def test_rendering_does_not_weaken_subsequent_validation() -> None:
    notebook = _notebook(nbformat.v4.new_code_cell("visible"))
    render_notebook(_bytes(notebook))
    notebook["unknown_top_level_field"] = "must not be accepted"
    with pytest.raises(NotebookValidationError):
        validate_notebook(_bytes(notebook))


def test_duplicate_ids_rejected() -> None:
    notebook = _notebook(nbformat.v4.new_code_cell(), nbformat.v4.new_markdown_cell())
    notebook.cells[1].id = notebook.cells[0].id
    with pytest.raises(NotebookValidationError, match="unique"):
        validate_notebook(_bytes(notebook))


def test_missing_ids_only_normalized_on_render_copy() -> None:
    notebook = _notebook(nbformat.v4.new_code_cell("visible"),
                         nbformat.v4.new_markdown_cell("also visible"))
    del notebook.cells[0]["id"]
    notebook.cells[1].id = "relate-cell-0"
    original = _bytes(notebook)
    validated = validate_notebook(original)
    assert "id" not in validated.cells[0]
    rendered = render_notebook(original)
    assert "Missing cell IDs" in _text(rendered.body_html)
    assert original == _bytes(notebook)
    ids = [node.attrib["id"] for node in _tree(rendered.body_html).iter()
           if "id" in node.attrib]
    assert len(ids) == len(set(ids))
    assert any("relate-cell-0-" in cell_id for cell_id in ids)


def test_code_markdown_raw_outputs_and_math() -> None:
    notebook = _notebook(
        nbformat.v4.new_markdown_cell("# Heading\n\n**bold** and $x^2$"),
        nbformat.v4.new_raw_cell("<script>alert(1)</script><b>raw source</b>"),
        nbformat.v4.new_code_cell("print('source')", execution_count=7, outputs=[
            nbformat.v4.new_output(
                "stream", name="stdout", text="\x1b[31mred\x1b[0m\n"),
            nbformat.v4.new_output("error", ename="ValueError", evalue="bad",
                                  traceback=["ValueError: <bad>\x1b[0m"]),
            _output({"text/html": (
                "<table><tr><th>column</th><td>value</td></tr></table>")}),
            _output({"text/markdown": "**markdown output**"}),
            _output({"text/latex": r"\frac{1}{2}<script>math attack</script>"}),
        ]),
    )
    rendered = render_notebook(_bytes(notebook))
    text = _text(rendered.body_html)
    assert "Heading" in text and "bold" in text and "$x^2$" in text
    assert "<script>alert(1)</script><b>raw source</b>" in text
    assert "source" in text and "7" in text and "red" in text
    assert "ValueError: <bad>" in text
    assert "column" in text and "value" in text and "markdown output" in text
    assert r"\frac{1}{2}<script>math attack</script>" in text
    assert "not reproduced by execution" in text
    assert list(_tree(rendered.body_html).iter("table"))
    _assert_inert(rendered.body_html)


def test_multiline_strings() -> None:
    notebook = _notebook(nbformat.v4.new_code_cell(outputs=[
        nbformat.v4.new_output("stream", name="stderr", text=""),
        _output({"text/plain": ""}),
    ]))
    notebook.cells[0].source = ["first line\n", "second line"]
    notebook.cells[0].outputs[0].text = ["stream one\n", "stream two"]
    notebook.cells[0].outputs[1].data["text/plain"] = ["output one\n", "output two"]
    rendered = render_notebook(_bytes(notebook))
    text = _text(rendered.body_html)
    for value in ("first line", "second line", "stream one", "stream two",
                  "output one", "output two"):
        assert value in text


@pytest.mark.parametrize("active_type", [
    "application/javascript", "application/vnd.jupyter.widget-view+json",
    "image/svg+xml", "application/pdf", "text/vnd.mermaid", "application/x-unknown",
])
def test_unsupported_mime_fallbacks(active_type: str) -> None:
    value = {} if active_type.endswith("+json") else "active payload"
    notebook = _notebook(nbformat.v4.new_code_cell(outputs=[
        _output({active_type: value, "text/plain": "usable fallback"}),
        _output({active_type: value}),
    ]))
    rendered = render_notebook(_bytes(notebook))
    text = _text(rendered.body_html)
    assert "usable fallback" in text
    assert "Output omitted: no supported representation" in text
    assert "active payload" not in text
    assert "Unsupported or invalid output representations" in text
    _assert_inert(rendered.body_html)


def test_raster_output_and_attachments(png: str) -> None:
    notebook = _notebook(
        nbformat.v4.new_markdown_cell("![plot](attachment:plot.png)", attachments={
            "plot.png": {"image/svg+xml": "<svg onload='attack()'/>", "image/png": png},
        }),
        nbformat.v4.new_code_cell(outputs=[
            _output({"image/png": [png[:20], "\n", png[20:]],
                     "text/plain": "plot fallback"}),
        ]),
    )
    notebook.cells[1].outputs[0].metadata = {
        "filenames": {"image/png": "/etc/passwd"},
        "image/png": {"width": '1 onerror="attack()"', "unconfined": True},
    }
    rendered = render_notebook(_bytes(notebook))
    images = list(_tree(rendered.body_html).iter("img"))
    assert len(images) == 2
    assert all(image.attrib.get("src") == f"data:image/png;base64,{png}"
               for image in images)
    assert all("width" not in image.attrib for image in images)
    assert "/etc/passwd" not in rendered.body_html
    _assert_inert(rendered.body_html)


@pytest.mark.parametrize("bad_image", [
    "not base64!", base64.b64encode(b"<svg onload='attack()'/>").decode("ascii"),
    base64.b64encode(b"\x89PNG\r\n\x1a\n<script>attack()</script>").decode("ascii"),
])
def test_invalid_images_fall_back(bad_image: str) -> None:
    notebook = _notebook(nbformat.v4.new_code_cell(outputs=[
        _output({"image/png": bad_image, "text/plain": "image fallback"}),
    ]))
    rendered = render_notebook(_bytes(notebook))
    assert "image fallback" in _text(rendered.body_html)
    assert not list(_tree(rendered.body_html).iter("img"))


@pytest.mark.parametrize("mime", [None, "text/html", "text/markdown"])
def test_inline_raster_images_remain_validated(png: str, mime: str | None) -> None:
    spoof = base64.b64encode(b"<svg onload='attack()'/>").decode("ascii")
    html = (
        f'<img src="data:image/png;base64,{png}" alt="plot" '
        'onerror="attack()" srcset="https://evil.test/plot.png 2x" '
        'style="display:none">'
        f'<img src="data:image/png;base64,{spoof}">'
        '<img src="https://evil.test/remote.png">'
    )
    cell = (nbformat.v4.new_markdown_cell(html) if mime is None
            else nbformat.v4.new_code_cell(outputs=[_output({mime: html})]))
    rendered = render_notebook(_bytes(_notebook(cell)))
    sources = [image.attrib["src"] for image in _tree(rendered.body_html).iter("img")
               if "src" in image.attrib]
    assert sources == [f"data:image/png;base64,{png}"]
    _assert_inert(rendered.body_html)


def test_cross_cell_fragment_links_are_checked_after_export() -> None:
    notebook = _notebook(
        nbformat.v4.new_markdown_cell("[local](#destination) [missing](#missing)"),
        nbformat.v4.new_markdown_cell('<h2 id="destination">destination</h2>'),
    )
    rendered = render_notebook(_bytes(notebook))
    links = {link.text: link.attrib.get("href")
             for link in _tree(rendered.body_html).iter("a")}
    assert links["local"] == "#destination"
    assert links["missing"] is None
    _assert_inert(rendered.body_html)


def test_jpeg_output_and_attachment(jpeg: str) -> None:
    notebook = _notebook(
        nbformat.v4.new_markdown_cell("![jpeg](attachment:plot.jpg)", attachments={
            "plot.jpg": {"image/jpeg": jpeg},
        }),
        nbformat.v4.new_code_cell(outputs=[_output({"image/jpeg": jpeg})]),
    )
    rendered = render_notebook(_bytes(notebook))
    images = list(_tree(rendered.body_html).iter("img"))
    assert len(images) == 2
    assert all(image.attrib.get("src") == f"data:image/jpeg;base64,{jpeg}"
               for image in images)
    _assert_inert(rendered.body_html)
    assert rendering._raster("image/png", jpeg) is None
    assert rendering._raster("image/jpeg", jpeg[:-8]) is None


def test_missing_or_unsupported_attachments() -> None:
    notebook = _notebook(nbformat.v4.new_markdown_cell(
        "![missing](attachment:missing)\n![svg](attachment:only.svg)",
        attachments={"only.svg": {"image/svg+xml": "<svg/>"}},
    ))
    rendered = render_notebook(_bytes(notebook))
    assert "Some images or attachments were omitted" in _text(rendered.body_html)
    assert all("src" not in node.attrib
               for node in _tree(rendered.body_html).iter("img"))


def test_strips_trust_visibility_and_exporter_metadata() -> None:
    notebook = _notebook(nbformat.v4.new_code_cell("must remain visible", outputs=[
        _output({"text/plain": "visible saved output"}),
    ]))
    notebook.metadata.update({
        "title": "<script>title attack</script>",
        "widgets": {"application/vnd.jupyter.widget-state+json": {"state": {}}},
        "language_info": {
            "name": "../../hostile-lexer", "pygments_lexer": "/etc/passwd"},
    })
    notebook.cells[0].metadata.update({
        "trusted": True, "tags": ["remove-cell", "hide-input", "remove-output"],
        "collapsed": True, "scrolled": True,
        "transient": {"remove_source": True},
        "jupyter": {"source_hidden": True, "outputs_hidden": True},
        "magics_language": "/etc/passwd",
    })
    original = deepcopy(notebook)
    copy = rendering._render_copy(notebook, set())
    assert notebook == original
    assert copy.metadata == {"language_info": {"name": "text"}}
    assert copy.cells[0].metadata == {}
    assert copy.cells[0].outputs[0].metadata == {}
    rendered = render_notebook(_bytes(notebook))
    assert "must remain visible" in _text(rendered.body_html)
    assert "visible saved output" in _text(rendered.body_html)
    for value in ("title attack", "hostile-lexer", "/etc/passwd", "remove-cell"):
        assert value not in rendered.body_html


_ATTACKS = [
    '<script src="https://evil.test/a.js">attack()</script>',
    ('<style>body{display:none}</style>'
     '<link rel="stylesheet" href="https://evil.test/a.css">'),
    ('<img src="https://evil.test/a.png" '
     'srcset="https://evil.test/b.png 2x" onerror="attack()">'),
    '<img src="data:image/svg+xml;base64,PHN2Zy8+">',
    '<img src="data:text/html;base64,PHNjcmlwdD4=">',
    ('<a href="https://evil.test/" ping="https://evil.test/ping" '
     'target="_top">external</a>'),
    '<a href="java&#x09;script:attack()">javascript</a>',
    ('<base href="https://evil.test/">'
     '<meta http-equiv="refresh" content="0;url=//evil.test">'),
    ('<form action="https://evil.test/"><input autofocus>'
     '<button formaction="/delete">go</button></form>'),
    ('<iframe srcdoc="&lt;script&gt;attack()&lt;/script&gt;"></iframe>'
     '<object data="/secret"></object>'),
    ('<svg><a xlink:href="javascript:attack()">svg link</a></svg>'
     '<math href="/secret">math</math>'),
    ('</div></main></body></html><head><style>body{display:none}</style></head>'
     '<body onload="attack()">'),
    '<table><tr><td></table><img src="/secret" onerror="attack()">',
    ('<svg><foreignObject><p onload="attack()">foreign content</p>'
     '</foreignObject></svg>'),
    ('<math><mtext><table><mglyph><style><!--</style>'
     '<img title="--><img src=/secret onerror=attack()>">'),
    '<noscript><p title="</noscript><img src=/secret onerror=attack()>">repair</p>',
    '<div style="position:fixed" nonce="forged" class="jp-mod-hidden">styled</div>',
    '<img width="' + "9" * 5000 + '" src="/secret">',
]


@pytest.mark.parametrize("attack", _ATTACKS)
def test_html5_body_sanitation(attack: str) -> None:
    sanitized = rendering._sanitize_body(attack, set())
    _assert_inert(sanitized)
    # Reparse as a complete shell too: fragments may not acquire head elements.
    shell = html5lib.parse(
        "<!doctype html><html><head><title>trusted</title></head><body>"
        + sanitized + "</body></html>", namespaceHTMLElements=False)
    head = shell.find("head")
    assert head is not None
    assert [node.tag for node in head] == ["title"]


@pytest.mark.parametrize("attack", _ATTACKS)
def test_malicious_notebook_rendering(attack: str) -> None:
    notebook = _notebook(
        nbformat.v4.new_markdown_cell(attack),
        nbformat.v4.new_code_cell(outputs=[_output({"text/html": attack})]),
    )
    rendered = render_notebook(_bytes(notebook))
    _assert_inert(rendered.body_html)
    assert "evil.test" not in rendered.css and "forged" not in rendered.css


def test_validated_raster_data_and_fragment_links(png: str) -> None:
    body = ('<h2 id="section">section</h2><a href="#section">local</a>'
            '<a href="#missing">missing</a><a href="/#section">not local</a>'
            f'<img src="data:image/png;base64,{png}" alt="plot">')
    sanitized = rendering._sanitize_body(body, set())
    links = list(_tree(sanitized).iter("a"))
    assert links[0].attrib["href"] == "#section"
    assert "href" not in links[1].attrib and "href" not in links[2].attrib
    assert next(_tree(sanitized).iter("img")).attrib["src"].endswith(png)
    _assert_inert(sanitized)


def test_markdown_fences_are_not_active() -> None:
    source = ("```mermaid\n</pre><script>attack()</script>\n```\n"
              "```../../hostile-lexer\n<script>code attack</script>\n```")
    rendered = render_notebook(_bytes(_notebook(nbformat.v4.new_markdown_cell(source))))
    assert "<script>attack()</script>" in _text(rendered.body_html)
    assert "<script>code attack</script>" in _text(rendered.body_html)
    _assert_inert(rendered.body_html)


def test_no_execution_or_markdown_file_embedding(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail(
            "Static rendering attempted execution, conversion, or file embedding")

    from nbconvert.filters.markdown_mistune import IPythonRenderer
    from nbconvert.preprocessors import ExecutePreprocessor, SVG2PDFPreprocessor

    monkeypatch.setattr(ExecutePreprocessor, "preprocess", forbidden)
    monkeypatch.setattr(SVG2PDFPreprocessor, "preprocess", forbidden)
    monkeypatch.setattr(IPythonRenderer, "_src_to_base64", forbidden)
    secret = tmp_path / "secret.png"
    secret.write_text("local file secret")
    notebook = _notebook(
        nbformat.v4.new_code_cell("raise RuntimeError('must not execute')"),
        nbformat.v4.new_markdown_cell(
            f"![local]({secret})\n![remote](https://evil.test/image.png)"),
    )
    rendered = render_notebook(_bytes(notebook))
    assert "local file secret" not in rendered.body_html
    assert all("src" not in node.attrib
               for node in _tree(rendered.body_html).iter("img"))
    _assert_inert(rendered.body_html)


def test_packaged_css_and_template_contract(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Neither local template/config discovery nor notebook styles are trusted.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JUPYTER_PATH", str(tmp_path))
    malicious_template = tmp_path / "nbconvert/templates/lab"
    malicious_template.mkdir(parents=True)
    (malicious_template / "index.html.j2").write_text("LOCAL TEMPLATE ATTACK")
    (malicious_template / "conf.json").write_text('{"preprocessors": {}}')
    empty = render_notebook(_bytes(_notebook()))
    hostile = render_notebook(_bytes(_notebook(nbformat.v4.new_markdown_cell(
        "<style>STUDENT CSS ATTACK</style><script>attack()</script>"))))
    assert empty.css == hostile.css
    assert "STUDENT CSS ATTACK" not in hostile.css
    assert "LOCAL TEMPLATE ATTACK" not in hostile.body_html + hostile.css
    assert "--jp-" in empty.css and ".highlight" in empty.css
    assert "<style" not in empty.css and "<script" not in empty.body_html
    exporter = rendering._exporter()
    assert exporter.template_name == "lab" and exporter.theme == "light"
    assert exporter.sanitize_html and not exporter.embed_images
    assert exporter.default_preprocessors == []
    assert not any(preprocessor.enabled for preprocessor in exporter._preprocessors)
    raw, _ = exporter.from_notebook_node(_notebook())
    assert "<script" not in raw and "<style" not in raw and "<html" not in raw
    assert "jp-Notebook" in raw
    _assert_inert(hostile.body_html)
    field = "css"
    with pytest.raises(FrozenInstanceError):
        setattr(empty, field, "changed")
