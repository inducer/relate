from __future__ import division

__copyright__ = "Copyright (C) 2017 Dong Zhuang"

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

import six
import unittest
from django.test import TestCase
from django.conf import settings
from django.test.utils import override_settings  # noqa
from django.core import mail
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.urls import reverse

from relate.utils import string_concat

from course import constants
from course import enrollment
from course.models import (
    Participation, ParticipationRole, ParticipationPreapproval)
from course.constants import (
    participation_status as p_status, user_status as u_status)

from tests.base_test_mixins import (
    CoursesTestMixinBase, SingleCourseTestMixin,
    FallBackStorageMessageTestMixin
)
from tests.utils import LocmemBackendTestsMixin, mock
from tests import factories

TEST_EMAIL_SUFFIX1 = "@suffix.com"
TEST_EMAIL_SUFFIX2 = "suffix.com"

EMAIL_CONNECTIONS = "EMAIL_CONNECTIONS"
EMAIL_CONNECTION_DEFAULT = "EMAIL_CONNECTION_DEFAULT"
NO_REPLY_EMAIL_FROM = "NO_REPLY_EMAIL_FROM"
NOTIFICATION_EMAIL_FROM = "NOTIFICATION_EMAIL_FROM"
GRADER_FEEDBACK_EMAIL_FROM = "GRADER_FEEDBACK_EMAIL_FROM"
STUDENT_INTERACT_EMAIL_FROM = "STUDENT_INTERACT_EMAIL_FROM"
ENROLLMENT_EMAIL_FROM = "ENROLLMENT_EMAIL_FROM"

# {{{ message constants

MESSAGE_ENROLLMENT_SENT_TEXT = (
    "Enrollment request sent. You will receive notifcation "
    "by email once your request has been acted upon.")
MESSAGE_ENROLL_REQUEST_PENDING_TEXT = (
    "Your enrollment request is pending. You will be "
    "notified once it has been acted upon.")
MESSAGE_ENROLL_DENIED_NOT_ALLOWED_TEXT = (
    "Your enrollment request had been denied. Enrollment is not allowed.")
MESSAGE_ENROLL_DROPPED_NOT_ALLOWED_TEXT = (
    "You had been dropped from the course. Re-enrollment is not allowed.")
MESSAGE_ENROLL_REQUEST_ALREADY_PENDING_TEXT = (
    "You have previously sent the enrollment request. "
    "Re-sending the request is not allowed.")
MESSAGE_PARTICIPATION_ALREADY_EXIST_TEXT = (
    "A participation already exists. Enrollment attempt aborted.")
MESSAGE_CANNOT_REENROLL_TEXT = ("Already enrolled. Cannot re-enroll.")
MESSAGE_SUCCESSFULLY_ENROLLED_TEXT = ("Successfully enrolled.")
MESSAGE_EMAIL_SUFFIX_REQUIRED_PATTERN = (
    "Enrollment not allowed. Please use your '%s' email to enroll.")
MESSAGE_NOT_ACCEPTING_ENROLLMENTS_TEXT = ("Course is not accepting enrollments.")
MESSAGE_ENROLL_ONLY_ACCEPT_POST_REQUEST_TEXT = (
    "Can only enroll using POST request")
MESSAGE_ENROLLMENT_DENIED_TEXT = "Successfully denied."
MESSAGE_ENROLLMENT_DROPPED_TEXT = "Successfully dropped."

MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN = (
    "%(n_created)d preapprovals created, "
    "%(n_exist)d already existed, "
    "%(n_requested_approved)d pending requests approved.")

MESSAGE_EMAIL_NOT_CONFIRMED_TEXT = (
    "Your email address is not yet confirmed. "
    "Confirm your email to continue.")
MESSAGE_PARTICIPATION_CHANGE_SAVED_TEXT = ("Changes saved.")

EMAIL_NEW_ENROLLMENT_REQUEST_TITLE_PATTERN = (
    string_concat("[%s] ", "New enrollment request"))
EMAIL_ENROLLMENT_DECISION_TITLE_PATTERN = (
    string_concat("[%s] ", "Your enrollment request"))

VALIDATION_ERROR_USER_NOT_CONFIRMED = (
    "This user has not confirmed his/her email.")

# }}}


