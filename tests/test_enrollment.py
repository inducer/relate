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

from django.test import TestCase
from django.conf import settings
from django.test.utils import override_settings
from django.core import mail
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.shortcuts import get_object_or_404
from django.utils.translation import ugettext_lazy as _

from relate.utils import string_concat

from course.models import (
    Course,
    Participation, ParticipationRole, ParticipationPreapproval)
from course.constants import participation_status, user_status

from .base_test_mixins import (
    SingleCourseTestMixin,
    NONE_PARTICIPATION_USER_CREATE_KWARG_LIST,
    FallBackStorageMessageTestMixin
)
from .utils import LocmemBackendTestsMixin, mock


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

MESSAGE_ENROLLMENT_SENT_TEXT = _(
    "Enrollment request sent. You will receive notifcation "
    "by email once your request has been acted upon.")
MESSAGE_ENROLL_REQUEST_PENDING_TEXT = _(
    "Your enrollment request is pending. You will be "
    "notified once it has been acted upon.")
MESSAGE_ENROLL_DENIED_NOT_ALLOWED_TEXT = _(
    "Your enrollment request had been denied. Enrollment is not allowed.")
MESSAGE_ENROLL_DROPPED_NOT_ALLOWED_TEXT = _(
    "You had been dropped from the course. Re-enrollment is not allowed.")
MESSAGE_ENROLL_REQUEST_ALREADY_PENDING_TEXT = _(
    "You have previously sent the enrollment request. "
    "Re-sending the request is not allowed.")
MESSAGE_PARTICIPATION_ALREADY_EXIST_TEXT = _(
    "A participation already exists. Enrollment attempt aborted.")
MESSAGE_CANNOT_REENROLL_TEXT = _("Already enrolled. Cannot re-enroll.")
MESSAGE_SUCCESSFULLY_ENROLLED_TEXT = _("Successfully enrolled.")
MESSAGE_EMAIL_SUFFIX_REQUIRED_PATTERN = _(
    "Enrollment not allowed. Please use your '%s' email to enroll.")
MESSAGE_NOT_ACCEPTING_ENROLLMENTS_TEXT = _("Course is not accepting enrollments.")
MESSAGE_ENROLL_ONLY_ACCEPT_POST_REQUEST_TEXT = _(
    "Can only enroll using POST request")
MESSAGE_ENROLLMENT_DENIED_TEXT = _("Successfully denied.")
MESSAGE_ENROLLMENT_DROPPED_TEXT = _("Successfully dropped.")

MESSAGE_BATCH_PREAPPROVED_RESULT_PATTERN = _(
    "%(n_created)d preapprovals created, "
    "%(n_exist)d already existed, "
    "%(n_requested_approved)d pending requests approved.")

MESSAGE_EMAIL_NOT_CONFIRMED_TEXT = _(
    "Your email address is not yet confirmed. "
    "Confirm your email to continue.")
MESSAGE_PARTICIPATION_CHANGE_SAVED_TEXT = _("Changes saved.")

EMAIL_NEW_ENROLLMENT_REQUEST_TITLE_PATTERN = (
    string_concat("[%s] ", _("New enrollment request")))
EMAIL_ENROLLMENT_DECISION_TITLE_PATTERN = (
    string_concat("[%s] ", _("Your enrollment request")))

VALIDATION_ERROR_USER_NOT_CONFIRMED = _(
    "This user has not confirmed his/her email.")

# }}}


def course_get_object_or_404_sf_enroll_apprv_not_required(klass, *args, **kwargs):
    assert klass == Course
    course_object = get_object_or_404(klass, *args, **kwargs)
    course_object.enrollment_approval_required = False
    return course_object


def course_get_object_or_404_sf_not_accepts_enrollment(klass, *args, **kwargs):
    assert klass == Course
    course_object = get_object_or_404(klass, *args, **kwargs)
    course_object.accepts_enrollment = False
    return course_object


def course_get_object_or_404_sf_not_email_suffix1(klass, *args, **kwargs):
    assert klass == Course
    course_object = get_object_or_404(klass, *args, **kwargs)
    course_object.enrollment_required_email_suffix = TEST_EMAIL_SUFFIX1
    return course_object


def course_get_object_or_404_sf_not_email_suffix2(klass, *args, **kwargs):
    assert klass == Course
    course_object = get_object_or_404(klass, *args, **kwargs)
    course_object.enrollment_required_email_suffix = TEST_EMAIL_SUFFIX2
    return course_object


