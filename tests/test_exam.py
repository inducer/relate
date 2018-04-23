# -*- coding: utf-8 -*-

from __future__ import division

__copyright__ = "Copyright (C) 2014 Andreas Kloeckner, Zesheng Wang, Dong Zhuang"

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

import datetime
import pytz

import unittest
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.timezone import now, timedelta

from course.models import ExamTicket
from course import constants, exam

from tests.constants import (
    DATE_TIME_PICKER_TIME_FORMAT)

from tests.base_test_mixins import (
    SingleCourseTestMixin, MockAddMessageMixing)
from tests.utils import mock
from tests import factories


class GenTicketCodeTest(unittest.TestCase):
    """test exam.gen_ticket_code"""

    def test_unique(self):
        code = set()
        for i in range(10):
            code.add(exam.gen_ticket_code())

        self.assertEqual(len(code), 10)


class ExamTestMixin(SingleCourseTestMixin, MockAddMessageMixing):
    force_login_student_for_each_test = False

    default_faked_now = datetime.datetime(2019, 1, 1, tzinfo=pytz.UTC)

    default_valid_start_time = default_faked_now
    default_valid_end_time = default_valid_start_time + timedelta(hours=3)

    @classmethod
    def setUpTestData(cls):  # noqa
        super(ExamTestMixin, cls).setUpTestData()
        cls.add_user_permission(
            cls.instructor_participation.user, "can_issue_exam_tickets",
            model=ExamTicket)
        cls.exam = factories.ExamFactory(course=cls.course)

    def setUp(self):
        super(ExamTestMixin, self).setUp()
        self.c.force_login(self.instructor_participation.user)

    def get_post_data(self, **kwargs):
        data = {
            "user": self.student_participation.user.pk,
            "exam": self.exam.pk,
            "valid_start_time": (
                self.default_valid_start_time.strftime(
                    DATE_TIME_PICKER_TIME_FORMAT)),
            "valid_end_time": (
                self.default_valid_end_time.strftime(
                    DATE_TIME_PICKER_TIME_FORMAT))}
        data.update(kwargs)
        return data


class IssueExamTicketTest(ExamTestMixin, TestCase):
    """test exam.issue_exam_ticket
    """

    def get_issue_exam_ticket_url(self):
        from django.urls import reverse
        return reverse("relate-issue_exam_ticket")

    def get_issue_exam_ticket_view(self):
        return self.c.get(self.get_issue_exam_ticket_url())

    def post_issue_exam_ticket_view(self, data):
        return self.c.post(self.get_issue_exam_ticket_url(), data)

    def test_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_issue_exam_ticket_view()
            self.assertEqual(resp.status_code, 403)

            resp = self.post_issue_exam_ticket_view(data={})
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(ExamTicket.objects.count(), 0)

    def test_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_issue_exam_ticket_view()
            self.assertEqual(resp.status_code, 403)

            resp = self.post_issue_exam_ticket_view(data={})
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(ExamTicket.objects.count(), 0)

    def test_get_success(self):
        resp = self.get_issue_exam_ticket_view()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ExamTicket.objects.count(), 0)

    def test_post_success(self):
        resp = self.post_issue_exam_ticket_view(data=self.get_post_data())
        self.assertFormErrorLoose(resp, None)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ExamTicket.objects.count(), 1)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("Ticket issued for", reset=False)
        self.assertAddMessageCalledWith("The ticket code is")

    def test_form_invalid(self):
        with mock.patch("course.exam.IssueTicketForm.is_valid") as mock_is_valid:
            mock_is_valid.return_value = False
            resp = self.post_issue_exam_ticket_view(data=self.get_post_data())
            self.assertFormErrorLoose(resp, None)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(ExamTicket.objects.count(), 0)

    def test_participation_not_match(self):
        another_exam = factories.ExamFactory(
            course=factories.CourseFactory(identifier="another-course"))
        resp = self.post_issue_exam_ticket_view(
            data=self.get_post_data(exam=another_exam.pk))
        self.assertFormErrorLoose(resp, None)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ExamTicket.objects.count(), 0)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("User is not enrolled in course.")

    def test_revoke_revoke_prior_ticket(self):
        prior_ticket = factories.ExamTicketFactory(
            exam=self.exam,
            participation=self.student_participation,
            state=constants.exam_ticket_states.valid)

        resp = self.post_issue_exam_ticket_view(
            data=self.get_post_data(revoke_prior=True))
        self.assertFormErrorLoose(resp, None)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ExamTicket.objects.count(), 2)
        prior_ticket.refresh_from_db()
        self.assertEqual(prior_ticket.state, constants.exam_ticket_states.revoked)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("Ticket issued for", reset=False)
        self.assertAddMessageCalledWith("The ticket code is")


