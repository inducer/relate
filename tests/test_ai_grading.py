from __future__ import annotations


__copyright__ = "Copyright (C) 2026 Andreas Kloeckner"

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

import importlib
import json
from contextlib import ExitStack
from dataclasses import replace
from inspect import unwrap
from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps
from django.core import mail, signing
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils.timezone import now

from course import models
from course.ai_grading import (
    MAX_EVIDENCE_CHARACTERS,
    MAX_SECTION_CHARACTERS,
    MAX_SECTIONS,
    AIGradeResult,
    AIGradingError,
    build_messages,
    request_ai_grade,
)
from course.constants import ParticipationPermission as PPerm
from course.grade_storage import persist_grade
from course.grades import AIGradeFlowPageForm, ai_grade_by_opportunity
from course.grading import AI_DRAFT_MAX_AGE, AI_DRAFT_TICKET_SALT
from course.page import PageContext
from course.page.base import AIGradingInput, AIGradingSection, AnswerFeedback
from course.page.code import PythonCodeQuestionWithHumanTextFeedback
from course.page.text import HumanGradedRichTextQuestion, HumanGradedTextQuestion
from course.page.upload import FileUploadQuestion
from course.repo import deserialize_revision, serialize_revision
from course.tasks import batch_ai_grade_flow_page, draft_ai_grade
from tests import factories
from tests.test_grading import SingleCourseQuizPageGradeInterfaceTestMixin
from tests.utils import mock


FLOW_ID = "some-flow"
GROUP_ID = "some-group"
PAGE_ID = "some-page"


def make_page(grading_prompt: str | None = None) -> HumanGradedTextQuestion:
    # Bypass pydantic validation (which requires a full ValidationContext
    # with repo access) -- we just need a page object with known attribute
    # values to exercise course.ai_grading's logic.
    return HumanGradedTextQuestion.model_construct(
            id="qid",
            title="Question",
            type="HumanGradedTextQuestion",
            prompt="What is 2+2?",
            value=5,
            rubric="Full credit for the number 4, with reasoning.",
            grading_prompt=grading_prompt)


def make_page_context(course: models.Course) -> PageContext:
    return PageContext(
            course=course, repo=None, commit_sha=None, flow_session=None)


def make_matching_visit(
        course: models.Course, *, answer_text: str = "my answer",
        ) -> models.FlowPageVisit:
    participation = factories.ParticipationFactory(course=course)
    flow_session = factories.FlowSessionFactory(
            participation=participation, flow_id=FLOW_ID, in_progress=False)
    page_data = factories.FlowPageDataFactory(
            flow_session=flow_session, group_id=GROUP_ID, page_id=PAGE_ID)
    return factories.FlowPageVisitFactory(
            page_data=page_data, is_submitted_answer=True,
            answer={"answer": answer_text})


def make_input(*, rubric: str = "Full credit for 4.",
               instructions: str = "") -> AIGradingInput:
    return AIGradingInput(
            rubric=rubric, human_point_value=5, instructions=instructions,
            sections=(AIGradingSection("Submitted answer", "the answer", "text"),))


class BuildMessagesTest(TestCase):
    def setUp(self):
        super().setUp()
        self.course = factories.CourseFactory()
        self.page_context = make_page_context(self.course)

    def test_default_prompt_used_when_not_specified(self):
        messages = build_messages(make_input())

        system_message = messages[0]["content"]  # pyright: ignore[reportTypedDictNotRequiredAccess]
        self.assertIn("experienced", system_message)
        self.assertIn("grade_percent", system_message)

    def test_custom_grading_prompt_used_when_specified(self):
        messages = build_messages(make_input(
                instructions="Only grade based on correctness."))

        system_message = messages[0]["content"]  # pyright: ignore[reportTypedDictNotRequiredAccess]
        self.assertIn("Only grade based on correctness.", system_message)

    def test_rubric_and_answer_included(self):
        grading_input = make_input()
        messages = build_messages(grading_input)

        user_message = messages[1]["content"]  # pyright: ignore[reportTypedDictNotRequiredAccess]
        self.assertIn(grading_input.rubric, user_message)
        self.assertIn("the answer", user_message)


@pytest.mark.parametrize("grading_prompt", [None, "Grade correctness only."])
def test_point_marker_instructions(grading_prompt: str | None):
    messages = build_messages(make_input(
            rubric="- Reasoning [pts:/2 #reasoning]",
            instructions=grading_prompt or ""))

    system_message = messages[0]["content"]  # pyright: ignore[reportTypedDictNotRequiredAccess]
    assert isinstance(system_message, str)
    assert "updated version of the rubric" in system_message
    assert 'grade_percent: "COMPUTED"' in system_message
    assert "full points suffices as feedback" in system_message
    assert "do not add laudatory verbiage" in system_message


@pytest.mark.parametrize(("rubric", "grade_percent", "feedback", "expected_percent"), [
    ("[pts:/2 #answer] [pts:/2 #reasoning]", "COMPUTED",
     "- Answer [pts:2/2 #answer]\n- Reasoning [pts:1/2 #reasoning]", 75),
    ("[pts:/2] [pts:-0.5]", "COMPUTED",
     "- Answer [pts:2/2]\n- Penalty [pts:-0.5]", 75),
    ("[pts:/2]", "COMPUTED", "- Answer [pts:2.5/2]", 125),
    ("[pts:/2]", 75, "- Answer [pts:1.5/2]", 75),
    ("[pts:/3]", 100/3, "- Answer [pts:1/3]", 100/3),
    ("[pts: /3]", "COMPUTED", "- Answer [pts:1/3]", 100/3),
    ("[pts:/2]", 125, "- Answer [pts:2.5/2]", 125),
    ("[pts:/2]", 0, "- Answer [pts:0/2]", 0),
    ("Explain deductions.", 75, "Some reasoning missing.", 75),
    ("Penalty [pts:-1]", 75, "- Penalty [pts:-1]", 75),
])
def test_request_ai_grade_computes_percentage(
        rubric: str, grade_percent: str | float, feedback: str,
        expected_percent: float):
    course = models.Course(ai_grading_model="test-model")
    with mock.patch("course.ai_grading.get_openai_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value.choices[
                0].message.content = json.dumps({
                    "grade_percent": grade_percent, "feedback_text": feedback})
        result = request_ai_grade(course, make_input(rubric=rubric))

    assert result.grade_percent == pytest.approx(expected_percent)
    assert result.feedback_text == feedback


