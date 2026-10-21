from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from django import http
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.urls import resolve

from course import answer_resources as resources, flow, grading
from course.constants import FlowPermission, ParticipationPermission as PPerm
from course.models import FlowPageData
from course.page.base import AnswerResource, PageBase, PageContext
from course.utils import PageOrdinalOutOfRange
from tests import factories


if TYPE_CHECKING:
    from collections.abc import Set as AbstractSet
    from typing import Any, Literal

    from course.page.base import AnswerData, PageData


CHANNEL = "a" * 43


def assert_hardened(response: http.HttpResponse) -> None:
    csp = response["Content-Security-Policy"]
    for directive in [
            "default-src 'none'", "sandbox allow-scripts",
            "script-src-attr 'none'", "style-src-attr 'none'",
            "frame-ancestors 'self'", "connect-src 'none'", "form-action 'none'"]:
        assert directive in csp
    assert "allow-same-origin" not in csp
    assert "unsafe-inline" not in csp
    assert "unsafe-eval" not in csp
    assert response["Referrer-Policy"] == "no-referrer"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-Frame-Options"] == "SAMEORIGIN"
    assert "camera=()" in response["Permissions-Policy"]


@pytest.fixture
def environment(
        db: object,  # pyright: ignore[reportUnusedParameter]
        monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    session = factories.FlowSessionFactory(in_progress=True, page_count=2)
    data = factories.FlowPageDataFactory(flow_session=session, page_ordinal=0)
    visit = factories.FlowPageVisitFactory(
            page_data=data, answer={"content": "original bytes"},
            is_submitted_answer=True)
    request = RequestFactory().get("/", {"channel": CHANNEL})
    request.user = session.user
    request.session = {}
    request.relate_facilities = frozenset()
    pctx = SimpleNamespace(
            request=request, course=session.course,
            course_identifier=session.course.identifier,
            participation=session.participation, repo=Mock(),
            has_permission=Mock(return_value=True), permissions=Mock(return_value=[]))
    manager = Mock()
    manager.__enter__ = Mock(return_value=pctx)
    manager.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("course.utils.CoursePageContext", Mock(return_value=manager))
    monkeypatch.setattr(flow, "adjust_flow_session_page_data", Mock())
    monkeypatch.setattr(flow, "get_login_exam_ticket", Mock(return_value=None))
    monkeypatch.setattr(flow, "lock_down_if_needed", Mock())
    monkeypatch.setattr(messages, "add_message", Mock())
    access_rule = SimpleNamespace(permissions={FlowPermission.view}, message=None)
    monkeypatch.setattr(
            "course.utils.get_session_access_mode", Mock(return_value=access_rule))

    page = Mock()
    page.expects_answer.return_value = True
    page.is_answer_gradable.return_value = False

    def unchanged_permissions(
            permissions: AbstractSet[FlowPermission]) -> AbstractSet[FlowPermission]:
        return permissions

    def render_resource(
            _ctx: PageContext, _data: PageData, answer: dict[str, str],
            name: Literal["notebook-preview", "original"]) -> AnswerResource:
        return AnswerResource(name, answer["content"].encode(), "answer.ipynb")

    page.get_modified_permissions_for_page.side_effect = unchanged_permissions
    page.render_answer_resource.side_effect = render_resource
    contexts = []

    def make_fpctx(repo: Any, course: Any, flow_id: str, ordinal: int,
                   participation: Any, flow_session: Any,
                   request: Any) -> SimpleNamespace:
        if ordinal >= flow_session.page_count:
            raise PageOrdinalOutOfRange()
        page_data = FlowPageData.objects.get(
                flow_session=flow_session, page_ordinal=ordinal)
        ctx = SimpleNamespace(
                page=page, page_data=page_data, flow_desc=Mock(), flow_id=flow_id,
                page_ordinal=ordinal, course=course, course_commit_sha=b"revision",
                prev_answer_visit=visit,
                page_context=PageContext(course, repo, b"revision", flow_session,
                                         request=request))
        contexts.append((ctx, participation))
        return ctx

    monkeypatch.setattr(resources, "FlowPageContext", make_fpctx)
    monkeypatch.setattr(grading, "FlowPageContext", make_fpctx)
    # Isolate the HTTP contract from the renderer/dependency team's work.
    renderer = Mock(return_value=SimpleNamespace(
            body_html='<p id="cell">Sanitized notebook</p>', css="p { color: black; }"))
    monkeypatch.setitem(sys.modules, "course.notebook_rendering",
                        SimpleNamespace(render_notebook=renderer))

    def get(mode: str = "review", name: str = "original",
            requested_visit: int | None = None, ordinal: int = 0,
            method: str = "GET", query: dict[str, str] | None = None,
            ) -> http.HttpResponse:
        pctx.request.method = method
        if query is not None:
            pctx.request.GET = query
        return resources.answer_resource(
                pctx.request, session.course.identifier, session.pk, ordinal,
                visit.pk if requested_visit is None else requested_visit,
                mode, name)

    return SimpleNamespace(
            session=session, data=data, visit=visit, page=page, pctx=pctx,
            rule=access_rule, get=get, contexts=contexts, make_fpctx=make_fpctx,
                        renderer=renderer)


def test_page_api_defaults() -> None:
    ctx = PageContext(Mock(), Mock(), b"revision", None)
    assert ctx.answer_resource_url is None
    assert PageBase.render_answer_resource(Mock(), ctx, {}, {}, "original") is None


def test_original_authorized_bytes_and_download(environment: SimpleNamespace) -> None:
    response = environment.get()
    assert response.status_code == 200
    assert response.content == b"original bytes"
    assert response["Content-Type"] == "application/x-ipynb+json"
    assert response["Content-Disposition"] == 'attachment; filename="answer.ipynb"'
    assert_hardened(response)
    ctx, participation = environment.contexts[-1]
    assert participation == environment.pctx.participation
    assert ctx.page_context.commit_sha == b"revision"
    assert environment.page.render_answer_resource.call_args.args[2] == (
            environment.visit.answer)


def test_preview_trusted_nonces_and_resize_channel(
        environment: SimpleNamespace, settings: Any) -> None:
    settings.RELATE_BASE_URL = "https://lms.example/course-prefix/"
    response = environment.get(name="notebook-preview")
    body = response.content.decode()
    assert response.status_code == 200
    assert response["Content-Type"] == "text/html; charset=utf-8"
    assert "Sanitized notebook" in body
    assert "original bytes" not in body
    assert "Number.isFinite" in body
    assert "Math.min(20000" in body
    assert 'type: "relate-notebook-resize"' in body
    assert f'const channel = "{CHANNEL}"' in body
    assert 'const targetOrigin = "https://lms.example"' in body
    assert body.count("nonce=") == 2
    for tag, directive in [("script", "script-src"), ("style", "style-src")]:
        nonce = body.split(f'<{tag} nonce="')[1].split('"')[0]
        assert f"{directive} 'nonce-{nonce}'" in response["Content-Security-Policy"]
    assert '<p id="cell" nonce=' not in body
    assert_hardened(response)
    environment.renderer.assert_called_once_with(b"original bytes")


def test_preview_without_channel_has_no_script(environment: SimpleNamespace) -> None:
    response = environment.get(name="notebook-preview", query={})
    assert response.status_code == 200
    assert b"<script" not in response.content
    assert_hardened(response)


def test_request_origin_fallback(environment: SimpleNamespace, settings: Any) -> None:
    settings.RELATE_BASE_URL = None
    assert resources._lms_origin(environment.pctx.request) == "http://testserver"


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "OPTIONS"])
def test_read_only(environment: SimpleNamespace, method: str) -> None:
    response = environment.get(method=method)
    assert response.status_code == 405
    assert response["Allow"] == "GET, HEAD"
    assert_hardened(response)
    environment.page.render_answer_resource.assert_not_called()


