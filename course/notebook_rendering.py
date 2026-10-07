"""Static notebook previews, independent of storage, Django, and HTTP.

The returned body is untrusted-origin content even after sanitation. Callers must
supply the sandbox/CSP shell described in NOTEBOOK-GRADING-DESIGN.md, and must not
inline the body into a grading page. Only ``css`` belongs in a trusted style tag.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import struct
import zlib
from copy import deepcopy
from dataclasses import dataclass
from html import escape
from importlib.metadata import distribution
from pathlib import Path
from typing import TYPE_CHECKING, cast, final

import bleach
import html5lib
import nbformat
from jinja2 import pass_context
from jupyterlab_pygments import JupyterStyle
from nbconvert import HTMLExporter
from nbconvert.filters.markdown_mistune import IPythonRenderer, MarkdownWithMath
from pygments.formatters import HtmlFormatter
from pygments.token import STANDARD_TYPES
from traitlets.config import Config
from typing_extensions import override


if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

    from jinja2.runtime import Context
    from nbformat import NotebookNode


NOTEBOOK_MIME_TYPE = "application/x-ipynb+json"

_SUPPORTED_MINORS = frozenset(range(6))
_RASTER_TYPES = ("image/png", "image/jpeg")
_MIME_PRIORITY = (
    "text/html", "text/markdown", "image/png", "image/jpeg",
    "text/plain", "text/latex",
)
_LANGUAGES = {
    "python": "python", "python3": "python", "r": "r", "julia": "julia",
    "javascript": "javascript", "typescript": "typescript", "c": "c",
    "c++": "cpp", "cpp": "cpp", "java": "java", "rust": "rust",
    "bash": "bash", "sh": "bash", "sql": "sql", "text": "text",
}
_TEMPLATE_DIRECTORY = Path(__file__).parent / "templates/course/notebook-rendering"
# nbconvert's lab template prefixes cell anchors with the literal "cell-id=".
_IDENTIFIER = re.compile(r"(?:cell-id=)?[A-Za-z0-9_-][A-Za-z0-9_.:-]*\Z")
_DATA_IMAGE = re.compile(r"data:(image/(?:png|jpeg));base64,([A-Za-z0-9+/=]+)\Z")
_BODY_TAGS = frozenset({
    "a", "abbr", "b", "blockquote", "br", "caption", "code", "dd", "del",
    "div", "dl", "dt", "em", "h1", "h2", "h3", "h4", "h5", "h6", "hr",
    "i", "img", "kbd", "li", "main", "ol", "p", "pre", "s", "samp", "small",
    "span", "strong", "sub", "sup", "table", "tbody", "td", "th", "thead",
    "tfoot", "tr", "ul", "var",
})
_BODY_CLASSES = frozenset(STANDARD_TYPES.values()) | frozenset({
    "jp-Notebook", "jp-Cell", "jp-CodeCell", "jp-MarkdownCell", "jp-RawCell",
    "jp-Notebook-cell", "jp-mod-noOutputs", "jp-Cell-inputWrapper",
    "jp-Collapser", "jp-InputCollapser", "jp-Cell-inputCollapser", "jp-InputArea",
    "jp-Cell-inputArea", "jp-CodeMirrorEditor", "jp-Editor", "jp-InputArea-editor",
    "cm-editor", "cm-s-jupyter", "highlight", "jp-Cell-outputWrapper",
    "jp-OutputCollapser", "jp-Cell-outputCollapser", "jp-OutputArea",
    "jp-Cell-outputArea", "jp-InputPrompt", "jp-InputArea-prompt",
    "jp-OutputPrompt", "jp-OutputArea-prompt", "jp-OutputArea-child",
    "jp-OutputArea-executeResult", "jp-RenderedHTMLCommon", "jp-RenderedMarkdown",
    "jp-MarkdownOutput", "jp-RenderedText", "jp-OutputArea-output",
    "jp-RenderedHTML", "jp-RenderedImage", "jp-RenderedLatex", "anchor-link",
    "ansi-black-fg", "ansi-red-fg", "ansi-green-fg", "ansi-yellow-fg",
    "ansi-blue-fg", "ansi-magenta-fg", "ansi-cyan-fg", "ansi-white-fg",
    "ansi-black-intense-fg", "ansi-red-intense-fg", "ansi-green-intense-fg",
    "ansi-yellow-intense-fg", "ansi-blue-intense-fg", "ansi-magenta-intense-fg",
    "ansi-cyan-intense-fg", "ansi-white-intense-fg", "ansi-bold", "ansi-italic",
    "ansi-underline",
})


class NotebookValidationError(ValueError):
    """The submitted bytes are not a supported, valid notebook."""


@dataclass(frozen=True)
class RenderedNotebook:
    body_html: str
    css: str


def _reject_constant(_value: str) -> None:
    raise NotebookValidationError("Notebook JSON must not contain NaN or Infinity.")


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NotebookValidationError(
                "Notebook JSON contains duplicate object keys.")
        result[key] = value
    return result


def _fill_cell_ids(notebook: NotebookNode) -> bool:
    used = {cell["id"] for cell in notebook.cells if "id" in cell}
    changed = False
    for index, cell in enumerate(notebook.cells):
        if "id" not in cell:
            cell_id = f"relate-cell-{index}"
            while cell_id in used:
                cell_id += "-"
            cell["id"] = cell_id
            used.add(cell_id)
            changed = True
    return changed


def validate_notebook(data: bytes) -> NotebookNode:
    """Validate v4.0--v4.5 without conversion or modifying submitted content.

    Missing v4.5 cell IDs are the sole accepted schema normalization: validate a
    copy with generated IDs, but return the original node with its IDs untouched.
    The upload form enforces its configured byte limit before calling this service.
    """
    # Future budgets: separate preview bytes, JSON depth, cell/source/output
    # counts and lengths, embedded image bytes/pixels, and final HTML size.
    # Initially only the upload form's configured byte limit is enforced.
    try:
        parsed: object = json.loads(
            data.decode("utf-8"), parse_constant=_reject_constant,
            object_pairs_hook=_unique_keys)
    except (UnicodeDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, NotebookValidationError):
            raise
        raise NotebookValidationError(
            "Notebook must contain valid UTF-8 JSON.") from None
    if not isinstance(parsed, dict):
        raise NotebookValidationError("Notebook JSON must be an object.")
    parsed = cast("dict[str, object]", parsed)
    if type(parsed.get("nbformat")) is not int or parsed["nbformat"] != 4:
        raise NotebookValidationError("Only notebook format 4 is supported.")
    minor = parsed.get("nbformat_minor")
    if type(minor) is not int or minor not in _SUPPORTED_MINORS:
        raise NotebookValidationError(
            "Supported notebook minor versions are 0 through 5.")
    try:
        notebook = cast("NotebookNode", nbformat.from_dict(parsed))
        candidate = deepcopy(notebook)
        if minor == 5 and isinstance(candidate.get("cells"), list):
            ids: set[str] = set()
            for cell in candidate.cells:
                if not isinstance(cell, dict):
                    raise NotebookValidationError(
                        "Every notebook cell must be an object.")
                cell = cast("dict[str, object]", cell)
                if "id" in cell:
                    cell_id = cell["id"]
                    if not isinstance(cell_id, str):
                        raise NotebookValidationError("Cell IDs must be strings.")
                    if cell_id in ids:
                        raise NotebookValidationError(
                            "Notebook cell IDs must be unique.")
                    ids.add(cell_id)
            _fill_cell_ids(candidate)
        # iter_validate, unlike reads/validate, does not silently repair IDs or
        # strip invalid metadata. Do not expose schema messages containing input.
        if next(nbformat.validator.iter_validate(
                candidate, version=4, version_minor=minor), None) is not None:
            raise NotebookValidationError(
                "Notebook structure is invalid; "
                "check cell fields, outputs, and metadata.")
        return notebook
    except (RecursionError, TypeError, AttributeError, nbformat.ValidationError):
        raise NotebookValidationError("Notebook structure is invalid.") from None


def _text(value: str | list[str]) -> str:
    return value if isinstance(value, str) else "".join(value)


def _is_png(data: bytes) -> bool:
    """Check the raster container, not just its claimed MIME or magic bytes."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    offset = 8
    have_header = have_pixels = False
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset:offset + 4])
        kind = data[offset + 4:offset + 8]
        end = offset + 8 + length
        if end + 4 > len(data):
            return False
        payload = data[offset + 8:end]
        if zlib.crc32(kind + payload) != int.from_bytes(data[end:end + 4]):
            return False
        if not have_header:
            if kind != b"IHDR" or length != 13:
                return False
            (width, height, depth, color,
             compression, filtering, interlace) = struct.unpack(">IIBBBBB", payload)
            depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8},
                      4: {8, 16}, 6: {8, 16}}
            if (not width or not height or depth not in depths.get(color, set())
                    or compression or filtering or interlace not in (0, 1)):
                return False
            have_header = True
        elif kind == b"IHDR":
            return False
        if kind == b"IDAT":
            have_pixels |= length > 0
        if kind == b"IEND":
            return length == 0 and have_pixels and end + 4 == len(data)
        offset = end + 4
    return False