@pytest.mark.parametrize("parameters", [
    {},
    {"reasoning_effort": "high", "temperature": 0.5},
    {"thinking": {"type": "enabled", "budget_tokens": 1024}},
])
def test_request_ai_grade_passes_model_parameters(parameters: dict):
    course = models.Course(ai_grading_model="test-model",
            ai_grading_model_parameters=parameters)
    with mock.patch("course.ai_grading.get_openai_client") as client:
        create = client.return_value.chat.completions.create
        create.return_value.choices[0].message.content = json.dumps({
            "grade_percent": 75, "feedback_text": "Some reasoning missing."})
        request_ai_grade(course, make_input(rubric="Explain deductions."))

    assert create.call_args.kwargs["extra_body"] == parameters
    assert create.call_args.kwargs["model"] == "test-model"
    assert create.call_args.kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("parameters", [
    [], "high", None, 1,
    {"model": "other"}, {"messages": []},
    {"response_format": None}, {"stream": True},
])
def test_request_ai_grade_rejects_invalid_model_parameters(parameters: object):
    course = models.Course(ai_grading_model="test-model",
            ai_grading_model_parameters=parameters)
    with mock.patch("course.ai_grading.get_openai_client") as client:
        with pytest.raises(AIGradingError, match="model parameters"):
            request_ai_grade(course, make_input())
    client.return_value.chat.completions.create.assert_not_called()


@pytest.mark.parametrize(("grade_percent", "feedback"), [
    (80, "- Answer [pts:1.5/2]"),
    (0, "- Answer [pts:0.1/2]"),
    ("COMPUTED", "No markers."),
    ("COMPUTED", "- Answer [pts:2]"),
    ("COMPUTED", "- Answer [pts:/2]"),
    ("COMPUTED", "- Answer [pts:1/0]"),
    ("COMPUTED", "- Answer [pts:invalid]"),
    ("COMPUTED", "- Answer [pts:-1/2]"),
    ("COMPUTED", "- Answer [pts:1000/2]"),
])
def test_request_ai_grade_rejects_invalid_computed_grade(
        grade_percent: str | float, feedback: str):
    course = models.Course(ai_grading_model="test-model")
    with mock.patch("course.ai_grading.get_openai_client") as mock_client:
        mock_client.return_value.chat.completions.create.return_value.choices[
                0].message.content = json.dumps({
                    "grade_percent": grade_percent, "feedback_text": feedback})
        with pytest.raises(AIGradingError, match="malformed response"):
            request_ai_grade(course, make_input(rubric="- Answer [pts:/2]"))


@pytest.mark.parametrize("feedback", [
    "[pts:1/2 #answer]",  # missing marker
    "[pts:1/2 #answer] [pts:1/3 #reasoning] [pts:0]",  # extra marker
    "[pts:1/3 #reasoning] [pts:1/2 #answer]",  # reordered
    "[pts:1/3 #answer] [pts:1/3 #reasoning]",  # changed denominator
    "[pts:1 #answer] [pts:1/3 #reasoning]",  # removed denominator
    "[pts:1/3 #answer] [pts:1/2 #reasoning]",  # swapped denominators
    "[pts:1/2 #other] [pts:1/3 #reasoning]",  # changed identifier
])
def test_request_ai_grade_preserves_rubric_markers(feedback: str):
    with mock.patch("course.ai_grading.get_openai_client") as client:
        client.return_value.chat.completions.create.return_value.choices[
                0].message.content = json.dumps({
                    "grade_percent": "COMPUTED", "feedback_text": feedback})
        with pytest.raises(AIGradingError, match="marker count, order"):
            request_ai_grade(models.Course(ai_grading_model="test-model"),
                    make_input(rubric="[pts:/2 #answer] [pts:/3 #reasoning]"))


@pytest.mark.parametrize("weight", [0, 25, 100])
def test_code_page_ai_input(weight: float):
    page = PythonCodeQuestionWithHumanTextFeedback.model_construct(
            id="code", prompt="Implement <f>.", value=20,
            rubric="Readability [pts:/5]", human_feedback_percentage=weight,
            correct_code="def f():\n    return 4 < 5\n",
            correct_code_explanation="Use a comparison.",
            grading_prompt="Check style.")
    context = make_page_context(models.Course())
    code = "def f():\n    return '<raw>&code'\n"
    previous_feedback = AnswerFeedback(0.5,
            feedback='<p>Stored combined feedback</p><img src="https://invalid/">',
            bulk_feedback="<pre>Stored output &amp; details</pre>")
    with mock.patch.object(PythonCodeQuestionWithHumanTextFeedback,
                           "grade") as grade, \
            mock.patch("course.page.code.CodeQuestion.grade") as runner:
        grading_input = page.make_ai_grading_input(
                context, {}, {"answer": code}, None,
                previous_feedback=previous_feedback)
        assert page.supports_ai_grading() == (weight > 0)
        if weight == 0:
            assert grading_input is None
        else:
            assert grading_input is not None
            assert grading_input.human_point_value == 20 * weight / 100
            sections = {section.title: section for section in grading_input.sections}
            assert sections["Submitted code"].content == code
            assert sections["Submitted code"].format == "python"
            assert sections["Reference code"].content == page.correct_code
            assert sections["Reference explanation"].content == "Use a comparison."
            assert sections["Previous combined feedback (may contain human feedback)"
                    ].content == previous_feedback.feedback
            assert sections["Previous bulk output"].content == (
                    previous_feedback.bulk_feedback)
            messages = build_messages(grading_input)
            assert "not a combined page" in grading_input.instructions
            system_content = messages[0].get("content")
            user_content = messages[1].get("content")
            assert isinstance(system_content, str)
            assert isinstance(user_content, str)
            assert "Grade ONLY the human component" in system_content
            assert code in user_content
        grade.assert_not_called()
        runner.assert_not_called()


def test_code_page_missing_evidence_is_explicit():
    page = PythonCodeQuestionWithHumanTextFeedback.model_construct(
            id="code", prompt="Implement f.", value=20, rubric="Style",
            human_feedback_percentage=25)
    grading_input = page.make_ai_grading_input(
            make_page_context(models.Course()), {}, None, None,
            previous_feedback=None)
    assert grading_input is not None
    sections = {section.title: section.content for section in grading_input.sections}
    assert "Submitted code (missing)" in sections
    assert "Reference code (missing)" in sections
    assert "code was not executed" in sections["Previous bulk output (missing)"]


