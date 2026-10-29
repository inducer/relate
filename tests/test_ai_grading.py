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

import pytest
from django.apps import apps as django_apps
from django.test import TestCase

from course import models
from course.ai_grading import (
    AIGradeResult,
    build_messages,
    create_ai_grade,
)
from course.constants import ParticipationPermission as PPerm
from course.page import PageContext
from course.page.text import HumanGradedTextQuestion
from course.repo import serialize_revision
from course.tasks import ai_grade_flow_page
from tests import factories
from tests.test_grading import SingleCourseQuizPageGradeInterfaceTestMixin
from tests.test_tasks import TaskTestMixin
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
            type="HumanGradedTextQuestion",
            prompt="What is 2+2?",
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


class BuildMessagesTest(TestCase):
    def setUp(self):
        super().setUp()
        self.course = factories.CourseFactory()
        self.page_context = make_page_context(self.course)

    def test_default_prompt_used_when_not_specified(self):
        page = make_page(grading_prompt=None)
        messages = build_messages(
                page, self.page_context, {}, {"answer": "42"},
                point_value=5, grading_prompt=page.grading_prompt)

        system_message = messages[0]["content"]  # pyright: ignore[reportTypedDictNotRequiredAccess]
        self.assertIn("experienced", system_message)
        self.assertIn("grade_percent", system_message)

    def test_custom_grading_prompt_used_when_specified(self):
        page = make_page(grading_prompt="Only grade based on correctness.")
        messages = build_messages(
                page, self.page_context, {}, {"answer": "42"},
                point_value=5, grading_prompt=page.grading_prompt)

        system_message = messages[0]["content"]  # pyright: ignore[reportTypedDictNotRequiredAccess]
        self.assertIn("Only grade based on correctness.", system_message)

    def test_rubric_and_answer_included(self):
        page = make_page()
        messages = build_messages(
                page, self.page_context, {}, {"answer": "the answer"},
                point_value=5, grading_prompt=None)

        user_message = messages[1]["content"]  # pyright: ignore[reportTypedDictNotRequiredAccess]
        self.assertIn(page.rubric, user_message)
        self.assertIn("the answer", user_message)


class CreateAIGradeTest(TestCase):
    def test_creates_unreleased_ai_generated_grade(self):
        course = factories.CourseFactory(ai_grading_model="test-model")
        page = make_page()
        page_context = make_page_context(course)
        visit = make_matching_visit(course)

        ai_result = AIGradeResult(grade_percent=75, feedback_text="Nice work")

        grade = create_ai_grade(
                visit, page, page_context, b"some_sha", ai_result)

        grade.refresh_from_db()
        self.assertEqual(grade.ai_generated_by, "test-model")
        self.assertIsNone(grade.grader)
        self.assertFalse(grade.grade_data["released"])
        self.assertEqual(grade.grade_data["grade_percent"], 75)
        self.assertEqual(grade.grade_data["feedback_text"], "Nice work")
        self.assertIsNone(grade.correctness)
        self.assertIsNone(grade.feedback)
        self.assertEqual(
                grade.graded_at_git_commit_sha, serialize_revision(b"some_sha"))


class AddBatchAIGradePermissionMigrationTest(TestCase):
    def test_roles_with_assign_grade_get_new_permission(self):
        migration_module = importlib.import_module(
                "course.migrations.0124_ai_grading")

        course = factories.CourseFactory()
        role = factories.ParticipationRoleFactory(
                course=course, identifier="instructor")
        models.ParticipationRolePermission.objects.create(
                role=role, permission=PPerm.assign_grade)

        other_role = factories.ParticipationRoleFactory(
                course=course, identifier="student")
        models.ParticipationRolePermission.objects.create(
                role=other_role, permission=PPerm.view_calendar)

        migration_module.add_batch_ai_grade_flow_page_permission(
                django_apps, None)

        self.assertTrue(
                models.ParticipationRolePermission.objects.filter(
                    role=role,
                    permission=PPerm.batch_ai_grade_flow_page).exists())
        self.assertFalse(
                models.ParticipationRolePermission.objects.filter(
                    role=other_role,
                    permission=PPerm.batch_ai_grade_flow_page).exists())


