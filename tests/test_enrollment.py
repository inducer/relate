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

import unittest
import pytest
from random import randint
from django.test import TestCase, RequestFactory
from django.conf import settings
from django.test.utils import override_settings  # noqa
from django.core import mail
from django.contrib.auth import get_user_model
from django.urls import reverse

from relate.utils import string_concat

from course import constants
from course import enrollment
from course.models import (
    Participation, ParticipationRole, ParticipationPreapproval, ParticipationTag)
from course.constants import (
    participation_status as p_status, user_status as u_status)

from tests.base_test_mixins import (
    CoursesTestMixinBase, SingleCourseTestMixin,
    SingleCoursePageTestMixin, MockAddMessageMixing)
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


def get_not_empty_count_from_list(lst):
    return len([data for data in lst if data.strip()])


class EnrollmentTestMixin(MockAddMessageMixing, CoursesTestMixinBase):

    @classmethod
    def setUpTestData(cls):  # noqa
        super(EnrollmentTestMixin, cls).setUpTestData()
        cls.course = factories.CourseFactory()

    def setUp(self):
        super(EnrollmentTestMixin, self).setUp()
        self.course.refresh_from_db()

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

    @ classmethod
    def get_participation_tag_list_url(cls):
        return reverse("relate-view_participation_tags",
                       args=[cls.course.identifier])

    @classmethod
    def get_participation_tag_edit_url(cls, ptag_id):
        return reverse("relate-edit_participation_tag",
                       args=[cls.course.identifier, ptag_id])

    @classmethod
    def get_participation_tag_delete_url(cls, ptag_id):
        return reverse("relate-delete_participation_tag",
                       args=[cls.course.identifier, ptag_id])

    @ classmethod
    def get_participation_role_list_url(cls):
        return reverse("relate-view_participation_roles",
                       args=[cls.course.identifier])

    @classmethod
    def get_participation_role_edit_url(cls, prole_id):
        return reverse("relate-edit_participation_role",
                       args=[cls.course.identifier, prole_id])

    @classmethod
    def get_participation_role_delete_url(cls, prole_id):
        return reverse("relate-delete_participation_role",
                       args=[cls.course.identifier, prole_id])

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

    @property
    def preapproval_url(self):
        return reverse("relate-create_preapprovals",
                            args=[self.course.identifier])

    @property
    def default_preapprove_role(self):
        role, _ = (ParticipationRole.objects.get_or_create(
            course=self.course, identifier="student"))
        return [str(role.pk)]

    def get_preapproval_count(self):
        return ParticipationPreapproval.objects.all().count()


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
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(MESSAGE_ENROLL_REQUEST_ALREADY_PENDING_TEXT)
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
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(MESSAGE_ENROLL_DENIED_NOT_ALLOWED_TEXT)
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
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(MESSAGE_ENROLL_DROPPED_NOT_ALLOWED_TEXT)
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
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(MESSAGE_CANNOT_REENROLL_TEXT)
        self.assertParticiaptionStatusCallCount([1, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 0)

    def test_not_accepts_enrollment(self):
        self.update_course(accepts_enrollment=False)
        user = factories.UserFactory()

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(MESSAGE_NOT_ACCEPTING_ENROLLMENTS_TEXT)
        self.assertParticiaptionStatusCallCount([0, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 0)

    def test_not_post_request(self):
        user = factories.UserFactory()
        with self.temporarily_switch_to_user(user):
            resp = self.c.get(self.enroll_request_url)
            self.assertRedirects(
                resp, self.course_page_url, fetch_redirect_response=False)
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith(
                MESSAGE_ENROLL_ONLY_ACCEPT_POST_REQUEST_TEXT)
        self.assertParticiaptionStatusCallCount([0, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 0)

    def test_user_not_active(self):
        for status in dict(constants.USER_STATUS_CHOICES).keys():
            if status != u_status.active:
                with self.subTest(user_status=status):
                    user = factories.UserFactory(status=status)
                    with self.temporarily_switch_to_user(user):
                        resp = self.c.post(self.enroll_request_url)
                    self.assertRedirects(
                        resp, self.course_page_url, fetch_redirect_response=False)
                    self.assertAddMessageCallCount(1)
                    self.assertAddMessageCalledWith(
                        MESSAGE_EMAIL_NOT_CONFIRMED_TEXT)
        self.assertParticiaptionStatusCallCount([0, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 0)

    def test_no_restrictions(self):
        user = factories.UserFactory()
        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(MESSAGE_SUCCESSFULLY_ENROLLED_TEXT)

        self.assertParticiaptionStatusCallCount([1, 0, 0, 0])

    def test_no_restrictions_user_has_no_instid(self):
        user = factories.UserFactory(institutional_id=None)
        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(MESSAGE_SUCCESSFULLY_ENROLLED_TEXT)

        self.assertParticiaptionStatusCallCount([1, 0, 0, 0])

    def test_not_matching_preapproved_email(self):
        self.update_require_approval_course()
        user = factories.UserFactory()
        self.get_test_preapproval(email="blabla@com")

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(MESSAGE_ENROLLMENT_SENT_TEXT)
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
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(MESSAGE_SUCCESSFULLY_ENROLLED_TEXT)
        self.assertParticiaptionStatusCallCount([1, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 1)

    def test_course_not_require_inst_id_verified(self):
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
                self.assertAddMessageCallCount(1)
                self.assertAddMessageCalledWith(MESSAGE_SUCCESSFULLY_ENROLLED_TEXT)

        self.assertParticiaptionStatusCallCount([2, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 2)

    def test_course_require_inst_id_verified_user_inst_id_verified1(self):
        # matched
        self.update_require_approval_course(
            preapproval_require_verified_inst_id=True)

        user = factories.UserFactory(institutional_id_verified=True)
        self.get_test_preapproval(institutional_id=user.institutional_id)

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(MESSAGE_SUCCESSFULLY_ENROLLED_TEXT)
        self.assertParticiaptionStatusCallCount([1, 0, 0, 0])
        self.assertEqual(len(mail.outbox), 1)

    def test_course_require_inst_id_verified_user_inst_id_verified2(self):
        # not matched
        self.update_require_approval_course(
            preapproval_require_verified_inst_id=True)

        user = factories.UserFactory(institutional_id_verified=True)
        self.get_test_preapproval(institutional_id="not_exist_instid")

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(MESSAGE_ENROLLMENT_SENT_TEXT)
        self.assertEqual(len(mail.outbox), 1)
        self.assertParticiaptionStatusCallCount([0, 0, 0, 1])

    def test_preapprved_user_updated_inst_id_after_req_enrollment_roles_match(self):
        # Check assigned roles, testing issue #735
        self.update_require_approval_course(
            preapproval_require_verified_inst_id=True)

        user = factories.UserFactory()
        inst_id = user.institutional_id

        # Temporarily remove his/her inst_id
        user.institutional_id = None
        user.save()

        expected_role_identifier = "test_student"

        self.get_test_preapproval(
            institutional_id=inst_id, roles=[expected_role_identifier])

        with self.temporarily_switch_to_user(user):
            self.c.post(self.enroll_request_url)

        # Add back the inst_id
        user.institutional_id = inst_id
        user.institutional_id_verified = True
        user.save()

        user_participation = Participation.objects.get(user=user)
        self.assertIn(expected_role_identifier,
                      [role.identifier for role in user_participation.roles.all()])

    def test_course_require_inst_id_verified_user_inst_id_not_verified1(self):
        # thought matched
        self.update_require_approval_course(
            preapproval_require_verified_inst_id=True)

        user = factories.UserFactory(institutional_id_verified=False)
        self.get_test_preapproval(institutional_id=user.institutional_id)

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(MESSAGE_ENROLLMENT_SENT_TEXT)
        self.assertParticiaptionStatusCallCount([0, 0, 0, 1])
        self.assertEqual(len(mail.outbox), 1)

    def test_course_require_inst_id_verified_user_inst_id_not_verified2(self):
        # not matched
        self.update_require_approval_course(
            preapproval_require_verified_inst_id=True)

        user = factories.UserFactory(institutional_id_verified=False)
        self.get_test_preapproval(institutional_id="not_exist_instid")

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(MESSAGE_ENROLLMENT_SENT_TEXT)
        self.assertParticiaptionStatusCallCount([0, 0, 0, 1])
        self.assertEqual(len(mail.outbox), 1)

    def test_course_require_email_suffix_but_need_approval(self):
        self.update_require_approval_course(
            enrollment_required_email_suffix="@blabla.com")

        user = factories.UserFactory(email="abc@blabla.com")

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(MESSAGE_ENROLLMENT_SENT_TEXT)
        self.assertParticiaptionStatusCallCount([0, 0, 0, 1])
        self.assertEqual(len(mail.outbox), 1)

    def test_course_require_email_suffix_passed_without_at(self):
        # without @ in suffix config
        self.update_require_approval_course(
            enrollment_required_email_suffix="blabla.com")
        user = factories.UserFactory(email="abc@blabla.com")

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(MESSAGE_ENROLLMENT_SENT_TEXT)
        self.assertParticiaptionStatusCallCount([0, 0, 0, 1])
        self.assertEqual(len(mail.outbox), 1)

    def test_course_require_email_suffix_passed_without_at_pattern2(self):
        # without @ in suffix config
        self.update_require_approval_course(
            enrollment_required_email_suffix="blabla.com")
        user = factories.UserFactory(email="abc@edu.blabla.com")

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(MESSAGE_ENROLLMENT_SENT_TEXT)
        self.assertParticiaptionStatusCallCount([0, 0, 0, 1])
        self.assertEqual(len(mail.outbox), 1)

    def test_course_require_email_suffix_failed(self):
        required_suffix = "blabla.com"
        self.update_require_approval_course(
            enrollment_required_email_suffix=required_suffix)
        user = factories.UserFactory(email="abc@blabla.com.hk")

        with self.temporarily_switch_to_user(user):
            resp = self.c.post(self.enroll_request_url)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(
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
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith(MESSAGE_PARTICIPATION_ALREADY_EXIST_TEXT)

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


class EnrollmentTestBaseMixin(MockAddMessageMixing, SingleCourseTestMixin):

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
        cls.my_participation = cls.create_participation(
            cls.course, cls.non_ptcp_active_user1,
            status=p_status.requested)
        cls.my_participation_edit_url = (
            cls.get_participation_edit_url(cls.my_participation.pk))

    def get_edit_participation_form_data(self, op, **post_form_kwargs):
        time_factor = [str(self.my_participation.time_factor)]
        roles = [str(r.pk) for r in self.my_participation.roles.all()]
        notes = [str(self.my_participation.notes)]

        form_data = {"time_factor": time_factor,
                     "roles": roles, "notes": notes,
                     op: ""}
        form_data.update(post_form_kwargs)

        return form_data


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
                               self.get_edit_participation_form_data("approve"))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.requested),
            0)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(MESSAGE_SUCCESSFULLY_ENROLLED_TEXT)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.requested),
            0)

    def test_edit_participation_view_enroll_decision_approve_no_permission1(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.post(self.my_participation_edit_url,
                               self.get_edit_participation_form_data("approve"))

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.requested),
            1)

    def test_edit_participation_view_enroll_decision_approve_no_permission2(self):
        with self.temporarily_switch_to_user(self.non_ptcp_active_user1):
            resp = self.c.post(self.my_participation_edit_url,
                               self.get_edit_participation_form_data("approve"))

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.requested),
            1)

    def test_edit_participation_view_course_not_match(self):
        other_course_participation = factories.ParticipationFactory(
            course=factories.CourseFactory(identifier="another-course")
        )
        url = self.get_participation_edit_url(other_course_participation.pk)
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(url)
            self.assertEqual(resp.status_code, 400)

            resp = self.c.post(url, data={})
            self.assertEqual(resp.status_code, 400)

    def test_edit_participation_update_individual_permission(self):
        url = self.get_participation_edit_url(self.student_participation.pk)
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.post(
                url,
                self.get_edit_participation_form_data(
                    "submit", individual_permissions=[
                        "view_participant_masked_profile",
                        "view_hidden_course_page",
                    ]))
            self.assertEqual(resp.status_code, 200)
            self.assertFormErrorLoose(resp, None)
            self.student_participation.refresh_from_db()
            from course.constants import participation_permission as pperm
            self.assertTrue(
                self.student_participation.has_permission(
                    pperm.view_participant_masked_profile)
            )
            self.assertTrue(
                self.student_participation.has_permission(
                    pperm.view_hidden_course_page)
            )
            self.assertFalse(
                self.student_participation.has_permission(
                    pperm.edit_course)
            )

    def test_edit_participation_view_enroll_decision_deny(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.post(
                self.my_participation_edit_url,
                self.get_edit_participation_form_data("deny"))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.requested),
            0)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith([MESSAGE_ENROLLMENT_DENIED_TEXT])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.requested),
            0)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.denied),
            1)

    def test_edit_participation_view_unknown_post_op(self):
        post_data = self.get_edit_participation_form_data("approve").copy()
        del post_data["approve"]

        # add an unknown post operation
        post_data["unknown"] = ''

        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.post(
                self.my_participation_edit_url, data=post_data)

        self.assertEqual(resp.status_code, 200)
        self.assertFormErrorLoose(resp, None)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.requested),
            1)
        self.assertAddMessageCallCount(0)
        self.assertEqual(len(mail.outbox), 0)

    def test_edit_participation_view_enroll_decision_drop(self):
        self.create_participation(self.course, self.non_ptcp_unconfirmed_user1,
                                  status=p_status.active)
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.post(self.my_participation_edit_url,
                               self.get_edit_participation_form_data("drop"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.dropped),
            1)
        self.assertAddMessageCalledWith([MESSAGE_ENROLLMENT_DROPPED_TEXT])
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
        self.assertAddMessageCallCount(0)
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
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith([MESSAGE_PARTICIPATION_CHANGE_SAVED_TEXT])
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
            resp = self.c.post(
                self.my_participation_edit_url,
                self.get_edit_participation_form_data("deny"))

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
            resp = self.c.post(
                self.my_participation_edit_url,
                self.get_edit_participation_form_data("deny"))

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.requested),
            1)
        self.assertEqual(
            self.get_participation_count_by_status(p_status.denied),
            0)

    def test_edit_participation_view_save_integrity_error(self):
        with mock.patch(
                "course.enrollment.Participation.save"
        ) as mock_participation_save, mock.patch(
            "course.enrollment.EditParticipationForm.save"
        ) as mock_form_save:
            from django.db import IntegrityError
            mock_participation_save.side_effect = IntegrityError("my_error")
            mock_form_save.side_effect = IntegrityError("my_error")

            with self.temporarily_switch_to_user(
                    self.instructor_participation.user):
                resp = self.c.post(
                    self.my_participation_edit_url,
                    self.get_edit_participation_form_data("deny"))

            self.assertEqual(resp.status_code, 200)
            self.assertEqual(
                self.get_participation_count_by_status(p_status.requested),
                1)
            expected_error_msg = (
                "A data integrity issue was detected when saving "
                "this participation. Maybe a participation for "
                "this user already exists? (my_error)")
            self.assertAddMessageCalledWith([expected_error_msg])
            self.assertEqual(len(mail.outbox), 0)


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
        preapproved_data.insert(1, "  ")  # empty line
        preapproved_data.insert(0, "  ")  # empty line
        return preapproved_data

    @property
    def preapprove_data_institutional_ids(self):
        preapproved_user = [self.non_ptcp_active_user1,
                            self.non_ptcp_active_user2,
                            self.non_ptcp_unconfirmed_user1]
        preapproved_data = [u.institutional_id for u in preapproved_user]
        preapproved_data.insert(1, "  ")  # empty line
        preapproved_data.insert(0, "  ")  # empty line
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

    def post_preapproval(self, preapproval_type, preapproval_data=None,
                         force_login_instructor=True):
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
        if not force_login_instructor:
            approver = self.get_logged_in_user()
        else:
            approver = self.instructor_participation.user
        with self.temporarily_switch_to_user(approver):
            return self.c.post(self.preapproval_url, data, follow=True)

    def get_preapproval_count(self):
        return ParticipationPreapproval.objects.all().count()


