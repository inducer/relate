"""Authorized answer resources with a framework-owned browser security policy."""

from __future__ import annotations

import json
import logging
import re
import secrets
from html import escape
from typing import TYPE_CHECKING, Literal, cast
from urllib.parse import urlencode, urlsplit

from django import http
from django.conf import settings
from django.core.exceptions import (
    ObjectDoesNotExist,
    PermissionDenied,
    SuspiciousOperation,
)
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from course.models import FlowPageVisit, FlowSession
from course.utils import FlowPageContext, PageOrdinalOutOfRange, course_view


if TYPE_CHECKING:
    from course.page.base import AnswerData, AnswerResource, PageContext, PageData
    from course.utils import CoursePageContext


AccessMode = Literal["grading", "review"]
_RESOURCE_NAMES = frozenset({"notebook-preview", "original"})
_CHANNEL = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")
_MIME_TYPE = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+\Z")
logger = logging.getLogger(__name__)


def bind_answer_resource_url(
        page_context: PageContext,
        visit: FlowPageVisit | None,
        access_mode: AccessMode,
        ) -> None:
    """Bind URLs to displayed persisted bytes, not a session's latest answer.

    The random channel correlates resize messages only: it grants no access.
    Both URLs from one builder share it so the parent can read it from the URL.
    """
    page_context.answer_resource_url = None
    if (page_context.in_sandbox or visit is None or visit.pk is None
            or cast("AnswerData", visit.answer) is None
            or visit.page_data.page_ordinal is None):
        return

    channel = secrets.token_urlsafe(32)
    args = (page_context.course.identifier, visit.flow_session.pk,
            visit.page_data.page_ordinal, visit.pk, access_mode)

    def resource_url(resource_name: str) -> str:
        if resource_name not in _RESOURCE_NAMES:
            raise ValueError("Unsupported answer resource")
        return reverse("relate-answer_resource", args=(*args, resource_name)) + "?" + (
                urlencode({"channel": channel}))

    page_context.answer_resource_url = resource_url


def _harden_response(
        response: http.HttpResponse, script_nonce: str, style_nonce: str,
        ) -> http.HttpResponse:
    response["Content-Security-Policy"] = "; ".join([
        "default-src 'none'", "sandbox allow-scripts",
        f"script-src 'nonce-{script_nonce}'", "script-src-attr 'none'",
        f"style-src 'nonce-{style_nonce}'", "style-src-attr 'none'",
        "img-src data:", "font-src data:", "connect-src 'none'",
        "frame-src 'none'", "object-src 'none'", "base-uri 'none'",
        "form-action 'none'", "frame-ancestors 'self'",
    ])
    response["Referrer-Policy"] = "no-referrer"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    response["Permissions-Policy"] = (
            "accelerometer=(), autoplay=(), camera=(), display-capture=(), "
            "encrypted-media=(), fullscreen=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), midi=(), payment=(), usb=(), "
            "screen-wake-lock=(), xr-spatial-tracking=()")
    response["X-Frame-Options"] = "SAMEORIGIN"
    return response


def _error_response(message: str, status: int) -> http.HttpResponse:
    return http.HttpResponse(
            '<!doctype html><html><head><meta charset="utf-8">'
            '<title>Answer resource unavailable</title></head><body><p>'
            + escape(message) + "</p></body></html>",
            status=status, content_type="text/html; charset=utf-8")


def _log_failure() -> None:
    # Never log exception text, traceback locals, submitted bytes, or URLs.
    logger.error("Answer resource failed (error ID %s)", secrets.token_hex(8))


def _lms_origin(request: http.HttpRequest) -> str:
    configured_url = getattr(settings, "RELATE_BASE_URL", None)
    url = urlsplit(configured_url or f"{request.scheme}://{request.get_host()}")
    if (url.scheme not in {"https", "http"} or not url.netloc
            or url.username is not None or url.password is not None):
        raise SuspiciousOperation("Invalid configured LMS origin")
    return f"{url.scheme}://{url.netloc}"


def _script_json(value: str) -> str:
    return json.dumps(value).replace("<", "\\u003c").replace(
            ">", "\\u003e").replace("&", "\\u0026")


def _preview_response(
        request: http.HttpRequest,
        content: bytes,
        channel: str | None,
        script_nonce: str,
        style_nonce: str,
        ) -> http.HttpResponse:
    from course.notebook_rendering import render_notebook

    try:
        rendered = render_notebook(content)
    except Exception:
        _log_failure()
        return _error_response(
                "The notebook preview could not be rendered. "
                "Download the original submission instead.", 422)

    script = ""
    if channel is not None:
        # Observe the content container, not the viewport: changing the parent
        # iframe height must not create an ever-growing resize feedback loop.
        script = f"""<script nonce="{script_nonce}">
(() => {{
    const channel = {_script_json(channel)};
    const targetOrigin = {_script_json(_lms_origin(request))};
    const content = document.getElementById("relate-notebook");
    let pending = false;
    let lastHeight = -1;
    function schedule() {{
        if (pending) return;
        pending = true;
        setTimeout(() => {{
            pending = false;
            const measured = Math.ceil(content.getBoundingClientRect().height);
            if (!Number.isFinite(measured)) return;
            const height = Math.max(100, Math.min(20000, measured));
            if (height === lastHeight) return;
            lastHeight = height;
            window.parent.postMessage({{
                type: "relate-notebook-resize", channel, height
            }}, targetOrigin);
        }}, 100);
    }}
    if (typeof ResizeObserver !== "undefined") {{
        new ResizeObserver(schedule).observe(content);
    }}
    window.addEventListener("load", schedule);
    window.addEventListener("resize", schedule);
    content.addEventListener("load", schedule, true);
    schedule();
}})();
</script>"""

    return http.HttpResponse(
            '<!doctype html><html><head><meta charset="utf-8">'
            '<title>Submitted notebook preview</title>'
            f'<style nonce="{style_nonce}">{rendered.css}</style>'
            '</head><body><div id="relate-notebook">'
            + rendered.body_html + "</div>" + script + "</body></html>",
            content_type="text/html; charset=utf-8")