@pytest.mark.parametrize("name", ["original", "notebook-preview"])
def test_head_has_get_headers_without_body(
        environment: SimpleNamespace, name: str) -> None:
    response = environment.get(name=name, method="HEAD")
    assert response.status_code == 200
    assert response.content == b""
    assert int(response["Content-Length"]) > 0
    assert_hardened(response)


@pytest.mark.parametrize("mode,name", [
    ("review", "unknown"), ("staff", "original"), ("grading", "stylesheet"),
])
def test_resource_allowlist(environment: SimpleNamespace, mode: str, name: str) -> None:
    response = environment.get(mode=mode, name=name)
    assert response.status_code == 404
    assert_hardened(response)
    environment.page.render_answer_resource.assert_not_called()


@pytest.mark.parametrize("channel", [
    "", "short", "a" * 129, "<script>alert(1)</script>",
])
def test_invalid_channel_is_not_reflected(
        environment: SimpleNamespace, channel: str) -> None:
    response = environment.get(query={"channel": channel})
    assert response.status_code == 400
    assert b"<script>" not in response.content
    assert_hardened(response)
    environment.page.render_answer_resource.assert_not_called()


def test_channel_is_not_access_capability(environment: SimpleNamespace) -> None:
    environment.pctx.has_permission.return_value = False
    environment.pctx.request.user.is_staff = True
    response = environment.get(mode="grading")
    assert response.status_code == 403
    environment.pctx.has_permission.assert_called_once_with(PPerm.view_gradebook)
    assert_hardened(response)
    environment.page.render_answer_resource.assert_not_called()


