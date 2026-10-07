# Rendering uploaded notebooks for grading

## Decision

Render Jupyter notebooks **in Python, in process, using `nbformat` and
`nbconvert.HTMLExporter`**, without executing cells. Display the result in a
**sandboxed iframe with an opaque origin**, with a response-header Content
Security Policy (CSP) that also applies when the document is opened directly.
Use nbconvert's packaged `lab` template and CSS; do not vendor Jupyter CSS or
reimplement notebook presentation.

The iframe is a security boundary, not a choice of rendering engine. Python
rendering and an iframe are complementary. Make the frame borderless,
full-width, and automatically sized by a narrowly scoped, trusted resize
script. Keep grading controls, downloads, and preview-status notices outside
it, in RELATE's trusted document.

Start with a static preview: Markdown, source code, stream/error output,
sanitized HTML tables, and embedded PNG/JPEG plots. Do not support notebook
JavaScript, widgets, arbitrary extensions, external resources, or cell
execution. Initially show mathematical expressions as their source; math
rendering is a separately reviewed enhancement, not a reason to enable the
exporter's default CDN scripts.

**A separate domain is not required for this initial design:** a sandbox
without `allow-same-origin` creates an opaque origin even for a same-origin
URL. Enforce that sandbox both in the iframe and in the HTTP response. 

The initial static-preview implementation follows this design. The lockfile
selects nbconvert 7.17.1 and nbformat 5.11.1. Notebook validation supports format
4, minor versions 0 through 5; missing cell IDs are accepted and generated only
in the rendering copy, with a notice. The page's configured upload-byte limit
is the initial resource budget; further limits and caching remain future work.

The Python acceptance tests are in `tests/test_notebook_rendering.py`,
`tests/test_notebook_upload.py`, and `tests/test_answer_resources.py`. Real-browser
security tests are in `tests/test_notebook_browser.py` and have been exercised
in Chromium, Firefox, and WebKit with Playwright 1.63.0. To run them in a fresh
development environment, install Playwright and its browser/system dependencies
using its documented installation procedure, then run:

```sh
uv run --with playwright==1.63.0 pytest --slow tests/test_notebook_browser.py -v
```

These optional tests skip when Playwright or the selected browser is unavailable.
Deployment-specific reverse-proxy header preservation still requires checking
in the deployed environment.

## Pre-implementation integration points

- `course/page/upload.py` currently accepts PDF, plain text, and octet-stream.
  `file_to_answer_data()` records bytes in `RELATE_BULK_STORAGE` and saves a
  MIME type in answer JSON. With one configured MIME type it overrides the
  browser-provided type. With multiple types it keeps the browser's claim.
  `clean_uploaded_file()` currently checks a PDF header only when PDF is the
  sole configured type; it does not otherwise enforce a content-type whitelist.
- `form_to_html()` reads the entire upload and embeds a base64 data URL into
  `course/templates/course/file-upload-form.html`.
- `frontend/js/rlUtils.js` previews PDFs through an `<object>`; it has no
  notebook renderer. Notebooks must not go through this object/blob mechanism.
- Both `course/flow.py:view_flow_page()` and
  `course/grading.py:grade_flow_page()` call the page's `form_to_html()`.
  Consequently one preview implementation can serve student review and human
  grading. The grading view can display an older answer selected through a
  historical grade, not just the latest answer.
- `PageContext` has a flow session but no identifier for the exact displayed
  answer visit. `FlowPageContext` has `prev_answer_visit`, but historical grading
  can instead use `shown_grade.visit`. This distinction is important for a
  preview endpoint: it must render the answer currently on screen.
- `relate/urls.py` owns Django URL registration. The page API currently has no
  answer-resource endpoint hook.
- `pyproject.toml` already includes Bleach, html5lib, Pygments, and Celery, but
  not nbformat/nbconvert. No Jupyter server or kernel dependency is needed.

## Notebook identification and validation

Add `application/x-ipynb+json` to `UploadableMimeType` and the page documentation.
It is the conventional Jupyter notebook media type, not a basis for trusting
content. Map it explicitly to `.ipynb` for storage names and
`normalized_bytes_answer()`; do not depend on a platform's `mimetypes` database
knowing this extension.

For notebook-only questions, the configured MIME type determines the intended
format. Browser uploads frequently report JSON or octet-stream instead. Use an
`accept` hint such as `.ipynb,application/x-ipynb+json`, but make the server
parser authoritative. Do not require the browser to supply the notebook MIME
type and do not trust the filename.

For mixed-format questions, a notebook MIME claim selects notebook validation;
when notebooks are allowed, JSON-looking content may also be checked as a
notebook to accommodate generic browser types. Do not reinterpret arbitrary
JSON as a notebook or silently render octet-stream answers unless the question
allows notebooks. If multiple formats cannot be distinguished confidently,
require an explicit format choice rather than trusting a filename. Store the
validated, canonical notebook MIME type after recognition.