class BaseEmailConnectionMixin:
    EMAIL_CONNECTIONS = None
    EMAIL_CONNECTION_DEFAULT = None
    NO_REPLY_EMAIL_FROM = None
    NOTIFICATION_EMAIL_FROM = None
    GRADER_FEEDBACK_EMAIL_FROM = None
    STUDENT_INTERACT_EMAIL_FROM = None
    ENROLLMENT_EMAIL_FROM = None
    ROBOT_EMAIL_FROM = "robot@example.com"

    def setUp(self):
        kwargs = {}
        for attr in [EMAIL_CONNECTIONS, EMAIL_CONNECTION_DEFAULT,
                     NO_REPLY_EMAIL_FROM, NOTIFICATION_EMAIL_FROM,
                     GRADER_FEEDBACK_EMAIL_FROM, STUDENT_INTERACT_EMAIL_FROM,
                     ENROLLMENT_EMAIL_FROM]:
            attr_value = getattr(self, attr, None)
            if attr_value:
                kwargs.update({attr: attr_value})

        self.settings_email_connection_override = (
            override_settings(**kwargs))
        self.settings_email_connection_override.enable()

    def tearDown(self):
        self.settings_email_connection_override.disable()


class EnrollmentTestBaseMixin(SingleCourseTestMixin,
                              FallBackStorageMessageTestMixin):
    none_participation_user_create_kwarg_list = (
        NONE_PARTICIPATION_USER_CREATE_KWARG_LIST)

    @classmethod
    def setUpTestData(cls):  # noqa
        super(EnrollmentTestBaseMixin, cls).setUpTestData()
        assert cls.non_participation_users.count() >= 4
        cls.non_participation_user1 = cls.non_participation_users[0]
        cls.non_participation_user2 = cls.non_participation_users[1]
        cls.non_participation_user3 = cls.non_participation_users[2]
        cls.non_participation_user4 = cls.non_participation_users[3]
        if cls.non_participation_user1.status != user_status.active:
            cls.non_participation_user1.status = user_status.active
            cls.non_participation_user1.save()
        if cls.non_participation_user2.status != user_status.active:
            cls.non_participation_user2.status = user_status.active
            cls.non_participation_user2.save()
        if cls.non_participation_user3.status != user_status.unconfirmed:
            cls.non_participation_user3.status = user_status.unconfirmed
            cls.non_participation_user3.save()
        if cls.non_participation_user4.status != user_status.unconfirmed:
            cls.non_participation_user4.status = user_status.unconfirmed
            cls.non_participation_user4.save()

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


