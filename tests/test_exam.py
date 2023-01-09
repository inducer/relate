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
import pytz_deprecation_shim as pytz

import unittest
from django.test import Client, TestCase, override_settings
from django import http
from django.urls import reverse
from django.utils.timezone import now, timedelta

from course.models import ExamTicket, FlowSession
from course import constants, exam

from tests.constants import (
    DATE_TIME_PICKER_TIME_FORMAT)

from tests.base_test_mixins import (
    SingleCourseTestMixin, MockAddMessageMixing, SingleCoursePageTestMixin)
from tests.utils import mock, reload_urlconf
from tests import factories


class GenTicketCodeTest(unittest.TestCase):
    """test exam.gen_ticket_code"""

    def test_unique(self):
        code = set()
        for _i in range(10):
            code.add(exam.gen_ticket_code())

        self.assertEqual(len(code), 10)


class ExamTestMixin(SingleCourseTestMixin, MockAddMessageMixing):
    force_login_student_for_each_test = False

    default_faked_now = datetime.datetime(2019, 1, 1, tzinfo=pytz.UTC)

    default_valid_start_time = default_faked_now
    default_valid_end_time = default_valid_start_time + timedelta(hours=3)

    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()
        cls.add_user_permission(
            cls.instructor_participation.user, "can_issue_exam_tickets",
            model=ExamTicket)
        cls.exam = factories.ExamFactory(course=cls.course)

    def setUp(self):
        super().setUp()
        self.client.force_login(self.instructor_participation.user)

        fake_get_now_or_fake_time = mock.patch(
            "course.views.get_now_or_fake_time")
        self.mock_get_now_or_fake_time = fake_get_now_or_fake_time.start()
        self.mock_get_now_or_fake_time.return_value = now()
        self.addCleanup(fake_get_now_or_fake_time.stop)

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
        return self.client.get(self.get_issue_exam_ticket_url())

    def post_issue_exam_ticket_view(self, data):
        return self.client.post(self.get_issue_exam_ticket_url(), data)

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
        self.mock_get_now_or_fake_time.return_value = self.default_faked_now

        resp = self.post_issue_exam_ticket_view(data=self.get_post_data())
        self.assertFormErrorLoose(resp, None)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ExamTicket.objects.count(), 1)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("Ticket issued for", reset=False)
        self.assertAddMessageCalledWith("The ticket code is")

    def test_form_invalid(self):
        self.mock_get_now_or_fake_time.return_value = self.default_faked_now

        with mock.patch("course.exam.IssueTicketForm.is_valid") as mock_is_valid:
            mock_is_valid.return_value = False
            resp = self.post_issue_exam_ticket_view(data=self.get_post_data())
            self.assertFormErrorLoose(resp, None)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(ExamTicket.objects.count(), 0)

    def test_participation_not_match(self):
        self.mock_get_now_or_fake_time.return_value = self.default_faked_now

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
        self.mock_get_now_or_fake_time.return_value = self.default_faked_now

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
        return self.client.get(self.get_batch_issue_exam_ticket_url())

    def post_batch_issue_exam_ticket_view(self, data):
        return self.client.post(self.get_batch_issue_exam_ticket_url(), data)

    def get_post_data(self, **kwargs):
        data = super().get_post_data()
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
        super().setUp()
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
        super().setUp()
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
    """test exam.is_from_exams_only_facility"""
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
        self.mock_get_facilities_config.return_value = {}
        self.assertFalse(exam.is_from_exams_only_facility(self.requset))

    def test_false_2(self):
        self.mock_get_facilities_config.return_value = {
            "fa1": {"exams_only": False, "ip_range": "foo"},
            "fa3": {"exams_only": True, "ip_range": "bar"}}
        self.assertFalse(exam.is_from_exams_only_facility(self.requset))


class GetLoginExamTicketTest(ExamTestMixin, TestCase):
    """test exam.get_login_exam_ticket"""
    def setUp(self):
        super().setUp()
        self.ticket = factories.ExamTicketFactory(
            exam=self.exam, participation=self.student_participation,
            state=constants.exam_ticket_states.valid)
        self.request = mock.MagicMock()

    def test_none(self):
        self.request.session = {}
        self.assertIsNone(exam.get_login_exam_ticket(self.request))

    def test_object_does_not_exist(self):
        self.request.session = {
            "relate_exam_ticket_pk_used_for_login": 100
        }
        with self.assertRaises(ExamTicket.DoesNotExist):
            exam.get_login_exam_ticket(self.request)

    def test_get(self):
        self.request.session = {
            "relate_exam_ticket_pk_used_for_login": self.ticket.pk
        }
        self.assertEqual(exam.get_login_exam_ticket(self.request), self.ticket)