Use bounded UTF-8 JSON parsing followed by nbformat validation. Initially
support notebook format 4, with an explicit policy for supported minor
versions; reject unsupported major versions instead of silently guessing.
Decide explicitly whether benign normalization, such as missing cell IDs, is
accepted with a warning. Preserve the original submitted bytes regardless.
Validation is not a trust check: valid notebooks can contain malicious output.

New notebook submissions should receive actionable validation errors before
storage. Revalidate old stored answers before rendering; failed previews must
not prevent grading or downloading the original answer. Existing
`storage_filename` and legacy `base64_data` answers remain supported. No
submission schema migration is needed merely to add a preview.

## Rendering pipeline

Introduce a focused service, for example `course/notebook_rendering.py`,
independent of HTTP and page classes:

1. Read the original bytes through `get_content_from_answer_data()`, under a
   separate preview-size budget. Parse and validate under structural limits.
2. Build a **rendering-only copy**. Discard notebook/cell trust claims, widget
   state, tag-driven visibility controls, exporter filename/path metadata, and
   arbitrary presentation metadata. Preserve cell order, source, outputs, and
   execution counts. Retain only explicitly allowed bounded metadata, such as
   a known language name and validated image dimensions. Do not pass arbitrary
   lexer names or filesystem paths through to dependency configuration.
3. Filter output MIME bundles before export, not merely after choosing their
   highest-priority representation. Allow sanitized HTML/Markdown, PNG/JPEG,
   plain text, and escaped LaTeX source. Remove JavaScript, widget MIME types,
   SVG, Mermaid, PDF, and unknown active formats. Choose an explicit priority
   among the retained formats. If no supported representation remains, insert
   an honest "output omitted" marker; preserve a plain-text fallback where
   available. Do not allow an unsupported high-priority type to suppress a
   usable fallback.
4. Call `HTMLExporter.from_notebook_node()` directly with application-owned
   configuration, `template_name="lab"`, and `sanitize_html=True`. Use
   `embed_images=False`: Markdown embedding can read referenced files and must
   not become a local-file-disclosure feature. Support notebook-contained
   raster attachments, not server files or remote image retrieval.
5. Use a small derived template to suppress RequireJS, widget, MathJax,
   Mermaid, and other script blocks. Render raw cells as escaped source, not
   raw HTML. Keep all code cells and outputs visible, irrespective of notebook
   tags or hidden/collapsed metadata. Do not run execution, SVG/PDF conversion,
   browser export, custom preprocessors, or extension discovery controlled by
   the submission. Use explicit application configuration, not an nbconvert
   command-line application or user Jupyter config files.
6. Apply a restrictive HTML5-aware sanitation pass to the resulting **body
   fragment**. Allow the notebook's structural elements, tables, code, and
   raster images; remove script/style elements, event handlers, forms,
   embedded documents, objects, SVG/MathML, `base`, `meta`, inline styles,
   arbitrary URL-bearing attributes, and other active content. Allow image
   sources only for bounded, validated PNG/JPEG data URLs. Strip `srcset` and
   alternate fetching attributes. Allow only validated in-document fragment
   links; external links are visible text, not clickable navigation.
7. Assemble that fragment into a trusted HTML shell, using the stylesheet
   output from the package's template resources, plus RELATE's fixed resize
   script. Assign per-response nonces only to trusted style/script elements.
   Never attach a nonce to a tag obtained from the submitted body. The shell's
   title and all notices are escaped application text.

`sanitize_html=True` is defense in depth, not the complete policy: nbconvert's
own defaults and sanitizer policy are not a promise to enforce our MIME,
network, navigation, or stylesheet restrictions. Sanitize the body without
sanitizing away the trusted upstream styles, and test HTML parser-repair cases
that attempt to escape into the head.

Use the existing Bleach/html5lib stack if it can express the policy precisely;
image and attribute validation will need explicit callbacks. Reassess its
maintenance/security status when implementing rather than treating its
presence as sufficient evidence. In particular, allowing `data:` generically
is not the same as allowing validated raster data URLs.

### CSS ownership

nbconvert's `lab` template embeds packaged `static/index.css` and theme CSS
through `resources.include_css()`, with syntax-highlighting CSS in its
resources. Consume these from the installed dependency at render time. The
small derived template changes behavior, not the notebook stylesheet: RELATE
owns no copy of Jupyter CSS. The iframe prevents upstream global styles from
colliding with Bootstrap and grading controls.

Pin compatible, patched nbconvert/nbformat versions in the normal lockfile.
Test the derived template and asset collection when upgrading, since template
block names and packaged assets are an integration surface. Use a fixed
packaged light theme initially; do not search for themes named by notebook
metadata. A tiny RELATE stylesheet for the outer frame/status UI is fine.