class CreatePreapprovalsTest(EnrollmentTestMixin,
                             SingleCourseTestMixin, TestCase):
    # test enrollment.create_preapprovals
    @classmethod
    def setUpTestData(cls):  # noqa
        super(CreatePreapprovalsTest, cls).setUpTestData()
        cls.course.enrollment_approval_required = True
        cls.course.preapproval_require_verified_inst_id = True
        cls.course.save()

    def setUp(self):
        super(CreatePreapprovalsTest, self).setUp()
        fake_send_enrollment_decision = mock.patch(
            "course.enrollment.send_enrollment_decision")
        self.mock_send_enrollment_decision = (
            fake_send_enrollment_decision.start())
        self.addCleanup(fake_send_enrollment_decision.stop)

    def post_preapproval(
            self, preapproval_type, data, force_login_instructor=True):

        data = {
            "preapproval_type": [preapproval_type],
            "preapproval_data": data,
            "roles": self.student_role_post_data,
            "submit": [""]
        }
        if not force_login_instructor:
            approver = self.get_logged_in_user()
        else:
            approver = self.instructor_participation.user
        with self.temporarily_switch_to_user(approver):
            return self.c.post(self.preapproval_url, data, follow=True)

    def test_no_permission(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(self.preapproval_url)
            self.assertEqual(resp.status_code, 403)
            resp = self.c.post(self.preapproval_url, data={})
            self.assertEqual(resp.status_code, 403)

    def test_login_required(self):
        with self.temporarily_switch_to_user(None):
            resp = self.c.get(self.preapproval_url)
            self.assertEqual(resp.status_code, 302)
            resp = self.c.post(self.preapproval_url, data={})
            self.assertEqual(resp.status_code, 302)

    def test_get(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(self.preapproval_url)
            self.assertEqual(resp.status_code, 200)

    def test_post_form_not_valid(self):
        resp = self.post_preapproval("email", {})
        self.assertEqual(resp.status_code, 200)

        resp = self.post_preapproval("some_type", {})
        self.assertEqual(resp.status_code, 200)

        resp = self.post_preapproval("institutional_id", {})
        self.assertEqual(resp.status_code, 200)

    def test_create_preapproval_email(self):
        approval_data = "abc@foo.com\n  \n cde@foo.com\n  \n"
        resp = self.post_preapproval(
            "email",
            approval_data)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(
            self.get_preapproval_count(), 2)
        self.assertAddMessageCalledWith(
            [MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN
             % {
                 'n_created': 2,
                 'n_exist': 0,
                 'n_requested_approved': 0
             }])

        # repost same data
        resp = self.post_preapproval(
            "email",
            approval_data)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(
            self.get_preapproval_count(), 2)
        self.assertAddMessageCalledWith(
            [MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN
             % {
                 'n_created': 0,
                 'n_exist': 2,
                 'n_requested_approved': 0
             }])

    def test_create_preapproval_email_handle_pendinng(self):
        user = factories.UserFactory()
        factories.ParticipationFactory(
            course=self.course, user=user, status=p_status.requested
        )
        approval_data = "%s\n  \n cde@foo.com\n  \n" % user.email.upper()
        resp = self.post_preapproval(
            "email",
            approval_data)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(
            self.get_preapproval_count(), 2)
        self.assertAddMessageCalledWith(
            [MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN
             % {
                 'n_created': 2,
                 'n_exist': 0,
                 'n_requested_approved': 1
             }])
        self.assertEqual(
            self.mock_send_enrollment_decision.call_count, 1)
        self.mock_send_enrollment_decision.reset_mock()

        # repost same data
        resp = self.post_preapproval(
            "email",
            approval_data)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(
            self.get_preapproval_count(), 2)
        self.assertAddMessageCalledWith(
            [MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN
             % {
                 'n_created': 0,
                 'n_exist': 2,
                 'n_requested_approved': 0
             }])
        self.assertEqual(
            self.mock_send_enrollment_decision.call_count, 0)

    def test_create_preapproval_inst_id(self):
        approval_data = "abc\n  \ncde \n  \n"
        resp = self.post_preapproval(
            "institutional_id",
            approval_data)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(
            self.get_preapproval_count(), 2)
        self.assertAddMessageCalledWith(
            [MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN
             % {
                 'n_created': 2,
                 'n_exist': 0,
                 'n_requested_approved': 0
             }])

        # repost same data
        resp = self.post_preapproval(
            "institutional_id",
            approval_data)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(
            self.get_preapproval_count(), 2)
        self.assertAddMessageCalledWith(
            [MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN
             % {
                 'n_created': 0,
                 'n_exist': 2,
                 'n_requested_approved': 0
             }])

    def test_create_preapproval_inst_id_handle_pending_require_verified(self):
        self.course.preapproval_require_verified_inst_id = False
        self.course.save()
        user1 = factories.UserFactory(institutional_id_verified=True)
        user2 = factories.UserFactory(institutional_id_verified=False)
        factories.ParticipationFactory(
            course=self.course, user=user1, status=p_status.requested)
        factories.ParticipationFactory(
            course=self.course, user=user2, status=p_status.requested)
        approval_data = "%s\n  \ncde \n  %s\n" % (
            user1.institutional_id.upper(), user2.institutional_id)

        resp = self.post_preapproval(
            "institutional_id",
            approval_data)

        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)

        self.assertEqual(
            self.get_preapproval_count(), 3)

        self.assertAddMessageCalledWith(
            [MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN
             % {
                 'n_created': 3,
                 'n_exist': 0,
                 'n_requested_approved': 2
             }])

        self.assertEqual(
            self.mock_send_enrollment_decision.call_count, 2)
        self.mock_send_enrollment_decision.reset_mock()

        # repost same data
        resp = self.post_preapproval(
            "institutional_id",
            approval_data)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(
            self.get_preapproval_count(), 3)
        self.assertAddMessageCalledWith(
            [MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN
             % {
                 'n_created': 0,
                 'n_exist': 3,
                 'n_requested_approved': 0
             }])
        self.assertEqual(
            self.mock_send_enrollment_decision.call_count, 0)

    def test_create_preapproval_inst_id_handle_pending(self):
        user1 = factories.UserFactory(institutional_id_verified=True)
        user2 = factories.UserFactory(institutional_id_verified=False)
        factories.ParticipationFactory(
            course=self.course, user=user1, status=p_status.requested)
        factories.ParticipationFactory(
            course=self.course, user=user2, status=p_status.requested)
        approval_data = "%s\n  \ncde \n  %s\n" % (
            user1.institutional_id, user2.institutional_id)

        resp = self.post_preapproval(
            "institutional_id",
            approval_data)

        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)

        self.assertEqual(
            self.get_preapproval_count(), 3)

        self.assertAddMessageCalledWith(
            [MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN
             % {
                 'n_created': 3,
                 'n_exist': 0,
                 'n_requested_approved': 1
             }])
        self.assertEqual(
            self.mock_send_enrollment_decision.call_count, 1)
        self.mock_send_enrollment_decision.reset_mock()

        # repost same data
        resp = self.post_preapproval(
            "institutional_id",
            approval_data)
        self.assertRedirects(
            resp, self.course_page_url, fetch_redirect_response=False)
        self.assertEqual(
            self.get_preapproval_count(), 3)
        self.assertAddMessageCalledWith(
            [MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN
             % {
                 'n_created': 0,
                 'n_exist': 3,
                 'n_requested_approved': 0
             }])
        self.assertEqual(
            self.mock_send_enrollment_decision.call_count, 0)
        self.mock_send_enrollment_decision.reset_mock()

        # update_course
        self.course.preapproval_require_verified_inst_id = False
        self.course.save()

        # user2 is expected to be approved as active participation upon
        # course update.
        self.assertEqual(
            Participation.objects.get(user=user2).status, p_status.active)
        self.assertEqual(
            self.mock_send_enrollment_decision.call_count, 1)
        self.mock_send_enrollment_decision.reset_mock()


