from __future__ import division

__copyright__ = "Copyright (C) 2018 Dong Zhuang"

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

import copy
from django.test import TestCase
from django.urls import reverse
from tests.utils import mock

from tests.base_test_mixins import (
    TwoCoursePageTestMixin, TWO_COURSE_SETUP_LIST)

from course import models
from course.constants import participation_permission as pperm
from course.flow import get_pv_purgeable_courses_for_user_qs

# {{{ make sure the second course has a different instructor
second_course_instructor_dict = {
                    "username": "test_instructor2",
                    "password": "test_instructor2",
                    "email": "test_instructor2@example.com",
                    "first_name": "Test2",
                    "last_name": "Instructor2"}

PURGE_VIEW_TWO_COURSE_SETUP_LIST = copy.deepcopy(TWO_COURSE_SETUP_LIST)

PURGE_VIEW_TWO_COURSE_SETUP_LIST[1]["participations"][0]["user"] \
    = second_course_instructor_dict

# }}}


class PurgeViewMixin(TwoCoursePageTestMixin):
    courses_setup_list = PURGE_VIEW_TWO_COURSE_SETUP_LIST

    @classmethod
    def setUpTestData(cls):  # noqa
        super(PurgeViewMixin, cls).setUpTestData()
        assert cls.course1_instructor_participation.has_permission(
            pperm.use_admin_interface)
        assert cls.course2_instructor_participation.has_permission(
            pperm.use_admin_interface)


class GetPvPurgeableCoursesForUserQs(PurgeViewMixin, TestCase):
    """ test get_pv_purgeable_courses_for_user_qs
    """
    def test_purgeable_qset_superuser(self):
        purgeable_qset = get_pv_purgeable_courses_for_user_qs(self.superuser)
        self.assertTrue(models.Course.objects.count(), purgeable_qset.count())

    def test_purgeable_qset_instructor(self):
        purgeable_qset = get_pv_purgeable_courses_for_user_qs(
            self.course1_instructor_participation.user)
        self.assertEqual(purgeable_qset.count(), 1)
        self.assertTrue(self.course1 in purgeable_qset)

    def test_purgeable_qset_instructor_remove_role_pperm(self):
        """
        This make sure pperm.use_admin_interface is responsible for
        permission of the operation
        """
        perms = models.ParticipationRolePermission.objects.filter(
            role__identifier="instructor",
            permission=pperm.use_admin_interface
        )
        for perm in perms:
            perm.delete()
        purgeable_qset = get_pv_purgeable_courses_for_user_qs(
            self.course2_instructor_participation.user)
        self.assertEqual(purgeable_qset.count(), 0)

    def test_purgeable_qset_ta(self):
        purgeable_qset = get_pv_purgeable_courses_for_user_qs(
            self.course1_ta_participation.user)
        self.assertEqual(purgeable_qset.count(), 0)

    def test_purgeable_qset_student(self):
        purgeable_qset = get_pv_purgeable_courses_for_user_qs(
            self.course1_student_participation.user)
        self.assertEqual(purgeable_qset.count(), 0)


class PurgePageViewDataTest(PurgeViewMixin, TestCase):
    def get_purge_page_view_url(self):
        return reverse("relate-purge_page_view_data")

    def get_purget_page_view(self):
        return self.c.get(self.get_purge_page_view_url())

    def post_purget_page_view(self, course_id, add_submit=True):
        post_data = {}
        if add_submit:
            post_data["submit"] = True
        post_data["course"] = course_id
        return self.c.post(self.get_purge_page_view_url(), data=post_data)

    def test_get_purge_page_view_anonymous(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_purget_page_view()
            self.assertEqual(resp.status_code, 302)

            resp = self.post_purget_page_view(self.course1.pk)
            self.assertEqual(resp.status_code, 302)

    def test_get_purge_page_view_student(self):
        with self.temporarily_switch_to_user(
                self.course1_student_participation.user):
            resp = self.get_purget_page_view()
            self.assertEqual(resp.status_code, 403)

            resp = self.post_purget_page_view(self.course1.pk)
            self.assertEqual(resp.status_code, 403)

    def test_get_purge_page_view_ta(self):
        with self.temporarily_switch_to_user(
                self.course1_ta_participation.user):
            resp = self.get_purget_page_view()
            self.assertEqual(resp.status_code, 403)

            resp = self.post_purget_page_view(self.course1.pk)
            self.assertEqual(resp.status_code, 403)

    def test_purge_page_view_superuser(self):
        with self.temporarily_switch_to_user(self.superuser):
            resp = self.get_purget_page_view()
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(
                resp.context.get("form").fields["course"].queryset.count(), 2)

            with mock.patch("celery.app.task.Task.delay") \
                    as mocked_delay,\
                    mock.patch("course.views.monitor_task"):
                # post without "submit"
                resp = self.post_purget_page_view(self.course1.pk, add_submit=False)

                # Nothing happened
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(mocked_delay.call_count, 0)

                # post with "submit"
                # Manually fake an async result id
                faked_async_result_id = "64907302-3166-43d8-b822"
                mocked_delay.return_value.id = faked_async_result_id

                resp = self.post_purget_page_view(self.course1.pk)
                self.assertRedirects(resp,
                                     reverse("relate-monitor_task",
                                             args=[faked_async_result_id]),
                                     fetch_redirect_response=False)

                self.assertEqual(mocked_delay.call_count, 1)
                self.assertTrue(self.course1.id in mocked_delay.call_args[0])

    def test_purge_page_view_course_not_purgeable(self):
        with self.temporarily_switch_to_user(
                self.course1_instructor_participation.user):
            resp = self.get_purget_page_view()
            self.assertEqual(resp.status_code, 200)
            purgeable_qset = resp.context.get("form").fields["course"].queryset
            self.assertEqual(purgeable_qset.count(), 1)
            self.assertEqual(purgeable_qset[0].identifier, "test-course1")

            # Now we post purge course 2 which is not purgeable by instructor of
            # course 1.
            from celery.exceptions import NotRegistered
            with mock.patch("celery.app.task.Task") as mocked_task:
                try:
                    resp = self.post_purget_page_view(course_id=self.course2.pk)
                except NotRegistered:
                    self.fail("Celery tasks are not expected to run!")

                self.assertEqual(mocked_task.call_count, 0)
                expected_form_field_error_msg = (
                    "Select a valid choice. That choice is not one of "
                    "the available choices.")
                self.assertFormError(resp, "form", "course",
                                     expected_form_field_error_msg)