class EnrollmentTestMixin(CoursesTestMixinBase):
    @classmethod
    def setUpTestData(cls):  # noqa
        super(EnrollmentTestMixin, cls).setUpTestData()
        cls.course = factories.CourseFactory()

    def setUp(self):
        super(EnrollmentTestMixin, self).setUp()
        self.course.refresh_from_db()
        fake_add_message = mock.patch('course.enrollment.messages.add_message')
        self.mock_add_message = fake_add_message.start()
        self.addCleanup(fake_add_message.stop)

    @property
    def course_page_url(self):
        return self.get_course_page_url(self.course.identifier)

    @property
    def enroll_request_url(self):
        return reverse("relate-enroll", args=[self.course.identifier])

    @classmethod
    def get_participation_edit_url(cls, participation_id):
        return reverse("relate-edit_participation",
                       args=[cls.course.identifier, participation_id])

    def get_participation_count_by_status(self, status):
        return Participation.objects.filter(
            course__identifier=self.course.identifier,
            status=status
        ).count()

    def update_course(self, **kwargs):
        self.course.__dict__.update(kwargs)
        self.course.save()

    def update_require_approval_course(self, **kwargs):
        self.course.__dict__.update(kwargs)
        self.course.enrollment_approval_required = True
        self.course.save()

    def get_test_participation(self, **kwargs):
        return factories.ParticipationFactory(
            course=self.course, **kwargs)

    def get_test_preapproval(self, **kwargs):
        defaults = {"course": self.course,
                    "email": None,
                    "institutional_id": None}
        defaults.update(kwargs)

        return factories.ParticipationPreapprovalFactory(**defaults)

    def assertMockAddedMessagesCalledWith(self, expected_messages, reset=True):  # noqa
        args = "; ".join([
            "'%s'" % str(arg[2])
            for arg, _ in self.mock_add_message.call_args_list])
        if not isinstance(expected_messages, list):
            expected_messages = [expected_messages]

        not_called = []
        for msg in expected_messages:
            if msg not in args:
                not_called.append(msg)

        if not_called:
            self.fail(
                "%s unexpectedly not added in messages, "
                "the actual message are \"%s\"" % (repr(not_called), args))
        if reset:
            self.mock_add_message.reset_mock()

    def assertParticiaptionStatusCallCount(self, expected_counts):  # noqa
        from collections import OrderedDict
        d = OrderedDict()
        counts = []
        for status in sorted(
                list(dict(constants.PARTICIPATION_STATUS_CHOICES).keys())):
            count = Participation.objects.filter(
                course=self.course, status=status
            ).count()
            d[status] = count
            counts.append(count)

        self.assertListEqual(counts, expected_counts, repr(d))

    @property
    def student_role_post_data(self):
        role, _ = (ParticipationRole.objects.get_or_create(
            course=self.course, identifier="student"))
        return [str(role.pk)]