class EditParticipationFormTest(SingleCourseTestMixin, TestCase):
    # test enrollment.EditParticipationForm
    # (currently for cases not covered by other tests)
    # todo: full test

    def setUp(self):
        super(EditParticipationFormTest, self).setUp()
        rf = RequestFactory()
        self.request = rf.get(self.get_course_page_url())

    def get_pctx_by_participation(self, participation):
        self.request.user = participation.user

        from course.utils import CoursePageContext
        return CoursePageContext(self.request, self.course.identifier)

    def test_role_button_disabled(self):
        pctx = self.get_pctx_by_participation(self.ta_participation)
        form = enrollment.EditParticipationForm(
            add_new=False, pctx=pctx, instance=self.student_participation)
        self.assertTrue(form.fields["roles"].disabled)

    def test_role_button_not_disabled(self):
        pctx = self.get_pctx_by_participation(self.instructor_participation)
        form = enrollment.EditParticipationForm(
            add_new=False, pctx=pctx, instance=self.student_participation)
        self.assertFalse(form.fields["roles"].disabled)

    def test_drop_button_not_added_for_dropped_participation(self):
        dropped = factories.ParticipationFactory(
            course=self.course, status=p_status.dropped)

        pctx = self.get_pctx_by_participation(self.instructor_participation)
        form = enrollment.EditParticipationForm(
            add_new=False, pctx=pctx, instance=dropped)

        names, _ = self.get_form_submit_inputs(form)
        self.assertNotIn("drop", names)