class BatchIssueExamTicketsTest(ExamTestMixin, TestCase):
    def get_batch_issue_exam_ticket_url(self, course_identifier=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        return self.get_course_view_url(
            "relate-batch_issue_exam_tickets",
            course_identifier=course_identifier)

    def get_batch_issue_exam_ticket_view(self):
        return self.c.get(self.get_batch_issue_exam_ticket_url())

    def post_batch_issue_exam_ticket_view(self, data):
        return self.c.post(self.get_batch_issue_exam_ticket_url(), data)

    def get_post_data(self, **kwargs):
        data = super(BatchIssueExamTicketsTest, self).get_post_data()
        del data["user"]
        data["format"] = "{{ tickets }}{{checkin_uri}}"
        data.update(kwargs)
        return data

    def test_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_batch_issue_exam_ticket_view()
            self.assertEqual(resp.status_code, 403)

            resp = self.post_batch_issue_exam_ticket_view(data={})
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(ExamTicket.objects.count(), 0)

    def test_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_batch_issue_exam_ticket_view()
            self.assertEqual(resp.status_code, 403)

            resp = self.post_batch_issue_exam_ticket_view(data={})
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(ExamTicket.objects.count(), 0)

    def test_get_success(self):
        resp = self.get_batch_issue_exam_ticket_view()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ExamTicket.objects.count(), 0)

    def test_form_invalid(self):
        with mock.patch("course.exam.BatchIssueTicketsForm.is_valid"
                        ) as mock_is_valid:
            mock_is_valid.return_value = False
            resp = self.post_batch_issue_exam_ticket_view(data=self.get_post_data())
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(ExamTicket.objects.count(), 0)

    def test_template_syntax_error(self):
        with mock.patch("course.content.markup_to_html") as mock_mth:
            from jinja2 import TemplateSyntaxError
            mock_mth.side_effect = TemplateSyntaxError(
                lineno=10, message=b"my error")
            resp = self.post_batch_issue_exam_ticket_view(data=self.get_post_data())
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(ExamTicket.objects.count(), 0)
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith("Template rendering failed")

    def test_unknown_error(self):
        with mock.patch("course.content.markup_to_html") as mock_mth:
            mock_mth.side_effect = RuntimeError("my error")
            resp = self.post_batch_issue_exam_ticket_view(data=self.get_post_data())
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(ExamTicket.objects.count(), 0)
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith("Template rendering failed")

    def test_post_success(self):
        factories.ParticipationFactory(course=self.course)
        factories.ParticipationFactory(
            course=self.course, status=constants.participation_status.dropped)
        resp = self.post_batch_issue_exam_ticket_view(
            data=self.get_post_data())
        self.assertEqual(resp.status_code, 200)
        self.assertFormErrorLoose(resp, None)
        self.assertEqual(ExamTicket.objects.count(), 4)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("4 tickets issued.")

    def test_revoke_revoke_prior_ticket(self):
        prior_ticket = factories.ExamTicketFactory(
            exam=self.exam,
            participation=self.student_participation,
            state=constants.exam_ticket_states.valid)

        resp = self.post_batch_issue_exam_ticket_view(
            data=self.get_post_data(revoke_prior=True))
        self.assertFormErrorLoose(resp, None)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ExamTicket.objects.count(), 4)
        prior_ticket.refresh_from_db()
        self.assertEqual(prior_ticket.state, constants.exam_ticket_states.revoked)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("3 tickets issued.")


