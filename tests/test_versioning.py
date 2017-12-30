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

from copy import deepcopy
from django.test import TestCase, RequestFactory, mock
from course.models import Course, Participation
from course import versioning

from .base_test_mixins import (
    CoursesTestMixinBase, SINGLE_COURSE_SETUP_LIST,
    FallBackStorageMessageTestMixin)
from .utils import suppress_stdout_decorator


class CourseCreationTest(CoursesTestMixinBase, FallBackStorageMessageTestMixin,
                         TestCase):
    courses_setup_list = []

    @classmethod
    def setUpTestData(cls):  # noqa
        super(CourseCreationTest, cls).setUpTestData()
        cls.instructor = cls.create_user(
            SINGLE_COURSE_SETUP_LIST[0]["participations"][0]["user"])
        cls.add_user_permission(cls.instructor, "add_course")

    def setUp(self):
        super(CourseCreationTest, self).setUp()
        self.rf = RequestFactory()
        self.addCleanup(self.force_remove_all_course_dir)

    def get_set_up_new_course_form_data(self):
        return deepcopy(SINGLE_COURSE_SETUP_LIST[0]["course"])

    @classmethod
    def add_user_permission(cls, user, perm):
        from django.contrib.contenttypes.models import ContentType
        content_type = ContentType.objects.get_for_model(Course)
        from django.contrib.auth.models import Permission
        permission = Permission.objects.get(
            codename=perm, content_type=content_type)
        user.user_permissions.add(permission)

    def test_non_auth_set_up_new_course(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_set_up_new_course()
            self.assertTrue(resp.status_code, 403)

            data = SINGLE_COURSE_SETUP_LIST[0]["course"]
            resp = self.post_create_course(data, raise_error=False,
                                           login_superuser=False)
            self.assertTrue(resp.status_code, 403)
            self.assertEqual(Course.objects.count(), 0)

    def test_set_up_new_course_no_perm(self):
        # create a user which has no perm for creating course
        ta = self.create_user(
            SINGLE_COURSE_SETUP_LIST[0]["participations"][1]["user"])
        self.assertFalse(ta.has_perm("course.add_course"))
        self.assertFalse(ta.has_perm("course.change_course"))
        self.assertFalse(ta.has_perm("course.delete_course"))

        with self.temporarily_switch_to_user(ta):
            resp = self.get_set_up_new_course()
            self.assertTrue(resp.status_code, 403)

            data = self.get_set_up_new_course_form_data()
            resp = self.post_create_course(data, raise_error=False,
                                           login_superuser=False)
            self.assertTrue(resp.status_code, 403)
            self.assertEqual(Course.objects.count(), 0)

    def test_set_up_new_course(self):
        # In this test, we use client instead of request factory to simplify
        # the logic.

        with self.temporarily_switch_to_user(self.instructor):
            # the permission is cached, need to repopulated from db
            resp = self.get_set_up_new_course()
            self.assertTrue(resp.status_code, 200)

            with mock.patch("dulwich.client.GitClient.fetch",
                            return_value={b"HEAD": b"some_commit_sha"}),\
                mock.patch("course.versioning.transfer_remote_refs",
                           return_value=None),\
                mock.patch('course.versioning.messages') as mock_messages,\
                mock.patch("course.validation.validate_course_content",
                           return_value=None):
                data = self.get_set_up_new_course_form_data()

                resp = self.post_create_course(data, raise_error=False,
                                               login_superuser=False)
                self.assertTrue(resp.status_code, 200)
                self.assertEqual(Course.objects.count(), 1)
                self.assertEqual(Participation.objects.count(), 1)
                self.assertEqual(Participation.objects.first().user.username,
                                 "test_instructor")
                self.assertIn("Course content validated, creation succeeded.",
                              mock_messages.add_message.call_args[0])

                from course.enrollment import get_participation_role_identifiers

                # the user who setup the course has role instructor
                self.assertTrue(
                    get_participation_role_identifiers(
                        Course.objects.first(),
                        Participation.objects.first()),
                    "instructor")

    def test_set_up_new_course_form_invalid(self):
        for field_name in ["identifier", "name", "number", "time_period",
                           "git_source", "from_email", "notify_email"]:
            form_data = self.get_set_up_new_course_form_data()
            del form_data[field_name]
            request = self.rf.post(self.get_set_up_new_course_url(), data=form_data)
            request.user = self.instructor
            form = versioning.CourseCreationForm(request.POST)
            self.assertFalse(form.is_valid())

    @suppress_stdout_decorator(suppress_stderr=True)
    def test_set_up_new_course_git_source_invalid(self):
        data = self.get_set_up_new_course_form_data()
        request = self.rf.post(self.get_set_up_new_course_url(), data=data)
        request.user = self.instructor
        with mock.patch("dulwich.client.GitClient.fetch",
                        return_value=None),\
            mock.patch('course.versioning.messages') as mock_messages,\
            mock.patch("course.models.Course.save") as mock_save,\
                mock.patch("course.versioning.render"):
            resp = versioning.set_up_new_course(request)
            self.assertTrue(resp.status_code, 200)
            self.assertEqual(mock_save.call_count, 0)
            self.assertIn("No refs found in remote repository",
                          mock_messages.add_message.call_args[0][2])

    @suppress_stdout_decorator(suppress_stderr=True)
    def test_set_up_new_course_subdir(self):
        data = self.get_set_up_new_course_form_data()
        data["course_root_path"] = "some_dir"
        request = self.rf.post(self.get_set_up_new_course_url(), data=data)
        request.user = self.instructor
        with mock.patch("dulwich.client.GitClient.fetch",
                        return_value={b"HEAD": b"some_commit_sha"}), \
                mock.patch('course.versioning.messages'), \
                mock.patch("course.validation.validate_course_content",
                           return_value=None) as mock_validate, \
                mock.patch("course.models.Course.save"), \
                mock.patch("course.models.Participation.save", return_value=True), \
                mock.patch("course.versioning.render"):
            resp = versioning.set_up_new_course(request)
            from course.content import SubdirRepoWrapper
            self.assertIsInstance(mock_validate.call_args[0][0], SubdirRepoWrapper)
            self.assertTrue(resp.status_code, 200)