class EnrollmentEmailConnectionsTestMixin(LocmemBackendTestsMixin):
    # Ensure request/decision mail will be sent with/without EmailConnection
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


# Todo: refactor email connections in all views
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
                self.c.post(
                    self.my_participation_edit_url,
                    self.get_edit_participation_form_data("approve"))

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
                self.c.post(
                    self.my_participation_edit_url,
                    self.get_edit_participation_form_data("approve"))

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
                self.c.post(
                    self.my_participation_edit_url,
                    self.get_edit_participation_form_data("approve"))

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
                self.c.post(self.my_participation_edit_url,
                            self.get_edit_participation_form_data("approve"))
            msg = mail.outbox[0]
            self.assertEqual(msg.from_email, expected_from_email)
    # }}}


@pytest.mark.django_db
class ParticipationQueryFormTest(unittest.TestCase):
    #test enrollment.ParticipationQueryForm
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


class QueryParticipationsTestMixin(MockAddMessageMixing, SingleCoursePageTestMixin):

    @property
    def query_participation_url(self):
        return self.get_course_view_url(
            "relate-query_participations", self.course.identifier)

    @classmethod
    def setup_participation_data(cls):
        p_list = [factories.ParticipationFactory(
            course=cls.course,
            status=p_status.requested,
            tags=list(factories.ParticipationTagFactory.create_batch(
                size=2, course=cls.course)))]

        p_list.extend(factories.ParticipationFactory.create_batch(
            size=3, course=cls.course,
            tags=list(factories.ParticipationTagFactory.create_batch(
                size=2, course=cls.course))))

        return p_list

    def post_query_participation(self, queries, op=None, tag=None, apply=False,
                                 force_login_instructor=True):
        form_data = {"queries": queries}
        form_data["op"] = op or "apply_tag"
        form_data["tag"] = tag or ""
        if apply:
            form_data["apply"] = ""
        else:
            form_data["submit"] = ""

        if not force_login_instructor:
            u = self.get_logged_in_user()
        else:
            u = self.instructor_participation.user
        with self.temporarily_switch_to_user(u):
            return self.c.post(self.query_participation_url, data=form_data)