def _is_jpeg(data: bytes) -> bool:
    if not data.startswith(b"\xff\xd8"):
        return False
    offset = 2
    have_frame = have_scan = False
    while offset < len(data):
        if data[offset] != 0xff:
            return False
        while offset < len(data) and data[offset] == 0xff:
            offset += 1
        if offset >= len(data):
            return False
        marker = data[offset]
        offset += 1
        if marker == 0xd9:
            return have_frame and have_scan and offset == len(data)
        if marker in (0, 0xd8) or 0xd0 <= marker <= 0xd7:
            return False
        if offset + 2 > len(data):
            return False
        length = int.from_bytes(data[offset:offset + 2])
        if length < 2 or offset + length > len(data):
            return False
        if marker in (0xc0, 0xc1, 0xc2):
            if length < 8 or not int.from_bytes(data[offset + 3:offset + 5]):
                return False
            if not int.from_bytes(data[offset + 5:offset + 7]):
                return False
            have_frame = True
        offset += length
        if marker == 0xda:
            have_scan = True
            # Skip entropy-coded bytes, including stuffed FFs and restart markers.
            while offset < len(data):
                if data[offset] != 0xff:
                    offset += 1
                elif offset + 1 < len(data) and (
                        data[offset + 1] == 0 or 0xd0 <= data[offset + 1] <= 0xd7):
                    offset += 2
                else:
                    break
    return False