@override_settings(RELATE_TICKET_MINUTES_VALID_AFTER_USE=120)
class CheckExamTicketTest(ExamTestMixin, TestCase):
    def setUp(self):
        super(CheckExamTicketTest, self).setUp()
        self.exam.refresh_from_db()
        self.now = now()
        self.facilities = frozenset([])
        self.exam.no_exams_after = self.now + timedelta(days=1)
        self.exam.no_exams_before = self.now - timedelta(days=2)
        self.exam.save()
        self.ticket = factories.ExamTicketFactory(
            exam=self.exam, participation=self.student_participation,
            state=constants.exam_ticket_states.valid,
            usage_time=self.now + timedelta(minutes=100),
            valid_start_time=self.now - timedelta(minutes=20),
            valid_end_time=self.now + timedelta(minutes=100),
        )

    def test_object_not_found(self):
        result, msg = exam.check_exam_ticket(
            username="abcd",
            code=self.ticket.code,
            now_datetime=self.now,
            facilities=self.facilities)
        self.assertFalse(result)
        self.assertEqual(msg, "User name or ticket code not recognized.")

    def test_ticket_not_usable(self):
        result, msg = exam.check_exam_ticket(
            username=self.student_participation.user.username,
            code=self.ticket.code,
            now_datetime=self.now,
            facilities=self.facilities)

        self.assertTrue(result, msg=msg)

        self.ticket.state = constants.exam_ticket_states.revoked
        self.ticket.save()

        result, msg = exam.check_exam_ticket(
            username=self.student_participation.user.username,
            code=self.ticket.code,
            now_datetime=self.now,
            facilities=self.facilities)
        self.assertFalse(result, msg=msg)
        self.assertEqual(
            msg, "Ticket is not in usable state. (Has it been revoked?)")

    def test_ticket_expired(self):
        self.ticket.usage_time = self.now - timedelta(days=1)
        self.ticket.state = constants.exam_ticket_states.used
        self.ticket.save()
        result, msg = exam.check_exam_ticket(
            username=self.student_participation.user.username,
            code=self.ticket.code,
            now_datetime=self.now,
            facilities=self.facilities)

        self.assertFalse(result, msg=msg)
        self.assertEqual(msg, "Ticket has exceeded its validity period.")

    def test_ticket_not_active(self):
        self.exam.active = False
        self.exam.save()

        result, msg = exam.check_exam_ticket(
            username=self.student_participation.user.username,
            code=self.ticket.code,
            now_datetime=self.now,
            facilities=self.facilities)

        self.assertFalse(result, msg=msg)
        self.assertEqual(msg, "Exam is not active.")

    def test_not_started(self):
        result, msg = exam.check_exam_ticket(
            username=self.student_participation.user.username,
            code=self.ticket.code,
            now_datetime=self.now - timedelta(days=5),
            facilities=self.facilities)
        self.assertFalse(result, msg=msg)
        self.assertEqual(msg, "Exam has not started yet.")

    def test_ended(self):
        result, msg = exam.check_exam_ticket(
            username=self.student_participation.user.username,
            code=self.ticket.code,
            now_datetime=self.now + timedelta(days=5),
            facilities=self.facilities)
        self.assertFalse(result, msg=msg)
        self.assertEqual(msg, "Exam has ended.")

    def test_restrict_to_facility(self):
        self.ticket.restrict_to_facility = "my_fa1"
        self.ticket.save()

        result, msg = exam.check_exam_ticket(
            username=self.student_participation.user.username,
            code=self.ticket.code,
            now_datetime=self.now,
            facilities=frozenset(["my_fa2"]))
        self.assertFalse(result, msg=msg)
        self.assertEqual(
            msg, "Exam ticket requires presence in facility 'my_fa1'.")

        result, msg = exam.check_exam_ticket(
            username=self.student_participation.user.username,
            code=self.ticket.code,
            now_datetime=self.now,
            facilities=None)
        self.assertFalse(result, msg=msg)
        self.assertEqual(
            msg, "Exam ticket requires presence in facility 'my_fa1'.")

        result, msg = exam.check_exam_ticket(
            username=self.student_participation.user.username,
            code=self.ticket.code,
            now_datetime=self.now,
            facilities=self.facilities)
        self.assertFalse(result, msg=msg)
        self.assertEqual(
            msg, "Exam ticket requires presence in facility 'my_fa1'.")

        result, msg = exam.check_exam_ticket(
            username=self.student_participation.user.username,
            code=self.ticket.code,
            now_datetime=self.now,
            facilities=frozenset(["my_fa1", "my_fa2"]))
        self.assertTrue(result, msg=msg)

    def test_not_yet_valid(self):
        result, msg = exam.check_exam_ticket(
            username=self.student_participation.user.username,
            code=self.ticket.code,
            now_datetime=self.ticket.valid_start_time - timedelta(minutes=1),
            facilities=self.facilities)
        self.assertFalse(result, msg=msg)
        self.assertEqual(
            msg, "Exam ticket is not yet valid.")

    def test_expired(self):
        result, msg = exam.check_exam_ticket(
            username=self.student_participation.user.username,
            code=self.ticket.code,
            now_datetime=self.ticket.valid_end_time + timedelta(minutes=1),
            facilities=self.facilities)
        self.assertFalse(result, msg=msg)
        self.assertEqual(
            msg, "Exam ticket has expired.")