class EnrollmentRequestTest(
        LocmemBackendTestsMixin, EnrollmentTestBaseMixin, TestCase):

    courses_attributes_extra_list = [{"enrollment_approval_required": True}]

    def test_enroll_request_non_participation(self):
        with self.temporarily_switch_to_user(self.non_participation_user1):
            resp = self.c.post(self.enroll_request_url, follow=True)
        self.assertResponseMessagesCount(resp, 2)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_ENROLLMENT_SENT_TEXT,
                   MESSAGE_ENROLL_REQUEST_PENDING_TEXT])
        self.assertResponseMessageLevelsEqual(
            resp, [messages.INFO, messages.INFO])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.requested),
            1)

        # Second and after visits to course page should display only 1 messages
        with self.temporarily_switch_to_user(self.non_participation_user1):
            resp = self.c.get(self.course_page_url)
        self.assertResponseMessagesCount(resp, 1)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_ENROLL_REQUEST_PENDING_TEXT])

        mailmessage = self.get_the_email_message()
        self.assertEqual(mailmessage["Subject"],
                         EMAIL_NEW_ENROLLMENT_REQUEST_TITLE_PATTERN
                         % self.course.identifier)

        with self.temporarily_switch_to_user(self.non_participation_user2):
            resp = self.c.post(self.enroll_request_url, follow=True)
        self.assertRedirects(resp, self.course_page_url)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.requested),
            2)

    @mock.patch("course.enrollment.get_object_or_404",
                side_effect=course_get_object_or_404_sf_enroll_apprv_not_required)
    def test_enroll_request_non_participation_not_require_approval(
            self, mocked_get_object_or_404):
        expected_active_participation_count = (
            self.get_participation_count_by_status(participation_status.active) + 1)
        with self.temporarily_switch_to_user(self.non_participation_user1):
            resp = self.c.post(self.enroll_request_url, follow=True)
        self.assertResponseMessagesCount(resp, 1)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_SUCCESSFULLY_ENROLLED_TEXT])
        self.assertResponseMessageLevelsEqual(
            resp, [messages.SUCCESS])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.requested),
            0)

        mailmessage = self.get_the_email_message()
        self.assertEqual(mailmessage["Subject"],
                         EMAIL_ENROLLMENT_DECISION_TITLE_PATTERN
                         % self.course.identifier)

        # Second and after visits to course page should display no messages
        with self.temporarily_switch_to_user(self.non_participation_user1):
            resp = self.c.get(self.course_page_url)
        self.assertResponseMessagesCount(resp, 0)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.active),
            expected_active_participation_count
        )

    @mock.patch("course.enrollment.get_object_or_404",
                side_effect=course_get_object_or_404_sf_not_accepts_enrollment)
    def test_enroll_request_non_participation_course_not_accept_enrollment(
            self, mocked_get_object_or_404):
        expected_active_participation_count = (
            self.get_participation_count_by_status(participation_status.active))
        with self.temporarily_switch_to_user(self.non_participation_user1):
            resp = self.c.post(self.enroll_request_url, follow=True)
        self.assertResponseMessagesCount(resp, 1)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_NOT_ACCEPTING_ENROLLMENTS_TEXT])
        self.assertResponseMessageLevelsEqual(
            resp, [messages.ERROR])
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.requested),
            0)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.active),
            expected_active_participation_count
        )

        # Second and after visits to course page should display no messages
        with self.temporarily_switch_to_user(self.non_participation_user1):
            resp = self.c.get(self.course_page_url)
        self.assertResponseMessagesCount(resp, 0)

    # https://github.com/inducer/relate/issues/370
    def test_pending_user_re_enroll_request_failure(self):
        self.create_participation(self.course, self.non_participation_user1,
                                  status=participation_status.requested)
        with self.temporarily_switch_to_user(self.non_participation_user1):
            resp = self.c.post(self.enroll_request_url, follow=True)

        # Second enroll request won't send more emails,
        self.assertEqual(len(mail.outbox), 0)

        self.assertResponseMessagesCount(resp, 2)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_ENROLL_REQUEST_ALREADY_PENDING_TEXT,
                   MESSAGE_ENROLL_REQUEST_PENDING_TEXT])

        self.assertResponseMessageLevelsEqual(
            resp, [messages.ERROR,
                   messages.INFO])

    def test_denied_user_enroll_request_failure(self):
        self.create_participation(self.course, self.non_participation_user1,
                                  status=participation_status.denied)
        with self.temporarily_switch_to_user(self.non_participation_user1):
            resp = self.c.post(self.enroll_request_url, follow=True)

        self.assertEqual(len(mail.outbox), 0)
        self.assertResponseMessagesCount(resp, 1)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_ENROLL_DENIED_NOT_ALLOWED_TEXT])

        self.assertResponseMessageLevelsEqual(
            resp, [messages.ERROR])

    def test_dropped_user_re_enroll_request_failure(self):
        self.create_participation(self.course, self.non_participation_user1,
                                  status=participation_status.dropped)
        with self.temporarily_switch_to_user(self.non_participation_user1):
            resp = self.c.post(self.enroll_request_url, follow=True)

        self.assertEqual(len(mail.outbox), 0)
        self.assertResponseMessagesCount(resp, 1)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_ENROLL_DROPPED_NOT_ALLOWED_TEXT])

        self.assertResponseMessageLevelsEqual(
            resp, [messages.ERROR])

    #  https://github.com/inducer/relate/issues/369
    def test_unconfirmed_user_enroll_request(self):
        with self.temporarily_switch_to_user(self.non_participation_user4):
            resp = self.c.post(self.enroll_request_url, follow=True)
        self.assertResponseMessagesCount(resp, 1)
        self.assertResponseMessagesEqual(
            resp,
            [MESSAGE_EMAIL_NOT_CONFIRMED_TEXT])
        self.assertResponseMessageLevelsEqual(resp, [messages.ERROR])
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.requested),
            0)

    def test_enroll_request_fail_re_enroll(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.post(self.enroll_request_url, follow=True)
        self.assertResponseMessagesCount(resp, 1)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_CANNOT_REENROLL_TEXT])
        self.assertResponseMessageLevelsEqual(resp, [messages.ERROR])
        self.assertEqual(len(mail.outbox), 0)

    def test_enroll_by_get(self):
        with self.temporarily_switch_to_user(self.non_participation_user1):
            self.c.get(self.enroll_request_url)
            resp = self.c.get(self.course_page_url)
        self.assertResponseMessagesCount(resp, 1)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_ENROLL_ONLY_ACCEPT_POST_REQUEST_TEXT])
        self.assertResponseMessageLevelsEqual(resp, [messages.ERROR])
        self.assertEqual(len(mail.outbox), 0)

        # for participations, this show MESSAGE_CANNOT_REENROLL_TEXT
        with self.temporarily_switch_to_user(self.student_participation.user):
            self.c.get(self.enroll_request_url)
            resp = self.c.get(self.course_page_url)
        self.assertResponseMessagesCount(resp, 1)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_CANNOT_REENROLL_TEXT])
        self.assertResponseMessageLevelsEqual(resp, [messages.ERROR])
        self.assertEqual(len(mail.outbox), 0)

    def test_edit_participation_view_get_for_requested(self):
        with self.temporarily_switch_to_user(self.non_participation_user1):
            self.c.post(self.enroll_request_url, follow=True)

        self.assertEqual(
            self.get_participation_count_by_status(participation_status.requested),
            1)
        my_participation = Participation.objects.get(
            user=self.non_participation_user1
        )
        my_participation_edit_url = (
            self.get_participation_edit_url(my_participation.pk))

        with self.temporarily_switch_to_user(self.non_participation_user1):
            resp = self.c.get(my_participation_edit_url)

        self.assertEqual(resp.status_code, 403)

        with self.temporarily_switch_to_user(self.non_participation_user2):
            resp = self.c.get(my_participation_edit_url)

        self.assertEqual(resp.status_code, 403)

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(my_participation_edit_url)

        self.assertEqual(resp.status_code, 403)

        # only instructor may view edit participation page
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(my_participation_edit_url)

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "submit-id-submit")
        self.assertContains(resp, "submit-id-approve")
        self.assertContains(resp, "submit-id-deny")

        with self.temporarily_switch_to_user(self.ta_participation.user):
            resp = self.c.get(my_participation_edit_url)

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "submit-id-submit")
        self.assertContains(resp, "submit-id-approve")
        self.assertContains(resp, "submit-id-deny")

    def test_edit_participation_view_get_for_enrolled(self):
        my_participation_edit_url = (
            self.get_participation_edit_url(self.student_participation.pk))
        resp = self.c.get(my_participation_edit_url)
        self.assertEqual(resp.status_code, 403)

        with self.temporarily_switch_to_user(self.non_participation_user1):
            resp = self.c.get(my_participation_edit_url)

        self.assertEqual(resp.status_code, 403)

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(my_participation_edit_url)

        self.assertEqual(resp.status_code, 403)

        # only instructor may view edit participation page
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(my_participation_edit_url)

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "submit-id-submit")
        self.assertContains(resp, "submit-id-drop")

        with self.temporarily_switch_to_user(self.ta_participation.user):
            resp = self.c.get(my_participation_edit_url)

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "submit-id-submit")
        self.assertContains(resp, "submit-id-drop")