def test_review_current_view_permission(environment: SimpleNamespace) -> None:
    environment.rule.permissions = set()
    response = environment.get()
    assert response.status_code == 403
    assert_hardened(response)
    environment.page.render_answer_resource.assert_not_called()


def test_review_page_modified_permissions(environment: SimpleNamespace) -> None:
    def no_permissions(_perms: AbstractSet[FlowPermission]) -> set[FlowPermission]:
        return set()

    environment.page.get_modified_permissions_for_page.side_effect = no_permissions
    assert environment.get().status_code == 403
    environment.page.render_answer_resource.assert_not_called()


def test_review_other_users_session(environment: SimpleNamespace) -> None:
    environment.pctx.participation = factories.ParticipationFactory(
            course=environment.session.course)
    response = environment.get()
    assert response.status_code == 403
    assert_hardened(response)
    environment.page.render_answer_resource.assert_not_called()


def test_review_delegated_session(environment: SimpleNamespace) -> None:
    environment.pctx.participation = factories.ParticipationFactory(
            course=environment.session.course)
    environment.pctx.permissions.return_value = [
        (PPerm.view_flow_sessions_from_role, "student")]
    assert environment.get().status_code == 200


@pytest.mark.parametrize("mode", ["review", "grading"])
def test_wrong_session_or_page_visit(environment: SimpleNamespace, mode: str) -> None:
    other = factories.FlowPageVisitFactory(answer={"content": "not yours"})
    response = environment.get(mode=mode, requested_visit=other.pk)
    assert response.status_code == 404
    other_data = factories.FlowPageDataFactory(
            flow_session=environment.session, page_ordinal=1)
    other = factories.FlowPageVisitFactory(
            page_data=other_data, answer={"content": "other page"})
    assert environment.get(mode=mode, requested_visit=other.pk).status_code == 404
    assert_hardened(response)
    environment.page.render_answer_resource.assert_not_called()


def test_wrong_course_is_hardened(environment: SimpleNamespace) -> None:
    environment.pctx.course = factories.CourseFactory(identifier="other")
    for mode in ["grading", "review"]:
        response = environment.get(mode=mode)
        assert response.status_code == 404
        assert_hardened(response)
    environment.page.render_answer_resource.assert_not_called()


def test_review_history_and_completed_session_drafts(
        environment: SimpleNamespace) -> None:
    old = factories.FlowPageVisitFactory(
            page_data=environment.data, answer={"content": "historical"},
            is_submitted_answer=True)
    draft = factories.FlowPageVisitFactory(
            page_data=environment.data, answer={"content": "draft"},
            is_submitted_answer=False)
    assert environment.get(requested_visit=old.pk).content == b"historical"
    assert environment.get(requested_visit=draft.pk).content == b"draft"
    environment.session.in_progress = False
    environment.session.save()
    assert environment.get(requested_visit=old.pk).content == b"historical"
    response = environment.get(requested_visit=draft.pk)
    assert response.status_code == 404
    assert_hardened(response)