@pytest.mark.slow
class AIGradeFlowPageTaskTest(
        SingleCourseQuizPageGradeInterfaceTestMixin, TaskTestMixin, TestCase):
    def test_drafts_grade_for_ungraded_submission_and_skips_human_graded(self):
        with mock.patch("course.ai_grading.get_openai_client"), \
                mock.patch("course.ai_grading.run_ai_grading_for_visit") as mock_run:
            mock_run.return_value = AIGradeResult(
                    grade_percent=80, feedback_text="Good effort")

            flow_session_id = self.this_flow_session_id
            flow_session = models.FlowSession.objects.get(id=flow_session_id)

            # The mixin only submits an answer, without ending the session
            # -- do so here (directly, to avoid needing a logged-in client),
            # since the batch task (like interactive grading) only considers
            # submissions of sessions that are no longer in progress.
            flow_session.in_progress = False
            flow_session.save()

            # create_ai_grade() records this on the grade it creates.
            self.course.ai_grading_model = "test-model"
            self.course.save()

            page_data = models.FlowPageData.objects.get(
                    flow_session=flow_session, page_id=self.page_id)

            result = ai_grade_flow_page(
                    self.course.pk, flow_session.flow_id,
                    page_data.group_id, page_data.page_id)

            self.assertIn("1", result["message"])

            ai_grades = models.FlowPageVisitGrade.objects.filter(
                    ai_generated_by__isnull=False)
            self.assertEqual(ai_grades.count(), 1)
            ai_grade = ai_grades.get()
            self.assertEqual(ai_grade.ai_generated_by, "test-model")
            self.assertIsNone(ai_grade.grader)
            self.assertFalse(ai_grade.grade_data["released"])
            self.assertEqual(ai_grade.grade_data["grade_percent"], 80)

            # Re-running drafts again (since the latest grade is still an
            # AI draft), rather than being skipped.
            mock_run.return_value = AIGradeResult(
                    grade_percent=95, feedback_text="Even better")
            ai_grade_flow_page(
                    self.course.pk, flow_session.flow_id,
                    page_data.group_id, page_data.page_id)

            self.assertEqual(
                    models.FlowPageVisitGrade.objects.filter(
                        ai_generated_by__isnull=False).count(),
                    2)

            # Now have a human grade it -- further runs must not touch it.
            grade_data = {
                "grade_percent": "60",
                "released": "on",
            }
            self.post_grade_by_page_id(self.page_id, grade_data)

            human_grade_count_before = models.FlowPageVisitGrade.objects.filter(
                    ai_generated_by__isnull=True).count()
            self.assertTrue(human_grade_count_before > 0)

            ai_grade_flow_page(
                    self.course.pk, flow_session.flow_id,
                    page_data.group_id, page_data.page_id)

            self.assertEqual(
                    models.FlowPageVisitGrade.objects.filter(
                        ai_generated_by__isnull=False).count(),
                    2)
            self.assertEqual(
                    models.FlowPageVisitGrade.objects.filter(
                        ai_generated_by__isnull=True).count(),
                    human_grade_count_before)


@pytest.mark.slow
class AIGradeBatchViewPermissionTest(
        SingleCourseQuizPageGradeInterfaceTestMixin, TestCase):
    def test_per_page_view_forbidden_without_permission(self):
        url = self.get_page_view_url_by_page_id(
                "relate-batch_ai_grade_flow_page", self.page_id)

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.client.post(url)
            self.assertEqual(resp.status_code, 403)

    def test_per_opportunity_view_forbidden_without_permission(self):
        # The TA role has 'view_gradebook' but (unlike the instructor role)
        # is not granted 'batch_ai_grade_flow_page', so this exercises the
        # new permission check specifically, rather than the pre-existing
        # 'view_gradebook' gate.
        from course.models import GradingOpportunity

        gopp = GradingOpportunity.objects.filter(
                course=self.course, flow_id=self.flow_id).first()
        if gopp is None:
            self.skipTest("no grading opportunity for this flow")

        from django.urls import reverse
        url = reverse(
                "relate-view_grades_by_opportunity",
                kwargs={
                    "course_identifier": self.course.identifier,
                    "opp_id": gopp.id})

        with self.temporarily_switch_to_user(self.ta_participation.user):
            resp = self.client.post(url, {"ai_grade": ["Draft AI grades"]})
            self.assertEqual(resp.status_code, 403)

# vim: foldmethod=marker