class ExamTicketBackendTest(ExamTestMixin, TestCase):
    def setUp(self):
        super(ExamTicketBackendTest, self).setUp()
        self.backend = exam.ExamTicketBackend()

    def test_not_authenticate(self):
        with mock.patch("course.exam.check_exam_ticket") as mock_check_ticket:
            mock_check_ticket.return_value = False, "msg"
            self.assertIsNone(self.backend.authenticate("foo", "bar"))

    def test_get_user(self):
        self.assertEqual(
            self.backend.get_user(self.instructor_participation.user.pk),
            self.instructor_participation.user)

        self.assertIsNone(self.backend.get_user(100))


class IsFromExamsOnlyFacilityTest(unittest.TestCase):
    # test exam.is_from_exams_only_facility
    def setUp(self):
        self.requset = mock.MagicMock()
        self.requset.relate_facilities = ["fa1", "fa2"]
        fake_get_facilities_config = mock.patch(
            "course.utils.get_facilities_config")
        self.mock_get_facilities_config = fake_get_facilities_config.start()
        self.addCleanup(fake_get_facilities_config.stop)

    def test_true(self):
        self.mock_get_facilities_config.return_value = {
            "fa1": {"exams_only": False, "ip_range": "foo"},
            "fa2": {"exams_only": True, "ip_range": "bar"}}
        self.assertTrue(exam.is_from_exams_only_facility(self.requset))

    def test_false(self):
        self.mock_get_facilities_config.return_value = dict()
        self.assertFalse(exam.is_from_exams_only_facility(self.requset))

    def test_false_2(self):
        self.mock_get_facilities_config.return_value = {
            "fa1": {"exams_only": False, "ip_range": "foo"},
            "fa3": {"exams_only": True, "ip_range": "bar"}}
        self.assertFalse(exam.is_from_exams_only_facility(self.requset))