def test_text_page_preserves_raw_answer_and_reference():
    page = make_page().model_copy(update={"correct_answer": "<reference>&"})
    assert page.supports_ai_grading()
    grading_input = page.make_ai_grading_input(
            make_page_context(models.Course()), {}, {"answer": "  <raw>&\n  "},
            None, previous_feedback=None)
    assert grading_input is not None
    assert grading_input.human_point_value == 5
    sections = {section.title: section.content for section in grading_input.sections}
    assert sections["Submitted answer"] == "  <raw>&\n  "
    assert sections["Reference answer"] == "<reference>&"


def test_rich_text_page_preserves_structured_document():
    page = HumanGradedRichTextQuestion.model_construct(
            id="rich", title="Rich text", prompt="Explain.", value=5,
            rubric="Accuracy", correct_answer="Reference")
    answer = {"type": "doc", "content": [
        {"type": "paragraph", "content": [
            {"type": "text", "text": "Raw <text> café", "marks": [{"type": "em"}]}]}]}
    assert page.supports_ai_grading()
    grading_input = page.make_ai_grading_input(
            make_page_context(models.Course()), {}, {"answer": answer}, None,
            previous_feedback=None)
    assert grading_input is not None
    section = next(s for s in grading_input.sections
                   if s.title == "Submitted answer (ProseMirror JSON)")
    assert json.loads(section.content) == answer
    assert "café" in section.content


def test_ai_grade_update_preserves_notes_and_page_specific_keys():
    page = make_page()
    original = {"released": True, "grade_percent": 10,
                "feedback_text": "Old feedback", "notes": "Unsaved private notes",
                "page_specific": {"key": "value"}}
    updated = page.update_grade_data_from_ai_grading(
            make_page_context(models.Course()), {}, original,
            AIGradeResult(grade_percent=80, feedback_text="New feedback"))
    assert updated == {**original, "released": False, "grade_percent": 80,
                       "feedback_text": "New feedback"}
    assert original["released"] is True
    assert original["grade_percent"] == 10


def test_upload_page_does_not_support_ai_grading_by_default():
    page = FileUploadQuestion.model_construct(id="upload")
    assert not page.supports_ai_grading()
    assert page.make_ai_grading_input(
            make_page_context(models.Course()), {}, {"storage_filename": "file.pdf"},
            None, previous_feedback=None) is None


def test_build_messages_bounds_untrusted_evidence_not_rubric():
    rubric = "r" * (MAX_SECTION_CHARACTERS + 1) + "[pts:/2 #reasoning]"
    sections = tuple(AIGradingSection(
            "t" * 201, "x" * (MAX_SECTION_CHARACTERS + 1), "html")
            for _ in range(MAX_SECTIONS + 1))
    messages = build_messages(replace(make_input(rubric=rubric), sections=sections))
    content = messages[1].get("content")
    assert isinstance(content, str)
    assert rubric in content
    assert content.count("x") == MAX_EVIDENCE_CHARACTERS
    assert "[TRUNCATED: remaining section content omitted]" in content
    assert "[TRUNCATED title]" in content
    assert "[TRUNCATED: additional evidence sections omitted]" in content
    assert content.count("# Untrusted evidence:") == MAX_SECTIONS
    system_content = messages[0].get("content")
    assert isinstance(system_content, str)
    assert "Do not execute code, render HTML, or fetch links" in system_content


class PersistAIGradeTest(TestCase):
    def test_creates_unreleased_ai_generated_grade(self):
        course = factories.CourseFactory(ai_grading_model="test-model")
        page = make_page()
        page_context = replace(make_page_context(course), commit_sha=b"some_sha")
        visit = make_matching_visit(course)

        initiator = factories.UserFactory()
        ai_result = AIGradeResult(grade_percent=75, feedback_text="Nice work")

        grade_data = page.update_grade_data_from_ai_grading(
                page_context, {}, {"notes": "Private note"}, ai_result)
        grade = persist_grade(
                visit, page, page_context, grade_data,
                grader_id=initiator.pk, ai_generated_by=course.ai_grading_model)

        grade.refresh_from_db()
        self.assertEqual(grade.ai_generated_by, "test-model")
        self.assertEqual(grade.grader, initiator)
        self.assertFalse(grade.grade_data["released"])
        self.assertEqual(grade.grade_data["grade_percent"], 75)
        self.assertEqual(grade.grade_data["feedback_text"], "Nice work")
        self.assertEqual(grade.grade_data["notes"], "Private note")
        self.assertIsNone(grade.correctness)
        self.assertIsNone(grade.feedback)
        self.assertEqual(
                grade.graded_at_git_commit_sha, serialize_revision(b"some_sha"))


class AddUseAIDraftingPermissionMigrationTest(TestCase):
    def test_roles_with_assign_grade_get_new_permission(self):
        migration_module = importlib.import_module(
                "course.migrations.0124_ai_grading")

        course = factories.CourseFactory()
        role = factories.ParticipationRoleFactory(
                course=course, identifier="custom-grader")
        models.ParticipationRolePermission.objects.create(
                role=role, permission=PPerm.assign_grade)

        other_role = factories.ParticipationRoleFactory(
                course=course, identifier="custom-observer")
        models.ParticipationRolePermission.objects.create(
                role=other_role, permission=PPerm.view_calendar)

        migration_module.add_use_ai_drafting_permission(
                django_apps, None)

        migration_module.add_use_ai_drafting_permission(
                django_apps, None)

        self.assertEqual(
                models.ParticipationRolePermission.objects.filter(
                    role=role,
                    permission=PPerm.use_ai_drafting).count(), 1)
        self.assertFalse(
                models.ParticipationRolePermission.objects.filter(
                    role=other_role,
                    permission=PPerm.use_ai_drafting).exists())


