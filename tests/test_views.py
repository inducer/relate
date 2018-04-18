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
import datetime
import unittest

from django.test import TestCase, RequestFactory
from django.test.utils import override_settings
from django.urls import reverse
from django.utils.timezone import now, timedelta
from django import http

from course import views, constants

from tests.base_test_mixins import (
    CoursesTestMixinBase, SingleCourseTestMixin, HackRepoMixin
)
from tests.test_auth import AuthTestMixin
from tests.utils import mock
from tests import factories

DATE_TIME_PICKER_TIME_FORMAT = "%Y-%m-%d %H:%M"

RELATE_FACILITIES = {
    # intentionally to be different from local_settings_example.py
    "test_center1": {
        "ip_ranges": [
            "192.168.100.0/24",
            ],
        "exams_only": False,
    },
}


class TestSetFakeTime(SingleCourseTestMixin, TestCase):
    fake_time = datetime.datetime(2038, 12, 31, 0, 0, 0, 0)
    set_fake_time_data = {"time": fake_time.strftime(DATE_TIME_PICKER_TIME_FORMAT),
                          "set": ['']}
    unset_fake_time_data = {"time": set_fake_time_data["time"], "unset": ['']}

    def test_set_fake_time_by_anonymous(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_set_fake_time()
            self.assertEqual(resp.status_code, 302)

            resp = self.post_set_fake_time(self.set_fake_time_data, follow=False)
            self.assertEqual(resp.status_code, 302)
            self.assertSessionFakeTimeIsNone(self.c.session)

    def test_set_fake_time_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_set_fake_time()
            self.assertEqual(resp.status_code, 403)

            resp = self.post_set_fake_time(self.set_fake_time_data)
            self.assertEqual(resp.status_code, 403)
            self.assertSessionFakeTimeIsNone(self.c.session)

    def test_set_fake_time_by_instructor(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.get_set_fake_time()
            self.assertEqual(resp.status_code, 200)

            # set fake time
            resp = self.post_set_fake_time(self.set_fake_time_data)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionFakeTimeEqual(self.c.session, self.fake_time)

            # revisit the page, just to make sure it works
            resp = self.get_set_fake_time()
            self.assertEqual(resp.status_code, 200)

            # unset fake time
            resp = self.post_set_fake_time(self.unset_fake_time_data)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionFakeTimeIsNone(self.c.session)

    def test_set_fake_time_by_instructor_when_impersonating(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.get_set_fake_time()
            self.assertEqual(resp.status_code, 200)

            self.post_impersonate(impersonatee=self.student_participation.user)

            # set fake time
            resp = self.post_set_fake_time(self.set_fake_time_data)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionFakeTimeEqual(self.c.session, self.fake_time)

            # unset fake time
            resp = self.post_set_fake_time(self.unset_fake_time_data)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionFakeTimeIsNone(self.c.session)

    def test_form_invalid(self):
        with mock.patch("course.views.FakeTimeForm.is_valid") as mock_is_valid:
            mock_is_valid.return_value = False
            with self.temporarily_switch_to_user(self.instructor_participation.user):
                resp = self.post_set_fake_time(self.set_fake_time_data)
                self.assertEqual(resp.status_code, 200)

                # fake failed
                self.assertSessionFakeTimeIsNone(self.c.session)


@override_settings(RELATE_FACILITIES=RELATE_FACILITIES)
class TestSetPretendFacilities(SingleCourseTestMixin, TestCase):
    set_pretend_facilities_data = {
        "facilities": ["test_center1"],
        "custom_facilities": [],
        "add_pretend_facilities_header": ["on"],
        "set": ['']}
    unset_pretend_facilities_data = set_pretend_facilities_data.copy()
    unset_pretend_facilities_data.pop("set")
    unset_pretend_facilities_data["unset"] = ['']

    def test_pretend_facilities_by_anonymous(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_set_pretend_facilities()
            self.assertEqual(resp.status_code, 302)

            resp = self.post_set_pretend_facilities(
                self.set_pretend_facilities_data, follow=False)
            self.assertEqual(resp.status_code, 302)
            self.assertSessionPretendFacilitiesIsNone(self.c.session)

    def test_pretend_facilities_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_set_pretend_facilities()
            self.assertEqual(resp.status_code, 403)

            resp = self.post_set_pretend_facilities(
                self.set_pretend_facilities_data)
            self.assertEqual(resp.status_code, 403)
            self.assertSessionPretendFacilitiesIsNone(self.c.session)

    def test_pretend_facilities_by_instructor(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.get_set_pretend_facilities()
            self.assertEqual(resp.status_code, 200)

            resp = self.post_set_pretend_facilities(
                self.set_pretend_facilities_data)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionPretendFacilitiesContains(self.c.session,
                                                        "test_center1")

            # revisit the page, just to make sure it works
            resp = self.get_set_pretend_facilities()
            self.assertEqual(resp.status_code, 200)

            resp = self.post_set_pretend_facilities(
                self.unset_pretend_facilities_data)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionPretendFacilitiesIsNone(self.c.session)

    def test_pretend_facilities_by_instructor_when_impersonating(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):

            self.post_impersonate(impersonatee=self.student_participation.user)

            resp = self.get_set_pretend_facilities()
            self.assertEqual(resp.status_code, 200)

            resp = self.post_set_pretend_facilities(
                self.set_pretend_facilities_data)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionPretendFacilitiesContains(self.c.session,
                                                        "test_center1")

            resp = self.post_set_pretend_facilities(
                self.unset_pretend_facilities_data)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionPretendFacilitiesIsNone(self.c.session)

    def test_form_invalid(self):
        with mock.patch("course.views.FakeFacilityForm.is_valid") as mock_is_valid:
            mock_is_valid.return_value = False
            with self.temporarily_switch_to_user(self.instructor_participation.user):
                resp = self.post_set_pretend_facilities(
                    self.set_pretend_facilities_data)
                self.assertEqual(resp.status_code, 200)

                # pretending failed
                self.assertSessionPretendFacilitiesIsNone(self.c.session)


class TestEditCourse(SingleCourseTestMixin, TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_non_auth_edit_get(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_edit_course()
        self.assertTrue(resp.status_code, 404)

    def test_non_auth_edit_post(self):
        with self.temporarily_switch_to_user(None):
            resp = self.post_edit_course(data={})
        self.assertTrue(resp.status_code, 404)

    def test_student_edit_get(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_edit_course()
        self.assertTrue(resp.status_code, 404)

    def test_student_edit_post(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.post_edit_course(data={})
        self.assertTrue(resp.status_code, 404)

    def test_instructor_edit_get(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.get_edit_course()
        self.assertTrue(resp.status_code, 200)

    def test_set_up_new_course_form_invalid(self):
        for field_name in ["name", "number", "time_period",
                           "git_source", "from_email", "notify_email"]:
            form_data = self.copy_course_dict_and_set_attrs_for_post()
            del form_data[field_name]
            request = self.rf.post(self.get_set_up_new_course_url(), data=form_data)
            request.user = self.instructor_participation.user
            form = views.EditCourseForm(request.POST)
            self.assertFalse(form.is_valid())

    def test_instructor_edit_post_unchanged(self):
        # test when form data is the same with current instance,
        # the message shows "no change"
        with mock.patch('course.views.EditCourseForm.is_valid') as mock_is_valid, \
            mock.patch('course.views.EditCourseForm.has_changed') as mock_changed, \
            mock.patch('course.views.messages') as mock_messages,\
            mock.patch("course.views.render_course_page"),\
                mock.patch("course.views._") as mock_gettext:

            mock_is_valid.return_value = True
            mock_changed.return_value = False
            mock_gettext.side_effect = lambda x: x
            request = self.rf.post(self.get_edit_course_url(),
                                   data=mock.MagicMock())
            request.user = self.instructor_participation.user
            course_identifier = self.get_default_course_identifier()
            resp = views.edit_course(request, course_identifier)
            self.assertTrue(resp.status_code, 200)
            self.assertTrue(mock_messages.add_message.call_count, 1)
            self.assertIn("No change was made on the settings.",
                          mock_messages.add_message.call_args[0])

    def test_instructor_edit_post_saved(self):
        # test when form data is_valid and different with the current instance,
        # the message shows "success"
        with mock.patch('course.views.EditCourseForm.is_valid') as mock_is_valid, \
            mock.patch('course.views.EditCourseForm.has_changed') as mock_changed, \
            mock.patch('course.views.EditCourseForm.save'), \
            mock.patch('course.views.messages') as mock_messages,\
            mock.patch("course.views.render_course_page"),\
                mock.patch("course.views._") as mock_gettext:

            mock_is_valid.return_value = True
            mock_changed.return_value = True
            mock_gettext.side_effect = lambda x: x
            request = self.rf.post(self.get_edit_course_url(),
                                   data=mock.MagicMock())
            request.user = self.instructor_participation.user
            course_identifier = self.get_default_course_identifier()
            resp = views.edit_course(request, course_identifier)
            self.assertTrue(resp.status_code, 200)
            self.assertTrue(mock_messages.add_message.call_count, 1)
            self.assertIn("Successfully updated course settings.",
                          mock_messages.add_message.call_args[0])

    @override_settings(LANGUAGES=(("en-us", "English"),))
    def test_instructor_edit_post_saved_default(self):
        # test when form is valid, the message show success
        self.course.force_lang = "en-us"
        self.course.save()
        data = self.copy_course_dict_and_set_attrs_for_post({"force_lang": ""})
        with mock.patch('course.views.EditCourseForm.save') as mock_save, \
            mock.patch('course.views.messages') as mock_messages,\
            mock.patch("course.views.render_course_page"),\
                mock.patch("course.views._") as mock_gettext:

            mock_gettext.side_effect = lambda x: x
            request = self.rf.post(self.get_edit_course_url(),
                                   data=data)
            request.user = self.instructor_participation.user
            course_identifier = self.get_default_course_identifier()
            resp = views.edit_course(request, course_identifier)
            self.assertTrue(resp.status_code, 200)
            self.assertTrue(mock_save.call_count, 1)
            self.assertTrue(mock_messages.add_message.call_count, 1)
            self.assertIn("Successfully updated course settings.",
                          mock_messages.add_message.call_args[0])

    @override_settings(LANGUAGES=(("en-us", "English"),))
    def test_instructor_edit_db_saved_default(self):
        # test force_lang can be an empty string (default value)
        self.course.force_lang = "en-us"
        self.course.save()

        self.course.force_lang = ""
        self.course.save()
        self.assertEqual(self.course.force_lang, "")

    def test_instructor_post_save_spaces_as_force_lang(self):
        # current force_lang is "", testing that the save won't occur
        data = self.copy_course_dict_and_set_attrs_for_post({"force_lang": "   "})
        with mock.patch('course.views.EditCourseForm.save') as mock_form_save, \
            mock.patch('course.views.messages') as mock_messages,\
            mock.patch("course.views.render_course_page"),\
                mock.patch("course.views._") as mock_gettext:

            mock_gettext.side_effect = lambda x: x
            request = self.rf.post(self.get_edit_course_url(),
                                   data=data)
            request.user = self.instructor_participation.user
            course_identifier = self.get_default_course_identifier()
            resp = views.edit_course(request, course_identifier)
            self.assertEqual(mock_form_save.call_count, 0)
            self.assertTrue(resp.status_code, 200)
            self.assertTrue(mock_messages.add_message.call_count, 1)
            self.assertIn("No change was made on the settings.",
                          mock_messages.add_message.call_args[0])

    def test_instructor_db_save_spaces_as_force_lang(self):
        # current force_lang is "", testing that the force_lang is still ""
        self.course.force_lang = "   "
        self.course.save()
        self.course.refresh_from_db()
        self.assertEqual(len(self.course.force_lang), 0)

    def test_instructor_edit_post_form_invalid(self):
        with mock.patch('course.views.EditCourseForm.is_valid') as mock_is_valid, \
            mock.patch('course.views.messages') as mock_messages,\
            mock.patch("course.views.render_course_page"),\
                mock.patch("course.views._") as mock_gettext:

            mock_is_valid.return_value = False
            mock_gettext.side_effect = lambda x: x
            request = self.rf.post(self.get_edit_course_url(),
                                   data=mock.MagicMock())
            request.user = self.instructor_participation.user
            course_identifier = self.get_default_course_identifier()
            resp = views.edit_course(request, course_identifier)
            self.assertTrue(resp.status_code, 200)
            self.assertTrue(mock_messages.add_message.call_count, 1)
            self.assertIn("Failed to update course settings.",
                          mock_messages.add_message.call_args[0])

    def test_instructor_db_save_invalid_force_lang(self):
        # test db save failure
        self.course.force_lang = "invalid_lang"
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.course.save()


class GenerateSshKeypairTest(CoursesTestMixinBase, AuthTestMixin, TestCase):
    def get_generate_ssh_keypair_url(self):
        return reverse("relate-generate_ssh_keypair")

    def test_anonymous(self):
        with self.temporarily_switch_to_user(None):
            resp = self.c.get(self.get_generate_ssh_keypair_url())
            self.assertEqual(resp.status_code, 302)

            expected_redirect_url = self.get_sign_in_choice_url(
                redirect_to=self.get_generate_ssh_keypair_url())

            self.assertRedirects(resp, expected_redirect_url,
                                 fetch_redirect_response=False)

    def test_not_staff(self):
        user = factories.UserFactory()
        assert not user.is_staff
        with self.temporarily_switch_to_user(user):
            resp = self.c.get(self.get_generate_ssh_keypair_url())
            self.assertEqual(resp.status_code, 403)

    def test_success(self):
        user = factories.UserFactory()
        user.is_staff = True
        user.save()
        with self.temporarily_switch_to_user(user):
            resp = self.c.get(self.get_generate_ssh_keypair_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextContains(
                resp, "public_key",
                ["-----BEGIN RSA PRIVATE KEY-----",
                 "-----END RSA PRIVATE KEY-----"], in_bulk=True)
            self.assertResponseContextContains(
                resp, "private_key",
                ["ssh-rsa", "relate-course-key"], in_bulk=True)


class HomeTest(CoursesTestMixinBase, TestCase):
    # test views.home

    def test(self):
        course1 = factories.CourseFactory(hidden=False)
        course2 = factories.CourseFactory(
            identifier="course2", hidden=True)
        course3 = factories.CourseFactory(listed=False,
            identifier="course3", hidden=False)
        course4 = factories.CourseFactory(
            identifier="course4", hidden=False, end_date=now() - timedelta(days=1))

        user = factories.UserFactory()
        factories.ParticipationFactory(
            course=course1, user=user, roles=["instructor"])
        factories.ParticipationFactory(
            course=course2, user=user, roles=["instructor"])
        factories.ParticipationFactory(
            course=course3, user=user, roles=["instructor"])

        with self.temporarily_switch_to_user(None):
            resp = self.c.get("/")
        self.assertResponseContextEqual(resp, "current_courses", [course1])
        self.assertResponseContextEqual(resp, "past_courses", [course4])

        with self.temporarily_switch_to_user(user):
            resp = self.c.get("/")
            self.assertResponseContextEqual(
                resp, "current_courses", [course1, course2])
            self.assertResponseContextEqual(resp, "past_courses", [course4])


class CheckCourseStateTest(SingleCourseTestMixin, TestCase):
    # test views.check_course_state
    def test_course_not_hidden(self):
        views.check_course_state(self.course, None)
        views.check_course_state(self.course, self.student_participation)
        views.check_course_state(self.course, self.ta_participation)
        views.check_course_state(self.course, self.instructor_participation)

    def test_course_hidden(self):
        self.course.hidden = True
        self.course.save()
        with self.assertRaises(views.PermissionDenied):
            views.check_course_state(self.course, None)

        with self.assertRaises(views.PermissionDenied):
            views.check_course_state(self.course, self.student_participation)

        views.check_course_state(self.course, self.ta_participation)
        views.check_course_state(self.course, self.instructor_participation)


class StaticPageTest(SingleCourseTestMixin, TestCase):
    # test views.static_page
    def get_static_page_url(self, page_path, course_identifier=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        return reverse("relate-content_page",
                       kwargs={"course_identifier": course_identifier,
                               "page_path": page_path})

    def get_static_page(self, page_path, course_identifier=None):
        return self.c.get(self.get_static_page_url(page_path, course_identifier))

    def test_success(self):
        resp = self.get_static_page("test")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp, '<h1>Demo page</h1>', html=True)
        self.assertContains(
            resp, 'I am just a simple demo page. Go back to the '
                  '<a href="/course/test-course/">course page</a>?')

    def test_404(self):
        resp = self.get_static_page("hello")
        self.assertEqual(resp.status_code, 404)


class CoursePageTest(SingleCourseTestMixin, TestCase):
    # test views.course_page

    def setUp(self):
        super(CoursePageTest, self).setUp()
        fake_add_message = mock.patch('course.views.messages.add_message')
        self.mock_add_message = fake_add_message.start()
        self.addCleanup(fake_add_message.stop)

    # {{{ test show enroll button
    def test_student_no_enroll_button(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "show_enroll_button", False)

    def test_anonymous_show_enroll_button(self):
        with self.temporarily_switch_to_user(None):
            resp = self.c.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "show_enroll_button", True)

    def test_non_participation_show_enroll_button(self):
        user = factories.UserFactory()
        with self.temporarily_switch_to_user(user):
            resp = self.c.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "show_enroll_button", True)

    def test_requested_not_show_enroll_button(self):
        requested = factories.ParticipationFactory(
            course=self.course, status=constants.participation_status.requested)
        with self.temporarily_switch_to_user(requested.user):
            resp = self.c.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "show_enroll_button", False)

        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertIn(
            "Your enrollment request is pending. You will be "
            "notified once it has been acted upon.",
            self.mock_add_message.call_args[0])

    def test_requested_hint_for_set_instid(self):
        requested = factories.ParticipationFactory(
            course=self.course, status=constants.participation_status.requested)
        factories.ParticipationPreapprovalFactory(
            course=self.course, institutional_id="inst_id1234")
        with self.temporarily_switch_to_user(requested.user):
            resp = self.c.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "show_enroll_button", False)

        self.assertEqual(self.mock_add_message.call_count, 2)
        self.assertIn(
            "Your institutional ID is not verified or "
            "preapproved. Please contact your course "
            "staff.",
            self.mock_add_message.call_args[0])
        self.mock_add_message.reset_mock()

        # remove course verify inst_id requirements
        self.course.preapproval_require_verified_inst_id = False
        self.course.save()

        with self.temporarily_switch_to_user(requested.user):
            resp = self.c.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "show_enroll_button", False)

        self.assertEqual(self.mock_add_message.call_count, 1)
        self.mock_add_message.reset_mock()

        # remove user inst_id
        requested.user.institutional_id = ""
        requested.user.save()
        with self.temporarily_switch_to_user(requested.user):
            resp = self.c.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "show_enroll_button", False)

        self.assertEqual(self.mock_add_message.call_count, 2)
        self.assertIn(
            "This course uses institutional ID for enrollment preapproval, "
            "please <a href='/profile/?referer=/course/test-course/"
            "&set_inst_id=1' role='button' class='btn btn-md btn-primary'>"
            "fill in your institutional ID &nbsp;&raquo;</a> in your profile.",
            self.mock_add_message.call_args[0])

    # }}}


class GetMediaTest(SingleCourseTestMixin, TestCase):
    # test views.get_media
    # currently only mock test, because there's no media in the sample repo

    def get_media_url(self, media_path, course_identifier=None, commit_sha=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        if commit_sha is None:
            commit_sha = self.course.active_git_commit_sha

        return reverse("relate-get_media",
                       kwargs={"course_identifier": course_identifier,
                               "commit_sha": commit_sha,
                               "media_path": media_path})

    def get_media_view(self, media_path, course_identifier=None, commit_sha=None):
        return self.c.get(
            self.get_media_url(media_path, course_identifier, commit_sha))

    def test(self):
        resp = self.get_media_view("foo.jpg")
        self.assertEqual(resp.status_code, 404)

    def test_func_call(self):
        with mock.patch(
                "course.views.get_repo_file_response") as mock_get_repo_file_resp:
            mock_get_repo_file_resp.return_value = http.HttpResponse("hi")
            resp = self.get_media_view("foo.jpg")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(mock_get_repo_file_resp.call_count, 1)

    def test_course_does_not_exist_404(self):
        with mock.patch(
                "course.views.get_repo_file_response") as mock_get_repo_file_resp:
            mock_get_repo_file_resp.return_value = http.HttpResponse("hi")
            resp = self.get_media_view("foo.jpg", course_identifier="no-course")
            self.assertEqual(resp.status_code, 404)
            self.assertEqual(mock_get_repo_file_resp.call_count, 0)


class GetRepoFileTestMixin(SingleCourseTestMixin):
    # test views.get_repo_file and  views.get_current_repo_file
    def get_repo_file_url(self, path, course_identifier=None, commit_sha=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        if commit_sha is None:
            commit_sha = self.course.active_git_commit_sha

        return reverse("relate-get_repo_file",
                       kwargs={"course_identifier": course_identifier,
                               "commit_sha": commit_sha,
                               "path": path})

    def get_repo_file_view(self, path, course_identifier=None, commit_sha=None):
        return self.c.get(
            self.get_repo_file_url(path, course_identifier, commit_sha))

    def get_current_repo_file_url(self, path, course_identifier=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        return reverse("relate-get_current_repo_file",
                       kwargs={"course_identifier": course_identifier,
                               "path": path})

    def get_current_repo_file_view(self, path, course_identifier=None):
        return self.c.get(
            self.get_current_repo_file_url(path, course_identifier))


@unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
class GetRepoFileTest(GetRepoFileTestMixin, TestCase):
    # test views.get_repo_file
    def test_file_not_exist(self):

        repo_file = "images/file_not_exist.png"
        tup = ((None, 404),
               (self.student_participation.user, 404),
               (self.ta_participation.user, 404),
               (self.instructor_participation.user, 404))
        for user, status_code in tup:
            with self.subTest(user=user):
                with self.temporarily_switch_to_user(user):
                    resp = self.get_repo_file_view(repo_file)
                    self.assertEqual(resp.status_code, status_code)

                    resp = self.get_current_repo_file_view(repo_file)
                    self.assertEqual(resp.status_code, status_code)

    def test_accessible_by_unenrolled_and_above_wildcard(self):
        """
        This make sure file name with wildcard character "*.png" works
            unenrolled:
                - "*.png"
        """
        repo_file = "images/cc.png"
        tup = ((None, 200),
               (self.student_participation.user, 200),
               (self.ta_participation.user, 200),
               (self.instructor_participation.user, 200))
        for user, status_code in tup:
            with self.subTest(user=user):
                with self.temporarily_switch_to_user(user):
                    resp = self.get_repo_file_view(repo_file)
                    self.assertEqual(resp.status_code, status_code)

                    resp = self.get_current_repo_file_view(repo_file)
                    self.assertEqual(resp.status_code, status_code)

    def test_commit_sha_not_exist(self):
        repo_file = "images/django-logo.png"
        tup = ((None, 403),
               (self.student_participation.user, 403),
               (self.ta_participation.user, 403),
               (self.instructor_participation.user, 403))
        for user, status_code in tup:
            with self.subTest(user=user):
                with self.temporarily_switch_to_user(user):
                    resp = self.get_repo_file_view(repo_file, commit_sha="123abc")
                    self.assertEqual(resp.status_code, status_code)

    def test_content_type(self):
        tup = (
            ("images/cc.png", "image/png"),
            ("images/classroom.jpeg", "image/jpeg"),
            ("pdfs/sample.pdf", "application/pdf"),
            ("ipynbs/Ipynb_example.ipynb", "application/octet-stream"),
        )
        for repo_file, content_type in tup:
            with self.subTest(repo_file=repo_file):
                resp = self.get_repo_file_view(repo_file)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp["Content-Type"], content_type)

                resp = self.get_current_repo_file_view(repo_file)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp["Content-Type"], content_type)


@unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
class GetRepoFileTestMocked(GetRepoFileTestMixin, HackRepoMixin, TestCase):
    """
    Test views.get_repo_file, with get_repo_blob mocked as class level,
    the purpose is to test role permissions to repo files

        unenrolled:
        - "cc.png"

        in_exam:
        - "*.jpeg"

        ta:
        - "django-logo.png"

    """

    initial_commit_sha = "abcdef001"

    def test_accessible_by_unenrolled_and_above_fullname(self):
        repo_file = "images/cc.png"
        tup = ((None, 200),
               (self.student_participation.user, 200),
               (self.ta_participation.user, 200),
               (self.instructor_participation.user, 200))
        for user, status_code in tup:
            with self.subTest(user=user):
                with self.temporarily_switch_to_user(user):
                    resp = self.get_repo_file_view(repo_file)
                    self.assertEqual(resp.status_code, status_code)

                    resp = self.get_current_repo_file_view(repo_file)
                    self.assertEqual(resp.status_code, status_code)

    def test_accessible_by_ta_and_above_fullname(self):
        repo_file = "images/django-logo.png"
        tup = ((None, 403),
               (self.student_participation.user, 403),
               (self.ta_participation.user, 200),
               (self.instructor_participation.user, 200))
        for user, status_code in tup:
            with self.subTest(user=user):
                with self.temporarily_switch_to_user(user):
                    resp = self.get_repo_file_view(repo_file)
                    self.assertEqual(resp.status_code, status_code)

                    resp = self.get_current_repo_file_view(repo_file)
                    self.assertEqual(resp.status_code, status_code)

    def test_accessible_in_exam(self):
        repo_file = "images/classroom.jpeg"
        tup = ((None, 403),
               (self.student_participation.user, 403),
               (self.ta_participation.user, 200),
               (self.instructor_participation.user, 200))
        for user, status_code in tup:
            with self.subTest(user=user):
                with self.temporarily_switch_to_user(user):
                    resp = self.get_repo_file_view(repo_file)
                    self.assertEqual(resp.status_code, status_code)

                    resp = self.get_current_repo_file_view(repo_file)
                    self.assertEqual(resp.status_code, status_code)

    def test_in_exam(self):
        req = RequestFactory()
        repo_file = "images/classroom.jpeg"
        request = req.get(self.get_repo_file_url(repo_file))
        request.relate_exam_lockdown = True

        from django.contrib.auth.models import AnonymousUser
        users = (AnonymousUser(),
                 self.student_participation.user,
                 self.ta_participation.user,
                 self.instructor_participation.user)

        for user in users:
            request.user = user
            with self.subTest(user=user):
                response = views.get_repo_file(
                    request, self.course.identifier,
                    self.course.active_git_commit_sha, repo_file)
                self.assertEqual(response.status_code, 200)

# vim: fdm=marker