class EnrollRequireEmailSuffixTest(LocmemBackendTestsMixin,
                                   EnrollmentTestBaseMixin, TestCase):
    courses_attributes_extra_list = [{"enrollment_approval_required": True}]

    # {{{ email suffix "@suffix.com"

    @mock.patch("course.enrollment.get_object_or_404",
                side_effect=course_get_object_or_404_sf_not_email_suffix1)
    def test_email_suffix_matched(self, mocked_email_suffix):
        with self.temporarily_switch_to_user(self.non_participation_user1):
            resp = self.c.post(self.enroll_request_url, follow=True)

        self.assertResponseMessagesCount(resp, 2)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_ENROLLMENT_SENT_TEXT,
                   MESSAGE_ENROLL_REQUEST_PENDING_TEXT])
        self.assertResponseMessageLevelsEqual(
            resp, [messages.INFO, messages.INFO])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            self.get_participation_count_by_status(
                participation_status.requested),
            1)

    @mock.patch("course.enrollment.get_object_or_404",
                side_effect=course_get_object_or_404_sf_not_email_suffix1)
    def test_email_suffix_not_matched(self, mocked_email_suffix):
        with self.temporarily_switch_to_user(self.non_participation_user2):
            resp = self.c.post(self.enroll_request_url, follow=True)

        self.assertResponseMessagesCount(resp, 1)
        self.assertResponseMessagesEqual(
            resp,
            [MESSAGE_EMAIL_SUFFIX_REQUIRED_PATTERN % TEST_EMAIL_SUFFIX1])
        self.assertResponseMessageLevelsEqual(resp, [messages.ERROR])
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.get_participation_count_by_status(
                participation_status.requested),
            0)

    @mock.patch("course.enrollment.get_object_or_404",
                side_effect=course_get_object_or_404_sf_not_email_suffix1)
    def test_email_suffix_matched_unconfirmed(self, mocked_email_suffix):
        with self.temporarily_switch_to_user(self.non_participation_user3):
            resp = self.c.post(self.enroll_request_url, follow=True)

        self.assertResponseMessagesCount(resp, 1)
        self.assertResponseMessagesEqual(
            resp,
            [MESSAGE_EMAIL_NOT_CONFIRMED_TEXT])
        self.assertResponseMessageLevelsEqual(resp, [messages.ERROR])
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.get_participation_count_by_status(
                participation_status.requested),
            0)

    @mock.patch("course.enrollment.get_object_or_404",
                side_effect=course_get_object_or_404_sf_not_email_suffix1)
    def test_email_suffix_not_matched_unconfirmed(self, mocked_email_suffix):
        with self.temporarily_switch_to_user(self.non_participation_user4):
            resp = self.c.post(self.enroll_request_url, follow=True)

        self.assertResponseMessagesCount(resp, 1)
        self.assertResponseMessagesEqual(
            resp,
            [MESSAGE_EMAIL_NOT_CONFIRMED_TEXT])
        self.assertResponseMessageLevelsEqual(resp, [messages.ERROR])
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.get_participation_count_by_status(
                participation_status.requested),
            0)
    # }}}

    # {{{ email suffix "suffix.com"
    @mock.patch("course.enrollment.get_object_or_404",
                side_effect=course_get_object_or_404_sf_not_email_suffix2)
    def test_email_suffix_domain_matched(self, mocked_email_suffix):
        with self.temporarily_switch_to_user(self.non_participation_user1):
            resp = self.c.post(self.enroll_request_url, follow=True)
        self.assertResponseMessagesCount(resp, 2)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_ENROLLMENT_SENT_TEXT,
                   MESSAGE_ENROLL_REQUEST_PENDING_TEXT])
        self.assertResponseMessageLevelsEqual(
            resp, [messages.INFO, messages.INFO])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            self.get_participation_count_by_status(
                participation_status.requested),
            1)

    @mock.patch("course.enrollment.get_object_or_404",
                side_effect=course_get_object_or_404_sf_not_email_suffix2)
    def test_email_suffix_domain_not_matched(self, mocked_email_suffix):
        with self.temporarily_switch_to_user(self.non_participation_user2):
            resp = self.c.post(self.enroll_request_url, follow=True)

        self.assertResponseMessagesCount(resp, 1)
        self.assertResponseMessagesEqual(
            resp,
            [MESSAGE_EMAIL_SUFFIX_REQUIRED_PATTERN % TEST_EMAIL_SUFFIX2])
        self.assertResponseMessageLevelsEqual(resp, [messages.ERROR])
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.get_participation_count_by_status(
                participation_status.requested),
            0)

    @mock.patch("course.enrollment.get_object_or_404",
                side_effect=course_get_object_or_404_sf_not_email_suffix2)
    def test_email_suffix_domain_matched_unconfirmed(self, mocked_email_suffix):
        with self.temporarily_switch_to_user(self.non_participation_user3):
            resp = self.c.post(self.enroll_request_url, follow=True)

        self.assertResponseMessagesCount(resp, 1)
        self.assertResponseMessagesEqual(
            resp,
            [MESSAGE_EMAIL_NOT_CONFIRMED_TEXT])
        self.assertResponseMessageLevelsEqual(resp, [messages.ERROR])
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.get_participation_count_by_status(
                participation_status.requested),
            0)

    @mock.patch("course.enrollment.get_object_or_404",
                side_effect=course_get_object_or_404_sf_not_email_suffix2)
    def test_email_suffix_dot_domain_matched(self, mocked_email_suffix):
        test_user5 = self.create_user({
            "username": "test_user5",
            "password": "test_user5",
            "email": "test_user5@some.suffix.com",
            "first_name": "Test",
            "last_name": "User5",
            "status": user_status.active
        })
        with self.temporarily_switch_to_user(test_user5):
            resp = self.c.post(self.enroll_request_url, follow=True)

        self.assertResponseMessagesCount(resp, 2)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_ENROLLMENT_SENT_TEXT,
                   MESSAGE_ENROLL_REQUEST_PENDING_TEXT])
        self.assertResponseMessageLevelsEqual(
            resp, [messages.INFO, messages.INFO])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            self.get_participation_count_by_status(
                participation_status.requested),
            1)
        get_user_model().objects.get(pk=test_user5.pk).delete()
    # }}}