class DraftAIGradeTaskTest(TestCase):
    def setUp(self):
        self.course = factories.CourseFactory(ai_grading_model="test-model")
        self.visit = make_matching_visit(self.course)
        self.page = make_page()
        self.revision = "pinned-draft-revision"
        self.initiator = factories.UserFactory()

    def check_worker(
            self, source_grade: models.FlowPageVisitGrade | None,
            *, failure: bool = False, change: str | None = None):
        before_grades = list(models.FlowPageVisitGrade.objects.values())
        before_sessions = list(models.FlowSession.objects.values())
        suggestion = AIGradeResult(grade_percent=85, feedback_text="AI feedback")

        def provider(*_args: object) -> AIGradeResult:
            if failure:
                raise AIGradingError("secret provider details")
            if change == "grade":
                factories.FlowPageVisitGradeFactory(
                        visit=self.visit, grade_time=now(),
                        grade_data={"notes": "Concurrent human edit"})
            elif change == "reopened":
                models.FlowSession.objects.filter(
                        pk=self.visit.flow_session_id).update(in_progress=True)
            elif change == "submission":
                factories.FlowPageVisitFactory(
                        page_data=self.visit.page_data, is_submitted_answer=True,
                        answer={"answer": "New answer"})
            return suggestion

        with mock.patch("course.tasks.get_course_repo") as get_repo, \
                mock.patch("course.content.get_flow_desc") as get_desc, \
                mock.patch("course.content.get_flow_page", return_value=self.page
                           ) as get_page, \
                mock.patch.object(HumanGradedTextQuestion, "make_ai_grading_input",
                                  autospec=True,
                                  side_effect=HumanGradedTextQuestion.make_ai_grading_input
                                  ) as make_input, \
                mock.patch("course.ai_grading.request_ai_grade",
                           side_effect=provider) as request, \
                mock.patch("course.utils.FlowContext") as flow_context, \
                mock.patch("course.utils.get_session_grading_mode") as grading_mode, \
                mock.patch("course.flow.grade_flow_session") as recalculate:
            result = draft_ai_grade(
                    self.course.pk, self.visit.pk, self.revision,
                    source_grade.pk if source_grade else None,
                    initiated_by_id=self.initiator.pk)
        repo = get_repo.return_value.__enter__.return_value
        get_repo.assert_called_once_with(self.course)
        get_desc.assert_called_once_with(
                repo, self.course, self.visit.flow_session.flow_id,
                deserialize_revision(self.revision))
        get_page.assert_called_once_with(
                self.visit.flow_session.flow_id, get_desc.return_value,
                self.visit.page_data.group_id, self.visit.page_data.page_id)
        make_input.assert_called_once()
        _, context, page_data, answer, grade_data = make_input.call_args.args
        self.assertEqual(context.course, self.course)
        self.assertIs(context.repo, repo)
        self.assertEqual(context.commit_sha, deserialize_revision(self.revision))
        self.assertEqual(context.flow_session, self.visit.flow_session)
        self.assertEqual(page_data, self.visit.page_data.data)
        self.assertEqual(answer, self.visit.answer)
        self.assertEqual(grade_data, source_grade.grade_data if source_grade else None)
        request.assert_called_once()
        requested_course, grading_input = request.call_args.args
        self.assertEqual(requested_course, self.course)
        self.assertIsInstance(grading_input, AIGradingInput)
        self.assertIn("my answer", [s.content for s in grading_input.sections])
        self.assertEqual(len(mail.outbox), 0)
        if failure or change:
            recalculate.assert_not_called()
            flow_context.assert_not_called()
            self.assertEqual(models.FlowPageVisitGrade.objects.filter(
                    ai_generated_by__isnull=False).count(),
                    sum(g["ai_generated_by"] is not None for g in before_grades))
            if change != "grade":
                self.assertEqual(
                        list(models.FlowPageVisitGrade.objects.values()), before_grades)
            if change != "reopened":
                self.assertEqual(
                        list(models.FlowSession.objects.values()), before_sessions)
        if failure:
            assert "message" in result
            self.assertEqual(result["state"], "failed")
            self.assertIn("Please try again", str(result["message"]))
            self.assertIn("AIGradingError: secret provider details",
                          str(result["message"]))
        elif change:
            assert "message" in result
            self.assertEqual(result["state"], "unavailable")
            self.assertIn("submission or grade changed", str(result["message"]))
            if change == "grade":
                self.assertEqual(self.visit.get_most_recent_grade().grade_data,
                                 {"notes": "Concurrent human edit"})
        else:
            grade = self.visit.get_most_recent_grade()
            self.assertEqual(result, {"state": "ready", "grade_id": grade.pk})
            self.assertEqual(models.FlowPageVisitGrade.objects.count(),
                             len(before_grades) + 1)
            self.assertEqual(grade.ai_generated_by, "test-model")
            self.assertEqual(grade.grader, self.initiator)
            self.assertEqual(grade.graded_at_git_commit_sha, self.revision)
            self.assertFalse(grade.grade_data["released"])
            self.assertEqual(grade.grade_data["grade_percent"], 85)
            self.assertEqual(grade.grade_data["feedback_text"], "AI feedback")
            self.assertIsNone(grade.correctness)
            self.assertIsNone(grade.feedback)
            if source_grade:
                source_grade.refresh_from_db()
                self.assertEqual(grade.grade_data["notes"], "Private note")
                self.assertEqual(source_grade.grade_data["grade_percent"], 40)
                self.assertTrue(source_grade.grade_data["released"])
                self.assertNotEqual(grade.pk, source_grade.pk)
            recalculate.assert_called_once_with(
                    flow_context.return_value, self.visit.flow_session,
                    grading_mode.return_value)
            self.assertEqual(list(models.FlowSession.objects.values()), before_sessions)
        return result

    def test_saves_unreleased_draft_and_recalculates(self):
        for kind in ["ungraded", "human", "ai"]:
            with self.subTest(kind=kind):
                models.FlowPageVisitGrade.objects.filter(visit=self.visit).delete()
                grade = (factories.FlowPageVisitGradeFactory(
                    visit=self.visit,
                    ai_generated_by="old-model" if kind == "ai" else None,
                    grade_data={
                        "grade_percent": 40, "feedback_text": "Prior feedback",
                        "notes": "Private note", "released": True})
                    if kind != "ungraded" else None)
                self.check_worker(grade)

    def test_rejects_grade_changed_during_provider(self):
        for graded in [False, True]:
            with self.subTest(graded=graded):
                models.FlowPageVisitGrade.objects.filter(visit=self.visit).delete()
                grade = (factories.FlowPageVisitGradeFactory(visit=self.visit)
                         if graded else None)
                self.check_worker(grade, change="grade")

    def test_rejects_session_reopened_during_provider(self):
        self.check_worker(None, change="reopened")

    def test_rejects_submission_created_during_provider(self):
        self.check_worker(None, change="submission")

    def test_human_follow_up_preserves_ai_history(self):
        result = self.check_worker(None)
        assert "grade_id" in result
        ai_grade = models.FlowPageVisitGrade.objects.get(pk=result["grade_id"])
        human_grade = persist_grade(
                self.visit, self.page,
                replace(make_page_context(self.course),
                        commit_sha=deserialize_revision(self.revision)),
                {**ai_grade.grade_data, "grade_percent": 90, "released": True},
                grader_id=self.initiator.pk)
        self.assertNotEqual(human_grade.pk, ai_grade.pk)
        self.assertIsNone(human_grade.ai_generated_by)
        self.assertEqual(self.visit.get_most_recent_grade(), human_grade)
        ai_grade.refresh_from_db()
        self.assertEqual(ai_grade.ai_generated_by, "test-model")
        self.assertEqual(ai_grade.grade_data["grade_percent"], 85)
        self.assertFalse(ai_grade.grade_data["released"])

    def test_expected_ai_failure_includes_exception_details(self):
        self.check_worker(None, failure=True)