class CheckInForExamTest(ExamTestMixin, TestCase):
    force_login_student_for_each_test = True

    def setUp(self):
        super().setUp()
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
        return self.client.get(self.get_check_in_for_exam_url())

    def post_check_in_for_exam_view(self, data):
        return self.client.post(self.get_check_in_for_exam_url(), data)

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
            session = self.client.session
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
                self.client.session["relate_pretend_facilities"], fa)
            self.assertEqual(
                self.client.session["relate_exam_ticket_pk_used_for_login"],
                self.instructor_ticket.pk)

            self.instructor_ticket.refresh_from_db()
            self.assertEqual(self.instructor_ticket.state,
                             constants.exam_ticket_states.used)


class ListAvailableExamsTest(ExamTestMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.ticket = factories.ExamTicketFactory(
            exam=self.exam, participation=self.student_participation,
            state=constants.exam_ticket_states.valid)
        self.instructor_ticket = factories.ExamTicketFactory(
            exam=self.exam, participation=self.instructor_participation,
            state=constants.exam_ticket_states.valid)

    def get_list_available_exams_url(self):
        return reverse("relate-list_available_exams")

    def get_list_available_view(self):
        return self.client.get(self.get_list_available_exams_url())

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


class ExamFacilityMiddlewareTest(SingleCoursePageTestMixin,
                                 MockAddMessageMixing, TestCase):
    """Integration tests for exam.ExamFacilityMiddleware"""
    def setUp(self):
        super().setUp()
        fake_is_from_exams_only_facility = mock.patch(
            "course.exam.is_from_exams_only_facility")
        self.mock_is_from_exams_only_facility = (
            fake_is_from_exams_only_facility.start())
        self.mock_is_from_exams_only_facility.return_value = True
        self.addCleanup(fake_is_from_exams_only_facility.stop)

    def test_not_exams_only_facility(self):
        self.mock_is_from_exams_only_facility.return_value = False
        resp = self.client.get(self.course_page_url)
        self.assertEqual(resp.status_code, 200)

    def test_exams_only_facility(self):
        resp = self.client.get(self.course_page_url)
        self.assertRedirects(
            resp, reverse("relate-list_available_exams"),
            fetch_redirect_response=False)

    def test_exams_only_facility_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.client.get(self.course_page_url)
            self.assertRedirects(
                resp, reverse("relate-sign_in_choice"),
                fetch_redirect_response=False)

    def test_already_locked_down(self):
        fs = factories.FlowSessionFactory(
            participation=self.student_participation, flow_id=self.flow_id)
        session = self.client.session
        session["relate_session_locked_to_exam_flow_session_pk"] = fs.pk
        session.save()

        resp = self.client.get(self.course_page_url)

        self.assertRedirects(
            resp, self.get_view_start_flow_url(self.flow_id),
            fetch_redirect_response=False)

    def test_ok_views(self):
        # we only test ta participation
        from course.auth import make_sign_in_key

        # make sign in key for a user
        u = factories.UserFactory(
            first_name="foo", last_name="bar",
            status=constants.user_status.unconfirmed)
        sign_in_key = make_sign_in_key(u)
        u.sign_in_key = sign_in_key
        u.save()

        self.client.force_login(self.ta_participation.user)

        my_session = factories.FlowSessionFactory(
            participation=self.ta_participation, flow_id=self.flow_id)

        with override_settings(RELATE_SIGN_IN_BY_USERNAME_ENABLED=True):
            for url, args, kwargs, code_or_redirect in [
                ("relate-sign_in_choice", [], {}, 200),
                ("relate-sign_in_by_email", [], {}, 200),

                ("relate-sign_in_stage2_with_token",
                    [u.pk, sign_in_key], {}, "/"),
                ("relate-sign_in_by_user_pw", [], {}, 200),
                ("relate-impersonate", [], {}, 200),

                # because not we are testing get, while stop_impersonating view
                # doesn't allow get, if it return 403 instead of 302
                # we think it passed test.
                ("relate-stop_impersonating", [], {}, 403),
                ("relate-check_in_for_exam", [], {}, 200),
                ("relate-list_available_exams", [], {}, 200),
                ("relate-view_start_flow", [],
                     {"course_identifier": self.course.identifier,
                      "flow_id": self.flow_id}, 200),
                ("relate-view_resume_flow", [],
                    {"course_identifier": self.course.identifier,
                     "flow_session_id": my_session.pk},
                    self.get_page_url_by_ordinal(0, flow_session_id=my_session.pk)),
                ("relate-user_profile", [], {}, 200),
                ("relate-logout", [], {}, "/"),
                ("relate-set_pretend_facilities", [], {}, 200),
            ]:
                with self.subTest(url=url):
                    if "sign_in" in url:
                        switch_to = None
                    else:
                        switch_to = self.ta_participation.user
                    with self.temporarily_switch_to_user(switch_to):
                        resp = self.client.get(
                                reverse(url, args=args, kwargs=kwargs))
                        try:
                            code = int(code_or_redirect)
                            self.assertEqual(resp.status_code, code)
                        except ValueError:
                            self.assertRedirects(
                                resp, code_or_redirect,
                                fetch_redirect_response=False)

    def test_ok_with_saml2_views(self):
        with override_settings(RELATE_SIGN_IN_BY_SAML2_ENABLED=True):
            reload_urlconf()

            with self.temporarily_switch_to_user(None):
                # "Settings" object has no attribute "SAML_CONFIG"
                # with that error raised, we can confirm it is actually
                # requesting the view
                with self.assertRaises(AttributeError):
                    self.client.get(reverse("saml2_login"))

    def test_ok_with_select2_views(self):
        # test by using the select2 widget of impersonating form
        with self.temporarily_switch_to_user(self.ta_participation.user):
            resp = self.get_impersonate_view()
            field_id = self.get_select2_field_id_from_response(resp)

            # With no search term, should display all impersonatable users
            term = None
            resp = self.select2_get_request(field_id=field_id, term=term)
            self.assertEqual(resp.status_code, 200)

    def test_ok_issue_exam_ticket_view_with_pperm(self):
        tup = (
            (self.student_participation.user, 302),
            (self.ta_participation.user, 302),
            (self.superuser, 200),)

        for user, status_code in tup:
            with self.subTest(user=user):
                with self.temporarily_switch_to_user(user):
                    resp = self.client.get(reverse("relate-issue_exam_ticket"))
                    self.assertEqual(resp.status_code, status_code)

    def test_not_ok_view_flow_page(self):
        fs = factories.FlowSessionFactory(
            participation=self.student_participation, flow_id=self.flow_id)
        resp = self.client.get(
                self.get_page_url_by_ordinal(0, flow_session_id=fs.pk))
        self.assertRedirects(
            resp, reverse("relate-list_available_exams"),
            fetch_redirect_response=False)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(
            "Access to flows in an exams-only facility "
            "is only granted if the flow is locked down. "
            "To do so, add 'lock_down_as_exam_session' to "
            "your flow's access permissions.")


class ExamLockdownMiddlewareTest(SingleCoursePageTestMixin,
                                 MockAddMessageMixing, TestCase):
    """Integration tests for exam.ExamLockdownMiddleware
    """
    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCoursePageTestMixin, cls).setUpTestData()
        client = Client()
        client.force_login(cls.student_participation.user)
        cls.start_flow(client, cls.flow_id)
        cls.fs = FlowSession.objects.last()

    def setUp(self):
        super().setUp()
        self.fs.refresh_from_db()

    def tweak_session_to_lock_down(self, flow_session_id=None):
        session = self.client.session
        session["relate_session_locked_to_exam_flow_session_pk"] = (
            flow_session_id or FlowSession.objects.last().pk)
        session.save()

    def test_relate_exam_lockdown(self):
        """make sure when not locked down, request.relate_exam_lockdown is True"""

        # not locked down
        with mock.patch("course.views.render") as mock_render:
            mock_render.return_value = http.HttpResponse("hello")
            self.client.get("/")
            request_obj = mock_render.call_args[0][0]
            self.assertTrue(hasattr(request_obj, "relate_exam_lockdown"))
            self.assertFalse(request_obj.relate_exam_lockdown)

        # add lock down to the session
        self.tweak_session_to_lock_down()
        with mock.patch("course.utils.render") as mock_render:
            mock_render.return_value = http.HttpResponse("hello")
            resp = self.client.get("/")
            self.assertRedirects(
                resp,
                self.get_view_start_flow_url(self.flow_id))
            request_obj = mock_render.call_args[0][0]
            self.assertTrue(hasattr(request_obj, "relate_exam_lockdown"))
            self.assertTrue(request_obj.relate_exam_lockdown)

    def test_lock_down_session_does_not_exist(self):
        """lock down to a session which does not exist"""
        self.tweak_session_to_lock_down(flow_session_id=100)
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 403)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(
            "Error while processing exam lockdown: "
            "flow session not found.")

    def test_ok_views(self):
        # we only test student participation user

        from course.auth import make_sign_in_key

        # make sign in key for a user
        u = factories.UserFactory(
            first_name="foo", last_name="bar",
            status=constants.user_status.unconfirmed)
        sign_in_key = make_sign_in_key(u)
        u.sign_in_key = sign_in_key
        u.save()

        with override_settings(RELATE_SIGN_IN_BY_USERNAME_ENABLED=True):
            for url, args, kwargs, code_or_redirect in [
                # 403, because these file do not have "in_exam" access permission
                ("relate-get_repo_file", [], {
                    "course_identifier": self.course.identifier,
                    "commit_sha": self.course.active_git_commit_sha,
                    "path": "images/cc.png"}, 403),
                ("relate-get_current_repo_file", [], {
                    "course_identifier": self.course.identifier,
                    "path": "pdfs/sample.pdf"}, 403),

                ("relate-check_in_for_exam", [], {}, 200),
                ("relate-list_available_exams", [], {}, 200),

                ("relate-sign_in_choice", [], {}, 200),
                ("relate-sign_in_by_email", [], {}, 200),
                ("relate-sign_in_stage2_with_token",
                    [u.pk, sign_in_key], {}, "/"),
                ("relate-sign_in_by_user_pw", [], {}, 200),
                ("relate-user_profile", [], {}, 200),
                ("relate-logout", [], {}, "/"),
            ]:
                with self.subTest(url=url):
                    if "sign_in" in url:
                        switch_to = None
                    else:
                        switch_to = self.student_participation.user
                    with self.temporarily_switch_to_user(switch_to):
                        self.tweak_session_to_lock_down()
                        resp = self.client.get(
                                reverse(url, args=args, kwargs=kwargs))
                        try:
                            code = int(code_or_redirect)
                            self.assertEqual(resp.status_code, code)
                        except ValueError:
                            self.assertRedirects(
                                resp, code_or_redirect,
                                fetch_redirect_response=False)

    def test_ok_with_saml2_views(self):
        with override_settings(RELATE_SIGN_IN_BY_SAML2_ENABLED=True):
            reload_urlconf()

            with self.temporarily_switch_to_user(None):
                self.tweak_session_to_lock_down()
                # 'Settings' object has no attribute 'SAML_CONFIG'
                # with that error raised, we can confirm it is actually
                # requesting the view
                with self.assertRaises(AttributeError):
                    self.client.get(reverse("saml2_login"))
                self.assertAddMessageCallCount(0)

    def test_ok_with_select2_views(self):
        # There's curently no views using select2 when locked down.
        # Here we are testing by using link from the select2 widget of
        # impersonating form
        with self.temporarily_switch_to_user(self.ta_participation.user):
            resp = self.get_impersonate_view()
            field_id = self.get_select2_field_id_from_response(resp)

            # With no search term, should display all impersonatable users
            term = None

            self.tweak_session_to_lock_down()
            resp = self.select2_get_request(field_id=field_id, term=term)
            self.assertEqual(resp.status_code, 200)

    def test_flow_page_related_view_ok(self):
        for url, args, kwargs, code_or_redirect in [
            ("relate-view_resume_flow", [],
                 {"course_identifier": self.course.identifier,
                  "flow_session_id": self.fs.pk},
                 self.get_page_url_by_ordinal(0, flow_session_id=self.fs.pk)),
            ("relate-view_flow_page", [],
                 {"course_identifier": self.course.identifier,
                  "flow_session_id": self.fs.pk,
                  "page_ordinal": 0}, 200),
            ("relate-update_expiration_mode", [],
                 {"course_identifier": self.course.identifier,
                  "flow_session_id": self.fs.pk},
                 400),  # this view doesn't allow get
            ("relate-update_page_bookmark_state", [],
                 {"course_identifier": self.course.identifier,
                  "flow_session_id": self.fs.pk, "page_ordinal": 0},
                 400),  # this view doesn't allow get
            ("relate-finish_flow_session_view", [],
                 {"course_identifier": self.course.identifier,
                  "flow_session_id": self.fs.pk}, 200),
        ]:
            with self.subTest(url=url):
                self.tweak_session_to_lock_down()
                resp = self.client.get(reverse(url, args=args, kwargs=kwargs))
                try:
                    code = int(code_or_redirect)
                    self.assertEqual(resp.status_code, code)
                except ValueError:
                    self.assertRedirects(
                        resp, code_or_redirect,
                        fetch_redirect_response=False)

    def test_flow_page_related_view_not_ok(self):
        another_flow_id = "jinja-yaml"
        self.start_flow(flow_id=another_flow_id)
        another_fs = FlowSession.objects.get(flow_id=another_flow_id)

        for url, args, kwargs, code_or_redirect in [
            ("relate-view_resume_flow", [],
                 {"course_identifier": self.course.identifier,
                  "flow_session_id": another_fs.pk},
                 self.get_view_start_flow_url(self.flow_id)),
            ("relate-view_flow_page", [],
                 {"course_identifier": self.course.identifier,
                  "flow_session_id": another_fs.pk, "page_ordinal": 0},
                 self.get_view_start_flow_url(self.flow_id)),
            ("relate-update_expiration_mode", [],
                 {"course_identifier": self.course.identifier,
                  "flow_session_id": another_fs.pk},
                 self.get_view_start_flow_url(self.flow_id)),
            ("relate-update_page_bookmark_state", [],
                 {"course_identifier": self.course.identifier,
                  "flow_session_id": another_fs.pk, "page_ordinal": 0},
                 self.get_view_start_flow_url(self.flow_id)),
            ("relate-finish_flow_session_view", [],
                 {"course_identifier": self.course.identifier,
                  "flow_session_id": another_fs.pk},
                 self.get_view_start_flow_url(self.flow_id)),
        ]:
            with self.subTest(url=url):
                self.tweak_session_to_lock_down()
                resp = self.client.get(reverse(url, args=args, kwargs=kwargs))
                try:
                    code = int(code_or_redirect)
                    self.assertEqual(resp.status_code, code)
                except ValueError:
                    self.assertRedirects(
                        resp, code_or_redirect,
                        fetch_redirect_response=False)
                self.assertAddMessageCallCount(1)
                self.assertAddMessageCalledWith(
                    "Your RELATE session is currently locked down "
                    "to this exam flow. Navigating to other parts of "
                    "RELATE is not currently allowed. "
                    "To exit this exam, log out.")

    def test_start_flow_ok(self):
        for url, args, kwargs, code_or_redirect in [
            ("relate-view_start_flow", [],
                 {"course_identifier": self.course.identifier,
                  "flow_id": self.flow_id}, 200),
        ]:
            with self.subTest(url=url):
                self.tweak_session_to_lock_down()
                resp = self.client.get(reverse(url, args=args, kwargs=kwargs))
                try:
                    code = int(code_or_redirect)
                    self.assertEqual(resp.status_code, code)
                except ValueError:
                    self.assertRedirects(
                        resp, code_or_redirect,
                        fetch_redirect_response=False)

                self.assertAddMessageCallCount(0, reset=True)

    def test_start_flow_not_ok(self):
        another_flow_id = "jinja-yaml"

        for url, args, kwargs, code_or_redirect in [
            ("relate-view_start_flow", [],
                 {"course_identifier": self.course.identifier,
                  "flow_id": another_flow_id},
                 self.get_view_start_flow_url(self.flow_id)),
        ]:
            with self.subTest(url=url):
                self.tweak_session_to_lock_down()
                resp = self.client.get(reverse(url, args=args, kwargs=kwargs))
                try:
                    code = int(code_or_redirect)
                    self.assertEqual(resp.status_code, code)
                except ValueError:
                    self.assertRedirects(
                        resp, code_or_redirect,
                        fetch_redirect_response=False)
                self.assertAddMessageCallCount(1)
                self.assertAddMessageCalledWith(
                    "Your RELATE session is currently locked down "
                    "to this exam flow. Navigating to other parts of "
                    "RELATE is not currently allowed. "
                    "To exit this exam, log out.")

# vim: fdm=marker