class EnrollmentDecisionTestMixin(LocmemBackendTestsMixin, EnrollmentTestBaseMixin):
    courses_attributes_extra_list = [{"enrollment_approval_required": True}]

    @classmethod
    def setUpTestData(cls):  # noqa
        super(EnrollmentDecisionTestMixin, cls).setUpTestData()
        my_participation = cls.create_participation(
            cls.course, cls.non_participation_user1,
            status=participation_status.requested)
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
            self.get_participation_count_by_status(participation_status.requested),
            1)
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.post(self.my_participation_edit_url,
                               self.approve_post_data)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.requested),
            0)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_SUCCESSFULLY_ENROLLED_TEXT])
        self.assertResponseMessageLevelsEqual(resp, [messages.SUCCESS])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.requested),
            0)

    def test_edit_participation_view_enroll_decision_approve_no_permission1(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.post(self.my_participation_edit_url,
                               self.approve_post_data)

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.requested),
            1)

    def test_edit_participation_view_enroll_decision_approve_no_permission2(self):
        with self.temporarily_switch_to_user(self.non_participation_user1):
            resp = self.c.post(self.my_participation_edit_url,
                               self.approve_post_data)

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.requested),
            1)

    def test_edit_participation_view_enroll_decision_deny(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.post(self.my_participation_edit_url, self.deny_post_data)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.requested),
            0)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_ENROLLMENT_DENIED_TEXT])
        self.assertResponseMessageLevelsEqual(resp, [messages.SUCCESS])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.requested),
            0)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.denied),
            1)

    def test_edit_participation_view_enroll_decision_drop(self):
        self.create_participation(self.course, self.non_participation_user3,
                                  status=participation_status.active)
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.post(self.my_participation_edit_url, self.drop_post_data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.dropped),
            1)
        self.assertResponseMessagesEqual(
            resp, [MESSAGE_ENROLLMENT_DROPPED_TEXT])
        self.assertResponseMessageLevelsEqual(resp, [messages.SUCCESS])
        self.assertEqual(len(mail.outbox), 0)

    def test_edit_participation_view_add_new_unconfirmed_user(self):
        self.c.force_login(self.instructor_participation.user)
        resp = self.c.get(self.add_new_url)
        self.assertTrue(resp.status_code, 200)

        if self.non_participation_user3.status != user_status.unconfirmed:
            self.non_participation_user3.status = user_status.unconfirmed
            self.non_participation_user3.save()

        expected_active_user_count = (
            get_user_model()
            .objects.filter(status=user_status.unconfirmed).count())

        expected_active_participation_count = (
            self.get_participation_count_by_status(participation_status.active))

        form_data = {"user": [str(self.non_participation_user3.pk)],
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
            self.get_participation_count_by_status(participation_status.active),
            expected_active_participation_count)

        self.assertEqual(
            get_user_model()
            .objects.filter(status=user_status.unconfirmed).count(),
            expected_active_user_count)
        self.assertResponseMessagesCount(resp, 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_edit_participation_view_add_new_active_user(self):
        self.c.force_login(self.instructor_participation.user)
        resp = self.c.get(self.add_new_url)
        self.assertTrue(resp.status_code, 200)

        if self.non_participation_user4.status != user_status.active:
            self.non_participation_user4.status = user_status.active
            self.non_participation_user4.save()

        expected_active_user_count = (
            get_user_model()
            .objects.filter(status=user_status.unconfirmed).count()
        )

        expected_active_participation_count = (
            self.get_participation_count_by_status(participation_status.active) + 1
        )

        form_data = {"user": [str(self.non_participation_user4.pk)],
                     "time_factor": 1,
                     "roles": self.student_role_post_data, "notes": [""],
                     "add_new": True
                     }
        add_post_data = {"submit": [""]}
        add_post_data.update(form_data)
        resp = self.c.post(self.add_new_url, add_post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.active),
            expected_active_participation_count)

        self.assertEqual(
            get_user_model()
            .objects.filter(status=user_status.unconfirmed).count(),
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
            self.get_participation_count_by_status(participation_status.requested),
            1)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.denied),
            0)

    def test_edit_participation_view_enroll_decision_deny_no_permission2(self):
        with self.temporarily_switch_to_user(self.non_participation_user1):
            resp = self.c.post(self.my_participation_edit_url, self.deny_post_data)

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.requested),
            1)
        self.assertEqual(
            self.get_participation_count_by_status(participation_status.denied),
            0)