class QueryParticipationsParseQueryTest(QueryParticipationsTestMixin, TestCase):
    # test enrollment.query_participations for parse query
    @classmethod
    def setUpTestData(cls):  # noqa
        super(QueryParticipationsParseQueryTest, cls).setUpTestData()

        # Participations are created here should not be modified
        cls.participations = cls.setup_participation_data()

    def test_no_query_permission(self):
        with self.temporarily_switch_to_user(self.participations[0].user):
            resp = self.c.get(self.query_participation_url)
            self.assertEqual(resp.status_code, 403)
            resp = self.c.post(self.query_participation_url, data={})
            self.assertEqual(resp.status_code, 403)

    def test_with_view_participant_masked_profile_permission(self):
        with self.temporarily_switch_to_user(self.ta_participation.user):
            resp = self.c.get(self.query_participation_url)
            self.assertEqual(resp.status_code, 200)
            resp = self.c.post(self.query_participation_url, data={})
            self.assertEqual(resp.status_code, 200)

        from course.constants import participation_permission as pperm
        from course.models import ParticipationPermission
        pp = ParticipationPermission(
            participation=self.ta_participation,
            permission=pperm.view_participant_masked_profile)
        pp.save()

        with self.temporarily_switch_to_user(self.ta_participation.user):
            resp = self.c.get(self.query_participation_url)
            self.assertEqual(resp.status_code, 403)
            resp = self.c.post(self.query_participation_url, data={})
            self.assertEqual(resp.status_code, 403)

    def test_user_id_equal(self):
        queries = "id:%d" % self.participations[0].user.id

        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "result", [self.participations[0]])

    def test_user_email_equal(self):
        queries = "email:%s" % self.participations[0].user.email

        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "result", [self.participations[0]])

    def test_user_email_contains(self):
        queries = "email-contains:test_factory_"

        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)
        result = resp.context["result"]
        self.assertSetEqual(set(result), set(self.participations))

    def test_username_equal(self):
        queries = "username:%s" % self.participations[0].user.username

        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "result", [self.participations[0]])

    def test_username_contains(self):
        queries = "username-contains:testuser_"

        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)
        result = resp.context["result"]
        self.assertSetEqual(set(result), set(self.participations))

    def test_inst_id_equal(self):
        queries = "institutional-id:%s" % (
            self.participations[0].user.institutional_id)

        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "result", [self.participations[0]])

    def test_inst_id_contains(self):
        queries = "institutional-id-contains:institutional_id"

        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)
        result = resp.context["result"]
        self.assertSetEqual(set(result), set(self.participations))

    def test_tagged(self):
        queries = "tagged:%s" % (
            self.participations[0].tags.all()[0].name)

        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "result", [self.participations[0]])

    def test_tagged2(self):
        queries = "tagged:%s" % (
            self.participations[1].tags.all()[0].name)

        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "result", self.participations[1:])

    def test_role(self):
        queries = "role:%s" % (
            self.participations[1].roles.all()[0].identifier)
        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)
        result = resp.context["result"]

        self.assertEqual(len(result), 5)

    def test_role_ta(self):
        queries = "role:teaching_assistant"
        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "result", [self.ta_participation])

    def test_status(self):
        queries = "status:requested"

        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "result", [self.participations[0]])

    def test_has_started_flow(self):
        with self.temporarily_switch_to_user(self.participations[1].user):
            self.start_flow(self.flow_id)
        with self.temporarily_switch_to_user(self.participations[2].user):
            self.start_flow(self.flow_id)

        queries = "has-started:%s" % self.flow_id

        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "result", [self.participations[1], self.participations[2]])

    def test_has_submitted_flow(self):
        with self.temporarily_switch_to_user(self.participations[1].user):
            self.start_flow(self.flow_id)
        with self.temporarily_switch_to_user(self.participations[2].user):
            self.start_flow(self.flow_id)
            self.end_flow()

        queries = "has-submitted:%s" % self.flow_id

        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "result", [self.participations[2]])

    def test_and(self):
        queries = "role:student and status:requested"
        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)

        self.assertResponseContextEqual(
            resp, "result", [self.participations[0]])

    def test_not(self):
        queries = "role:student not status:active"
        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)

        self.assertResponseContextEqual(
            resp, "result", [self.participations[0]])

    def test_or(self):
        queries = "id:%d or status:requested" % self.participations[0].user.id
        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)

        self.assertResponseContextEqual(
            resp, "result", [self.participations[0]])

    def test_parentheses(self):
        queries = "role:student and (email-contains:.com not status:active)"
        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)

        self.assertResponseContextEqual(
            resp, "result", [self.participations[0]])

    def test_multiple_line(self):
        queries = (
            "id:%s\n  \n  id:%s" % (
                self.participations[0].user.id, self.participations[2].user.id))

        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)

        self.assertResponseContextEqual(
            resp, "result", [self.participations[0], self.participations[2]])

    def test_input_not_valid(self):
        queries = "unknown:"
        resp = self.post_query_participation(queries)
        self.assertEqual(resp.status_code, 200)

        self.assertFormErrorLoose(resp, None)
        self.assertResponseContextEqual(
            resp, "result", None)

        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(
            "Error in line 1: InvalidTokenError: at index 0: ...unknown:...")

    # {{{ apply

    def test_apply_tag(self):
        p1 = factories.ParticipationFactory(
            course=self.course,
            user=factories.UserFactory(username="temp_user"))
        p2 = factories.ParticipationFactory(
            course=self.course,
            user=factories.UserFactory(username="temp_user2"))

        queries = "username:%s or username:%s" % (
            p1.user.username, p2.user.username)
        resp = self.post_query_participation(
            queries, apply=True, op="apply_tag", tag="temp_tag")
        self.assertEqual(resp.status_code, 200)

        p1.refresh_from_db()
        p2.refresh_from_db()
        self.assertEqual(p1.tags.all()[0].name, "temp_tag")
        self.assertEqual(p2.tags.all()[0].name, "temp_tag")
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(
            "Operation successful on 2 participations.")

    def test_remove_tag(self):
        to_remove_tag = "to_remove"
        p1 = factories.ParticipationFactory(
            course=self.course,
            user=factories.UserFactory(username="temp_user"),
            tags=[to_remove_tag, "abcd"]
        )
        p2 = factories.ParticipationFactory(
            course=self.course,
            user=factories.UserFactory(username="temp_user2"),
            tags=[to_remove_tag, "cdef"])

        queries = "username:%s or username:%s" % (
            p1.user.username, p2.user.username)
        resp = self.post_query_participation(
            queries, apply=True, op="remove_tag", tag=to_remove_tag)
        self.assertEqual(resp.status_code, 200)

        p1.refresh_from_db()
        p2.refresh_from_db()
        self.assertEqual(p1.tags.all()[0].name, "abcd")
        self.assertEqual(p2.tags.all()[0].name, "cdef")

        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(
            "Operation successful on 2 participations.")

    def test_drop(self):
        to_remove_tag = "to_remove"
        p1 = factories.ParticipationFactory(
            course=self.course,
            user=factories.UserFactory(username="temp_user"),
            tags=[to_remove_tag, "abcd"])
        p2 = factories.ParticipationFactory(
            course=self.course,
            user=factories.UserFactory(username="temp_user2"),
            tags=[to_remove_tag, "cdef"])

        queries = "tagged:%s" % to_remove_tag
        resp = self.post_query_participation(
            queries, apply=True, op="drop")
        self.assertEqual(resp.status_code, 200)

        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(
            "Operation successful on 2 participations.")

        p1.refresh_from_db()
        p2.refresh_from_db()
        self.assertEqual(p1.status, p_status.dropped)
        self.assertEqual(p2.status, p_status.dropped)

    # }}}