class EnrollViewTest(EnrollmentTestMixin, TestCase):
    # test enrollment.enroll_view

    def test_participation_status_requested(self):
        participation = self.get_test_participation(
            status=p_status.requested)
        self.assertParticiaptionStatusCallCount([0, 0, 0, 1])
        with self.temporarily_switch_to_user(participation.user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertMockAddedMessagesCalledWith(
            MESSAGE_ENROLL_REQUEST_ALREADY_PENDING_TEXT)
        self.assertParticiaptionStatusCallCount([0, 0, 0, 1])
        self.assertEqual(len(mail.outbox), 0)

    def test_participation_status_denied(self):
        participation = self.get_test_participation(
            status=p_status.denied)
        self.assertParticiaptionStatusCallCount([0, 1, 0, 0])
        with self.temporarily_switch_to_user(participation.user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertIn(
            MESSAGE_ENROLL_DENIED_NOT_ALLOWED_TEXT,
            self.mock_add_message.call_args[0])
        self.assertParticiaptionStatusCallCount([0, 1, 0, 0])
        self.assertEqual(len(mail.outbox), 0)

    def test_participation_status_dropped(self):
        participation = self.get_test_participation(
            status=p_status.dropped)
        self.assertParticiaptionStatusCallCount([0, 0, 1, 0])
        with self.temporarily_switch_to_user(participation.user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertIn(
            MESSAGE_ENROLL_DROPPED_NOT_ALLOWED_TEXT,
            self.mock_add_message.call_args[0])
        self.assertParticiaptionStatusCallCount([0, 0, 1, 0])
        self.assertEqual(len(mail.outbox), 0)

    def test_participation_status_active(self):
        participation = self.get_test_participation(
            status=p_status.active)
        self.assertParticiaptionStatusCallCount([1, 0, 0, 0])
        with self.temporarily_switch_to_user(participation.user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertIn(
            MESSAGE_CANNOT_REENROLL_TEXT,
            self.mock_add_message.call_args[0])
        self.assertParticiaptionStatusCallCount([1, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 0)

    def test_not_accepts_enrollment(self):
        self.update_course(accepts_enrollment=False)
        user = factories.UserFactory()

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertIn(
            MESSAGE_NOT_ACCEPTING_ENROLLMENTS_TEXT,
            self.mock_add_message.call_args[0])
        self.assertParticiaptionStatusCallCount([0, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 0)

    def test_not_post_request(self):
        user = factories.UserFactory()
        with self.temporarily_switch_to_user(user):
            resp = self.c.get(self.enroll_request_url)
            self.assertRedirects(
                resp, self.course_page_url, fetch_redirect_response=False)
            self.assertEqual(self.mock_add_message.call_count, 1)
            self.assertIn(
                MESSAGE_ENROLL_ONLY_ACCEPT_POST_REQUEST_TEXT,
                self.mock_add_message.call_args[0])
        self.assertParticiaptionStatusCallCount([0, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 0)

    @unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_user_not_active(self):
        for status in dict(constants.USER_STATUS_CHOICES).keys():
            if status != u_status.active:
                with self.subTest(user_status=status):
                    user = factories.UserFactory(status=status)
                    with self.temporarily_switch_to_user(user):
                        resp = self.c.post(self.enroll_request_url)
                    self.assertRedirects(
                        resp, self.course_page_url, fetch_redirect_response=False)
                    self.assertEqual(self.mock_add_message.call_count, 1)
                    self.assertIn(
                        MESSAGE_EMAIL_NOT_CONFIRMED_TEXT,
                        self.mock_add_message.call_args[0])
        self.assertParticiaptionStatusCallCount([0, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 0)

    def test_no_restrictions(self):
        user = factories.UserFactory()
        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertIn(
            MESSAGE_SUCCESSFULLY_ENROLLED_TEXT,
            self.mock_add_message.call_args[0])

        self.assertParticiaptionStatusCallCount([1, 0, 0, 0])

    def test_no_restrictions_user_has_no_instid(self):
        user = factories.UserFactory(institutional_id=None)
        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertIn(
            MESSAGE_SUCCESSFULLY_ENROLLED_TEXT,
            self.mock_add_message.call_args[0])

        self.assertParticiaptionStatusCallCount([1, 0, 0, 0])

    def test_not_matching_preapproved_email(self):
        self.update_require_approval_course()
        user = factories.UserFactory()
        self.get_test_preapproval(email="blabla@com")

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertMockAddedMessagesCalledWith(MESSAGE_ENROLLMENT_SENT_TEXT)
        self.assertEqual(len(mail.outbox), 1)
        self.assertParticiaptionStatusCallCount([0, 0, 0, 1])

    def test_matched_preapproved_email(self):
        self.update_require_approval_course()
        user = factories.UserFactory()
        self.get_test_preapproval(email=user.email)

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertMockAddedMessagesCalledWith(
            MESSAGE_SUCCESSFULLY_ENROLLED_TEXT)
        self.assertParticiaptionStatusCallCount([1, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 1)

    @unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_coures_not_require_inst_id_verified(self):
        self.update_require_approval_course(
            preapproval_require_verified_inst_id=False)

        for verified in [True, False]:
            with self.subTest(user_inst_id_verified=verified):
                user = factories.UserFactory(institutional_id_verified=verified)
                self.get_test_preapproval(institutional_id=user.institutional_id)

                with self.temporarily_switch_to_user(user):
                    resp = self.c.post(self.enroll_request_url)
                self.assertRedirects(
                    resp, self.course_page_url, fetch_redirect_response=False)
                self.assertEqual(self.mock_add_message.call_count, 1)
                self.assertMockAddedMessagesCalledWith(
                    MESSAGE_SUCCESSFULLY_ENROLLED_TEXT)

        self.assertParticiaptionStatusCallCount([2, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 2)

    def test_coures_require_inst_id_verified_user_inst_id_verified1(self):
        # matched
        self.update_require_approval_course(
            preapproval_require_verified_inst_id=True)

        user = factories.UserFactory(institutional_id_verified=True)
        self.get_test_preapproval(institutional_id=user.institutional_id)

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertMockAddedMessagesCalledWith(MESSAGE_SUCCESSFULLY_ENROLLED_TEXT)
        self.assertParticiaptionStatusCallCount([1, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 1)

    def test_coures_require_inst_id_verified_user_inst_id_verified2(self):
        # not matched
        self.update_require_approval_course(
            preapproval_require_verified_inst_id=True)

        user = factories.UserFactory(institutional_id_verified=True)
        self.get_test_preapproval(institutional_id="not_exist_instid")

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertMockAddedMessagesCalledWith(MESSAGE_ENROLLMENT_SENT_TEXT)
        self.assertEqual(len(mail.outbox), 1)
        self.assertParticiaptionStatusCallCount([0, 0, 0, 1])

    def test_coures_require_inst_id_verified_user_inst_id_not_verified1(self):
        # thought matched
        self.update_require_approval_course(
            preapproval_require_verified_inst_id=True)

        user = factories.UserFactory(institutional_id_verified=False)
        self.get_test_preapproval(institutional_id=user.institutional_id)

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertMockAddedMessagesCalledWith(MESSAGE_ENROLLMENT_SENT_TEXT)
        self.assertParticiaptionStatusCallCount([0, 0, 0, 1])
        self.assertEqual(len(mail.outbox), 1)

    def test_coures_require_inst_id_verified_user_inst_id_not_verified2(self):
        # not matched
        self.update_require_approval_course(
            preapproval_require_verified_inst_id=True)

        user = factories.UserFactory(institutional_id_verified=False)
        self.get_test_preapproval(institutional_id="not_exist_instid")

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertMockAddedMessagesCalledWith(MESSAGE_ENROLLMENT_SENT_TEXT)
        self.assertParticiaptionStatusCallCount([0, 0, 0, 1])
        self.assertEqual(len(mail.outbox), 1)

    def test_coures_require_email_suffix_passed(self):
        self.update_require_approval_course(
            enrollment_required_email_suffix="@blabla.com")

        user = factories.UserFactory(email="abc@blabla.com")

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertMockAddedMessagesCalledWith(MESSAGE_SUCCESSFULLY_ENROLLED_TEXT)
        self.assertParticiaptionStatusCallCount([1, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 1)

    def test_coures_require_email_suffix_passed_without_at(self):
        # without @ in suffix config
        self.update_require_approval_course(
            enrollment_required_email_suffix="blabla.com")
        user = factories.UserFactory(email="abc@blabla.com")

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertMockAddedMessagesCalledWith(MESSAGE_SUCCESSFULLY_ENROLLED_TEXT)
        self.assertParticiaptionStatusCallCount([1, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 1)

    def test_coures_require_email_suffix_passed_without_at_pattern2(self):
        # without @ in suffix config
        self.update_require_approval_course(
            enrollment_required_email_suffix="blabla.com")
        user = factories.UserFactory(email="abc@edu.blabla.com")

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertMockAddedMessagesCalledWith(MESSAGE_SUCCESSFULLY_ENROLLED_TEXT)
        self.assertParticiaptionStatusCallCount([1, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 1)

    def test_coures_require_email_suffix_failed(self):
        required_suffix = "blabla.com"
        self.update_require_approval_course(
            enrollment_required_email_suffix=required_suffix)
        user = factories.UserFactory(email="abc@blabla.com.hk")

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertMockAddedMessagesCalledWith(
            MESSAGE_EMAIL_SUFFIX_REQUIRED_PATTERN % required_suffix)
        self.assertParticiaptionStatusCallCount([0, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 0)

    def test_integrity_error(self):
        with mock.patch(
                "course.enrollment.handle_enrollment_request"
        ) as mock_handle_enrollment_request:
            from django.db import IntegrityError
            mock_handle_enrollment_request.side_effect = IntegrityError
            user = factories.UserFactory()
            with self.temporarily_switch_to_user(user):
                resp = self.c.post(self.enroll_request_url)
            self.assertRedirects(
                resp, self.course_page_url, fetch_redirect_response=False)
            self.assertEqual(self.mock_add_message.call_count, 1)
            self.assertMockAddedMessagesCalledWith(
                MESSAGE_PARTICIPATION_ALREADY_EXIST_TEXT)

            self.assertParticiaptionStatusCallCount([0, 0, 0, 0])


class HandleEnrollmentRequestTest(SingleCourseTestMixin,
                                  EnrollmentTestMixin, TestCase):
    # test enrollment.handle_enrollment_request
    def setUp(self):
        super(HandleEnrollmentRequestTest, self).setUp()
        fake_send_enrollment_decision = mock.patch(
            "course.enrollment.send_enrollment_decision")
        self.mock_send_enrollment_decision = fake_send_enrollment_decision.start()
        self.addCleanup(fake_send_enrollment_decision.stop)

    def test_approve_new(self):
        user = factories.UserFactory()
        status = p_status.active
        roles = [
            factories.ParticipationRoleFactory(course=self.course, identifier="1"),
            factories.ParticipationRoleFactory(course=self.course, identifier="2")]
        request = mock.MagicMock()

        participation = enrollment.handle_enrollment_request(
            self.course, user, status, roles, request=request)

        self.assertEqual(participation.user, user)
        self.assertEqual(participation.status, status)
        self.assertSetEqual(
            set([role for role in participation.roles.all()]), set(roles))
        self.assertEqual(self.mock_send_enrollment_decision.call_count, 1)
        self.mock_send_enrollment_decision.assert_called_with(
            participation, True, request)

    def test_approve_new_none_roles(self):
        user = factories.UserFactory()
        status = p_status.active
        roles = None
        request = mock.MagicMock()

        participation = enrollment.handle_enrollment_request(
            self.course, user, status, roles, request=request)

        self.assertEqual(participation.user, user)
        self.assertEqual(participation.status, status)
        self.assertSetEqual(
            set([role for role in participation.roles.all()]), set())
        self.assertEqual(self.mock_send_enrollment_decision.call_count, 1)
        self.mock_send_enrollment_decision.assert_called_with(
            participation, True, request)

    def test_deny_new(self):
        user = factories.UserFactory()
        status = p_status.denied
        roles = [
            factories.ParticipationRoleFactory(course=self.course, identifier="3"),
            factories.ParticipationRoleFactory(course=self.course, identifier="4")]
        request = mock.MagicMock()

        participation = enrollment.handle_enrollment_request(
            self.course, user, status, roles, request=request)

        self.assertEqual(participation.user, user)
        self.assertEqual(participation.status, status)
        self.assertSetEqual(
            set([role for role in participation.roles.all()]), set(roles))
        self.assertEqual(self.mock_send_enrollment_decision.call_count, 1)
        self.mock_send_enrollment_decision.assert_called_with(
            participation, False, request)

    def test_approve_requested(self):
        user = factories.UserFactory()
        request_participation = factories.ParticipationFactory(
            course=self.course, user=user, status=p_status.requested,
        )
        status = p_status.active
        roles = [
            factories.ParticipationRoleFactory(course=self.course, identifier="1"),
            factories.ParticipationRoleFactory(course=self.course, identifier="2")]
        request = mock.MagicMock()

        participation = enrollment.handle_enrollment_request(
            self.course, user, status, roles, request=request)

        self.assertEqual(participation.user, user)
        self.assertEqual(participation.status, status)
        self.assertSetEqual(
            set([role for role in participation.roles.all()]),
            set([role for role in request_participation.roles.all()]))
        self.assertEqual(self.mock_send_enrollment_decision.call_count, 1)
        self.mock_send_enrollment_decision.assert_called_with(
            participation, True, request)

    def test_deny_requested(self):
        user = factories.UserFactory()
        request_participation = factories.ParticipationFactory(
            course=self.course, user=user, status=p_status.requested,
        )
        status = p_status.denied
        roles = [
            factories.ParticipationRoleFactory(course=self.course, identifier="1"),
            factories.ParticipationRoleFactory(course=self.course, identifier="2")]
        request = mock.MagicMock()

        participation = enrollment.handle_enrollment_request(
            self.course, user, status, roles, request=request)

        self.assertEqual(participation.user, user)
        self.assertEqual(participation.status, status)
        self.assertSetEqual(
            set([role for role in participation.roles.all()]),
            set([role for role in request_participation.roles.all()]))
        self.assertEqual(self.mock_send_enrollment_decision.call_count, 1)
        self.mock_send_enrollment_decision.assert_called_with(
            participation, False, request)


class SendEnrollmentDecisionTest(SingleCourseTestMixin, TestCase):
    # test enrollment.send_enrollment_decision
    def test_request_none(self):
        participation = factories.ParticipationFactory()
        enrollment.send_enrollment_decision(participation, True, None)
        self.assertEqual(len(mail.outbox), 1)


class EnrollmentTestBaseMixin(SingleCourseTestMixin,
                              FallBackStorageMessageTestMixin):

    @classmethod
    def setUpTestData(cls):  # noqa
        super(EnrollmentTestBaseMixin, cls).setUpTestData()
        (cls.non_ptcp_active_user1, cls.non_ptcp_active_user2) = (
            factories.UserFactory.create_batch(
                size=2))
        (cls.non_ptcp_unconfirmed_user1, cls.non_ptcp_unconfirmed_user2) = (
            factories.UserFactory.create_batch(
                size=2, status=u_status.unconfirmed))

    @property
    def enroll_request_url(self):
        return reverse("relate-enroll", args=[self.course.identifier])

    @classmethod
    def get_participation_edit_url(cls, participation_id):
        return reverse("relate-edit_participation",
                       args=[cls.course.identifier, participation_id])

    def get_participation_count_by_status(self, status):
        return Participation.objects.filter(
            course__identifier=self.course.identifier,
            status=status
        ).count()

    @property
    def student_role_post_data(self):
        role, _ = (ParticipationRole.objects.get_or_create(
            course=self.course, identifier="student"))
        return [str(role.pk)]


class EnrollmentDecisionTestMixin(LocmemBackendTestsMixin, EnrollmentTestBaseMixin):
    courses_attributes_extra_list = [{"enrollment_approval_required": True}]

    @classmethod
    def setUpTestData(cls):  # noqa
        super(EnrollmentDecisionTestMixin, cls).setUpTestData()
        my_participation = cls.create_participation(
            cls.course, cls.non_ptcp_active_user1,
            status=p_status.requested)
        time_factor = [str(my_participation.time_factor)]
        roles = [str(r.pk) for r in my_participation.roles.all()]
        notes = [str(my_participation.notes)]

        cls.my_participation_edit_url = (
            cls.get_participation_edit_url(my_participation.pk))

        form_data = {"time_factor": time_factor,
                     "roles": roles, "notes": notes}
        cls.approve_post_data = {"approve": [""]}
        cls.approve_post_data.update(form_data)
        cls.deny_post_data = {"deny": [""]}
        cls.deny_post_data.update(form_data)
        cls.drop_post_data = {"drop": [""]}
        cls.drop_post_data.update(form_data)


class EnrollmentDecisionTest(EnrollmentDecisionTestMixin, TestCase):
    courses_attributes_extra_list = [{"enrollment_approval_required": True}]

    @property
    def add_new_url(self):
        return self.get_participation_edit_url(-1)

    def test_edit_participation_view_enroll_decision_approve(self):
        self.assertEqual(
            self.get_participation_count_by_status(p_status.requested),
            1)
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.post(self.my_participation_edit_url,
                               self.approve_post_data)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.requested),
            0)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_SUCCESSFULLY_ENROLLED_TEXT])
        self.assertResponseMessageLevelsEqual(resp, [messages.SUCCESS])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.requested),
            0)

    def test_edit_participation_view_enroll_decision_approve_no_permission1(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.post(self.my_participation_edit_url,
                               self.approve_post_data)

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.requested),
            1)

    def test_edit_participation_view_enroll_decision_approve_no_permission2(self):
        with self.temporarily_switch_to_user(self.non_ptcp_active_user1):
            resp = self.c.post(self.my_participation_edit_url,
                               self.approve_post_data)

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.requested),
            1)

    def test_edit_participation_view_enroll_decision_deny(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.post(self.my_participation_edit_url, self.deny_post_data)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.requested),
            0)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_ENROLLMENT_DENIED_TEXT])
        self.assertResponseMessageLevelsEqual(resp, [messages.SUCCESS])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.requested),
            0)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.denied),
            1)

    def test_edit_participation_view_enroll_decision_drop(self):
        self.create_participation(self.course, self.non_ptcp_unconfirmed_user1,
                                  status=p_status.active)
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.post(self.my_participation_edit_url, self.drop_post_data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.dropped),
            1)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_ENROLLMENT_DROPPED_TEXT])
        self.assertResponseMessageLevelsEqual(resp, [messages.SUCCESS])
        self.assertEqual(len(mail.outbox), 0)

    def test_edit_participation_view_add_new_unconfirmed_user(self):
        self.c.force_login(self.instructor_participation.user)
        resp = self.c.get(self.add_new_url)
        self.assertTrue(resp.status_code, 200)

        if self.non_ptcp_unconfirmed_user1.status != u_status.unconfirmed:
            self.non_ptcp_unconfirmed_user1.status = u_status.unconfirmed
            self.non_ptcp_unconfirmed_user1.save()

        expected_active_user_count = (
            get_user_model()
            .objects.filter(status=u_status.unconfirmed).count())

        expected_active_participation_count = (
            self.get_participation_count_by_status(p_status.active))

        form_data = {"user": [str(self.non_ptcp_unconfirmed_user1.pk)],
                     "time_factor": 1,
                     "roles": self.student_role_post_data, "notes": [""],
                     "add_new": True
                     }
        add_post_data = {"submit": [""]}
        add_post_data.update(form_data)
        resp = self.c.post(self.add_new_url, add_post_data, follow=True)
        self.assertFormError(resp, 'form', 'user',
                             VALIDATION_ERROR_USER_NOT_CONFIRMED)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.active),
            expected_active_participation_count)

        self.assertEqual(
            get_user_model()
            .objects.filter(status=u_status.unconfirmed).count(),
            expected_active_user_count)
        self.assertResponseMessagesCount(resp, 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_edit_participation_view_add_new_active_user(self):
        self.c.force_login(self.instructor_participation.user)
        resp = self.c.get(self.add_new_url)
        self.assertTrue(resp.status_code, 200)

        if self.non_ptcp_unconfirmed_user2.status != u_status.active:
            self.non_ptcp_unconfirmed_user2.status = u_status.active
            self.non_ptcp_unconfirmed_user2.save()

        expected_active_user_count = (
            get_user_model()
            .objects.filter(status=u_status.unconfirmed).count()
        )

        expected_active_participation_count = (
            self.get_participation_count_by_status(p_status.active) + 1
        )

        form_data = {"user": [str(self.non_ptcp_unconfirmed_user2.pk)],
                     "time_factor": 1,
                     "roles": self.student_role_post_data, "notes": [""],
                     "add_new": True
                     }
        add_post_data = {"submit": [""]}
        add_post_data.update(form_data)
        resp = self.c.post(self.add_new_url, add_post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.active),
            expected_active_participation_count)

        self.assertEqual(
            get_user_model()
            .objects.filter(status=u_status.unconfirmed).count(),
            expected_active_user_count)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_PARTICIPATION_CHANGE_SAVED_TEXT])
        self.assertResponseMessageLevelsEqual(
            resp, [messages.SUCCESS])
        self.assertResponseMessagesCount(resp, 1)
        self.assertEqual(len(mail.outbox), 0)

    def test_edit_participation_view_add_new_invalid_choice(self):
        form_data = {"user": [str(self.student_participation.user.pk)],
                     "time_factor": 0.5,
                     "roles": self.student_role_post_data, "notes": [""],
                     "add_new": True
                     }
        add_post_data = {"submit": [""]}
        add_post_data.update(form_data)
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.post(self.add_new_url, add_post_data, follow=True)

        from django.forms.models import ModelChoiceField
        self.assertFormError(
            resp, 'form', 'user',
            ModelChoiceField.default_error_messages['invalid_choice'])

    def test_edit_participation_view_enroll_decision_deny_no_permission1(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.post(self.my_participation_edit_url, self.deny_post_data)

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.requested),
            1)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.denied),
            0)

    def test_edit_participation_view_enroll_decision_deny_no_permission2(self):
        with self.temporarily_switch_to_user(self.non_ptcp_active_user1):
            resp = self.c.post(self.my_participation_edit_url, self.deny_post_data)

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.requested),
            1)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.denied),
            0)