@pytest.mark.slow
class InteractiveAIGradeTest(SingleCourseQuizPageGradeInterfaceTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.course.ai_grading_model = "test-model"
        self.course.ai_grading_api_base_url = "https://example.invalid/v1"
        self.course.ai_grading_api_key = "test-key"
        self.course.save()
        session = models.FlowSession.objects.get(pk=self.this_flow_session_id)
        session.in_progress = False
        session.save()
        models.FlowPageVisit.objects.filter(
                flow_session=session, is_submitted_answer=True).update(
                    answer={"answer": "Student answer"})
        self.page_patch = mock.patch("course.content.get_flow_page",
                                     return_value=make_page())
        self.page_patch.start()
        self.addCleanup(self.page_patch.stop)
        self.url = self.get_page_view_url_by_page_id(
                "relate-grade_flow_page", self.page_id)
        self.posted = {
            "draft_ai_grade": "Draft with AI",
            "grade_percent": "not a valid percentage",
            "grade_points": "also invalid",
            "feedback_text": "Unsaved feedback",
            "notes": "Unsaved private notes",
            "released": "on", "notify": "on", "notify_instructor": "on",
            "may_reply": "on", "unrelated": "Preserve me",
        }

    def test_button_in_normal_form(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="draft_ai_grade"', response.context["grading_form_html"])

    def get_visit(self):
        return (models.FlowPageVisit.objects.filter(
                flow_session_id=self.this_flow_session_id,
                page_data__page_id=self.page_id, is_submitted_answer=True)
                .order_by("-visit_time", "-pk").first())

    def get_displayed_source(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        grade_id = response.context["ai_draft_grade_id"]
        return {
            "ai_draft_visit_id": str(response.context["ai_draft_visit_id"]),
            "ai_draft_grade_id": str(grade_id) if grade_id is not None else "",
        }

    def enqueue(self):
        posted = {**self.posted, **self.get_displayed_source()}
        with self.temporarily_switch_to_user(self.instructor_participation.user), \
                mock.patch("course.tasks.draft_ai_grade.delay",
                           return_value=SimpleNamespace(id="draft-task")) as delay:
            response = self.client.post(self.url, posted)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        return response.json()["ticket"], delay

    def poll(self, ticket: str):
        url = reverse("relate-ai_grade_draft_return", args=[self.course.identifier])
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            return self.client.get(url, {"ticket": ticket})

    def test_get_context_provides_displayed_source_ids(self):
        visit = self.get_visit()
        for graded in [False, True]:
            with self.subTest(graded=graded):
                models.FlowPageVisitGrade.objects.filter(visit=visit).delete()
                grade = (factories.FlowPageVisitGradeFactory(visit=visit)
                         if graded else None)
                with self.temporarily_switch_to_user(
                        self.instructor_participation.user):
                    response = self.client.get(self.url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["ai_draft_visit_id"], visit.pk)
                self.assertEqual(response.context["ai_draft_grade_id"],
                                 grade.pk if grade else None)

    def test_enqueue_rejects_stale_displayed_grade(self):
        visit = self.get_visit()
        for graded in [False, True]:
            with self.subTest(graded=graded):
                models.FlowPageVisitGrade.objects.filter(visit=visit).delete()
                if graded:
                    factories.FlowPageVisitGradeFactory(visit=visit)
                posted = {**self.posted, **self.get_displayed_source()}
                factories.FlowPageVisitGradeFactory(visit=visit, grade_time=now())
                self.check_enqueue_conflict(posted)

    def test_enqueue_rejects_stale_displayed_visit(self):
        visit = self.get_visit()
        models.FlowPageVisitGrade.objects.filter(visit=visit).delete()
        posted = {**self.posted, **self.get_displayed_source()}
        factories.FlowPageVisitFactory(
                page_data=visit.page_data, is_submitted_answer=True,
                answer={"answer": "New answer"})
        self.check_enqueue_conflict(posted)

    def check_enqueue_conflict(self, posted: dict[str, str]):
        before = list(models.FlowPageVisitGrade.objects.values())
        with self.temporarily_switch_to_user(self.instructor_participation.user), \
                mock.patch("course.tasks.draft_ai_grade.delay") as delay, \
                mock.patch("course.ai_grading.request_ai_grade") as request, \
                mock.patch("course.grade_storage.persist_grade") as persist, \
                mock.patch("course.flow.grade_flow_session") as recalculate:
            response = self.client.post(self.url, posted)
        self.assertEqual(response.status_code, 409)
        self.assertIn("out of date", response.json()["message"])
        self.assertIn("refresh", response.json()["message"])
        delay.assert_not_called()
        request.assert_not_called()
        persist.assert_not_called()
        recalculate.assert_not_called()
        self.assertEqual(list(models.FlowPageVisitGrade.objects.values()), before)
        self.assertEqual(len(mail.outbox), 0)

    def test_enqueue_without_validation_provider_saving_or_email(self):
        for valid in [False, True]:
            for graded in [False, True]:
                with self.subTest(valid=valid, graded=graded):
                    visit = self.get_visit()
                    models.FlowPageVisitGrade.objects.filter(visit=visit).delete()
                    grade = (factories.FlowPageVisitGradeFactory(visit=visit)
                             if graded else None)
                    if valid:
                        self.posted.update(grade_percent="40", grade_points="")
                    before = list(models.FlowPageVisitGrade.objects.values())
                    with mock.patch("course.ai_grading.request_ai_grade") as request, \
                            mock.patch("course.grade_storage.persist_grade"
                                       ) as persist, \
                            mock.patch("course.flow.grade_flow_session"
                                       ) as recalculate, \
                            mock.patch.object(HumanGradedTextQuestion,
                                              "post_grading_form") as form:
                        ticket, delay = self.enqueue()
                    delay.assert_called_once_with(
                            self.course.pk, visit.pk,
                            self.course.active_git_commit_sha,
                            grade.pk if grade else None,
                            initiated_by_id=self.instructor_participation.user.pk)
                    self.assertEqual(signing.loads(ticket, salt=AI_DRAFT_TICKET_SALT,
                                                   max_age=AI_DRAFT_MAX_AGE), {
                        "task_id": "draft-task",
                        "user_id": self.instructor_participation.user.pk,
                        "course_id": self.course.pk,
                        "visit_id": visit.pk,
                        "grade_id": grade.pk if grade else None,
                    })
                    request.assert_not_called()
                    persist.assert_not_called()
                    recalculate.assert_not_called()
                    form.assert_not_called()
                    self.assertEqual(list(models.FlowPageVisitGrade.objects.values()),
                                     before)
                    self.assertEqual(len(mail.outbox), 0)

    def test_return_task_states(self):
        grade = factories.FlowPageVisitGradeFactory(visit=self.get_visit())
        ticket, _ = self.enqueue()
        ready = {"state": "ready", "grade_id": grade.pk}
        before = list(models.FlowPageVisitGrade.objects.values())
        for state in ["PENDING", "STARTED", "RETRY", "SUCCESS", "FAILURE", "REVOKED"]:
            with self.subTest(state=state), \
                    mock.patch("celery.result.AsyncResult",
                        return_value=SimpleNamespace(
                            state=state, result=ready if state == "SUCCESS" else
                            RuntimeError("secret provider details"))) as result, \
                    mock.patch("course.grade_storage.persist_grade") as persist, \
                    mock.patch("course.flow.grade_flow_session") as recalculate:
                response = self.poll(ticket)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Cache-Control"], "no-store")
                result.assert_called_once_with("draft-task")
                if state == "SUCCESS":
                    self.assertEqual(response.json(), {"state": "ready"})
                elif state in ["FAILURE", "REVOKED"]:
                    self.assertEqual(response.json()["state"], "failed")
                    self.assertIn("Please try again", response.json()["message"])
                    self.assertIn("RuntimeError: secret provider details",
                                                      response.json()["message"])
                else:
                    self.assertEqual(response.json(), {"state": "pending"})
                persist.assert_not_called()
                recalculate.assert_not_called()
        self.assertEqual(list(models.FlowPageVisitGrade.objects.values()), before)
        self.assertEqual(len(mail.outbox), 0)

    def test_return_saved_grade_repeatedly_then_rejects_later_changes(self):
        visit = self.get_visit()
        for change in ["human", "submission", "reopened"]:
            with self.subTest(change=change):
                ticket, _ = self.enqueue()
                saved_grade = factories.FlowPageVisitGradeFactory(
                        visit=visit, grade_time=now(), ai_generated_by="test-model",
                        grader=self.instructor_participation.user,
                        grade_data={"grade_percent": 85, "feedback_text": "AI feedback",
                                    "notes": "Private note", "released": False})
                ready = {"state": "ready", "grade_id": saved_grade.pk}
                before = list(models.FlowPageVisitGrade.objects.values())
                with mock.patch("celery.result.AsyncResult",
                        return_value=SimpleNamespace(state="SUCCESS", result=ready)
                        ) as result, \
                        mock.patch("course.grade_storage.persist_grade") as persist, \
                        mock.patch("course.flow.grade_flow_session") as recalculate:
                    for _ in range(2):
                        response = self.poll(ticket)
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json(), {"state": "ready"})
                        self.assertEqual(response["Cache-Control"], "no-store")
                    self.assertEqual(
                            list(models.FlowPageVisitGrade.objects.values()), before)
                    new_visit = None
                    if change == "human":
                        factories.FlowPageVisitGradeFactory(
                                visit=visit, grade_time=now(), ai_generated_by=None,
                                grade_data={**saved_grade.grade_data,
                                            "grade_percent": 90, "released": True})
                    elif change == "submission":
                        new_visit = factories.FlowPageVisitFactory(
                                page_data=visit.page_data, is_submitted_answer=True,
                                answer={"answer": "New answer"})
                    else:
                        models.FlowSession.objects.filter(
                                pk=self.this_flow_session_id).update(in_progress=True)
                    response = self.poll(ticket)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["state"], "unavailable")
                    self.assertIn("submission or grade changed",
                                  response.json()["message"])
                    self.assertEqual(result.call_count, 3)
                    persist.assert_not_called()
                    recalculate.assert_not_called()
                if new_visit is not None:
                    new_visit.delete()
        self.assertEqual(len(mail.outbox), 0)

    def test_return_rejects_malformed_or_tampered_ticket(self):
        ticket, _ = self.enqueue()
        for invalid in ["", "not-a-ticket", ticket + "tampered"]:
            with self.subTest(ticket=invalid), \
                    mock.patch("celery.result.AsyncResult") as result:
                self.assertEqual(self.poll(invalid).status_code, 403)
                result.assert_not_called()

    def test_return_rejects_invalid_ticket_data(self):
        ticket, _ = self.enqueue()
        data = signing.loads(ticket, salt=AI_DRAFT_TICKET_SALT)
        invalid_payloads = [None, [], "not a mapping", {},
                            {**data, "unexpected": True}]
        for key in data:
            invalid_payloads.append({k: v for k, v in data.items() if k != key})
            invalid_values = [None, 123, []] if key == "task_id" else [
                "123", True, 1.5, []]
            if key not in {"task_id", "grade_id"}:
                invalid_values.append(None)
            invalid_payloads.extend({**data, key: value} for value in invalid_values)

        for payload in invalid_payloads:
            with self.subTest(payload=payload), \
                    mock.patch("celery.result.AsyncResult") as result, \
                    mock.patch("course.grading.get_object_or_404") as get_visit:
                invalid_ticket = signing.dumps(payload, salt=AI_DRAFT_TICKET_SALT)
                self.assertEqual(self.poll(invalid_ticket).status_code, 403)
                result.assert_not_called()
                get_visit.assert_not_called()

    def test_return_expired_ticket(self):
        with mock.patch("django.core.signing.time.time", return_value=1000):
            ticket, _ = self.enqueue()
        with mock.patch("django.core.signing.time.time",
                        return_value=1000 + AI_DRAFT_MAX_AGE + 1), \
                mock.patch("celery.result.AsyncResult") as result:
            response = self.poll(ticket)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "unavailable")
        self.assertIn("expired", response.json()["message"])
        result.assert_not_called()

    def test_return_rejects_wrong_user_or_course(self):
        ticket, _ = self.enqueue()
        data = signing.loads(ticket, salt=AI_DRAFT_TICKET_SALT)
        for key in ["user_id", "course_id"]:
            with self.subTest(key=key), \
                    mock.patch("celery.result.AsyncResult") as result:
                wrong_ticket = signing.dumps(
                        {**data, key: data[key] + 1}, salt=AI_DRAFT_TICKET_SALT)
                self.assertEqual(self.poll(wrong_ticket).status_code, 403)
                result.assert_not_called()

    def test_return_requires_get(self):
        ticket, _ = self.enqueue()
        url = reverse("relate-ai_grade_draft_return", args=[self.course.identifier])
        with self.temporarily_switch_to_user(self.instructor_participation.user), \
                mock.patch("celery.result.AsyncResult") as result:
            response = self.client.post(url, {"ticket": ticket})
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Allow"], "GET")
        result.assert_not_called()

    def test_drafting_and_return_recheck_permissions(self):
        ticket, _ = self.enqueue()
        for missing in [PPerm.view_gradebook, PPerm.assign_grade,
                        PPerm.use_ai_drafting]:
            with self.subTest(missing=missing):
                permission = models.ParticipationRolePermission.objects.get(
                        role__course=self.course, role__identifier="instructor",
                        permission=missing)
                permission.delete()
                try:
                    with self.temporarily_switch_to_user(
                            self.instructor_participation.user), \
                            mock.patch("course.tasks.draft_ai_grade.delay") as delay, \
                            mock.patch("celery.result.AsyncResult") as result:
                        response = self.client.post(self.url, self.posted)
                        self.assertEqual(response.status_code, 403)
                        self.assertEqual(self.poll(ticket).status_code, 403)
                    delay.assert_not_called()
                    result.assert_not_called()
                finally:
                    permission.pk = None
                    permission.save()

    def test_return_rejects_changed_grade(self):
        visit = self.get_visit()
        for graded in [False, True]:
            with self.subTest(graded=graded):
                models.FlowPageVisitGrade.objects.filter(visit=visit).delete()
                if graded:
                    factories.FlowPageVisitGradeFactory(visit=visit)
                ticket, _ = self.enqueue()
                factories.FlowPageVisitGradeFactory(visit=visit, grade_time=now())
                self.check_stale_ticket(ticket)

    def test_return_rejects_new_submission(self):
        ticket, _ = self.enqueue()
        visit = self.get_visit()
        factories.FlowPageVisitFactory(
                page_data=visit.page_data, is_submitted_answer=True,
                answer={"answer": "New answer"})
        self.check_stale_ticket(ticket)

    def test_return_rejects_reopened_session(self):
        ticket, _ = self.enqueue()
        models.FlowSession.objects.filter(pk=self.this_flow_session_id).update(
                in_progress=True)
        self.check_stale_ticket(ticket)

    def check_stale_ticket(self, ticket: str):
        with mock.patch("celery.result.AsyncResult", return_value=SimpleNamespace(
                state="PENDING", result=None)) as result:
            response = self.poll(ticket)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "unavailable")
        self.assertIn("submission or grade changed", response.json()["message"])
        result.assert_called_once_with("draft-task")