def _raster(mime: str, value: str) -> str | None:
    # Notebook base64 commonly has line breaks; canonicalize before interpolation.
    compact = "".join(value.split())
    try:
        data = base64.b64decode(compact, validate=True)
    except (ValueError, binascii.Error):
        return None
    valid = _is_png(data) if mime == "image/png" else _is_jpeg(data)
    return base64.b64encode(data).decode("ascii") if valid else None


def _render_copy(notebook: NotebookNode, notices: set[str]) -> NotebookNode:
    result = deepcopy(notebook)
    language = notebook.metadata.get("language_info", {}).get("name", "text")
    lexer = _LANGUAGES.get(language.lower(), "text")
    result.metadata = nbformat.from_dict({"language_info": {"name": lexer}})
    if _fill_cell_ids(result):
        notices.add("Missing cell IDs were generated for this preview only.")
    result.nbformat_minor = 5
    for cell in result.cells:
        cell.metadata = nbformat.NotebookNode()
        cell.source = _text(cell.source)
        if "attachments" in cell:
            attachments: dict[str, dict[str, str]] = {}
            for name, bundle in cell.attachments.items():
                safe: dict[str, str] = {}
                for mime in _RASTER_TYPES:
                    if mime in bundle:
                        image = _raster(mime, _text(bundle[mime]))
                        if image is not None:
                            safe[mime] = image
                if safe:
                    attachments[name] = safe
                if len(safe) != len(bundle):
                    notices.add("Some images or attachments were omitted.")
            cell.attachments = nbformat.from_dict(attachments)
        for output in cell.get("outputs", []):
            if output.output_type == "stream":
                output.text = _text(output.text)
                continue
            if output.output_type not in ("display_data", "execute_result"):
                continue
            filtered: dict[str, str] = {}
            for mime in _MIME_PRIORITY:
                if mime in output.data:
                    value = _text(output.data[mime])
                    if mime in _RASTER_TYPES:
                        value = _raster(mime, value)
                    if value is not None:
                        filtered[mime] = value
            if len(filtered) != len(output.data):
                notices.add(
                    "Unsupported or invalid output representations were omitted.")
            if not filtered:
                filtered["text/plain"] = (
                    "[Output omitted: no supported representation.]")
            output.data = nbformat.from_dict(filtered)
            output.metadata = nbformat.NotebookNode()
    return result