class EnrollmentPreapprovalTestMixin(LocmemBackendTestsMixin,
                                     EnrollmentTestBaseMixin):

    @classmethod
    def setUpTestData(cls):  # noqa
        super(EnrollmentPreapprovalTestMixin, cls).setUpTestData()
        cls.non_ptcp_active_user1.institutional_id_verified = True
        cls.non_ptcp_active_user1.save()
        cls.non_ptcp_active_user2.institutional_id_verified = False
        cls.non_ptcp_active_user2.save()

    @property
    def preapprove_data_emails(self):
        preapproved_user = [self.non_ptcp_active_user1,
                            self.non_ptcp_active_user2]
        preapproved_data = [u.email for u in preapproved_user]
        return preapproved_data

    @property
    def preapprove_data_institutional_ids(self):
        preapproved_user = [self.non_ptcp_active_user1,
                            self.non_ptcp_active_user2,
                            self.non_ptcp_unconfirmed_user1]
        preapproved_data = [u.institutional_id for u in preapproved_user]
        return preapproved_data

    @property
    def preapproval_url(self):
        return reverse("relate-create_preapprovals",
                            args=[self.course.identifier])

    @property
    def default_preapprove_role(self):
        role, _ = (ParticipationRole.objects.get_or_create(
            course=self.course, identifier="student"))
        return [str(role.pk)]

    def post_preapprovel(self, preapproval_type, preapproval_data=None,
                         force_loggin_instructor=True):
        if preapproval_data is None:
            if preapproval_type == "email":
                preapproval_data = self.preapprove_data_emails
            elif preapproval_type == "institutional_id":
                preapproval_data = self.preapprove_data_institutional_ids

        assert preapproval_data is not None
        assert isinstance(preapproval_data, list)

        data = {
            "preapproval_type": [preapproval_type],
            "preapproval_data": ["\n".join(preapproval_data)],
            "roles": self.student_role_post_data,
            "submit": [""]
        }
        if not force_loggin_instructor:
            approver = self.get_logged_in_user()
        else:
            approver = self.instructor_participation.user
        with self.temporarily_switch_to_user(approver):
            return self.c.post(self.preapproval_url, data, follow=True)

    def get_preapproval_count(self):
        return ParticipationPreapproval.objects.all().count()