@pytest.mark.slow
class AIGradeBatchViewPermissionTest(
        SingleCourseQuizPageGradeInterfaceTestMixin, TestCase):

    def setUp(self):
        super().setUp()
        # Keep view_gradebook so denial specifically tests use_ai_drafting.
        models.ParticipationRolePermission.objects.filter(
                role__in=self.ta_participation.roles.all(),
                permission=PPerm.use_ai_drafting).delete()

    def test_per_opportunity_view_forbidden_without_permission(self):
        from course.models import GradingOpportunity

        gopp = GradingOpportunity.objects.filter(
                course=self.course, flow_id=self.flow_id).first()
        if gopp is None:
            self.skipTest("no grading opportunity for this flow")

        from django.urls import reverse
        url = reverse(
                "relate-ai_grade_by_opportunity",
                kwargs={
                    "course_identifier": self.course.identifier,
                    "opp_id": gopp.id})

        with self.temporarily_switch_to_user(self.ta_participation.user):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 403)
            resp = self.client.post(url, {"ai_grade": ["Draft AI grades"]})
            self.assertEqual(resp.status_code, 403)

    def test_per_opportunity_view_requires_assign_grade(self):
        from django.urls import reverse

        roles = self.ta_participation.roles.all()
        for role in roles:
            models.ParticipationRolePermission.objects.get_or_create(
                    role=role, permission=PPerm.use_ai_drafting)
        models.ParticipationRolePermission.objects.filter(
                role__in=roles, permission=PPerm.assign_grade).delete()

        opportunity = models.GradingOpportunity.objects.get(
                course=self.course, flow_id=self.flow_id)
        url = reverse(
                "relate-ai_grade_by_opportunity",
                kwargs={
                    "course_identifier": self.course.identifier,
                    "opp_id": opportunity.id})

        with self.temporarily_switch_to_user(self.ta_participation.user):
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_per_opportunity_form_on_separate_page(self):
        from django.urls import reverse

        opportunity = models.GradingOpportunity.objects.get(
                course=self.course, flow_id=self.flow_id)
        kwargs = {
            "course_identifier": self.course.identifier,
            "opp_id": opportunity.id,
        }
        gradebook_url = reverse("relate-view_grades_by_opportunity", kwargs=kwargs)
        form_url = reverse("relate-ai_grade_by_opportunity", kwargs=kwargs)

        with self.temporarily_switch_to_user(self.instructor_participation.user):
            response = self.client.get(gradebook_url)
            self.assertContains(response, f'href="{form_url}"')
            self.assertNotContains(response, 'name="page_id"')

            response = self.client.get(form_url)
            self.assertContains(response, 'name="page_id"')
            self.assertContains(response, 'name="override_human_grades"')
            self.assertFalse(
                    response.context["ai_grade_form"]["override_human_grades"].value())
            self.assertContains(response, f'href="{gradebook_url}"')
            page_id = response.context["ai_grade_form"].fields["page_id"].choices[0][0]

            with mock.patch("course.tasks.batch_ai_grade_flow_page.delay") as delay:
                delay.return_value.id = "01234567-89ab-cdef-0123-456789abcdef"
                response = self.client.post(form_url, {
                    "ai_grade": "Draft AI grades",
                    "page_id": "invalid/page",
                })
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["ai_grade_form"].errors)
                delay.assert_not_called()

                response = self.client.post(form_url, {
                    "ai_grade": "Draft AI grades",
                    "page_id": page_id,
                })
                self.assertEqual(response.status_code, 302)
                group_id, page_id = page_id.split("/", 1)
                delay.assert_called_once_with(
                        self.course.id, self.flow_id, group_id, page_id,
                        override_human_grades=False, redraft_ai_grades=False,
                        initiated_by_id=self.instructor_participation.user.pk)

                delay.reset_mock()
                response = self.client.post(form_url, {
                    "ai_grade": "Draft AI grades",
                    "page_id": f"{group_id}/{page_id}",
                    "override_human_grades": "on",
                })
                self.assertEqual(response.status_code, 302)
                delay.assert_called_once_with(
                        self.course.id, self.flow_id, group_id, page_id,
                        override_human_grades=True, redraft_ai_grades=False,
                        initiated_by_id=self.instructor_participation.user.pk)

        with self.temporarily_switch_to_user(self.ta_participation.user):
            response = self.client.get(gradebook_url)
            self.assertNotContains(response, f'href="{form_url}"')