def test_selection_keeps_ui_fallback_but_resource_fails_closed(
        environment: SimpleNamespace) -> None:
    visits, selected, historical = flow.select_flow_page_answer_visit(
            environment.data, 999999)
    assert selected.pk == environment.visit.pk
    assert not historical
    assert visits == [selected]
    with pytest.raises(http.Http404):
        flow.select_flow_page_answer_visit(environment.data, 999999, strict=True)


@pytest.mark.parametrize("mode", ["review", "grading"])
def test_no_answer_or_missing_page(environment: SimpleNamespace, mode: str) -> None:
    environment.visit.answer = None
    environment.visit.save()
    response = environment.get(mode=mode)
    assert response.status_code == 404
    assert_hardened(response)
    environment.page.render_answer_resource.assert_not_called()
    assert environment.get(mode=mode, ordinal=10).status_code == 404


def test_declined_or_mismatched_hook(environment: SimpleNamespace) -> None:
    environment.page.render_answer_resource.side_effect = None
    for result in [None, AnswerResource("notebook-preview", b"notebook")]:
        environment.page.render_answer_resource.return_value = result
        response = environment.get()
        assert response.status_code == 404
        assert_hardened(response)


def test_preview_failure_does_not_leak_content(
        environment: SimpleNamespace, caplog: pytest.LogCaptureFixture) -> None:
    environment.renderer.side_effect = ValueError(
            "SECRET <script>notebook contents</script>")
    response = environment.get(name="notebook-preview")
    assert response.status_code == 422
    assert b"SECRET" not in response.content
    assert b"<script" not in response.content
    assert "SECRET" not in caplog.text
    assert "error ID" in caplog.text
    assert_hardened(response)
    assert environment.get().content == b"original bytes"


def test_unexpected_failure_is_inert(
        environment: SimpleNamespace, caplog: pytest.LogCaptureFixture) -> None:
    environment.page.render_answer_resource.side_effect = RuntimeError("SECRET")
    response = environment.get()
    assert response.status_code == 500
    assert "SECRET" not in caplog.text
    assert b"SECRET" not in response.content
    assert_hardened(response)


def test_outer_course_context_errors_are_hardened(
        environment: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
            "course.utils.CoursePageContext", Mock(side_effect=PermissionDenied))
    response = environment.get()
    assert response.status_code == 403
    assert_hardened(response)
    monkeypatch.setattr(
            "course.utils.CoursePageContext", Mock(side_effect=http.Http404))
    response = environment.get(method="HEAD")
    assert response.status_code == 404
    assert response.content == b""
    assert_hardened(response)


def test_error_text_is_escaped() -> None:
    response = resources._error_response('<script>"hostile"</script>', 422)
    assert b"<script>" not in response.content
    assert b"&lt;script&gt;" in response.content


def test_download_name_and_mime_are_header_safe(environment: SimpleNamespace) -> None:
    environment.page.render_answer_resource.side_effect = None
    environment.page.render_answer_resource.return_value = AnswerResource(
            "original", b"bytes", "../../\\bad\r\nname.ipynb",
            "text/html\r\nX-Evil: injected")
    response = environment.get()
    assert response.status_code == 200
    assert response["Content-Type"] == "application/octet-stream"
    assert response["Content-Disposition"] == 'attachment; filename="bad__name.ipynb"'
    assert "X-Evil" not in response
    assert_hardened(response)


def test_url_builder_exact_visit_channel_and_default_absence(
        environment: SimpleNamespace) -> None:
    ctx = PageContext(
            environment.session.course, Mock(), b"revision", environment.session)
    resources.bind_answer_resource_url(ctx, environment.visit, "grading")
    builder = ctx.answer_resource_url
    assert builder is not None
    preview = builder("notebook-preview")
    original = builder("original")
    match = resolve(urlsplit(preview).path)
    assert match.func == resources.answer_resource
    assert int(match.kwargs["visit_id"]) == environment.visit.pk
    assert match.kwargs["access_mode"] == "grading"
    assert parse_qs(urlsplit(preview).query) == parse_qs(urlsplit(original).query)
    assert resources._CHANNEL.fullmatch(parse_qs(urlsplit(preview).query)["channel"][0])
    with pytest.raises(ValueError):
        builder("anything")
    resources.bind_answer_resource_url(ctx, None, "grading")
    assert ctx.answer_resource_url is None
    ctx.in_sandbox = True
    resources.bind_answer_resource_url(ctx, environment.visit, "grading")
    assert ctx.answer_resource_url is None