class ParticipationTagCRUDTest(
        SingleCourseTestMixin, EnrollmentTestMixin, TestCase):
    def setUp(self):
        super(ParticipationTagCRUDTest, self).setUp()
        self.c.force_login(self.instructor_participation.user)

    def get_default_edit_ptag_post_data(self, **kwargs):
        data = {"name": "a_tag"}
        data.update(kwargs)
        return data

    def get_default_delete_ptag_post_data(self, **kwargs):
        data = {}
        if not kwargs.pop("no_delete_in_post", None):
            data = {"delete": True}
        data.update(kwargs)
        return data

    @property
    def ptag_list_url(self):
        return self.get_participation_tag_list_url()

    def test_view_ptag_list_permission_denied(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(self.ptag_list_url)
            self.assertEqual(resp.status_code, 403)

    def test_view_ptag_list_success(self):
        n_tags = randint(2, 10)
        factories.ParticipationTagFactory.create_batch(
            size=n_tags, course=self.course)

        resp = self.c.get(self.ptag_list_url)
        self.assertEqual(resp.status_code, 200)

        self.assertResponseContextLengthEqual(
                resp, "participation_tags", n_tags)

    def test_edit_ptag_permission_denied(self):
        self.c.force_login(self.student_participation.user)

        # GET requests
        resp = self.c.get(self.get_participation_tag_edit_url(0))
        self.assertEqual(resp.status_code, 403)

        n_tags = randint(2, 10)
        ptags = factories.ParticipationTagFactory.create_batch(
            size=n_tags, course=self.course)

        resp = self.c.get(self.get_participation_tag_edit_url(ptags[0].id))
        self.assertEqual(resp.status_code, 403)

        resp = self.c.get(self.get_participation_tag_edit_url(-1))
        self.assertEqual(resp.status_code, 403)

        # POST requests
        resp = self.c.post(self.get_participation_tag_edit_url(-1),
                           data=self.get_default_edit_ptag_post_data())
        self.assertEqual(resp.status_code, 403)

        resp = self.c.post(self.get_participation_tag_edit_url(0),
                           data=self.get_default_edit_ptag_post_data())
        self.assertEqual(resp.status_code, 403)

    def test_edit_ptag_get_success(self):
        resp = self.c.get(self.get_participation_tag_edit_url(0))
        self.assertEqual(resp.status_code, 404)

        n_tags = randint(2, 10)
        ptags = factories.ParticipationTagFactory.create_batch(
            size=n_tags, course=self.course)

        resp = self.c.get(self.get_participation_tag_edit_url(ptags[-1].id))
        self.assertEqual(resp.status_code, 200)

        resp = self.c.get(self.get_participation_tag_edit_url(-1))
        self.assertEqual(resp.status_code, 200)

    def test_edit_ptag_post_update(self):
        n_tags = randint(2, 10)
        ptags = factories.ParticipationTagFactory.create_batch(
            size=n_tags, course=self.course)

        expected_ptag_name = "some_tag_name"

        # Get a ptag with has different name with expected_ptag_name
        ptag = None
        for ptag in ptags:
            if ptag.name != expected_ptag_name:
                break

        resp = self.c.post(
            self.get_participation_tag_edit_url(ptag.id),
            data=self.get_default_edit_ptag_post_data(name=expected_ptag_name),
        )
        self.assertEqual(ParticipationTag.objects.count(), n_tags)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ParticipationTag.objects.get(pk=ptag.id).name,
                         expected_ptag_name)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("Changes saved.")

    def test_edit_ptag_from_another_course(self):
        ptag = factories.ParticipationTagFactory(
            course=factories.CourseFactory(identifier="another-course"))

        resp = self.c.get(self.get_participation_tag_edit_url(ptag.id))
        self.assertEqual(resp.status_code, 400)

    def test_edit_ptag_post_update_integrity_error(self):
        n_tags = randint(2, 10)
        ptags = factories.ParticipationTagFactory.create_batch(
            size=n_tags, course=self.course)

        exist_ptag_name = None

        ptag = None
        for ptag in ptags:
            if exist_ptag_name is None:
                exist_ptag_name = ptag.name
                continue
            if ptag.name != exist_ptag_name:
                break

        ptag_name = ptag.name

        resp = self.c.post(
            self.get_participation_tag_edit_url(ptag.id),
            data=self.get_default_edit_ptag_post_data(name=exist_ptag_name),
        )

        self.assertEqual(ParticipationTag.objects.count(), n_tags)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ParticipationTag.objects.get(pk=ptag.id).name,
                         ptag_name)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(
            "A participation tag with that name already exists.")

    def test_edit_ptag_post_create_new_success(self):
        n_tags = randint(2, 10)
        factories.ParticipationTagFactory.create_batch(
            size=n_tags, course=self.course)

        resp = self.c.post(
            self.get_participation_tag_edit_url(-1),
            data=self.get_default_edit_ptag_post_data(),
        )

        self.assertEqual(ParticipationTag.objects.count(), n_tags+1)
        self.assertEqual(resp.status_code, 302)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("New participation tag saved.")

    def test_edit_ptag_post_create_new_integrity_error(self):
        n_tags = randint(2, 10)
        ptags = factories.ParticipationTagFactory.create_batch(
            size=n_tags, course=self.course)

        resp = self.c.post(
            self.get_participation_tag_edit_url(-1),
            data=self.get_default_edit_ptag_post_data(name=ptags[0].name),
        )

        self.assertEqual(ParticipationTag.objects.count(), n_tags)
        self.assertEqual(resp.status_code, 200)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(
            "A participation tag with that name already exists.")

    def test_edit_ptag_post_form_invalid(self):
        n_tags = randint(2, 10)
        factories.ParticipationTagFactory.create_batch(
            size=n_tags, course=self.course)

        # Spaces are not allowed in ptag
        resp = self.c.post(
            self.get_participation_tag_edit_url(-1),
            data=self.get_default_edit_ptag_post_data(name="a tag"),
        )

        self.assertEqual(ParticipationTag.objects.count(), n_tags)
        self.assertEqual(resp.status_code, 200)
        self.assertAddMessageCallCount(0)
        self.assertFormErrorLoose(resp, "invalid characters.")

    def test_delete_ptag_permission_denied(self):
        n_tags = randint(2, 10)
        ptags = factories.ParticipationTagFactory.create_batch(
            size=n_tags, course=self.course)

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(self.get_participation_tag_delete_url(ptags[0].id))
            self.assertEqual(resp.status_code, 403)

            resp = self.c.post(
                self.get_participation_tag_delete_url(ptags[0].id),
                data=self.get_default_delete_ptag_post_data(),
                HTTP_X_REQUESTED_WITH='XMLHttpRequest'
            )
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(ParticipationTag.objects.count(), n_tags)

    def test_delete_ptag_get_or_non_ajax_post_not_allowed(self):
        n_tags = randint(2, 10)
        ptags = factories.ParticipationTagFactory.create_batch(
            size=n_tags, course=self.course)

        resp = self.c.get(self.get_participation_tag_delete_url(ptags[0].id))
        self.assertEqual(resp.status_code, 403)

        resp = self.c.post(
            self.get_participation_tag_delete_url(ptags[0].id),
            data=self.get_default_delete_ptag_post_data(),
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(ParticipationTag.objects.count(), n_tags)

    def test_delete_ptag_success(self):
        n_tags = randint(2, 10)
        ptags = factories.ParticipationTagFactory.create_batch(
            size=n_tags, course=self.course)

        resp = self.c.post(
            self.get_participation_tag_delete_url(ptags[0].id),
            data=self.get_default_delete_ptag_post_data(),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ParticipationTag.objects.count(), n_tags-1)

    def test_delete_ptag_suspicious(self):
        n_tags = randint(2, 10)
        ptags = factories.ParticipationTagFactory.create_batch(
            size=n_tags, course=self.course)

        resp = self.c.post(
            self.get_participation_tag_delete_url(ptags[0].id),
            data=self.get_default_delete_ptag_post_data(
                no_delete_in_post=True, some_action=True),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ParticipationTag.objects.count(), n_tags)

    def test_delete_ptag_from_another_course(self):
        ptag = factories.ParticipationTagFactory(
            course=factories.CourseFactory(identifier="another-course"))

        resp = self.c.post(
            self.get_participation_tag_delete_url(ptag.id),
            data=self.get_default_delete_ptag_post_data(),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ParticipationTag.objects.count(), 1)

    def test_delete_ptag_exception_raised(self):
        n_tags = randint(2, 10)
        ptags = factories.ParticipationTagFactory.create_batch(
            size=n_tags, course=self.course)

        with mock.patch("course.models.ParticipationTag.delete") as mock_ptag_del:
            mock_ptag_del.side_effect = (
                RuntimeError("some error"))

            resp = self.c.post(
                self.get_participation_tag_delete_url(ptags[0].id),
                data=self.get_default_delete_ptag_post_data(),
                HTTP_X_REQUESTED_WITH='XMLHttpRequest'
            )
            self.assertEqual(resp.status_code, 400)

            import json
            self.assertIn(
                "Error when deleting participation tag",
                json.loads(resp.content.decode())["error"]
            )


class ParticipationRoleCRUDTest(
        SingleCourseTestMixin, EnrollmentTestMixin, TestCase):
    def setUp(self):
        super(ParticipationRoleCRUDTest, self).setUp()
        self.c.force_login(self.instructor_participation.user)
        self.default_number_of_roles = ParticipationRole.objects.count()

    def get_default_edit_role_post_data(self, **kwargs):
        data = {"identifier": "a_role", "name": "the name"}
        data.update(kwargs)
        return data

    def get_default_delete_role_post_data(self, **kwargs):
        data = {}
        if not kwargs.pop("no_delete_in_post", None):
            data = {"delete": True}
        data.update(kwargs)
        return data

    @property
    def prole_list_url(self):
        return self.get_participation_role_list_url()

    def test_view_prole_list_permission_denied(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(self.prole_list_url)
            self.assertEqual(resp.status_code, 403)

    def test_view_prole_list_success(self):
        factories.ParticipationRoleFactory(
            course=self.course, identifier="some_role")

        resp = self.c.get(self.prole_list_url)
        self.assertEqual(resp.status_code, 200)

        self.assertResponseContextLengthEqual(
            resp, "participation_roles", self.default_number_of_roles + 1)

    def test_edit_prole_permission_denied(self):
        self.c.force_login(self.student_participation.user)

        # GET requests
        resp = self.c.get(self.get_participation_role_edit_url(0))
        self.assertEqual(resp.status_code, 403)

        prole = factories.ParticipationRoleFactory(
            identifier="some_role", course=self.course)

        resp = self.c.get(self.get_participation_role_edit_url(prole.id))
        self.assertEqual(resp.status_code, 403)

        resp = self.c.get(self.get_participation_role_edit_url(-1))
        self.assertEqual(resp.status_code, 403)

        # POST requests
        resp = self.c.post(self.get_participation_role_edit_url(-1),
                           data=self.get_default_edit_role_post_data())
        self.assertEqual(resp.status_code, 403)

        resp = self.c.post(self.get_participation_role_edit_url(0),
                           data=self.get_default_edit_role_post_data())
        self.assertEqual(resp.status_code, 403)

    def test_edit_prole_get_success(self):
        resp = self.c.get(self.get_participation_role_edit_url(0))
        self.assertEqual(resp.status_code, 404)

        prole = factories.ParticipationRoleFactory(
            identifier="some_role", course=self.course)

        resp = self.c.get(self.get_participation_role_edit_url(prole.id))
        self.assertEqual(resp.status_code, 200)

        resp = self.c.get(self.get_participation_role_edit_url(-1))
        self.assertEqual(resp.status_code, 200)

    def test_edit_prole_post_update(self):
        expected_prole_identifier = "some_role_identifier"

        # Get a prole with has different identifier with expected_prole_identifier
        prole = None
        for prole in ParticipationRole.objects.all():
            if prole.identifier != expected_prole_identifier:
                break

        resp = self.c.post(
            self.get_participation_role_edit_url(prole.id),
            data=self.get_default_edit_role_post_data(
                identifier=expected_prole_identifier),
        )
        self.assertEqual(ParticipationRole.objects.count(),
                         self.default_number_of_roles)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ParticipationRole.objects.get(pk=prole.id).identifier,
                         expected_prole_identifier)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("Changes saved.")

    def test_edit_prole_from_another_course(self):
        prole = factories.ParticipationRoleFactory(
            course=factories.CourseFactory(identifier="another-course"))

        resp = self.c.get(self.get_participation_role_edit_url(prole.id))
        self.assertEqual(resp.status_code, 400)

    def test_edit_prole_post_update_integrity_error(self):
        new_prole = factories.ParticipationRoleFactory(
            identifier="some_role", course=self.course)

        new_prole_identifier = new_prole.identifier

        prole = None
        for prole in ParticipationRole.objects.all():
            if prole.identifier != new_prole_identifier:
                break

        prole_identifier = prole.identifier

        resp = self.c.post(
            self.get_participation_role_edit_url(prole.id),
            data=self.get_default_edit_role_post_data(
                identifier=new_prole_identifier),
        )

        self.assertEqual(ParticipationRole.objects.count(),
                         self.default_number_of_roles + 1)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ParticipationRole.objects.get(pk=prole.id).identifier,
                         prole_identifier)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(
            "A participation role with that identifier already exists.")

    def test_edit_prole_post_create_new_success(self):
        resp = self.c.post(
            self.get_participation_role_edit_url(-1),
            data=self.get_default_edit_role_post_data(),
        )

        self.assertEqual(ParticipationRole.objects.count(),
                         self.default_number_of_roles + 1)
        self.assertEqual(resp.status_code, 302)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("New participation role saved.")

    def test_edit_prole_post_create_new_integrity_error(self):
        prole = factories.ParticipationRoleFactory(
            identifier="some_role", course=self.course)

        resp = self.c.post(
            self.get_participation_role_edit_url(-1),
            data=self.get_default_edit_role_post_data(identifier=prole.identifier),
        )

        self.assertEqual(ParticipationRole.objects.count(),
                         self.default_number_of_roles + 1)
        self.assertEqual(resp.status_code, 200)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(
            "A participation role with that identifier already exists.")

    def test_edit_prole_post_form_invalid(self):
        # Spaces are not allowed in prole
        resp = self.c.post(
            self.get_participation_role_edit_url(-1),
            data=self.get_default_edit_role_post_data(identifier="a role"),
        )

        self.assertEqual(ParticipationRole.objects.count(),
                         self.default_number_of_roles)
        self.assertEqual(resp.status_code, 200)
        self.assertAddMessageCallCount(0)
        self.assertFormErrorLoose(resp, "invalid characters.")

    def test_delete_prole_permission_denied(self):
        prole = factories.ParticipationRoleFactory(
            identifier="some_role", course=self.course)

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(self.get_participation_role_delete_url(prole.id))
            self.assertEqual(resp.status_code, 403)

            resp = self.c.post(
                self.get_participation_role_delete_url(prole.id),
                data=self.get_default_delete_role_post_data(),
                HTTP_X_REQUESTED_WITH='XMLHttpRequest'
            )
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(ParticipationRole.objects.count(),
                             self.default_number_of_roles + 1)

    def test_delete_prole_get_or_non_ajax_post_not_allowed(self):
        prole = factories.ParticipationRoleFactory(
            identifier="some_role", course=self.course)

        resp = self.c.get(self.get_participation_role_delete_url(prole.id))
        self.assertEqual(resp.status_code, 403)

        resp = self.c.post(
            self.get_participation_role_delete_url(prole.id),
            data=self.get_default_delete_role_post_data(),
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(ParticipationRole.objects.count(),
                         self.default_number_of_roles + 1)

    def test_delete_prole_success(self):
        prole = factories.ParticipationRoleFactory(
            identifier="some_role", course=self.course)

        resp = self.c.post(
            self.get_participation_role_delete_url(prole.id),
            data=self.get_default_delete_role_post_data(),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ParticipationRole.objects.count(),
                         self.default_number_of_roles)

    def test_delete_prole_suspicious(self):
        prole = factories.ParticipationRoleFactory(
            identifier="some_role", course=self.course)

        resp = self.c.post(
            self.get_participation_role_delete_url(prole.id),
            data=self.get_default_delete_role_post_data(
                no_delete_in_post=True, some_action=True),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ParticipationRole.objects.count(),
                         self.default_number_of_roles + 1)

    def test_delete_prole_from_another_course(self):
        prole = factories.ParticipationRoleFactory(
            course=factories.CourseFactory(identifier="another-course"))

        prole_counts = ParticipationRole.objects.count()

        resp = self.c.post(
            self.get_participation_role_delete_url(prole.id),
            data=self.get_default_delete_role_post_data(),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ParticipationRole.objects.count(), prole_counts)

    def test_delete_prole_exception_raised(self):
        prole = factories.ParticipationRoleFactory(
            identifier="some_role", course=self.course)

        with mock.patch("course.models.ParticipationRole.delete") as mock_prole_del:
            mock_prole_del.side_effect = (
                RuntimeError("some error"))

            resp = self.c.post(
                self.get_participation_role_delete_url(prole.id),
                data=self.get_default_delete_role_post_data(),
                HTTP_X_REQUESTED_WITH='XMLHttpRequest'
            )
            self.assertEqual(resp.status_code, 400)

            import json
            self.assertIn(
                "Error when deleting participation role",
                json.loads(resp.content.decode())["error"]
            )


# vim: foldmethod=marker