class EnrollmentPreapprovalTest(EnrollmentPreapprovalTestMixin, TestCase):
    courses_attributes_extra_list = [{
        "enrollment_approval_required": True,
        "preapproval_require_verified_inst_id": True}]

    def test_preapproval_url_get(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(self.preapproval_url)

        self.assertTrue(resp.status_code, 200)

    def test_preapproval_create_email_type(self):
        resp = self.post_preapprovel(
            "email",
            self.preapprove_data_emails)
        self.assertEqual(
            self.get_preapproval_count(), len(self.preapprove_data_emails))
        self.assertResponseMessagesEqual(
            resp,
            [MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN
             % {
                 'n_created': len(self.preapprove_data_emails),
                 'n_exist': 0,
                 'n_requested_approved': 0
             }]
        )

        # repost same data
        resp = self.post_preapprovel(
            "email",
            self.preapprove_data_emails)
        self.assertEqual(
            self.get_preapproval_count(), len(self.preapprove_data_emails))
        self.assertResponseMessagesEqual(
            resp,
            [MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN
             % {
                 'n_created': 0,
                 'n_exist': len(self.preapprove_data_emails),
                 'n_requested_approved': 0
             }]
        )

    def test_preapproval_create_institutional_id_type(self):
        resp = self.post_preapprovel(
            "institutional_id",
            self.preapprove_data_institutional_ids)
        self.assertEqual(
            self.get_preapproval_count(),
            len(self.preapprove_data_institutional_ids))
        self.assertResponseMessagesEqual(
            resp,
            [MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN
             % {
                 'n_created': len(self.preapprove_data_institutional_ids),
                 'n_exist': 0,
                 'n_requested_approved': 0
             }]
        )

        # repost same data
        resp = self.post_preapprovel(
            "institutional_id",
            self.preapprove_data_institutional_ids)
        self.assertEqual(
            self.get_preapproval_count(),
            len(self.preapprove_data_institutional_ids))
        self.assertResponseMessagesEqual(
            resp,
            [MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN
             % {
                 'n_created': 0,
                 'n_exist': len(self.preapprove_data_institutional_ids),
                 'n_requested_approved': 0
             }]
        )

    def test_preapproval_create_permission_error(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(self.preapproval_url)
            self.assertEqual(resp.status_code, 403)
            resp = self.post_preapprovel(
                "email",
                self.preapprove_data_emails,
                force_loggin_instructor=False
            )
            self.assertEqual(
                self.get_preapproval_count(), 0)
            self.assertEqual(resp.status_code, 403)

    def test_preapproval_email_type_approve_pendings(self):
        enroll_request_users = [self.non_ptcp_active_user1]
        for u in enroll_request_users:
            with self.temporarily_switch_to_user(u):
                self.c.post(self.enroll_request_url, follow=True)

        self.flush_mailbox()
        expected_participation_count = (
            self.get_participation_count_by_status(p_status.active) + 1)
        resp = self.post_preapprovel(
            "email",
            self.preapprove_data_emails)
        self.assertEqual(
            self.get_participation_count_by_status(
                p_status.active), expected_participation_count)

        self.assertResponseMessagesEqual(
            resp,
            [MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN
             % {
                 'n_created': len(self.preapprove_data_emails),
                 'n_exist': 0,
                 'n_requested_approved': len(enroll_request_users)
             }]
        )
        self.assertEqual(
            len([m.to for m in mail.outbox]), len(enroll_request_users))

    def test_preapproval_inst_id_type_approve_pending_require_id_verified(self):
        assert self.course.preapproval_require_verified_inst_id is True
        enroll_request_users = [
            self.non_ptcp_active_user1, self.non_ptcp_active_user2]
        for u in enroll_request_users:
            with self.temporarily_switch_to_user(u):
                self.c.post(self.enroll_request_url, follow=True)

        self.flush_mailbox()
        n_expected_newly_enrolled_users = (
            len([u for u in enroll_request_users if u.institutional_id_verified]))
        expected_participation_count = (
            self.get_participation_count_by_status(p_status.active)
            + n_expected_newly_enrolled_users
        )
        resp = self.post_preapprovel(
            "institutional_id",
            self.preapprove_data_institutional_ids)
        self.assertEqual(
            self.get_participation_count_by_status(
                p_status.active), expected_participation_count)

        self.assertResponseMessagesEqual(
            resp,
            [MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN
             % {
                 'n_created': len(self.preapprove_data_institutional_ids),
                 'n_exist': 0,
                 'n_requested_approved': n_expected_newly_enrolled_users
             }]
        )
        self.assertEqual(
            len([m.to for m in mail.outbox]), n_expected_newly_enrolled_users)


class EnrollmentPreapprovalInstIdNotRequireVerifiedTest(
                                        EnrollmentPreapprovalTestMixin, TestCase):

    courses_attributes_extra_list = [{
        "enrollment_approval_required": True,
        "preapproval_require_verified_inst_id": False}]

    def test_preapproval_inst_id_type_approve_pending_not_require_id_verified(self):
        enroll_request_users = [
            self.non_ptcp_active_user1, self.non_ptcp_active_user2]
        for u in enroll_request_users:
            with self.temporarily_switch_to_user(u):
                self.c.post(self.enroll_request_url, follow=True)

        self.flush_mailbox()
        n_expected_newly_enrolled_users = len(enroll_request_users)
        expected_participation_count = (
            self.get_participation_count_by_status(p_status.active)
            + n_expected_newly_enrolled_users
        )
        resp = self.post_preapprovel(
            "institutional_id",
            self.preapprove_data_institutional_ids)
        self.assertEqual(
            self.get_participation_count_by_status(
                p_status.active), expected_participation_count)

        self.assertResponseMessagesEqual(
            resp,
            [MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN
             % {
                 'n_created': len(self.preapprove_data_institutional_ids),
                 'n_exist': 0,
                 'n_requested_approved': n_expected_newly_enrolled_users
             }]
        )

        self.assertEqual(
            len([m.to for m in mail.outbox]), n_expected_newly_enrolled_users)


class EnrollmentEmailConnectionsTestMixin(LocmemBackendTestsMixin):
    #  Ensure request/decision mail will be sent with/without EmailConnection
    # settings. https://github.com/inducer/relate/pull/366
    courses_attributes_extra_list = [{"enrollment_approval_required": True}]

    email_connections = {
        "enroll": {
            'host': 'smtp.gmail.com',
            'username': 'blah@blah.com',
            'password': 'password',
            'port': 587,
            'use_tls': True,
        },
    }

    email_connections_none = {}
    enrollment_email_from = "enroll@example.com"
    robot_email_from = "robot@example.com"


class EnrollmentRequestEmailConnectionsTest(
            EnrollmentEmailConnectionsTestMixin, EnrollmentTestBaseMixin, TestCase):

    def test_email_with_email_connections1(self):
        # with EMAIL_CONNECTIONS and ENROLLMENT_EMAIL_FROM configured
        with self.settings(
                EMAIL_CONNECTIONS=self.email_connections,
                ROBOT_EMAIL_FROM=self.robot_email_from,
                ENROLLMENT_EMAIL_FROM=self.enrollment_email_from):

            expected_from_email = settings.ENROLLMENT_EMAIL_FROM
            with self.temporarily_switch_to_user(self.non_ptcp_active_user1):
                self.c.post(self.enroll_request_url, follow=True)

            msg = mail.outbox[0]
            self.assertEqual(msg.from_email, expected_from_email)

    def test_email_with_email_connections3(self):
        # with neither EMAIL_CONNECTIONS nor ENROLLMENT_EMAIL_FROM configured
        with self.settings(
                EMAIL_CONNECTIONS=self.email_connections,
                ROBOT_EMAIL_FROM=self.robot_email_from):
            if hasattr(settings, ENROLLMENT_EMAIL_FROM):
                del settings.ENROLLMENT_EMAIL_FROM

            expected_from_email = settings.ROBOT_EMAIL_FROM

            with self.temporarily_switch_to_user(self.non_ptcp_active_user1):
                self.c.post(self.enroll_request_url, follow=True)

            msg = mail.outbox[0]
            self.assertEqual(msg.from_email, expected_from_email)


class EnrollmentDecisionEmailConnectionsTest(
        EnrollmentEmailConnectionsTestMixin, EnrollmentDecisionTestMixin, TestCase):

    # {{{ with EMAIL_CONNECTIONS and ENROLLMENT_EMAIL_FROM configured
    def test_email_with_email_connections1(self):
        with self.settings(
                RELATE_EMAIL_SMTP_ALLOW_NONAUTHORIZED_SENDER=False,
                EMAIL_CONNECTIONS=self.email_connections,
                ROBOT_EMAIL_FROM=self.robot_email_from,
                ENROLLMENT_EMAIL_FROM=self.enrollment_email_from):

            expected_from_email = settings.ENROLLMENT_EMAIL_FROM

            with self.temporarily_switch_to_user(
                    self.instructor_participation.user):
                self.c.post(self.my_participation_edit_url, self.approve_post_data)

            msg = mail.outbox[0]
            self.assertEqual(msg.from_email, expected_from_email)

    def test_email_with_email_connections2(self):
        with self.settings(
                RELATE_EMAIL_SMTP_ALLOW_NONAUTHORIZED_SENDER=True,
                EMAIL_CONNECTIONS=self.email_connections,
                ROBOT_EMAIL_FROM=self.robot_email_from,
                ENROLLMENT_EMAIL_FROM=self.enrollment_email_from):

            expected_from_email = self.course.from_email

            with self.temporarily_switch_to_user(
                    self.instructor_participation.user):
                self.c.post(self.my_participation_edit_url, self.approve_post_data)

            msg = mail.outbox[0]
            self.assertEqual(msg.from_email, expected_from_email)
    # }}}

    # {{{ with neither EMAIL_CONNECTIONS nor ENROLLMENT_EMAIL_FROM configured
    def test_email_with_email_connections3(self):
        with self.settings(
                RELATE_EMAIL_SMTP_ALLOW_NONAUTHORIZED_SENDER=False,
                ROBOT_EMAIL_FROM=self.robot_email_from):
            if hasattr(settings, EMAIL_CONNECTIONS):
                del settings.EMAIL_CONNECTIONS
            if hasattr(settings, ENROLLMENT_EMAIL_FROM):
                del settings.ENROLLMENT_EMAIL_FROM

            expected_from_email = settings.ROBOT_EMAIL_FROM

            with self.temporarily_switch_to_user(
                    self.instructor_participation.user):
                self.c.post(self.my_participation_edit_url, self.approve_post_data)

            msg = mail.outbox[0]
            self.assertEqual(msg.from_email, expected_from_email)

    def test_email_with_email_connections4(self):
        with self.settings(
                RELATE_EMAIL_SMTP_ALLOW_NONAUTHORIZED_SENDER=True,
                ROBOT_EMAIL_FROM=self.robot_email_from):
            if hasattr(settings, EMAIL_CONNECTIONS):
                del settings.EMAIL_CONNECTIONS
            if hasattr(settings, ENROLLMENT_EMAIL_FROM):
                del settings.ENROLLMENT_EMAIL_FROM

            expected_from_email = self.course.from_email

            with self.temporarily_switch_to_user(
                    self.instructor_participation.user):
                self.c.post(self.my_participation_edit_url, self.approve_post_data)
            msg = mail.outbox[0]
            self.assertEqual(msg.from_email, expected_from_email)
    # }}}


class ParticipationQueryFormTest(unittest.TestCase):
    def setUp(self):
        self.course = factories.CourseFactory()

    def test_form_valid(self):
        data = {
            "queries": "id:1234",
            "op": "apply_tag",
            "tag": "hello"}

        form = enrollment.ParticipationQueryForm(data=data)
        self.assertTrue(form.is_valid())

    def test_form_valid_no_tag(self):
        data = {
            "queries": "id:1234",
            "op": "drop"}

        form = enrollment.ParticipationQueryForm(data=data)
        self.assertTrue(form.is_valid())

    def test_form_tag_invalid(self):
        data = {
            "queries": "id:1234",
            "op": "apply_tag",
            "tag": "~hello~"}

        form = enrollment.ParticipationQueryForm(data=data)
        self.assertIn("Name contains invalid characters.", form.errors["tag"])

# vim: foldmethod=marker