def test_grading_driver_binds_historical_grade_visit(
        environment: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    old_visit = factories.FlowPageVisitFactory(
            page_data=environment.data, answer={"content": "historical"},
            is_submitted_answer=True)
    old_grade = factories.FlowPageVisitGradeFactory(visit=old_visit)
    environment.pctx.request.GET = {"grade_id": str(old_grade.pk)}
    monkeypatch.setattr(grading, "get_feedback_for_grade", Mock(return_value=None))
    monkeypatch.setattr(grading, "get_session_grading_mode", Mock(
            return_value=SimpleNamespace(grade_identifier=None)))
    monkeypatch.setattr(
            grading, "render_course_page", Mock(return_value=http.HttpResponse()))
    captured: list[tuple[str, AnswerData]] = []

    def capture_form(
            _req: http.HttpRequest, ctx: PageContext, _form: Any,
            answer: AnswerData) -> str:
        builder = ctx.answer_resource_url
        assert builder is not None
        captured.append((builder("original"), answer))
        return "form"

    environment.page.form_to_html.side_effect = capture_form
    grading.grade_flow_page(
            environment.pctx.request, environment.session.course.identifier,
            environment.session.pk, 0)
    url, answer = captured[0]
    assert int(resolve(urlsplit(url).path).kwargs["visit_id"]) == old_visit.pk
    assert answer == old_visit.answer
    assert environment.contexts[-1][1] == environment.session.participation


@pytest.mark.parametrize("historical", [False, True])
def test_review_driver_binds_displayed_answer(
        environment: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
        historical: bool) -> None:
    old_visit = factories.FlowPageVisitFactory(
            page_data=environment.data, answer={"content": "historical"},
            is_submitted_answer=True)
    selected = old_visit if historical else environment.visit
    # Ensure the UI's default still selects the latest original visit.
    from datetime import timedelta
    old_visit.visit_time = environment.visit.visit_time - timedelta(minutes=1)
    old_visit.save()
    environment.pctx.request.GET = {"visit_id": str(selected.pk)} if historical else {}
    environment.page.is_optional_page = False
    monkeypatch.setattr("course.utils.FlowPageContext", environment.make_fpctx)
    monkeypatch.setattr("course.utils.get_session_grading_mode", Mock(
            return_value=SimpleNamespace(grade_identifier=None, generates_grade=False)))
    monkeypatch.setattr("course.utils.render_course_page", Mock(
            return_value=http.HttpResponse()))
    monkeypatch.setattr(flow, "get_interaction_kind", Mock(return_value=None))
    captured: list[tuple[str, AnswerData]] = []

    def capture_form(
            _req: http.HttpRequest, ctx: PageContext, _form: Any,
            answer: AnswerData) -> str:
        builder = ctx.answer_resource_url
        assert builder is not None
        captured.append((builder("original"), answer))
        return "form"

    environment.page.form_to_html.side_effect = capture_form
    flow.view_flow_page(
            environment.pctx.request, environment.session.course.identifier,
            environment.session.pk, 0)
    url, answer = captured[0]
    assert int(resolve(urlsplit(url).path).kwargs["visit_id"]) == selected.pk
    assert answer == selected.answer


def test_post_driver_binds_newly_persisted_answer(
        environment: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    fpctx = environment.make_fpctx(
            environment.pctx.repo, environment.session.course,
            environment.session.flow_id, 0, environment.session.participation,
            environment.session, environment.pctx.request)
    form = Mock()
    form.is_valid.return_value = True
    environment.page.process_form_post.return_value = form
    environment.page.answer_data.return_value = {"content": "newly saved"}
    monkeypatch.setattr(flow, "get_pressed_button", Mock(return_value="save"))
    result = flow.post_flow_page(
            environment.session, fpctx, environment.pctx.request,
            {FlowPermission.submit_answer, FlowPermission.change_answer}, False)
    visits = result[1]
    assert visits[0].pk != environment.visit.pk
    assert visits[0].answer == {"content": "newly saved"}
    url = fpctx.page_context.answer_resource_url("original")
    assert int(resolve(urlsplit(url).path).kwargs["visit_id"]) == visits[0].pk