## Browser security contract

Assume every notebook field is hostile, including Markdown, HTML outputs,
metadata, code, attachments, and MIME claims. Notebook signatures or
`metadata.trusted` are never authority to enable richer rendering.

Serve the preview as `text/html; charset=utf-8`, with a response-header CSP
along these lines (the nonce placeholders represent fresh server-generated
values, not literal configuration):

```text
Content-Security-Policy:
  default-src 'none';
  sandbox allow-scripts;
  script-src 'nonce-<script nonce>';
  script-src-attr 'none';
  style-src 'nonce-<style nonce>';
  style-src-attr 'none';
  img-src data:;
  font-src data:;
  connect-src 'none';
  frame-src 'none';
  object-src 'none';
  base-uri 'none';
  form-action 'none';
  frame-ancestors 'self'
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
Cache-Control: private, no-store
```

The actual CSP header is one line. Any data-URL fonts must be trusted upstream
assets. Relaxations for particular versions' styles need tests, not a broad
`unsafe-inline` exception. Apply appropriate restrictive Permissions Policy
as well; the frame needs no device capabilities.

The parent uses `<iframe sandbox="allow-scripts" referrerpolicy="no-referrer">`.
**Do not add `allow-same-origin`, forms, popups, downloads, top-navigation,
storage-access, or sandbox-escape permissions.** No `unsafe-eval`, generic
script sources, remote CDNs, or network requests are necessary. Header sandbox
is essential because users can open the preview URL in a new tab; an iframe
attribute alone does not protect that case. A meta CSP cannot provide this
sandbox directive.

Allowing scripts here authorizes only the application script via CSP; it does
not authorize notebook JavaScript. Even a sanitizer bypass cannot acquire
RELATE's origin from this sandbox. Conversely, sandboxing does not prohibit
network access by itself, so retain CSP and URL filtering. `default-src` is
not a general navigation prohibition: remove external links and navigation
constructs rather than assuming CSP blocks them all.

Same-origin iframe navigation can initially carry RELATE's cookies to the
server for ordinary Django authorization. The resulting document cannot read
cookies, local storage, or the parent DOM. Do not enable CORS for opaque
`Origin: null`, and do not expose a privileged parent RPC bridge.

Make sure Django middleware, the reverse proxy, and error handlers preserve
the required headers. For a same-origin preview, ordinary SAMEORIGIN framing
headers are compatible; an inherited DENY would block it. Failed renders and
endpoint error documents must also be inert/sandboxed and must not fall back
to displaying raw notebook HTML. A browser without the required sandbox/CSP
support receives a download-only experience.

## Endpoint and page API

Add a small, read-only **answer-resource API**, rather than registering
arbitrary Django views from page implementations:

- Extend the page-rendering context with an optional framework-generated
  resource URL builder for the **exact displayed answer**. Default to absent
  for sandbox/unsaved answers. Keep course/session/visit authorization in the
  view layer, not in `FileUploadQuestion`.
- The flow and grading drivers bind this builder to their selected persisted
  answer visit. For historical grading this is `shown_grade.visit`, not the
  latest answer. This avoids guessing an answer from `PageContext.flow_session`
  or encoding bulk-storage filenames in public URLs.
- Give `PageBase` an optional hook such as
  `render_answer_resource(page_context, page_data, answer_data, resource_name)`
  returning an application-defined resource result, or declining the request.
  `FileUploadQuestion` supports explicit names such as `notebook-preview` and
  `original`. These are proposed interfaces, not existing methods.
- Register one framework dispatcher in `relate/urls.py`, with identifiers for
  course, session, page, answer visit, access mode, and allowlisted resource
  name. It accepts GET/HEAD only. It loads the answer from the database and
  reconstructs the appropriate page/version; it never accepts answer JSON,
  a filesystem path, an exporter name, or a template name from the requester.
- Factor the relevant existing authorization logic into shared helpers.
  Grading-mode access requires the same course-scoped
  `PPerm.view_gradebook` checks as `grade_flow_page()`. Student-review access
  requires the flow/session ownership or delegated-view permissions **and**
  applicable current page/answer-visibility rules. Session access alone is
  insufficient authority to enumerate every historical answer.
- Validate all course/session/page/visit relationships, current permissions,
  supported resource names, and answer availability before invoking the page
  hook or reading bulk storage. Match denial behavior to existing views.
  Never use Django's global `is_staff` flag as course authorization.
- Keep the sandbox/CSP policy in a framework-owned resource response builder.
  A page hook must not accidentally opt an untrusted preview into an ordinary
  trusted HTML response. Originals are attachment responses, not inline HTML.