class CheckInForExamTest(ExamTestMixin, TestCase):
    force_login_student_for_each_test = True

    def setUp(self):
        super(CheckInForExamTest, self).setUp()
        self.ticket = factories.ExamTicketFactory(
            exam=self.exam, participation=self.student_participation,
            state=constants.exam_ticket_states.valid)
        self.instructor_ticket = factories.ExamTicketFactory(
            exam=self.exam, participation=self.instructor_participation,
            state=constants.exam_ticket_states.valid)

        fake_check_exam_ticket = mock.patch("course.exam.check_exam_ticket")
        self.mock_check_exam_ticket = fake_check_exam_ticket.start()
        self.addCleanup(fake_check_exam_ticket.stop)

    def get_check_in_for_exam_url(self):
        return reverse("relate-check_in_for_exam")

    def get_check_in_for_exam_view(self):
        return self.c.get(self.get_check_in_for_exam_url())

    def post_check_in_for_exam_view(self, data):
        return self.c.post(self.get_check_in_for_exam_url(), data)

    def get_post_data(self, **kwargs):
        data = {
            "username": self.student_participation.user.username,
            "code": self.ticket.code
        }
        data.update(kwargs)
        return data

    def test_get(self):
        resp = self.get_check_in_for_exam_view()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.ticket.state, constants.exam_ticket_states.valid)

    def test_login_success(self):
        self.mock_check_exam_ticket.return_value = True, "hello"
        resp = self.post_check_in_for_exam_view(
            self.get_post_data())

        self.assertEqual(resp.status_code, 302)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.state, constants.exam_ticket_states.used)

    def test_login_failure(self):
        self.mock_check_exam_ticket.return_value = False, "what's wrong?"
        resp = self.post_check_in_for_exam_view(
            self.get_post_data())

        self.assertEqual(resp.status_code, 200)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("what's wrong?")
        self.assertEqual(self.ticket.state, constants.exam_ticket_states.valid)

    def test_form_invalid(self):
        with mock.patch("course.exam.ExamCheckInForm.is_valid"
                        ) as mock_is_valid:
            mock_is_valid.return_value = False
            resp = self.post_check_in_for_exam_view(data=self.get_post_data())
            self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.ticket.state, constants.exam_ticket_states.valid)

    def test_login_though_ticket_not_valid(self):
        self.ticket.state = constants.exam_ticket_states.used
        self.ticket.save()
        self.mock_check_exam_ticket.return_value = True, "hello"
        resp = self.post_check_in_for_exam_view(
            self.get_post_data())

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.ticket.state, constants.exam_ticket_states.used)

    def test_pretend_facility(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            session = self.c.session
            fa = ["my_falicity_1"]
            session["relate_pretend_facilities"] = fa
            session.save()

            self.mock_check_exam_ticket.return_value = True, "hello"
            resp = self.post_check_in_for_exam_view(
                self.get_post_data(
                    username=self.instructor_participation.user.username,
                    code=self.instructor_ticket.code
                ))
            self.assertEqual(resp.status_code, 302)

            self.assertIn(frozenset(fa), self.mock_check_exam_ticket.call_args[0])
            self.assertEqual(
                self.c.session["relate_pretend_facilities"], fa)
            self.assertEqual(
                self.c.session["relate_exam_ticket_pk_used_for_login"],
                self.instructor_ticket.pk)

            self.instructor_ticket.refresh_from_db()
            self.assertEqual(self.instructor_ticket.state,
                             constants.exam_ticket_states.used)


class ListAvailableExamsTest(ExamTestMixin, TestCase):

    def setUp(self):
        super(ListAvailableExamsTest, self).setUp()
        self.ticket = factories.ExamTicketFactory(
            exam=self.exam, participation=self.student_participation,
            state=constants.exam_ticket_states.valid)
        self.instructor_ticket = factories.ExamTicketFactory(
            exam=self.exam, participation=self.instructor_participation,
            state=constants.exam_ticket_states.valid)

    def get_list_available_exams_url(self):
        return reverse("relate-list_available_exams")

    def get_list_available_view(self):
        return self.c.get(self.get_list_available_exams_url())

    def test_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_list_available_view()
            exams = resp.context["exams"]
            self.assertEqual(exams.count(), 0)

    def test_not_found(self):
        self.exam.no_exams_after = now() - timedelta(days=1)
        self.exam.no_exams_before = now() - timedelta(days=2)
        self.exam.save()
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_list_available_view()
            exams = resp.context["exams"]
            self.assertEqual(exams.count(), 0)

    def test_found(self):
        self.exam.no_exams_after = now() + timedelta(days=1)
        self.exam.no_exams_before = now() - timedelta(days=2)
        self.exam.save()
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_list_available_view()
            exams = resp.context["exams"]
            self.assertEqual(exams.count(), 1)

# vim: fdm=marker