class _StaticMarkdownRenderer(IPythonRenderer):
    def __init__(
            self, *, notices: set[str], attachments: dict[str, dict[str, str]]) -> None:
        super().__init__(embed_images=False, escape=False, attachments=attachments)
        self.notices: set[str] = notices

    @override
    def block_code(self, code: str, info: str | None = None) -> str:
        # Fence info is input too: never resolve arbitrary lexer/plugin names.
        name = (info.strip().split(maxsplit=1)[0].lower()
                if info and info.strip() else "")
        return super().block_code(code, _LANGUAGES.get(name))

    @override
    def _embed_image_or_attachment(self, src: str) -> str:
        if src.startswith("attachment:"):
            name = src[len("attachment:"):]
            if name in self.attachments:
                return super()._embed_image_or_attachment(src)
        elif _valid_image_url(src):
            return src
        self.notices.add("Some images or attachments were omitted.")
        return ""


def _valid_image_url(value: str) -> bool:
    match = _DATA_IMAGE.fullmatch(value)
    return match is not None and _raster(match[1], match[2]) is not None


def _sanitize_body(
        body: str, notices: set[str], *, require_fragment_target: bool = True) -> str:
    tree = cast("Element", html5lib.parseFragment(
        body, treebuilder="etree", namespaceHTMLElements=False))
    identifiers = {
        node.attrib["id"] for node in tree.iter()
        if isinstance(node.tag, str) and node.tag in _BODY_TAGS
        and _IDENTIFIER.fullmatch(node.attrib.get("id", ""))
    }

    def attribute(tag: str, name: str, value: str) -> bool:
        if name == "id":
            return _IDENTIFIER.fullmatch(value) is not None
        if name == "class":
            return (bool(value.split())
                    and all(c in _BODY_CLASSES for c in value.split()))
        if name in ("title", "alt"):
            return name == "title" or tag == "img"
        if tag == "a" and name == "href":
            return (value.startswith("#")
                    and _IDENTIFIER.fullmatch(value[1:]) is not None
                    and (not require_fragment_target or value[1:] in identifiers))
        if tag == "img" and name == "src":
            valid = _valid_image_url(value)
            if not valid:
                notices.add("Some images or attachments were omitted.")
            return valid
        if ((tag in ("td", "th") and name in ("colspan", "rowspan"))
                or (tag == "ol" and name == "start")):
            return value.isascii() and value.isdecimal()
        if tag == "div" and name == "data-jp-theme-light":
            return value == "true"
        if tag == "div" and name == "data-jp-theme-name":
            return value == "JupyterLab Light"
        return False

    # Bleach uses an HTML5 parser, including foreign-content/parser-repair rules.
    # A fresh cleaner per call avoids sharing its non-thread-safe parser.
    return bleach.Cleaner(
        tags=_BODY_TAGS, attributes=attribute, protocols={"data"},
        strip=True, strip_comments=True).clean(body)