For notebooks, `form_to_html()` emits an authorized preview URL and a separate
original-download URL, not the notebook bytes as base64 in the parent DOM.
The notebook download gets an application-generated `.ipynb` name,
`Content-Disposition: attachment`, the canonical MIME type, `nosniff`, and
private caching policy. Downloading is outside the sandbox and is never
implemented with a notebook-controlled link.

Keep existing non-notebook behavior unchanged where possible; broad PDF
preview redesign is outside this change. The new resource facility is reusable
but should not become an arbitrary asset router before another page needs it.

## Making the iframe feel native

Use a full-width borderless frame, an accessible title, a loading/error state,
and an initial sensible height. Let the surrounding grading page scroll for
ordinary notebooks. The trusted script measures the notebook container after
load, on width changes, and when raster images load; a throttled
`ResizeObserver` sends a height-only message to the parent.

Opaque origins produce `event.origin === "null"`, which is **not** sufficient
message authentication. The parent must match `event.source` to the exact
frame's `contentWindow`, verify a per-frame random channel identifier, validate
the message schema, and clamp a finite numeric height. Accept no HTML, URLs,
selectors, commands, or rendering configuration. The child sends only to the
server-configured LMS origin. Never have the parent measure the child DOM by
adding `allow-same-origin`.

Cap automatic height and message frequency; exceptionally long notebooks use
a bounded inner scroller or a standalone expanded preview. This is preferable
to an arbitrarily tall hostile document. Provide a visible preview-status
summary and download fallback outside the frame. A standalone preview link
uses the same hardened endpoint and `rel="noopener noreferrer"`.

No notebook content appears in grading controls. Omitted outputs, remote
resources, and truncations are clearly indicated. State explicitly that saved
outputs were submitted by the student and were **not reproduced by execution**;
they are not evidence that the displayed code generated them.

## Resource usage, errors, and caching

As a first step, only limit upload bytes.

Leave implementation comments for additional limits as outlined in this section.

One could define separate budgets for preview bytes,
JSON nesting, cells, source lengths, output counts/lengths, embedded-image bytes
and pixel dimensions, and final HTML size. Start conservatively, make limits
configurable, and tune using representative course submissions. Bound parsing
before relying on schema validation; deeply nested JSON can fail earlier.

Prepare the design for caching of rendered notebooks, but build no caches.

When parsing, conversion, sanitation, or limits fail, retain the saved answer
and grading form, show a clear escaped error, and offer the original download.
Log an internal error identifier without recording notebook contents or
access capabilities. Preview availability must not determine gradeability.

## Math and richer outputs

Math is useful but not free: nbconvert's default lab HTML includes a MathJax
script hook, and current upstream templates also include other script hooks.

Load a pinned, locally packaged renderer only in
the sandbox, with safe settings, no user extension
loading, and tests for URL/CSS/HTML-producing commands. Its script/font/CSP
needs require a separate review.

Do not add an instructor "trust this notebook" switch. Interactive widgets,
JavaScript plots, and SVG-only outputs remain unsupported unless a separate
threat model and rendering policy is approved. Prefer retained PNG or text
representations; do not launch external conversion programs to recover them.

## Implementation order and acceptance tests

1. Add the MIME type, explicit extension mapping, parser/limits, and validation
   tests, including generic browser MIME reports and legacy stored answers.
2. Implement the pure conversion service and small derived template. Test
   code, Markdown, raw cells, errors/ANSI text, tables, raster plots,
   attachments, unsupported MIME fallbacks, and hidden-cell metadata.
3. Add the answer-resource context/hook/dispatcher and shared authorization.
   Test another course, another student, historical grades, revoked
   permissions, absent answers, fabricated relationships, and cache hits.
4. Add the iframe, resize bridge, download route, and status/error UI in the
   existing upload template/frontend integration.
5. Run browser-level security and visual tests in supported Chromium, Firefox,
   and WebKit. Check cookies/storage/parent DOM access are denied, unauthorized
   scripts never run, no notebook-triggered network requests occur, and direct
   URL navigation remains sandboxed. Exercise script/event-handler injection,
   parser-repair attacks, metadata/attribute injection, SVG/data-HTML URLs,
   remote images/CSS, meta refresh, base tags, forms, nested frames, external
   navigation, and forged resize messages. Verify hostile content cannot hide
   grading controls and cannot silently hide entire code cells.
6. Check deployment headers on successes, errors, and standalone previews;
   verify framing compatibility, font/image rendering, output sanitation,
   auto-height behavior, large-notebook fallback, and rendering without CDNs.

Use Python tests for conversion and access control, but do not treat sanitizer
unit tests as proof of browser isolation. Add dependency-upgrade regression
fixtures for the template and CSP contract. Run `uv run ruff check`,
`uv run basedpyright`, and the targeted pytest suite for implementation changes.