@pytest.mark.parametrize("redraft", [False, True])
@pytest.mark.parametrize("override", [False, True])
def test_batch_form_independent_options(redraft: bool, override: bool):
    form = AIGradeFlowPageForm(["group/page"], {
        "page_id": "group/page",
        "redraft_ai_grades": redraft,
        "override_human_grades": override,
    })
    assert form.is_valid()
    assert form.cleaned_data["redraft_ai_grades"] is redraft
    assert form.cleaned_data["override_human_grades"] is override


def test_batch_form_options_default_off():
    unbound = AIGradeFlowPageForm(["group/page"])
    bound = AIGradeFlowPageForm(["group/page"], {"page_id": "group/page"})
    assert bound.is_valid()
    for name in ["redraft_ai_grades", "override_human_grades"]:
        assert unbound.fields[name].initial is False
        assert bound.cleaned_data[name] is False


@pytest.mark.django_db
@pytest.mark.parametrize("redraft", [False, True])
@pytest.mark.parametrize("override", [False, True])
def test_batch_view_passes_options(redraft: bool, override: bool):
    course = factories.CourseFactory()
    opportunity = factories.GradingOpportunityFactory(course=course)
    request = RequestFactory().post("/", {
        "page_id": "group/page",
        "redraft_ai_grades": redraft,
        "override_human_grades": override,
    })
    request.user = factories.UserFactory()
    pctx = SimpleNamespace(
        course=course, request=request, has_permission=mock.Mock(return_value=True))
    with mock.patch("course.grades.get_ai_gradable_page_ids",
                    return_value=["group/page"]), \
            mock.patch("course.tasks.batch_ai_grade_flow_page.delay") as delay:
        delay.return_value.id = "12345678-1234-5678-1234-567812345678"
        response = unwrap(ai_grade_by_opportunity)(pctx, str(opportunity.pk))
    assert response.status_code == 302
    delay.assert_called_once_with(
        course.pk, opportunity.flow_id, "group", "page",
        override_human_grades=override, redraft_ai_grades=redraft,
        initiated_by_id=request.user.pk)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["ungraded", "placeholder", "ai", "human"])