@final
class _StaticHTMLExporter(HTMLExporter):
    @override
    def _init_preprocessors(self) -> None:
        # Even disabled preprocessors trigger nbconvert's relaxed validation and
        # can alter nbformat's shared schema cache. We need no preprocessing at
        # all: MIME filtering/normalization and packaged CSS are supplied here.
        self._preprocessors = []


def _exporter() -> HTMLExporter:
    # Resolve wheel-owned assets, not JUPYTER_PATH, CWD, or a user's templates.
    package = distribution("nbconvert")
    for entry in package.files or ():
        if entry.as_posix().endswith(
                "share/jupyter/nbconvert/templates/lab/index.html.j2"):
            root = Path(str(package.locate_file(entry))).resolve().parents[1]
            break
    else:
        raise RuntimeError(
            "The installed nbconvert lab template assets are unavailable.")
    config = Config({
        "NbConvertBase": {"display_data_priority": list(_MIME_PRIORITY)},
    })
    return _StaticHTMLExporter(
        config=config, template_name="lab", template_file="static.html.j2",
        template_paths=[str(_TEMPLATE_DIRECTORY), str(root / "lab"),
                        str(root / "base"), str(root)],
        template_data_paths=[], extra_template_basedirs=[], extra_template_paths=[],
        default_preprocessors=[], preprocessors=[],
        sanitize_html=True, embed_images=False, theme="light",
    )


def render_notebook(data: bytes) -> RenderedNotebook:
    """Render saved outputs without executing cells or reading referenced files."""
    notices = {"Saved outputs were submitted by the student and were not reproduced "
               "by execution."}
    notebook = _render_copy(validate_notebook(data), notices)
    exporter = _exporter()

    @pass_context
    def markdown(context: Context, source: str) -> str:
        cell = context.get("cell", {})
        renderer = _StaticMarkdownRenderer(
            notices=notices, attachments=cell.get("attachments", {}))
        return MarkdownWithMath(renderer=renderer).render(source)

    exporter.register_filter("markdown2html", markdown)

    # nbconvert's default clean_html escapes all img tags, including validated
    # raster attachments. Use our stricter policy here as well as on the final
    # fragment: neither pass permits generic data URLs or external resources.
    # Cell-local passes cannot yet check links to targets in other cells. Keep
    # syntactically safe fragments here; the final pass checks actual targets.
    def clean_html(html: str) -> str:
        return _sanitize_body(html, notices, require_fragment_target=False)

    exporter.register_filter("clean_html", clean_html)
    body, _ = exporter.from_notebook_node(notebook)
    body = _sanitize_body(body, notices)

    # An independent, empty notebook is the only source of trusted CSS. Never
    # extract styles from the submitted body, even after parsing it as HTML.
    css_html, _ = exporter.from_notebook_node(
        nbformat.v4.new_notebook(), resources={
            "relate_css_only": True,
            "inlining": {"css": [HtmlFormatter(style=JupyterStyle).get_style_defs(
                ".highlight")]},
        })
    css_tree = cast("Element", html5lib.parseFragment(
        css_html, treebuilder="etree", namespaceHTMLElements=False))
    css_parts: list[str] = []
    for node in css_tree:
        if node.tag != "style":
            raise RuntimeError("Unexpected content in packaged notebook stylesheets.")
        css_parts.append(node.text or "")
    if not css_parts:
        raise RuntimeError("Packaged notebook stylesheets are missing.")
    notice_html = "".join(f"<p>{escape(notice)}</p>" for notice in sorted(notices))
    return RenderedNotebook(body_html=notice_html + body, css="\n".join(css_parts))
