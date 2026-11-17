from __future__ import annotations


__copyright__ = "Copyright (C) 2026 University of Illinois Board of Trustees"

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

from contextlib import ExitStack
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import resolve, reverse

from course.ai_grading import AIGradeResult, AIGradingError
from course.models import FlowPageVisitGrade
from course.page.text import HumanGradedTextQuestion
from course.tasks import batch_ai_grade_flow_page, draft_ai_grade
from tests import factories
from tests.utils import mock


if TYPE_CHECKING:
    from types import EllipsisType


LOCMEM_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
REVIEW_REASON = "Private review reason about Sensitive Student"
FEEDBACK = "Private feedback containing the student's answer"


@override_settings(
    RELATE_BASE_URL="https://relate.example.com/",
    ROBOT_EMAIL_FROM="robot@example.com",
    NOTIFICATION_EMAIL_FROM="notifications@example.com",
    MAILERS={alias: {"BACKEND": LOCMEM_BACKEND}
             for alias in ["default", "robot", "notification"]})
class AIGradingNotificationsTest(TestCase):
    def setUp(self):
        self.course = factories.CourseFactory(
                ai_grading_model="test-model", notify_email="course@example.com")
        self.initiator = factories.UserFactory(email="initiator@example.com")
        self.student = factories.UserFactory(
                username="sensitive-student-login", first_name="Sensitive",
                last_name="Student", email="sensitive-student@example.com",
                institutional_id="sensitive-student-id")
        self.participation = factories.ParticipationFactory(
                course=self.course, user=self.student)
        self.visit = self.make_visit()
        page_data = self.visit.page_data
        self.page = HumanGradedTextQuestion.model_construct(
                id=page_data.page_id, title="Private question title",
                type="HumanGradedTextQuestion", prompt="Private question prompt",
                value=5, rubric="Private rubric")

        stack = self.enterContext(ExitStack())
        for target in [
                "course.tasks.get_course_repo", "course.content.get_flow_desc",
                "course.ai_grading.get_openai_client", "course.utils.FlowContext",
                "course.utils.get_session_grading_mode",
                "course.flow.grade_flow_session", "celery.app.task.Task.update_state"]:
            stack.enter_context(mock.patch(target))
        stack.enter_context(mock.patch(
                "course.content.get_flow_page", return_value=self.page))
        self.request_grade = stack.enter_context(mock.patch(
                "course.ai_grading.request_ai_grade",
                return_value=self.suggestion()))

    def make_visit(self):
        session = factories.FlowSessionFactory(
                participation=self.participation, flow_id="notification-flow",
                in_progress=False)
        page_data = factories.FlowPageDataFactory(
                flow_session=session, group_id="notification-group",
                page_id="notification-page", page_ordinal=7)
        return factories.FlowPageVisitFactory(
                page_data=page_data, is_submitted_answer=True,
                answer={"answer": "Private student answer"})

    def suggestion(self, human_review: str | None = REVIEW_REASON):
        return AIGradeResult.model_validate({
            "grade_percent": 80, "feedback_text": FEEDBACK,
            "human_review": human_review,
            "confidence": {"score_percent": 60, "justification": "Private confidence"},
        })

    def run_batch(self, *, initiated_by_id: int | EllipsisType | None = ...):
        page_data = self.visit.page_data
        options = ({"initiated_by_id": initiated_by_id}
                   if initiated_by_id is not ... else {})
        return batch_ai_grade_flow_page(
                self.course.pk, self.visit.flow_session.flow_id,
                page_data.group_id, page_data.page_id, **options)

    def test_flagged_saved_grade_notifies_initiator_and_course(self):
        result = self.run_batch(initiated_by_id=self.initiator.pk)
        self.assertIn("1 grade(s) drafted", result["message"])
        grade = FlowPageVisitGrade.objects.get(visit=self.visit)
        self.assertEqual(grade.grader_id, self.initiator.pk)
        self.assertFalse(grade.grade_data["released"])
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.initiator.email])
        self.assertEqual(message.cc, [self.course.notify_email])
        self.assertEqual(message.bcc, [])
        self.assertCountEqual(
                message.recipients(), [self.initiator.email, self.course.notify_email])
        self.assertEqual(message.from_email, settings.NOTIFICATION_EMAIL_FROM)
        self.assertEqual(message.sent_using, "notification")

        content = message.subject + "\n" + message.body
        for expected in [self.visit.flow_session.flow_id,
                         self.visit.page_data.group_id, self.visit.page_data.page_id]:
            self.assertIn(expected, content)
        for private in [
                self.student.username, self.student.get_full_name(), self.student.email,
                self.student.institutional_id, REVIEW_REASON, FEEDBACK,
                "Private confidence", "Private question title",
                "Private question prompt", "Private rubric", "Private student answer"]:
            self.assertNotIn(private, content)

        path = reverse("relate-grade_flow_page", kwargs={
            "course_identifier": self.course.identifier,
            "flow_session_id": grade.visit.flow_session_id,
            "page_ordinal": grade.visit.page_data.page_ordinal,
        })
        url = f"https://relate.example.com{path}?grade_id={grade.pk}"
        self.assertIn(url, message.body)
        parsed = urlsplit(url)
        self.assertEqual(parse_qs(parsed.query), {"grade_id": [str(grade.pk)]})
        self.assertEqual(resolve(parsed.path).url_name, "relate-grade_flow_page")

    def test_robot_sender_and_mailer_fallback(self):
        del settings.NOTIFICATION_EMAIL_FROM
        self.run_batch(initiated_by_id=self.initiator.pk)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].from_email, settings.ROBOT_EMAIL_FROM)
        self.assertEqual(mail.outbox[0].sent_using, "robot")

    @override_settings(MAILERS={"default": {"BACKEND": LOCMEM_BACKEND}})
    def test_default_mailer_fallback(self):
        self.run_batch(initiated_by_id=self.initiator.pk)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].sent_using, "default")

    def test_unflagged_grade_does_not_notify(self):
        self.request_grade.return_value = self.suggestion(human_review=None)
        self.run_batch(initiated_by_id=self.initiator.pk)
        self.assertEqual(FlowPageVisitGrade.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_legacy_call_without_initiator_does_not_notify(self):
        for initiated_by_id in [..., None]:
            with self.subTest(initiated_by_id=initiated_by_id):
                FlowPageVisitGrade.objects.all().delete()
                self.run_batch(initiated_by_id=initiated_by_id)
                grade = FlowPageVisitGrade.objects.get(visit=self.visit)
                self.assertIsNone(grade.grader_id)
                self.assertEqual(len(mail.outbox), 0)

    def test_initiator_without_email_does_not_notify_course_alone(self):
        self.initiator.email = ""
        self.initiator.save()
        self.run_batch(initiated_by_id=self.initiator.pk)
        self.assertEqual(FlowPageVisitGrade.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_existing_grade_is_skipped_without_notification(self):
        factories.FlowPageVisitGradeFactory(
                visit=self.visit, ai_generated_by="previous-model",
                grade_data={"grade_percent": 40, "released": False})
        result = self.run_batch(initiated_by_id=self.initiator.pk)
        self.assertIn("0 grade(s) drafted", result["message"])
        self.request_grade.assert_not_called()
        self.assertEqual(len(mail.outbox), 0)

    def test_concurrently_reopened_session_does_not_notify(self):
        def reopen(*_args: object):
            session = self.visit.flow_session
            session.in_progress = True
            session.save()
            return self.suggestion()

        self.request_grade.side_effect = reopen
        result = self.run_batch(initiated_by_id=self.initiator.pk)
        self.assertIn("0 grade(s) drafted", result["message"])
        self.assertFalse(FlowPageVisitGrade.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_missing_submission_does_not_notify(self):
        self.visit.is_submitted_answer = False
        self.visit.save()
        self.run_batch(initiated_by_id=self.initiator.pk)
        self.request_grade.assert_not_called()
        self.assertEqual(len(mail.outbox), 0)

    def test_unsupported_grading_input_does_not_notify(self):
        with mock.patch.object(HumanGradedTextQuestion, "make_ai_grading_input",
                               return_value=None):
            self.run_batch(initiated_by_id=self.initiator.pk)
        self.request_grade.assert_not_called()
        self.assertEqual(len(mail.outbox), 0)

    def test_interactive_flagged_draft_does_not_notify(self):
        result = draft_ai_grade(
                self.course.pk, self.visit.pk, "test-revision", None,
                initiated_by_id=self.initiator.pk)
        self.assertEqual(result["state"], "ready")
        self.assertEqual(FlowPageVisitGrade.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_notification_sent_before_later_batch_failure(self):
        self.make_visit()
        calls = 0

        def provider(*_args: object):
            nonlocal calls
            calls += 1
            if calls == 2:
                # Delivery must already have occurred, not just been queued.
                self.assertEqual(len(mail.outbox), 1)
                self.assertEqual(FlowPageVisitGrade.objects.count(), 1)
                raise AIGradingError("Later provider failure")
            return self.suggestion()

        self.request_grade.side_effect = provider
        with self.assertRaisesMessage(AIGradingError, "Later provider failure"):
            self.run_batch(initiated_by_id=self.initiator.pk)
        self.assertEqual(calls, 2)
        self.assertEqual(len(mail.outbox), 1)
        grade = FlowPageVisitGrade.objects.get()
        self.assertIn(f"grade_id={grade.pk}", mail.outbox[0].body)