class EnrollmentPreapprovalTestMixin(LocmemBackendTestsMixin,
                                     EnrollmentTestBaseMixin):

    @classmethod
    def setUpTestData(cls):  # noqa
        super(EnrollmentPreapprovalTestMixin, cls).setUpTestData()
        assert cls.non_participation_user1.institutional_id_verified is True
        assert cls.non_participation_user2.institutional_id_verified is False

    @property
    def preapprove_data_emails(self):
        preapproved_user = [self.non_participation_user1,
                            self.non_participation_user2]
        preapproved_data = [u.email for u in preapproved_user]
        return preapproved_data

    @property
    def preapprove_data_institutional_ids(self):
        preapproved_user = [self.non_participation_user1,
                            self.non_participation_user2,
                            self.non_participation_user3]
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
        enroll_request_users = [self.non_participation_user1]
        for u in enroll_request_users:
            with self.temporarily_switch_to_user(u):
                self.c.post(self.enroll_request_url, follow=True)

        self.flush_mailbox()
        expected_participation_count = (
            self.get_participation_count_by_status(participation_status.active) + 1)
        resp = self.post_preapprovel(
            "email",
            self.preapprove_data_emails)
        self.assertEqual(
            self.get_participation_count_by_status(
                participation_status.active), expected_participation_count)

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
            self.non_participation_user1, self.non_participation_user2]
        for u in enroll_request_users:
            with self.temporarily_switch_to_user(u):
                self.c.post(self.enroll_request_url, follow=True)

        self.flush_mailbox()
        n_expected_newly_enrolled_users = (
            len([u for u in enroll_request_users if u.institutional_id_verified]))
        expected_participation_count = (
            self.get_participation_count_by_status(participation_status.active)
            + n_expected_newly_enrolled_users
        )
        resp = self.post_preapprovel(
            "institutional_id",
            self.preapprove_data_institutional_ids)
        self.assertEqual(
            self.get_participation_count_by_status(
                participation_status.active), expected_participation_count)

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

    # We'll have to mock course at two place if use mock, so I separate this
    # test out of EnrollmentPreapprovalTest
    courses_attributes_extra_list = [{
        "enrollment_approval_required": True,
        "preapproval_require_verified_inst_id": False}]

    def test_preapproval_inst_id_type_approve_pending_not_require_id_verified(self):
        assert self.course.preapproval_require_verified_inst_id is False
        enroll_request_users = [
            self.non_participation_user1, self.non_participation_user2]
        for u in enroll_request_users:
            with self.temporarily_switch_to_user(u):
                self.c.post(self.enroll_request_url, follow=True)

        self.flush_mailbox()
        n_expected_newly_enrolled_users = len(enroll_request_users)
        expected_participation_count = (
            self.get_participation_count_by_status(participation_status.active)
            + n_expected_newly_enrolled_users
        )
        resp = self.post_preapprovel(
            "institutional_id",
            self.preapprove_data_institutional_ids)
        self.assertEqual(
            self.get_participation_count_by_status(
                participation_status.active), expected_participation_count)

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
            with self.temporarily_switch_to_user(self.non_participation_user1):
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

            with self.temporarily_switch_to_user(self.non_participation_user1):
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


# vim: foldmethod=marker