@pytest.mark.parametrize("redraft", [False, True])
@pytest.mark.parametrize("override", [False, True])
def test_batch_grade_selection(kind: str, redraft: bool, override: bool):
    _check_drafting(kind, redraft=redraft, override=override)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["ai", "human"])
def test_batch_defaults_preserve_existing_grades(kind: str):
    _check_drafting(kind)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["ai", "human"])
@pytest.mark.parametrize("redraft", [False, True])
@pytest.mark.parametrize("override", [False, True])
def test_batch_rechecks_grades_after_ai_request(
        kind: str, redraft: bool, override: bool):
    _check_drafting(kind, redraft=redraft, override=override, concurrent=True)


def _check_drafting(kind: str, *, redraft: bool | None = None,
                    override: bool | None = None,
                    concurrent: bool = False):
    course = factories.CourseFactory(ai_grading_model="test-model")
    session = factories.FlowSessionFactory(course=course, in_progress=False)
    page_data = factories.FlowPageDataFactory(flow_session=session)
    visit = factories.FlowPageVisitFactory(
        page_data=page_data, is_submitted_answer=True,
        answer={"answer": "Student answer"})
    page = HumanGradedTextQuestion.model_construct(
        id=page_data.page_id, title="Question", type="HumanGradedTextQuestion",
        prompt="What is 2+2?", value=5, rubric="Full credit for 4.")

    def create_grade(*_args: object) -> AIGradeResult:
        if kind != "ungraded":
            factories.FlowPageVisitGradeFactory(
                visit=visit,
                ai_generated_by="test-model" if kind == "ai" else None,
                grade_data=None if kind == "placeholder" else {
                    "grade_percent": 50, "feedback_text": "Previous feedback",
                    "released": False, "notes": "Private notes"})
        return AIGradeResult(grade_percent=80, feedback_text="New feedback")

    if not concurrent:
        create_grade()
    allowed = (kind in {"ungraded", "placeholder"}
               or (kind == "ai" and bool(redraft))
               or (kind == "human" and bool(override)))
    with ExitStack() as stack:
        for target in [
                "course.tasks.get_course_repo", "course.content.get_flow_desc",
                "course.ai_grading.get_openai_client",
                "celery.app.task.Task.update_state"]:
            stack.enter_context(mock.patch(target))
        stack.enter_context(mock.patch(
            "course.content.get_flow_page", return_value=page))
        stack.enter_context(mock.patch("course.utils.FlowContext"))
        stack.enter_context(mock.patch("course.utils.get_session_grading_mode"))
        stack.enter_context(mock.patch("course.flow.grade_flow_session"))
        request = stack.enter_context(mock.patch(
            "course.ai_grading.request_ai_grade",
            side_effect=create_grade if concurrent else None,
            return_value=AIGradeResult(grade_percent=80, feedback_text="New feedback")))
        persist = stack.enter_context(mock.patch("course.grade_storage.persist_grade"))
        options = {}
        if redraft is not None:
            options["redraft_ai_grades"] = redraft
        if override is not None:
            options["override_human_grades"] = override
        result = batch_ai_grade_flow_page(
            course.pk, session.flow_id, page_data.group_id, page_data.page_id,
            **options)
    assert request.call_count == int(concurrent or allowed)
    assert persist.call_count == int(allowed)
    assert result["message"] == (
        f"{int(allowed)} grade(s) drafted, {int(not allowed)} already graded (skipped)")
    if allowed:
        assert persist.call_args.args[3]["released"] is False
        assert persist.call_args.kwargs["ai_generated_by"] == "test-model"

# vim: foldmethod=marker