def _original_response(resource: AnswerResource) -> http.HttpResponse:

    # Hooks provide application-owned MIME/name, not the upload's claims. Still
    # defend against paths, controls, or malformed headers at this boundary.
    name = (resource.filename or "answer.ipynb").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name).lstrip(".")[:150] or "answer.ipynb"
    content_type = resource.content_type
    if not _MIME_TYPE.fullmatch(content_type):
        content_type = "application/octet-stream"
    response = http.HttpResponse(resource.content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


@course_view
def _dispatch_answer_resource(
        pctx: CoursePageContext,
        flow_session_id: int,
        page_ordinal: int,
        visit_id: int,
        access_mode: str,
        resource_name: str,
        channel: str | None,
        script_nonce: str,
        style_nonce: str,
        ) -> http.HttpResponse:
    from course.flow import (
        adjust_flow_session_page_data,
        check_flow_page_view_permissions,
        get_and_check_flow_session,
        select_flow_page_answer_visit,
    )
    from course.grading import check_gradebook_permission

    if access_mode == "grading":
        check_gradebook_permission(pctx)
        flow_session = get_object_or_404(
                FlowSession, pk=flow_session_id, course=pctx.course)
        if flow_session.participation is None:
            raise SuspiciousOperation("Cannot grade anonymous session")
        participation = flow_session.participation
    elif access_mode == "review":
        flow_session = get_and_check_flow_session(pctx, flow_session_id)
        participation = pctx.participation
    else:
        raise http.Http404()

    adjust_flow_session_page_data(
            pctx.repo, flow_session, respect_preview=access_mode == "review")
    fpctx = FlowPageContext(
            pctx.repo, pctx.course, flow_session.flow_id, page_ordinal,
            participation=participation, flow_session=flow_session,
            request=pctx.request)
    if fpctx.page is None or fpctx.page_context is None:
        raise http.Http404()

    if access_mode == "review":
        check_flow_page_view_permissions(pctx, fpctx, flow_session)
        _, visit, _ = select_flow_page_answer_visit(
                fpctx.page_data, visit_id, strict=True)
    else:
        visit = get_object_or_404(
                FlowPageVisit, pk=visit_id, flow_session=flow_session,
                page_data=fpctx.page_data)

    # Check both foreign keys even for malformed legacy records. Do this before
    # the hook can read any bulk storage.
    if (visit is None or visit.flow_session.pk != flow_session.pk
            or visit.page_data.pk != fpctx.page_data.pk
            or cast("AnswerData", visit.answer) is None
            or not fpctx.page.expects_answer()):
        raise http.Http404()

    bind_answer_resource_url(fpctx.page_context, visit, access_mode)
    resource = fpctx.page.render_answer_resource(
            fpctx.page_context, cast("PageData", fpctx.page_data.data),
            cast("AnswerData", visit.answer), resource_name)
    if resource is None or resource.kind != resource_name:
        raise http.Http404()
    if resource.kind == "notebook-preview":
        return _preview_response(
                pctx.request, resource.content, channel, script_nonce, style_nonce)
    return _original_response(resource)


@csrf_exempt
def answer_resource(
        request: http.HttpRequest,
        course_identifier: str,
        flow_session_id: int,
        page_ordinal: int,
        visit_id: int,
        access_mode: str,
        resource_name: str,
        ) -> http.HttpResponse:
    """GET/HEAD-only dispatcher, including inert failures outside course_view.

    CSRF exemption ensures disallowed methods get our hardened 405 rather than
    an ordinary middleware error document; this endpoint never accepts writes.
    """
    script_nonce = secrets.token_urlsafe(24)
    style_nonce = secrets.token_urlsafe(24)
    try:
        if request.method not in {"GET", "HEAD"}:
            response = _error_response("Only GET and HEAD are allowed.", 405)
            response["Allow"] = "GET, HEAD"
        elif (resource_name not in _RESOURCE_NAMES
                or access_mode not in {"grading", "review"}):
            response = _error_response("Answer resource not found.", 404)
        else:
            channel = request.GET.get("channel")
            if channel is not None and not _CHANNEL.fullmatch(channel):
                raise SuspiciousOperation("Invalid frame channel")
            response = _dispatch_answer_resource(
                    request, course_identifier, int(flow_session_id), int(page_ordinal),
                    int(visit_id), access_mode, resource_name, channel,
                    script_nonce, style_nonce)
    except PermissionDenied:
        response = _error_response("You may not view this answer resource.", 403)
    except (http.Http404, ObjectDoesNotExist, PageOrdinalOutOfRange):
        response = _error_response("Answer resource not found.", 404)
    except (SuspiciousOperation, ValueError):
        response = _error_response("Invalid answer resource request.", 400)
    except Exception:
        _log_failure()
        response = _error_response("The answer resource is currently unavailable.", 500)

    response = _harden_response(response, script_nonce, style_nonce)
    response["Content-Length"] = str(len(response.content))
    if request.method == "HEAD":
        response = http.HttpResponse(
                b"", status=response.status_code, headers=dict(response.items()))
    return response
