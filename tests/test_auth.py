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
from django.contrib import messages
from course.auth import get_impersonable_user_qset
from course.models import FlowPageVisit, ParticipationPermission

from .base_test_mixins import (
    SingleCoursePageTestMixin, TwoCourseTestMixin,
    FallBackStorageMessageTestMixin, TWO_COURSE_SETUP_LIST,
    NONE_PARTICIPATION_USER_CREATE_KWARG_LIST)

NOT_IMPERSONATING_MESSAGE = "Not currently impersonating anyone."
NO_LONGER_IMPERSONATING_MESSAGE = "No longer impersonating anyone."
ALREADY_IMPERSONATING_SOMEONE_MESSAGE = "Already impersonating someone."
ERROR_WHILE_IMPERSONATING_MESSAGE = "Error while impersonating."
IMPERSONATE_FORM_ERROR_NOT_VALID_USER_MSG = (
    "Select a valid choice. That choice is "
    "not one of the available choices.")


class ImpersonateTest(SingleCoursePageTestMixin,
                      FallBackStorageMessageTestMixin, TestCase):

    def test_impersonate_by_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_impersonate()
            self.assertEqual(resp.status_code, 403)

            resp = self.post_impersonate(
                impersonatee=self.student_participation.user)
            self.assertEqual(resp.status_code, 403)

            resp = self.get_stop_impersonate()
            self.assertEqual(resp.status_code, 403)

            resp = self.post_stop_impersonate()
            self.assertEqual(resp.status_code, 403)

    def test_impersonate_by_student(self):
        user = self.student_participation.user
        impersonatable = get_impersonable_user_qset(user)
        self.assertEqual(impersonatable.count(), 0)

        with self.temporarily_switch_to_user(user):
            resp = self.get_impersonate()
            self.assertEqual(resp.status_code, 403)

            resp = self.post_impersonate(
                impersonatee=self.student_participation.user)
            self.assertEqual(resp.status_code, 403)
            resp = self.get_stop_impersonate()
            self.assertEqual(resp.status_code, 403)
            self.assertIsNone(self.c.session.get("impersonate_id"))

            resp = self.post_stop_impersonate()
            self.assertEqual(resp.status_code, 403)

    def test_impersonate_by_ta(self):
        user = self.ta_participation.user
        impersonatable = get_impersonable_user_qset(user)
        self.assertEqual(impersonatable.count(), 1)
        self.assertNotIn(self.instructor_participation.user, impersonatable)

        with self.temporarily_switch_to_user(user):
            resp = self.get_impersonate()
            self.assertEqual(resp.status_code, 200)

            resp = self.post_impersonate(
                impersonatee=self.student_participation.user)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(self.c.session["impersonate_id"],
                             self.student_participation.user.pk)

            # re-impersonate without stop_impersonating
            resp = self.post_impersonate(
                impersonatee=self.student_participation.user)
            # because the request.user is the impernatee (student)
            # who has no pperm
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(self.c.session["impersonate_id"],
                             self.student_participation.user.pk)

            resp = self.get_stop_impersonate()
            self.assertEqual(resp.status_code, 200)

            # stop_impersonating
            resp = self.post_stop_impersonate()
            self.assertIsNone(self.c.session.get("impersonate_id"))
            self.assertResponseMessageLevelsEqual(resp, [messages.INFO])
            self.assertResponseMessagesEqual(resp, NO_LONGER_IMPERSONATING_MESSAGE)

            # fail re-stop_impersonating
            resp = self.post_stop_impersonate()
            self.assertEqual(resp.status_code, 200)
            self.assertResponseMessageLevelsEqual(resp, [messages.ERROR])
            self.assertResponseMessagesEqual(resp, NOT_IMPERSONATING_MESSAGE)

            # not allowed to impersonate instructor
            resp = self.post_impersonate(
                impersonatee=self.instructor_participation.user)

            self.assertEqual(resp.status_code, 200)
            self.assertFormError(resp, 'form', 'user',
                                 IMPERSONATE_FORM_ERROR_NOT_VALID_USER_MSG)
            self.assertIsNone(self.c.session.get("impersonate_id"))

            # not allowed to impersonate self
            resp = self.post_impersonate(
                impersonatee=user)
            self.assertEqual(resp.status_code, 200)
            self.assertFormError(resp, 'form', 'user',
                                 IMPERSONATE_FORM_ERROR_NOT_VALID_USER_MSG)
            self.assertIsNone(self.c.session.get("impersonate_id"))

    def test_impersonate_by_superuser(self):
        user = self.superuser
        impersonatable = get_impersonable_user_qset(user)
        self.assertEqual(impersonatable.count(), 3)

        with self.temporarily_switch_to_user(user):
            resp = self.post_impersonate(
                impersonatee=self.instructor_participation.user)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(self.c.session["impersonate_id"],
                             self.instructor_participation.user.pk)

    def test_impersonate_by_instructor(self):
        user = self.instructor_participation.user
        impersonatable = get_impersonable_user_qset(user)
        self.assertEqual(impersonatable.count(), 2)

        with self.temporarily_switch_to_user(user):
            resp = self.get_impersonate()
            self.assertEqual(resp.status_code, 200)

            # first impersonate ta who has pperm
            resp = self.post_impersonate(
                impersonatee=self.ta_participation.user)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(self.c.session["impersonate_id"],
                             self.ta_participation.user.pk)

            # then impersonate student without stop_impersonating,
            # this will fail
            resp = self.post_impersonate(
                impersonatee=self.student_participation.user)
            self.assertEqual(resp.status_code, 200)
            self.assertResponseMessageLevelsEqual(resp, [messages.ERROR])
            self.assertResponseMessagesEqual(
                resp, ALREADY_IMPERSONATING_SOMEONE_MESSAGE)
            self.assertEqual(self.c.session["impersonate_id"],
                             self.ta_participation.user.pk)

            resp = self.get_stop_impersonate()
            self.assertEqual(resp.status_code, 200)

            # stop_impersonating
            resp = self.post_stop_impersonate()
            self.assertEqual(resp.status_code, 200)
            self.assertResponseMessageLevelsEqual(resp, [messages.INFO])
            self.assertResponseMessagesEqual(resp, NO_LONGER_IMPERSONATING_MESSAGE)

            # re-stop_impersonating
            resp = self.post_stop_impersonate()
            self.assertEqual(resp.status_code, 200)
            self.assertResponseMessageLevelsEqual(resp, [messages.ERROR])
            self.assertResponseMessagesEqual(resp, NOT_IMPERSONATING_MESSAGE)

    def test_impersonate_error_none_user(self):
        with self.temporarily_switch_to_user(self.ta_participation.user):
            self.post_impersonate(
                impersonatee=self.student_participation.user)
            session = self.c.session
            session["impersonate_id"] = None
            session.save()

            resp = self.c.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseMessageLevelsEqual(resp, [messages.ERROR])
            self.assertResponseMessagesEqual(resp,
                                             ERROR_WHILE_IMPERSONATING_MESSAGE)

    def test_impersonatee_error_none_existing_user(self):
        with self.temporarily_switch_to_user(self.ta_participation.user):
            self.post_impersonate(
                impersonatee=self.student_participation.user)
            session = self.c.session
            session["impersonate_id"] = 100
            session.save()

            resp = self.c.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseMessageLevelsEqual(resp, [messages.ERROR])
            self.assertResponseMessagesEqual(resp,
                                             ERROR_WHILE_IMPERSONATING_MESSAGE)

    def test_impersonate_error_no_impersonatable(self):
        with self.temporarily_switch_to_user(self.ta_participation.user):
            self.post_impersonate(
                impersonatee=self.student_participation.user)

            # drop the only impersonatable participation
            from course.constants import participation_status
            self.student_participation.status = participation_status.dropped
            self.student_participation.save()

            resp = self.c.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseMessageLevelsEqual(resp, [messages.ERROR])
            self.assertResponseMessagesEqual(resp,
                                             ERROR_WHILE_IMPERSONATING_MESSAGE)

    def test_impersonator_flow_page_visit(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            self.start_flow("quiz-test")
            self.c.get(self.get_page_url_by_ordinal(page_ordinal=0))
            self.assertEqual(FlowPageVisit.objects.count(), 1)
            first_visit = FlowPageVisit.objects.first()
            self.assertFalse(first_visit.is_impersonated())
            self.assertIsNone(first_visit.impersonated_by)

        with self.temporarily_switch_to_user(self.ta_participation.user):
            resp = self.c.get(self.get_page_url_by_ordinal(page_ordinal=0))
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(FlowPageVisit.objects.count(), 2)
            second_visit = FlowPageVisit.objects.all().order_by('-pk')[0]

            # this visit is not impersonated
            self.assertFalse(second_visit.is_impersonated())
            self.assertIsNone(second_visit.impersonated_by)

            # this visit is not impersonated
            self.post_impersonate(impersonatee=self.student_participation.user)
            resp = self.c.get(self.get_page_url_by_ordinal(page_ordinal=0))
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(FlowPageVisit.objects.count(), 3)
            second_visit = FlowPageVisit.objects.all().order_by('-pk')[0]
            self.assertTrue(second_visit.is_impersonated())
            self.assertEqual(second_visit.impersonated_by,
                             self.ta_participation.user)


class CrossCourseImpersonateTest(TwoCourseTestMixin,
                                 FallBackStorageMessageTestMixin, TestCase):
    courses_setup_list = TWO_COURSE_SETUP_LIST
    none_participation_user_create_kwarg_list = (
        NONE_PARTICIPATION_USER_CREATE_KWARG_LIST)

    @classmethod
    def setUpTestData(cls):  # noqa
        super(CrossCourseImpersonateTest, cls).setUpTestData()
        cls.extra_participation_user1 = cls.non_participation_users[0]
        cls.create_participation(cls.course2, cls.extra_participation_user1)

    def test_impersonate_across_courses(self):
        user = self.course1_ta_participation.user
        self.assertEqual(self.course1_ta_participation.user,
                         self.course2_ta_participation.user)
        impersonatable = get_impersonable_user_qset(user)
        # one is student_participation.user, another is extra_participation_user1
        # in two courses
        self.assertEqual(impersonatable.count(), 2)

    def test_impersonate_across_courses_pperm_view_masked_profile_403(self):
        """
        view_participant_masked_profile pperm will disable impersonating
        site-wise
        """
        from course.constants import participation_permission as pperm
        pp = ParticipationPermission(
            participation=self.course1_ta_participation,
            permission=pperm.view_participant_masked_profile)
        pp.save()

        user = self.course1_ta_participation.user
        self.assertEqual(self.course1_ta_participation.user,
                         self.course2_ta_participation.user)
        impersonatable = get_impersonable_user_qset(user)
        self.assertEqual(impersonatable.count(), 0)

        with self.temporarily_switch_to_user(user):
            resp = self.get_impersonate()
            self.assertEqual(resp.status_code, 403)
