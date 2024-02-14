from __future__ import annotations


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

import datetime
import unittest

from celery import states, uuid
from django import http
from django.test import RequestFactory, TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils.timezone import now, timedelta

from course import constants, models, views
from relate.celery import app
from relate.utils import as_local_time
from tests import factories
from tests.base_test_mixins import (
    CoursesTestMixinBase,
    HackRepoMixin,
    MockAddMessageMixing,
    SingleCoursePageTestMixin,
    SingleCourseTestMixin,
)
from tests.constants import DATE_TIME_PICKER_TIME_FORMAT
from tests.test_auth import AuthTestMixin
from tests.utils import mock


RELATE_FACILITIES = {
    # intentionally to be different from local_settings_example.py
    "test_center1": {
        "ip_ranges": [
            "192.168.100.0/24",
            ],
        "exams_only": False,
    },
}


class SetFakeTimeTest(SingleCourseTestMixin, TestCase):
    # test views.set_fake_time
    fake_time = datetime.datetime(2038, 12, 31, 0, 0, 0, 0)
    set_fake_time_data = {"time": fake_time.strftime(DATE_TIME_PICKER_TIME_FORMAT),
                          "set": [""]}
    unset_fake_time_data = {"time": set_fake_time_data["time"], "unset": [""]}

    def test_set_fake_time_by_anonymous(self):
        with self.temporarily_switch_to_user(None):
            # the faking url is not rendered in template
            resp = self.client.get(self.course_page_url)
            self.assertNotContains(resp, self.get_fake_time_url())

            resp = self.get_set_fake_time()
            self.assertEqual(resp.status_code, 302)

            resp = self.post_set_fake_time(self.set_fake_time_data, follow=False)
            self.assertEqual(resp.status_code, 302)
            self.assertSessionFakeTimeIsNone(self.client.session)

    def test_set_fake_time_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            # the faking url is not rendered in template
            resp = self.client.get(self.course_page_url)
            self.assertNotContains(resp, self.get_fake_time_url())

            resp = self.get_set_fake_time()
            self.assertEqual(resp.status_code, 403)

            resp = self.post_set_fake_time(self.set_fake_time_data)
            self.assertEqual(resp.status_code, 403)
            self.assertSessionFakeTimeIsNone(self.client.session)

    def test_set_fake_time_by_instructor(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            # the faking url is rendered in template
            resp = self.client.get(self.course_page_url)
            self.assertContains(resp, self.get_fake_time_url())

            resp = self.get_set_fake_time()
            self.assertEqual(resp.status_code, 200)

            # set fake time
            resp = self.post_set_fake_time(self.set_fake_time_data)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionFakeTimeEqual(self.client.session, self.fake_time)

            # revisit the page, just to make sure it works
            resp = self.get_set_fake_time()
            self.assertEqual(resp.status_code, 200)

            # unset fake time
            resp = self.post_set_fake_time(self.unset_fake_time_data)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionFakeTimeIsNone(self.client.session)

    def test_set_fake_time_by_instructor_when_impersonating(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.get_set_fake_time()
            self.assertEqual(resp.status_code, 200)

            self.post_impersonate_view(impersonatee=self.student_participation.user)
            # the faking url is rendered in template
            resp = self.client.get(self.course_page_url)
            self.assertContains(resp, self.get_fake_time_url())

            # set fake time
            resp = self.post_set_fake_time(self.set_fake_time_data)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionFakeTimeEqual(self.client.session, self.fake_time)

            # unset fake time
            resp = self.post_set_fake_time(self.unset_fake_time_data)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionFakeTimeIsNone(self.client.session)

    def test_form_invalid(self):
        with mock.patch("course.views.FakeTimeForm.is_valid") as mock_is_valid:
            mock_is_valid.return_value = False
            with self.temporarily_switch_to_user(self.instructor_participation.user):
                resp = self.post_set_fake_time(self.set_fake_time_data)
                self.assertEqual(resp.status_code, 200)

                # fake failed
                self.assertSessionFakeTimeIsNone(self.client.session)


class GetNowOrFakeTimeTest(unittest.TestCase):
    # test views.get_now_or_fake_time
    mock_now_value = mock.MagicMock()

    def setUp(self):
        fake_get_fake_time = mock.patch("course.views.get_fake_time")
        self.mock_get_fake_time = fake_get_fake_time.start()
        self.addCleanup(fake_get_fake_time.stop)
        fake_now = mock.patch("django.utils.timezone.now")
        self.mock_now = fake_now.start()
        self.mock_now.return_value = self.mock_now_value
        self.addCleanup(fake_now.stop)
        rf = RequestFactory()
        self.request = rf.get("/")

    def test_fake_time_is_none(self):
        self.mock_get_fake_time.return_value = None
        self.assertEqual(
            views.get_now_or_fake_time(self.request), self.mock_now_value)

    def test_fake_time_is_not_none(self):
        mock_fake_time = mock.MagicMock()
        self.mock_get_fake_time.return_value = mock_fake_time
        self.assertEqual(
            views.get_now_or_fake_time(self.request), mock_fake_time)


@override_settings(RELATE_FACILITIES=RELATE_FACILITIES)
class TestSetPretendFacilities(SingleCourseTestMixin, TestCase):
    set_pretend_facilities_data = {
        "facilities": ["test_center1"],
        "custom_facilities": [],
        "add_pretend_facilities_header": ["on"],
        "set": [""]}
    unset_pretend_facilities_data = set_pretend_facilities_data.copy()
    unset_pretend_facilities_data.pop("set")
    unset_pretend_facilities_data["unset"] = [""]

    def test_pretend_facilities_by_anonymous(self):
        with self.temporarily_switch_to_user(None):
            # the pretending url is not rendered in template
            resp = self.client.get(self.course_page_url)
            self.assertNotContains(resp, self.get_set_pretend_facilities_url())

            resp = self.get_set_pretend_facilities()
            self.assertEqual(resp.status_code, 302)

            resp = self.post_set_pretend_facilities(
                self.set_pretend_facilities_data, follow=False)
            self.assertEqual(resp.status_code, 302)
            self.assertSessionPretendFacilitiesIsNone(self.client.session)

    def test_pretend_facilities_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            # the pretending url is not rendered in template
            resp = self.client.get(self.course_page_url)
            self.assertNotContains(resp, self.get_set_pretend_facilities_url())

            resp = self.get_set_pretend_facilities()
            self.assertEqual(resp.status_code, 403)

            resp = self.post_set_pretend_facilities(
                self.set_pretend_facilities_data)
            self.assertEqual(resp.status_code, 403)
            self.assertSessionPretendFacilitiesIsNone(self.client.session)

    def test_pretend_facilities_by_instructor(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            # the pretending url is rendered in template
            resp = self.client.get(self.course_page_url)
            self.assertContains(resp, self.get_set_pretend_facilities_url())

            resp = self.get_set_pretend_facilities()
            self.assertEqual(resp.status_code, 200)

            resp = self.post_set_pretend_facilities(
                self.set_pretend_facilities_data)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionPretendFacilitiesContains(self.client.session,
                                                        "test_center1")

            # revisit the page, just to make sure it works
            resp = self.get_set_pretend_facilities()
            self.assertEqual(resp.status_code, 200)

            resp = self.post_set_pretend_facilities(
                self.unset_pretend_facilities_data)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionPretendFacilitiesIsNone(self.client.session)

    def test_pretend_facilities_by_instructor_when_impersonating(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):

            self.post_impersonate_view(impersonatee=self.student_participation.user)

            # the pretending url is rendered in template
            resp = self.client.get(self.course_page_url)
            self.assertContains(resp, self.get_set_pretend_facilities_url())

            resp = self.get_set_pretend_facilities()
            self.assertEqual(resp.status_code, 200)

            resp = self.post_set_pretend_facilities(
                self.set_pretend_facilities_data)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionPretendFacilitiesContains(self.client.session,
                                                        "test_center1")

            resp = self.post_set_pretend_facilities(
                self.unset_pretend_facilities_data)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionPretendFacilitiesIsNone(self.client.session)

    def test_form_invalid(self):
        with mock.patch("course.views.FakeFacilityForm.is_valid") as mock_is_valid:
            mock_is_valid.return_value = False
            with self.temporarily_switch_to_user(self.instructor_participation.user):
                resp = self.post_set_pretend_facilities(
                    self.set_pretend_facilities_data)
                self.assertEqual(resp.status_code, 200)

                # pretending failed
                self.assertSessionPretendFacilitiesIsNone(self.client.session)


class TestEditCourse(SingleCourseTestMixin, MockAddMessageMixing, TestCase):

    def setUp(self):
        super().setUp()
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
        with mock.patch("course.views.EditCourseForm.is_valid") as mock_is_valid, \
            mock.patch("course.views.EditCourseForm.has_changed") as mock_changed, \
            mock.patch("course.views.render_course_page"), \
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
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith(
                "No change was made on the settings.")

    def test_instructor_edit_post_saved(self):
        # test when form data is_valid and different with the current instance,
        # the message shows "success"
        with mock.patch("course.views.EditCourseForm.is_valid") as mock_is_valid, \
            mock.patch("course.views.EditCourseForm.has_changed") as mock_changed, \
            mock.patch("course.views.EditCourseForm.save")as mock_save, \
            mock.patch("course.views.render_course_page"), \
                mock.patch("course.views._") as mock_gettext:

            mock_save.return_value = self.course
            mock_is_valid.return_value = True
            mock_changed.return_value = True
            mock_gettext.side_effect = lambda x: x
            request = self.rf.post(self.get_edit_course_url(),
                                   data=mock.MagicMock())
            request.user = self.instructor_participation.user
            course_identifier = self.get_default_course_identifier()
            resp = views.edit_course(request, course_identifier)
            self.assertTrue(resp.status_code, 200)
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith(
                "Successfully updated course settings.")

    @override_settings(LANGUAGES=(("en-us", "English"),))
    def test_instructor_edit_post_saved_default(self):
        # test when form is valid, the message show success
        self.course.force_lang = "en-us"
        self.course.save()
        data = self.copy_course_dict_and_set_attrs_for_post({"force_lang": ""})
        with mock.patch("course.views.EditCourseForm.save") as mock_save, \
            mock.patch("course.views.render_course_page"), \
                mock.patch("course.views._") as mock_gettext:

            mock_gettext.side_effect = lambda x: x
            mock_save.return_value = self.course
            request = self.rf.post(self.get_edit_course_url(),
                                   data=data)
            request.user = self.instructor_participation.user
            course_identifier = self.get_default_course_identifier()
            resp = views.edit_course(request, course_identifier)
            self.assertTrue(resp.status_code, 200)
            self.assertTrue(mock_save.call_count, 1)
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith(
                "Successfully updated course settings.")

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
        with mock.patch("course.views.EditCourseForm.save") as mock_form_save, \
            mock.patch("course.views.render_course_page"), \
                mock.patch("course.views._") as mock_gettext:

            mock_gettext.side_effect = lambda x: x
            request = self.rf.post(self.get_edit_course_url(),
                                   data=data)
            request.user = self.instructor_participation.user
            course_identifier = self.get_default_course_identifier()
            resp = views.edit_course(request, course_identifier)
            self.assertEqual(mock_form_save.call_count, 0)
            self.assertTrue(resp.status_code, 200)
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith(
                "No change was made on the settings.")

    def test_instructor_db_save_spaces_as_force_lang(self):
        # current force_lang is "", testing that the force_lang is still ""
        self.course.force_lang = "   "
        self.course.save()
        self.course.refresh_from_db()
        self.assertEqual(len(self.course.force_lang), 0)

    def test_instructor_edit_post_form_invalid(self):
        with mock.patch("course.views.EditCourseForm.is_valid") as mock_is_valid, \
            mock.patch("course.views.render_course_page"), \
                mock.patch("course.views._") as mock_gettext:

            mock_is_valid.return_value = False
            mock_gettext.side_effect = lambda x: x
            request = self.rf.post(self.get_edit_course_url(),
                                   data=mock.MagicMock())
            request.user = self.instructor_participation.user
            course_identifier = self.get_default_course_identifier()
            resp = views.edit_course(request, course_identifier)
            self.assertTrue(resp.status_code, 200)
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith(
                "Failed to update course settings.")

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
            resp = self.client.get(self.get_generate_ssh_keypair_url())
            self.assertEqual(resp.status_code, 302)

            expected_redirect_url = self.get_sign_in_choice_url(
                redirect_to=self.get_generate_ssh_keypair_url())

            self.assertRedirects(resp, expected_redirect_url,
                                 fetch_redirect_response=False)

    def test_not_staff(self):
        user = factories.UserFactory()
        assert not user.is_staff
        with self.temporarily_switch_to_user(user):
            resp = self.client.get(self.get_generate_ssh_keypair_url())
            self.assertEqual(resp.status_code, 403)

    def test_success(self):
        user = factories.UserFactory()
        user.is_staff = True
        user.save()
        with self.temporarily_switch_to_user(user):
            resp = self.client.get(self.get_generate_ssh_keypair_url())
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
            resp = self.client.get("/")
        self.assertResponseContextEqual(resp, "current_courses", [course1])
        self.assertResponseContextEqual(resp, "past_courses", [course4])

        with self.temporarily_switch_to_user(user):
            resp = self.client.get("/")
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
        return self.client.get(
                self.get_static_page_url(page_path, course_identifier))

    def test_success(self):
        resp = self.get_static_page("test")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp, "<h1>Demo page</h1>", html=True)
        self.assertContains(
            resp, "I am just a simple demo page. Go back to the "
                  '<a href="/course/test-course/">course page</a>?')

    def test_404(self):
        resp = self.get_static_page("hello")
        self.assertEqual(resp.status_code, 404)


class CoursePageTest(SingleCourseTestMixin, MockAddMessageMixing, TestCase):
    # test views.course_page

    # {{{ test show enroll button
    def test_student_no_enroll_button(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.client.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "show_enroll_button", False)

    def test_anonymous_show_enroll_button(self):
        with self.temporarily_switch_to_user(None):
            resp = self.client.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "show_enroll_button", True)

    def test_non_participation_show_enroll_button(self):
        user = factories.UserFactory()
        with self.temporarily_switch_to_user(user):
            resp = self.client.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "show_enroll_button", True)

    def test_requested_not_show_enroll_button(self):
        requested = factories.ParticipationFactory(
            course=self.course, status=constants.participation_status.requested)
        with self.temporarily_switch_to_user(requested.user):
            resp = self.client.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "show_enroll_button", False)

        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(
            "Your enrollment request is pending. You will be "
            "notified once it has been acted upon.")

    def test_requested_hint_for_set_instid(self):
        requested = factories.ParticipationFactory(
            course=self.course, status=constants.participation_status.requested)
        factories.ParticipationPreapprovalFactory(
            course=self.course, institutional_id="inst_id1234")
        with self.temporarily_switch_to_user(requested.user):
            resp = self.client.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "show_enroll_button", False)

        self.assertAddMessageCallCount(2)
        self.assertAddMessageCalledWith(
            "Your institutional ID is not verified or "
            "preapproved. Please contact your course "
            "staff.", reset=True)

        # remove course verify inst_id requirements
        self.course.preapproval_require_verified_inst_id = False
        self.course.save()

        with self.temporarily_switch_to_user(requested.user):
            resp = self.client.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "show_enroll_button", False)

        self.assertAddMessageCallCount(1, reset=True)

        # remove user inst_id
        requested.user.institutional_id = ""
        requested.user.save()
        with self.temporarily_switch_to_user(requested.user):
            resp = self.client.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "show_enroll_button", False)

        self.assertAddMessageCallCount(2)
        self.assertAddMessageCalledWith(
            "This course uses institutional ID for enrollment preapproval, "
            "please <a href='/profile/?referer=/course/test-course/"
            "&set_inst_id=1' role='button' class='btn btn-md btn-primary'>"
            "fill in your institutional ID &nbsp;&raquo;</a> in your profile.")

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
        return self.client.get(
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
    force_login_student_for_each_test = True

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
        return self.client.get(
            self.get_repo_file_url(path, course_identifier, commit_sha))

    def get_current_repo_file_url(self, path, course_identifier=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        return reverse("relate-get_current_repo_file",
                       kwargs={"course_identifier": course_identifier,
                               "path": path})

    def get_current_repo_file_view(self, path, course_identifier=None):
        return self.client.get(
            self.get_current_repo_file_url(path, course_identifier))


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
            ("images/django-logo.png", "image/png"),
            ("images/classroom.jpeg", "image/jpeg"),
            ("pdfs/sample.pdf", "application/pdf"),
            ("ipynbs/Ipynb_example.ipynb", "application/x-ipynb+json"),
        )
        for repo_file, content_type in tup:
            with self.subTest(repo_file=repo_file):
                resp = self.get_repo_file_view(repo_file)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp["Content-Type"], content_type)

                resp = self.get_current_repo_file_view(repo_file)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp["Content-Type"], content_type)


class GetRepoFileTestMocked(GetRepoFileTestMixin, HackRepoMixin, TestCase):
    """
    Test views.get_repo_file, with get_repo_blob mocked as class level,
    the purpose is to test role permissions to repo files

        in_exam:
        - "*.jpeg"

        ta:
        - "django-logo.png"

    """

    initial_commit_sha = "abcdef001"

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


class ManageInstantFlowRequestsTest(SingleCoursePageTestMixin, TestCase):
    # test views.manage_instant_flow_requests

    def get_manage_instant_flow_requests_url(self, course_identifier=None):
        return reverse(
            "relate-manage_instant_flow_requests",
            kwargs={"course_identifier":
                        course_identifier or self.get_default_course_identifier()})

    def get_manage_instant_flow_requests_view(
            self, course_identifier=None, force_login_instructor=True):
        course_identifier or self.get_default_course_identifier()

        if not force_login_instructor:
            u = self.get_logged_in_user()
        else:
            u = self.instructor_participation.user
        with self.temporarily_switch_to_user(u):
            return self.client.get(
                self.get_manage_instant_flow_requests_url(course_identifier))

    def post_manage_instant_flow_requests_view(
            self, data, course_identifier=None, force_login_instructor=True):
        course_identifier or self.get_default_course_identifier()

        if not force_login_instructor:
            u = self.get_logged_in_user()
        else:
            u = self.instructor_participation.user
        with self.temporarily_switch_to_user(u):
            return self.client.post(
                self.get_manage_instant_flow_requests_url(course_identifier),
                data=data)

    def get_default_post_data(self, action="add", **kwargs):
        data = {
            "flow_id": self.flow_id,
            "duration_in_minutes": 20,
            action: ""
        }
        data.update(kwargs)
        return data

    def test_anonymous(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_manage_instant_flow_requests_view(
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

            resp = self.post_manage_instant_flow_requests_view(
                data=self.get_default_post_data(), force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

            self.assertEqual(models.InstantFlowRequest.objects.count(), 0)

    def test_student(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_manage_instant_flow_requests_view(
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

            resp = self.post_manage_instant_flow_requests_view(
                data=self.get_default_post_data(), force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

            self.assertEqual(models.InstantFlowRequest.objects.count(), 0)

    def test_add(self):
        resp = self.get_manage_instant_flow_requests_view()
        self.assertEqual(resp.status_code, 200)

        resp = self.post_manage_instant_flow_requests_view(
            data=self.get_default_post_data())
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(models.InstantFlowRequest.objects.count(), 1)
        self.assertEqual(
            models.InstantFlowRequest.objects.filter(
                cancelled=False).count(), 1)

    def test_cancel(self):
        # 2 cancellable
        factories.InstantFlowRequestFactory(
            course=self.course, flow_id=self.flow_id,
            start_time=now() - timedelta(minutes=5),
            end_time=now() + timedelta(minutes=1))

        factories.InstantFlowRequestFactory(
            course=self.course, flow_id=self.flow_id,
            start_time=now() - timedelta(minutes=15),
            end_time=now() + timedelta(minutes=10))

        # not started
        inr3 = factories.InstantFlowRequestFactory(
            course=self.course, flow_id=self.flow_id,
            start_time=now() + timedelta(minutes=15),
            end_time=now() + timedelta(minutes=35))

        # expired
        inr4 = factories.InstantFlowRequestFactory(
            course=self.course, flow_id=self.flow_id,
            start_time=now() - timedelta(minutes=15),
            end_time=now() - timedelta(minutes=3))

        resp = self.post_manage_instant_flow_requests_view(
            data=self.get_default_post_data(action="cancel"))
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(models.InstantFlowRequest.objects.count(), 4)
        self.assertEqual(
            models.InstantFlowRequest.objects.filter(
                cancelled=True).count(), 2)

        inr3.refresh_from_db()
        self.assertFalse(inr3.cancelled)
        inr4.refresh_from_db()
        self.assertFalse(inr4.cancelled)

    def test_form_invalid(self):
        with mock.patch(
                "course.views.InstantFlowRequestForm.is_valid") as mock_is_valid:
            mock_is_valid.return_value = False

            with self.temporarily_switch_to_user(self.instructor_participation.user):
                # add
                resp = self.post_manage_instant_flow_requests_view(
                    data=self.get_default_post_data())
                self.assertEqual(resp.status_code, 200)

                self.assertEqual(models.InstantFlowRequest.objects.count(), 0)

                factories.InstantFlowRequestFactory(
                    course=self.course, flow_id=self.flow_id,
                    start_time=now() - timedelta(minutes=5),
                    end_time=now() + timedelta(minutes=1))

                resp = self.post_manage_instant_flow_requests_view(
                    data=self.get_default_post_data(action="cancel"))
                self.assertEqual(resp.status_code, 200)

                self.assertEqual(models.InstantFlowRequest.objects.count(), 1)
                self.assertEqual(
                    models.InstantFlowRequest.objects.filter(
                        cancelled=True).count(), 0)

    def test_invalid_operation(self):
        resp = self.post_manage_instant_flow_requests_view(
            data=self.get_default_post_data(action="unknown"))
        self.assertEqual(resp.status_code, 400)

        self.assertEqual(models.InstantFlowRequest.objects.count(), 0)

        factories.InstantFlowRequestFactory(
            course=self.course, flow_id=self.flow_id,
            start_time=now() - timedelta(minutes=5),
            end_time=now() + timedelta(minutes=1))

        resp = self.post_manage_instant_flow_requests_view(
            data=self.get_default_post_data(action="unknown"))
        self.assertEqual(resp.status_code, 400)

        self.assertEqual(models.InstantFlowRequest.objects.count(), 1)
        self.assertEqual(
            models.InstantFlowRequest.objects.filter(
                cancelled=True).count(), 0)


class TestFlowTest(SingleCoursePageTestMixin, TestCase):
    # test views.test_flow

    def get_test_flow_url(self, course_identifier=None):
        return reverse(
            "relate-test_flow",
            kwargs={"course_identifier":
                        course_identifier or self.get_default_course_identifier()})

    def get_test_flow_view(
            self, course_identifier=None, force_login_instructor=True):
        course_identifier or self.get_default_course_identifier()

        if not force_login_instructor:
            u = self.get_logged_in_user()
        else:
            u = self.instructor_participation.user
        with self.temporarily_switch_to_user(u):
            return self.client.get(
                self.get_test_flow_url(course_identifier))

    def post_test_flow_view(
            self, data, course_identifier=None, force_login_instructor=True):
        course_identifier or self.get_default_course_identifier()

        if not force_login_instructor:
            u = self.get_logged_in_user()
        else:
            u = self.instructor_participation.user
        with self.temporarily_switch_to_user(u):
            return self.client.post(
                self.get_test_flow_url(course_identifier),
                data=data)

    def get_default_post_data(self, action="test", **kwargs):
        data = {
            "flow_id": self.flow_id,
            action: ""
        }
        data.update(kwargs)
        return data

    def test_anonymous(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_test_flow_view(
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

            resp = self.post_test_flow_view(
                data=self.get_default_post_data(), force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

    def test_student(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_test_flow_view(
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

            resp = self.post_test_flow_view(
                data=self.get_default_post_data(), force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

    def test_success(self):
        resp = self.get_test_flow_view()
        self.assertEqual(resp.status_code, 200)

        resp = self.post_test_flow_view(data=self.get_default_post_data())
        self.assertFormErrorLoose(resp, None)
        self.assertRedirects(resp, self.get_view_start_flow_url(self.flow_id),
                             fetch_redirect_response=False)

    def test_form_invalid(self):
        with mock.patch(
                "course.views.FlowTestForm.is_valid") as mock_is_valid:
            mock_is_valid.return_value = False

            with self.temporarily_switch_to_user(self.instructor_participation.user):
                resp = self.post_test_flow_view(
                    data=self.get_default_post_data())
                self.assertEqual(resp.status_code, 200)

    def test_invalid_operation(self):
        resp = self.post_test_flow_view(
            data=self.get_default_post_data(action="unknown"))
        self.assertEqual(resp.status_code, 400)


class GrantExceptionTestMixin(MockAddMessageMixing, SingleCoursePageTestMixin):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.fs = factories.FlowSessionFactory(
            course=cls.course, participation=cls.student_participation,
            flow_id=cls.flow_id, in_progress=False)

    def setUp(self):
        super().setUp()
        self.fs.refresh_from_db()

    def get_grant_exception_url(self, course_identifier=None):
        return reverse(
            "relate-grant_exception",
            kwargs={"course_identifier":
                        course_identifier or self.get_default_course_identifier()})

    def get_grant_exception_view(
            self, course_identifier=None, force_login_instructor=True):

        if not force_login_instructor:
            u = self.get_logged_in_user()
        else:
            u = self.instructor_participation.user
        with self.temporarily_switch_to_user(u):
            return self.client.get(
                self.get_grant_exception_url(course_identifier))

    def post_grant_exception_view(
            self, data, course_identifier=None, force_login_instructor=True):

        if not force_login_instructor:
            u = self.get_logged_in_user()
        else:
            u = self.instructor_participation.user
        with self.temporarily_switch_to_user(u):
            return self.client.post(
                self.get_grant_exception_url(course_identifier),
                data=data)

    def get_grant_exception_stage_2_url(
            self, participation_id=None, flow_id=None, course_identifier=None):
        participation_id = participation_id or self.student_participation.id
        flow_id = flow_id or self.flow_id
        return reverse(
            "relate-grant_exception_stage_2",
            kwargs={"course_identifier":
                        course_identifier or self.get_default_course_identifier(),
                    "participation_id": participation_id,
                    "flow_id": flow_id})

    def get_grant_exception_stage_2_view(
            self, participation_id=None, flow_id=None, course_identifier=None,
            force_login_instructor=True):
        participation_id = participation_id or self.student_participation.id
        flow_id = flow_id or self.flow_id

        if not force_login_instructor:
            u = self.get_logged_in_user()
        else:
            u = self.instructor_participation.user
        with self.temporarily_switch_to_user(u):
            return self.client.get(
                self.get_grant_exception_stage_2_url(
                    participation_id, flow_id, course_identifier))

    def post_grant_exception_stage_2_view(
            self, data, participation_id=None, flow_id=None,
            course_identifier=None,
            force_login_instructor=True):

        participation_id = participation_id or self.student_participation.id
        flow_id = flow_id or self.flow_id
        if not force_login_instructor:
            u = self.get_logged_in_user()
        else:
            u = self.instructor_participation.user
        with self.temporarily_switch_to_user(u):
            return self.client.post(
                self.get_grant_exception_stage_2_url(
                    participation_id, flow_id, course_identifier),
                data=data)

    def get_grant_exception_stage_3_url(
            self, session_id=None, participation_id=None, flow_id=None,
            course_identifier=None):

        session_id = session_id or self.fs.pk
        participation_id = participation_id or self.student_participation.id
        flow_id = flow_id or self.flow_id

        return reverse(
            "relate-grant_exception_stage_3",
            kwargs={"course_identifier":
                        course_identifier or self.get_default_course_identifier(),
                    "participation_id": participation_id,
                    "flow_id": flow_id,
                    "session_id": session_id})

    def get_grant_exception_stage_3_view(
            self, session_id=None, participation_id=None, flow_id=None,
            course_identifier=None,
            force_login_instructor=True):
        session_id = session_id or self.fs.pk
        participation_id = participation_id or self.student_participation.id
        flow_id = flow_id or self.flow_id

        if not force_login_instructor:
            u = self.get_logged_in_user()
        else:
            u = self.instructor_participation.user
        with self.temporarily_switch_to_user(u):
            return self.client.get(
                self.get_grant_exception_stage_3_url(
                    session_id, participation_id, flow_id, course_identifier))

    def post_grant_exception_stage_3_view(
            self, data, session_id=None, participation_id=None, flow_id=None,
            course_identifier=None,
            force_login_instructor=True):
        session_id = session_id or self.fs.pk
        participation_id = participation_id or self.student_participation.id
        flow_id = flow_id or self.flow_id

        if not force_login_instructor:
            u = self.get_logged_in_user()
        else:
            u = self.instructor_participation.user
        with self.temporarily_switch_to_user(u):
            return self.client.post(
                self.get_grant_exception_stage_3_url(
                    session_id, participation_id, flow_id, course_identifier),
                data=data)


class GrantExceptionStage1Test(GrantExceptionTestMixin, TestCase):
    # test views.grant_exception

    def get_default_post_data(self, action="next", **kwargs):
        data = {
            "participation": self.student_participation.pk,
            "flow_id": self.flow_id,
            action: ""
        }
        data.update(kwargs)
        return data

    def test_anonymous(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_grant_exception_view(
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

            resp = self.post_grant_exception_view(
                data=self.get_default_post_data(), force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

    def test_student(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_grant_exception_view(
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

            resp = self.post_grant_exception_view(
                data=self.get_default_post_data(), force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

    def test_success(self):
        resp = self.get_grant_exception_view()
        self.assertEqual(resp.status_code, 200)

        resp = self.post_grant_exception_view(data=self.get_default_post_data())
        self.assertFormErrorLoose(resp, None)
        self.assertRedirects(
            resp, self.get_grant_exception_stage_2_url(),
            fetch_redirect_response=False)

    def test_form_invalid(self):
        with mock.patch(
                "course.views.ExceptionStage1Form.is_valid") as mock_is_valid:
            mock_is_valid.return_value = False

            with self.temporarily_switch_to_user(self.instructor_participation.user):
                resp = self.post_grant_exception_view(
                    data=self.get_default_post_data())
                self.assertEqual(resp.status_code, 200)


class GrantExceptionStage2Test(GrantExceptionTestMixin, TestCase):
    # test views.grant_exception_stage_2
    def get_default_post_data(self, action="next", **kwargs):
        data = {
            "session": self.fs.pk,
            action: ""
        }
        data.update(kwargs)
        return data

    def test_anonymous(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_grant_exception_stage_2_view(
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

            resp = self.post_grant_exception_stage_2_view(
                data=self.get_default_post_data(), force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

    def test_student(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_grant_exception_stage_2_view(
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

            resp = self.post_grant_exception_stage_2_view(
                data=self.get_default_post_data(), force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

    def test_flow_does_not_exist(self):
        with mock.patch("course.content.get_flow_desc") as mock_get_flow_desc:
            from django.core.exceptions import ObjectDoesNotExist
            mock_get_flow_desc.side_effect = ObjectDoesNotExist()

            resp = self.get_grant_exception_stage_2_view()
            self.assertEqual(resp.status_code, 404)

            resp = self.post_grant_exception_stage_2_view(
                data=self.get_default_post_data())
            self.assertEqual(resp.status_code, 404)

    def test_flow_desc_has_no_rule(self):
        hacked_flow_desc = self.get_hacked_flow_desc(del_rules=True)
        with mock.patch("course.content.get_flow_desc") as mock_get_flow_desc:
            mock_get_flow_desc.return_value = hacked_flow_desc
            resp = self.get_grant_exception_stage_2_view()
            self.assertEqual(resp.status_code, 200)

            resp = self.post_grant_exception_stage_2_view(
                data=self.get_default_post_data())
            self.assertFormErrorLoose(resp, None)
            self.assertRedirects(
                resp, self.get_grant_exception_stage_3_url(session_id=self.fs.pk),
                fetch_redirect_response=False)

    def test_post_next_success(self):
        resp = self.get_grant_exception_stage_2_view()
        self.assertEqual(resp.status_code, 200)

        resp = self.post_grant_exception_stage_2_view(
            data=self.get_default_post_data())
        self.assertFormErrorLoose(resp, None)
        self.assertRedirects(
            resp, self.get_grant_exception_stage_3_url(session_id=self.fs.pk),
            fetch_redirect_response=False)

    def test_post_create_session_success(self):
        resp = self.get_grant_exception_stage_2_view()
        self.assertEqual(resp.status_code, 200)

        resp = self.post_grant_exception_stage_2_view(
            data=self.get_default_post_data(
                action="create_session",
                access_rules_tag_for_new_session=[views.NONE_SESSION_TAG]
            ))
        self.assertFormErrorLoose(resp, None)
        self.assertEqual(resp.status_code, 200)
        all_fs = models.FlowSession.objects.all()
        self.assertEqual(all_fs.count(), 2)
        # no access_rules_tag is save
        self.assertEqual(all_fs.filter(access_rules_tag__isnull=True).count(), 2)

    def test_start_rule_not_may_start_new_session(self):
        session_start_rule = self.get_hacked_session_start_rule(
            may_start_new_session=False)
        with mock.patch("course.utils.get_session_start_rule") as mock_get_nrule:
            mock_get_nrule.return_value = session_start_rule

            resp = self.get_grant_exception_stage_2_view()
            self.assertEqual(resp.status_code, 200)
            self.assertContains(
                resp,
                "Creating a new session is (technically) not allowed "
                "by course rules. Clicking 'Create Session' anyway will "
                "override this rule.")
            create_session_form = resp.context["forms"][1]
            names, _ = self.get_form_submit_inputs(create_session_form)
            self.assertIn("create_session", names)

            all_fs = models.FlowSession.objects.all()
            self.assertEqual(all_fs.count(), 1)
            resp = self.post_grant_exception_stage_2_view(
                data=self.get_default_post_data(
                    action="create_session",
                    access_rules_tag_for_new_session=[views.NONE_SESSION_TAG]))
            self.assertEqual(resp.status_code, 200)
            all_fs = models.FlowSession.objects.all()
            self.assertEqual(all_fs.count(), 2)
            self.assertEqual(all_fs.filter(access_rules_tag__isnull=False).count(),
                             0)
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith(
                f"A new session was created for '{self.student_participation}' "
                f"for '{self.flow_id}'.")

    def test_exist_session_has_tags(self):
        another_fs_tag = "my_tag1"
        another_fs = factories.FlowSessionFactory(
            course=self.course, participation=self.student_participation,
            flow_id=self.flow_id, access_rules_tag=another_fs_tag)

        resp = self.get_grant_exception_stage_2_view()
        self.assertEqual(resp.status_code, 200)
        exception_form = resp.context["forms"][0]
        choices = exception_form.fields["session"].choices

        # stringified session name, the first is not tagged, the second is tagged
        self.assertNotIn("tagged", choices[0][1])
        self.assertIn(f"tagged '{another_fs_tag}'", choices[1][1])

        resp = self.post_grant_exception_stage_2_view(
            data=self.get_default_post_data(session=another_fs.pk))
        self.assertFormErrorLoose(resp, None)
        self.assertRedirects(
            resp, self.get_grant_exception_stage_3_url(session_id=another_fs.pk),
            fetch_redirect_response=False)
        self.assertAddMessageCallCount(0)

    def test_start_rule_has_tag_session(self):
        flow_desc_access_rule_tags = ["fdesc_tag1", "fdesc_tag2"]
        hacked_flow_desc = self.get_hacked_flow_desc_with_access_rule_tags(
            flow_desc_access_rule_tags)

        tag_session = "my_tag2"
        session_start_rule = self.get_hacked_session_start_rule(
            tag_session=tag_session)
        with mock.patch(
                "course.content.get_flow_desc") as mock_get_flow_desc, mock.patch(
                "course.utils.get_session_start_rule") as mock_get_nrule:
            mock_get_flow_desc.return_value = hacked_flow_desc
            mock_get_nrule.return_value = session_start_rule

            resp = self.get_grant_exception_stage_2_view()
            self.assertEqual(resp.status_code, 200)

            # because may start new session
            self.assertNotContains(
                resp,
                "Creating a new session is (technically) not allowed")

            create_session_form = resp.context["forms"][1]
            field = create_session_form.fields["access_rules_tag_for_new_session"]
            self.assertEqual(len(field.choices), 4)

            self.assertEqual(field.initial, tag_session)

            self.assertSetEqual(
                {*flow_desc_access_rule_tags, tag_session, views.NONE_SESSION_TAG},
                set(dict(field.choices).keys()))

            resp = self.post_grant_exception_stage_2_view(
                data=self.get_default_post_data(
                    action="create_session",
                    access_rules_tag_for_new_session=tag_session))
            self.assertEqual(resp.status_code, 200)
            all_fs = models.FlowSession.objects.all()
            self.assertEqual(all_fs.count(), 2)
            self.assertEqual(all_fs.filter(access_rules_tag=tag_session).count(), 1)
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith(
                f"A new session tagged '{tag_session}' was created for "
                f"'{self.student_participation}' for '{self.flow_id}'.")

    def test_start_rule_has_tag_session_with_in_flow_desc_arule_tags(self):
        flow_desc_access_rule_tags = ["my_tag1", "my_tag2"]
        hacked_flow_desc = self.get_hacked_flow_desc_with_access_rule_tags(
            flow_desc_access_rule_tags)

        tag_session = "my_tag2"
        session_start_rule = self.get_hacked_session_start_rule(
            tag_session=tag_session)
        with mock.patch(
                "course.content.get_flow_desc") as mock_get_flow_desc, mock.patch(
                "course.utils.get_session_start_rule") as mock_get_nrule:
            mock_get_flow_desc.return_value = hacked_flow_desc
            mock_get_nrule.return_value = session_start_rule

            resp = self.get_grant_exception_stage_2_view()
            self.assertEqual(resp.status_code, 200)

            # because may start new session
            self.assertNotContains(
                resp,
                "Creating a new session is (technically) not allowed")

            create_session_form = resp.context["forms"][1]
            field = create_session_form.fields["access_rules_tag_for_new_session"]
            self.assertEqual(len(field.choices), 3)

            self.assertEqual(field.initial, tag_session)

            self.assertSetEqual(
                {*flow_desc_access_rule_tags, views.NONE_SESSION_TAG},
                set(dict(field.choices).keys()))

            resp = self.post_grant_exception_stage_2_view(
                data=self.get_default_post_data(
                    action="create_session",
                    access_rules_tag_for_new_session=flow_desc_access_rule_tags[0]))
            self.assertEqual(resp.status_code, 200)
            all_fs = models.FlowSession.objects.all()
            self.assertEqual(all_fs.count(), 2)
            self.assertEqual(all_fs.filter(
                access_rules_tag=flow_desc_access_rule_tags[0]).count(), 1)

    def test_form_invalid(self):
        with mock.patch(
                "course.views.ExceptionStage2Form.is_valid") as mock_is_valid:
            mock_is_valid.return_value = False

            resp = self.post_grant_exception_stage_2_view(
                data=self.get_default_post_data())
            self.assertEqual(resp.status_code, 200)

    def test_invalid_operation(self):
        resp = self.post_grant_exception_stage_2_view(
            data=self.get_default_post_data(action="unknown"))
        self.assertEqual(resp.status_code, 400)


class GrantExceptionStage3Test(GrantExceptionTestMixin, TestCase):
    # test views.grant_exception_stage_2

    def setUp(self):
        super().setUp()
        fake_validate_session_access_rule = mock.patch(
            "course.validation.validate_session_access_rule")
        self.mock_validate_session_access_rule = (
            fake_validate_session_access_rule.start())
        self.addCleanup(fake_validate_session_access_rule.stop)
        fake_validate_session_grading_rule = mock.patch(
            "course.validation.validate_session_grading_rule")
        self.mock_validate_session_grading_rule = (
            fake_validate_session_grading_rule.start())
        self.addCleanup(fake_validate_session_grading_rule.stop)

    def get_default_post_data(self, action="submit", **kwargs):
        data = {
            "session": self.fs.pk,
            action: "",
            "comment": "my_comment"
        }
        data.update(kwargs)
        return data

    def test_anonymous(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_grant_exception_stage_3_view(
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

            resp = self.post_grant_exception_stage_3_view(
                data=self.get_default_post_data(), force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

    def test_student(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_grant_exception_stage_3_view(
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

            resp = self.post_grant_exception_stage_3_view(
                data=self.get_default_post_data(), force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

    def test_flow_does_not_exist(self):
        with mock.patch("course.content.get_flow_desc") as mock_get_flow_desc:
            from django.core.exceptions import ObjectDoesNotExist
            mock_get_flow_desc.side_effect = ObjectDoesNotExist()

            resp = self.get_grant_exception_stage_3_view()
            self.assertEqual(resp.status_code, 404)

            resp = self.post_grant_exception_stage_3_view(
                data=self.get_default_post_data())
            self.assertEqual(resp.status_code, 404)

    def test_success(self):
        resp = self.get_grant_exception_stage_3_view()
        self.assertEqual(resp.status_code, 200)
        form = resp.context["form"]

        # no tags in flow_desc.rule
        self.assertNotIn("set_access_rules_tag", form.fields)
        self.assertNotIn("restrict_to_same_tag", form.fields)

        resp = self.post_grant_exception_stage_3_view(
            data=self.get_default_post_data())
        self.assertFormErrorLoose(resp, None)
        self.assertRedirects(
            resp, self.get_grant_exception_url(),
            fetch_redirect_response=False)

        # The above doesn't create a FlowRuleException object
        self.assertEqual(models.FlowRuleException.objects.count(), 0)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(
            "No exception granted to the given flow session")

    def test_flow_desc_has_no_rule(self):
        hacked_flow_desc = self.get_hacked_flow_desc(del_rules=True)
        with mock.patch("course.content.get_flow_desc") as mock_get_flow_desc:
            mock_get_flow_desc.return_value = hacked_flow_desc
            resp = self.get_grant_exception_stage_3_view()
            self.assertEqual(resp.status_code, 200)

            form = resp.context["form"]

            # no flow_desc.rule
            self.assertNotIn("set_access_rules_tag", form.fields)
            self.assertNotIn("restrict_to_same_tag", form.fields)

            resp = self.post_grant_exception_stage_3_view(
                data=self.get_default_post_data())
            self.assertFormErrorLoose(resp, None)
            self.assertRedirects(
                resp, self.get_grant_exception_url(),
                fetch_redirect_response=False)

            # The above doesn't create a FlowRuleException object
            self.assertEqual(models.FlowRuleException.objects.count(), 0)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(
            "No exception granted to the given flow session")

    def test_flow_desc_rule_has_tags(self):
        flow_desc_access_rule_tags = ["fdesc_tag1", "fdesc_tag2"]
        hacked_flow_desc = self.get_hacked_flow_desc_with_access_rule_tags(
            flow_desc_access_rule_tags)

        fs_with_flow_desc_tag = factories.FlowSessionFactory(
            course=self.course, participation=self.student_participation,
            flow_id=self.flow_id, access_rules_tag=flow_desc_access_rule_tags[0])

        another_fs_tag = "my_tag1"
        another_fs = factories.FlowSessionFactory(
            course=self.course, participation=self.student_participation,
            flow_id=self.flow_id, access_rules_tag=another_fs_tag)

        with mock.patch("course.content.get_flow_desc") as mock_get_flow_desc:
            mock_get_flow_desc.return_value = hacked_flow_desc
            resp = self.get_grant_exception_stage_3_view()
            self.assertEqual(resp.status_code, 200)

            form = resp.context["form"]
            self.assertIn("set_access_rules_tag", form.fields)
            self.assertIn("restrict_to_same_tag", form.fields)

            self.assertEqual(
                len(form.fields["set_access_rules_tag"].choices), 3)
            # default to None tag
            self.assertEqual(
                form.fields["set_access_rules_tag"].initial, views.NONE_SESSION_TAG)

            # flow session with tags from flow_desc.rules
            resp = self.get_grant_exception_stage_3_view(
                session_id=fs_with_flow_desc_tag.pk)
            self.assertEqual(resp.status_code, 200)

            form = resp.context["form"]

            self.assertEqual(
                len(form.fields["set_access_rules_tag"].choices), 3)
            self.assertEqual(
                form.fields["set_access_rules_tag"].initial,
                fs_with_flow_desc_tag.access_rules_tag)

            # flow session with it's own tag
            resp = self.get_grant_exception_stage_3_view(session_id=another_fs.pk)
            self.assertEqual(resp.status_code, 200)

            form = resp.context["form"]

            self.assertEqual(
                len(form.fields["set_access_rules_tag"].choices), 4)
            self.assertEqual(
                form.fields["set_access_rules_tag"].initial, another_fs_tag)

    # {{{ create_access_exception
    def test_create_access_exception_not_restrict_to_same_tag(self):
        flow_desc_access_rule_tags = ["fdesc_tag1", "fdesc_tag2"]
        hacked_flow_desc = self.get_hacked_flow_desc_with_access_rule_tags(
            flow_desc_access_rule_tags)

        with mock.patch("course.content.get_flow_desc") as mock_get_flow_desc:
            mock_get_flow_desc.return_value = hacked_flow_desc

            # not restrict_to_same_tag
            resp = self.post_grant_exception_stage_3_view(
                data=self.get_default_post_data(
                    create_access_exception=True,
                    set_access_rules_tag=[flow_desc_access_rule_tags[1]]
                ))
            self.assertFormErrorLoose(resp, None)
            self.assertRedirects(
                resp, self.get_grant_exception_url(),
                fetch_redirect_response=False)

            self.assertEqual(models.FlowRuleException.objects.count(), 1)
            self.assertEqual(
                models.FlowRuleException.objects.filter(
                    kind=constants.flow_rule_kind.access).count(), 1)
            self.assertAddMessageCallCount(2)
            self.assertAddMessageCalledWith(
                ["Access rules tag of the selected session updated "
                 f"to '{flow_desc_access_rule_tags[1]}'.",
                 "'Session Access' exception granted to "], reset=True)
            self.fs.refresh_from_db()
            self.assertEqual(self.fs.access_rules_tag, flow_desc_access_rule_tags[1])
            self.assertEqual(self.mock_validate_session_access_rule.call_count, 1)
            self.mock_validate_session_access_rule.reset_mock()
            exc_rule = models.FlowRuleException.objects.last().rule

            self.assertIsNone(exc_rule.get("if_has_tag"),
                              msg="if_has_tag should not be created in this "
                                  "exception rule")

            # still not restrict_to_same_tag, but with NONE_SESSION_TAG
            resp = self.post_grant_exception_stage_3_view(
                data=self.get_default_post_data(
                    create_access_exception=True,
                    set_access_rules_tag=[views.NONE_SESSION_TAG]
                ))
            self.assertFormErrorLoose(resp, None)
            self.assertRedirects(
                resp, self.get_grant_exception_url(),
                fetch_redirect_response=False)

            self.assertEqual(models.FlowRuleException.objects.count(), 2)
            self.assertEqual(
                models.FlowRuleException.objects.filter(
                    kind=constants.flow_rule_kind.access).count(), 2)
            self.assertAddMessageCallCount(2)
            self.assertAddMessageCalledWith(
                ["Removed access rules tag of the selected session.",
                 "'Session Access' exception granted to "], reset=True)
            self.fs.refresh_from_db()
            self.assertEqual(self.fs.access_rules_tag, None)
            self.assertEqual(self.mock_validate_session_access_rule.call_count, 1)

            exc_rule = models.FlowRuleException.objects.last().rule
            self.assertIsNone(exc_rule.get("if_has_tag"),
                              msg="if_has_tag should not be created in this "
                                  "exception rule")

    def test_create_access_exception_restrict_to_same_tag(self):
        # restrict_to_same_tag, while session access_rules_tag is none
        flow_desc_access_rule_tags = ["fdesc_tag1", "fdesc_tag2"]
        hacked_flow_desc = self.get_hacked_flow_desc_with_access_rule_tags(
            flow_desc_access_rule_tags)

        with mock.patch("course.content.get_flow_desc") as mock_get_flow_desc:
            mock_get_flow_desc.return_value = hacked_flow_desc

            resp = self.post_grant_exception_stage_3_view(
                data=self.get_default_post_data(
                    create_access_exception=True,
                    set_access_rules_tag=[flow_desc_access_rule_tags[1]],
                    restrict_to_same_tag=True
                ))

            self.assertFormErrorLoose(resp, None)
            self.assertRedirects(
                resp, self.get_grant_exception_url(),
                fetch_redirect_response=False)

            self.assertEqual(models.FlowRuleException.objects.count(), 1)
            self.assertEqual(
                models.FlowRuleException.objects.filter(
                    kind=constants.flow_rule_kind.access).count(), 1)

            self.fs.refresh_from_db()
            self.assertEqual(self.fs.access_rules_tag, flow_desc_access_rule_tags[1])
            exc_rule = models.FlowRuleException.objects.last().rule
            self.assertEqual(exc_rule.get("if_has_tag"), None)

    def test_create_access_exception_restrict_to_same_tag2(self):
        flow_desc_access_rule_tags = ["fdesc_tag1", "fdesc_tag2"]
        hacked_flow_desc = self.get_hacked_flow_desc_with_access_rule_tags(
            flow_desc_access_rule_tags)

        # a flow session with it's own tag
        another_fs_tag = "my_tag1"
        another_fs = factories.FlowSessionFactory(
            course=self.course, participation=self.student_participation,
            flow_id=self.flow_id, access_rules_tag=another_fs_tag)

        with mock.patch("course.content.get_flow_desc") as mock_get_flow_desc:
            mock_get_flow_desc.return_value = hacked_flow_desc

            resp = self.post_grant_exception_stage_3_view(
                session_id=another_fs.pk,
                data=self.get_default_post_data(
                    session=another_fs.pk,
                    create_access_exception=True,
                    set_access_rules_tag=[flow_desc_access_rule_tags[1]],
                    restrict_to_same_tag=True  # then the above will be ignored
                ))

            self.assertFormErrorLoose(resp, None)
            self.assertRedirects(
                resp, self.get_grant_exception_url(),
                fetch_redirect_response=False)

            self.assertEqual(models.FlowRuleException.objects.count(), 1)
            self.assertEqual(
                models.FlowRuleException.objects.filter(
                    kind=constants.flow_rule_kind.access).count(), 1)

            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith(
                "'Session Access' exception granted to ")
            another_fs.refresh_from_db()
            self.assertEqual(another_fs.access_rules_tag, another_fs_tag)

            exc_rule = models.FlowRuleException.objects.last().rule
            self.assertEqual(exc_rule["if_has_tag"], another_fs_tag)

    def test_access_permissions_created(self):
        # ensure all flow permission is in the form, and will be
        # saved to the FlowRuleException permissions
        all_permissions = dict(constants.FLOW_PERMISSION_CHOICES).keys()

        from itertools import combinations
        from random import shuffle

        # 15 random flow permissions combination
        comb = list(combinations(all_permissions, 3))
        shuffle(comb)
        comb = comb[:15]

        for permissions in comb:
            with self.subTest(permissions=permissions):
                kwargs = dict.fromkeys(permissions, True)
                resp = self.post_grant_exception_stage_3_view(
                    data=self.get_default_post_data(
                        create_access_exception=True,
                        **kwargs))
                self.assertFormErrorLoose(resp, None)
                self.assertRedirects(
                    resp, self.get_grant_exception_url(),
                    fetch_redirect_response=False)
                exc_rule = models.FlowRuleException.objects.last().rule
                self.assertSetEqual(
                    set(exc_rule["permissions"]), set(permissions))

    def test_access_expires_created(self):
        expiration_time = as_local_time(now() + timedelta(days=3))
        resp = self.post_grant_exception_stage_3_view(
            data=self.get_default_post_data(
                create_access_exception=True,
                access_expires=expiration_time.strftime(
                    DATE_TIME_PICKER_TIME_FORMAT)))
        self.assertFormErrorLoose(resp, None)
        self.assertRedirects(
            resp, self.get_grant_exception_url(),
            fetch_redirect_response=False)
        expiration = models.FlowRuleException.objects.last().expiration
        self.assertIsNotNone(expiration)
        self.assertEqual(as_local_time(expiration).date(), expiration_time.date())
        self.assertEqual(as_local_time(expiration).hour, expiration_time.hour)
        self.assertEqual(as_local_time(expiration).minute, expiration_time.minute)

    # }}}

    def test_no_exception_created_but_updated_session_access_rule_tag(self):
        flow_desc_access_rule_tags = ["fdesc_tag1", "fdesc_tag2"]
        hacked_flow_desc = self.get_hacked_flow_desc_with_access_rule_tags(
            flow_desc_access_rule_tags)

        with mock.patch("course.content.get_flow_desc") as mock_get_flow_desc:
            mock_get_flow_desc.return_value = hacked_flow_desc

            # not restrict_to_same_tag
            resp = self.post_grant_exception_stage_3_view(
                data=self.get_default_post_data(
                    set_access_rules_tag=[flow_desc_access_rule_tags[1]]
                ))
            self.assertFormErrorLoose(resp, None)
            self.assertRedirects(
                resp, self.get_grant_exception_url(),
                fetch_redirect_response=False)

            self.assertEqual(models.FlowRuleException.objects.count(), 0)
            self.assertAddMessageCallCount(2)
            self.assertAddMessageCalledWith(
                ["Access rules tag of the selected session updated "
                 f"to '{flow_desc_access_rule_tags[1]}'.",
                 "No other exception granted to "], reset=True)
            self.fs.refresh_from_db()
            self.assertEqual(self.fs.access_rules_tag, flow_desc_access_rule_tags[1])

    # {{{ create_grading_exception

    def test_create_grading_exception_due_none(self):
        resp = self.post_grant_exception_stage_3_view(
            data=self.get_default_post_data(
                create_grading_exception=True))

        self.assertFormErrorLoose(resp, None)
        self.assertRedirects(
            resp, self.get_grant_exception_url(),
            fetch_redirect_response=False)

        self.assertEqual(self.mock_validate_session_grading_rule.call_count, 1)

        excs = models.FlowRuleException.objects.all()
        self.assertEqual(excs.count(), 1)
        self.assertEqual(
            excs.filter(
                kind=constants.flow_rule_kind.grading).count(), 1)
        if_completed_before = excs[0].rule.get("if_completed_before")
        self.assertIsNone(if_completed_before)

        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("'Grading' exception granted to ")

    def test_create_grading_exception_due(self):
        due = as_local_time(now() + timedelta(days=5))
        resp = self.post_grant_exception_stage_3_view(
            data=self.get_default_post_data(
                create_grading_exception=True,
                due=due.strftime(DATE_TIME_PICKER_TIME_FORMAT)))

        self.assertFormErrorLoose(resp, None)
        self.assertRedirects(
            resp, self.get_grant_exception_url(),
            fetch_redirect_response=False)

        self.assertEqual(self.mock_validate_session_grading_rule.call_count, 1)

        excs = models.FlowRuleException.objects.all()
        self.assertEqual(excs.count(), 1)
        self.assertEqual(
            excs.filter(
                kind=constants.flow_rule_kind.grading).count(), 1)
        if_completed_before = excs[0].rule.get("if_completed_before")
        self.assertIsNone(if_completed_before)

        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("'Grading' exception granted to ")

    def test_create_grading_exception_due_same_as_access_expiration(self):
        due = as_local_time(now() + timedelta(days=5))
        expiration_time = as_local_time(now() + timedelta(days=3))
        resp = self.post_grant_exception_stage_3_view(
            data=self.get_default_post_data(
                create_grading_exception=True,
                due_same_as_access_expiration=True,
                due=due.strftime(DATE_TIME_PICKER_TIME_FORMAT),
                access_expires=expiration_time.strftime(
                    DATE_TIME_PICKER_TIME_FORMAT)))

        self.assertFormErrorLoose(resp, None)
        self.assertRedirects(
            resp, self.get_grant_exception_url(),
            fetch_redirect_response=False)

        self.assertEqual(self.mock_validate_session_grading_rule.call_count, 1)

        excs = models.FlowRuleException.objects.all()
        self.assertEqual(excs.count(), 1)
        self.assertEqual(
            excs.filter(
                kind=constants.flow_rule_kind.grading).count(), 1)
        if_completed_before = excs[0].rule.get("if_completed_before")
        self.assertIsNone(if_completed_before)

        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("'Grading' exception granted to ")

    def test_create_grading_exception_due_same_as_access_expiration_while_expiration_not_set(self):  # noqa
        due = as_local_time(now() + timedelta(days=5))
        resp = self.post_grant_exception_stage_3_view(
            data=self.get_default_post_data(
                create_grading_exception=True,
                due_same_as_access_expiration=True,
                due=due.strftime(DATE_TIME_PICKER_TIME_FORMAT)))

        self.assertEqual(resp.status_code, 200)
        self.assertFormErrorLoose(
            resp, "Must specify access expiration if 'due same "
                  "as access expiration' is set.")

        self.assertEqual(self.mock_validate_session_grading_rule.call_count, 0)

    def test_create_grading_exception_credit_percent_recorded_in_description(self):
        resp = self.post_grant_exception_stage_3_view(
            data=self.get_default_post_data(
                create_grading_exception=True,
                credit_percent=89.1))

        self.assertFormErrorLoose(resp, None)
        self.assertRedirects(resp, self.get_grant_exception_url(),
                             fetch_redirect_response=False)

        self.assertEqual(self.mock_validate_session_grading_rule.call_count, 1)

        excs = models.FlowRuleException.objects.all()
        self.assertEqual(excs.count(), 1)
        self.assertEqual(
            excs.filter(
                kind=constants.flow_rule_kind.grading).count(), 1)
        description = excs[0].rule.get("description")
        self.assertIsNotNone(description)
        self.assertIn("89.1%", description)

        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("'Grading' exception granted to ")

    def test_grading_rule_generates_grade(self):
        # not generates_grade
        self.post_grant_exception_stage_3_view(
            data=self.get_default_post_data(
                # untick generates_grade
                create_grading_exception=True))

        self.assertEqual(self.mock_validate_session_grading_rule.call_count, 1)
        self.mock_validate_session_grading_rule.reset_mock()

        excs = models.FlowRuleException.objects.all()
        self.assertEqual(excs.count(), 1)
        self.assertEqual(
            excs.filter(
                kind=constants.flow_rule_kind.grading).count(), 1)
        generates_grade = excs[0].rule.get("generates_grade")
        self.assertFalse(generates_grade)

        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("'Grading' exception granted to ",
                                        reset=True)

        # second, generates_grade
        self.post_grant_exception_stage_3_view(
            data=self.get_default_post_data(
                create_grading_exception=True, generates_grade=True))

        self.assertEqual(self.mock_validate_session_grading_rule.call_count, 1)

        excs = models.FlowRuleException.objects.all()
        self.assertEqual(excs.count(), 2)
        self.assertEqual(
            excs.filter(
                kind=constants.flow_rule_kind.grading).count(), 2)
        generates_grade = excs[1].rule.get("generates_grade")
        self.assertTrue(generates_grade)

        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("'Grading' exception granted to ")

    def test_grading_rule_item_set(self):
        from random import random
        items = ["credit_percent", "bonus_points", "max_points",
                 "max_points_enforced_cap"]
        for item in items:
            value = random() * 100
            with self.subTest(item=item):
                data = self.get_default_post_data(
                    create_grading_exception=True)
                data[item] = value

                resp = self.post_grant_exception_stage_3_view(data=data)
                self.assertRedirects(resp, self.get_grant_exception_url(),
                                     fetch_redirect_response=False)

                self.assertEqual(
                    self.mock_validate_session_grading_rule.call_count, 1)
                self.mock_validate_session_grading_rule.reset_mock()

                rule = models.FlowRuleException.objects.last().rule
                self.assertEqual(rule[item], value)
                for other_item in items:
                    if other_item != item:
                        self.assertEqual(rule.get(other_item), None)

    def test_create_grading_exception_restrict_to_same_tag(self):
        # restrict_to_same_tag, while session access_rules_tag is none
        flow_desc_access_rule_tags = ["fdesc_tag1", "fdesc_tag2"]
        hacked_flow_desc = self.get_hacked_flow_desc_with_access_rule_tags(
            flow_desc_access_rule_tags)

        with mock.patch("course.content.get_flow_desc") as mock_get_flow_desc:
            mock_get_flow_desc.return_value = hacked_flow_desc

            resp = self.post_grant_exception_stage_3_view(
                data=self.get_default_post_data(
                    create_grading_exception=True,
                    set_access_rules_tag=[flow_desc_access_rule_tags[1]],
                    restrict_to_same_tag=True
                ))

            self.assertFormErrorLoose(resp, None)
            self.assertRedirects(
                resp, self.get_grant_exception_url(),
                fetch_redirect_response=False)

            self.assertEqual(models.FlowRuleException.objects.count(), 1)
            self.assertEqual(
                models.FlowRuleException.objects.filter(
                    kind=constants.flow_rule_kind.grading).count(), 1)

            # the session had the same tag as in the grading rule
            self.fs.refresh_from_db()
            self.assertEqual(
                self.fs.access_rules_tag, flow_desc_access_rule_tags[1])

            exc_rule = models.FlowRuleException.objects.last().rule
            self.assertEqual(
                exc_rule.get("if_has_tag"), None)

    def test_create_grading_exception_restrict_to_same_tag2(self):
        flow_desc_access_rule_tags = ["fdesc_tag1", "fdesc_tag2"]
        hacked_flow_desc = self.get_hacked_flow_desc_with_access_rule_tags(
            flow_desc_access_rule_tags)

        # a flow session with it's own tag
        another_fs_tag = "my_tag1"
        another_fs = factories.FlowSessionFactory(
            course=self.course, participation=self.student_participation,
            flow_id=self.flow_id, access_rules_tag=another_fs_tag)

        with mock.patch("course.content.get_flow_desc") as mock_get_flow_desc:
            mock_get_flow_desc.return_value = hacked_flow_desc

            resp = self.post_grant_exception_stage_3_view(
                session_id=another_fs.pk,
                data=self.get_default_post_data(
                    session=another_fs.pk,
                    create_grading_exception=True,
                    set_access_rules_tag=[flow_desc_access_rule_tags[1]],
                    restrict_to_same_tag=True  # then the above will be ignored
                ))

            self.assertFormErrorLoose(resp, None)
            self.assertRedirects(
                resp, self.get_grant_exception_url(),
                fetch_redirect_response=False)

            self.assertEqual(models.FlowRuleException.objects.count(), 1)
            self.assertEqual(
                models.FlowRuleException.objects.filter(
                    kind=constants.flow_rule_kind.grading).count(), 1)

            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith("'Grading' exception granted to ")
            another_fs.refresh_from_db()
            self.assertEqual(another_fs.access_rules_tag, another_fs_tag)

            exc_rule = models.FlowRuleException.objects.last().rule
            self.assertEqual(exc_rule["if_has_tag"], another_fs_tag)

    # }}}

    def test_form_invalid(self):
        with mock.patch(
                "course.views.ExceptionStage3Form.is_valid") as mock_is_valid:
            mock_is_valid.return_value = False
            resp = self.post_grant_exception_stage_3_view(
                data=self.get_default_post_data())
            self.assertEqual(resp.status_code, 200)

            self.assertEqual(models.FlowRuleException.objects.count(), 0)
            self.assertEqual(self.mock_validate_session_access_rule.call_count, 0)
            self.assertEqual(self.mock_validate_session_grading_rule.call_count, 0)


# {{{ test views.monitor_task

PYTRACEBACK = """\
Traceback (most recent call last):
  File "foo.py", line 2, in foofunc
    don't matter
  File "bar.py", line 3, in barfunc
    don't matter
Doesn't matter: really!\
"""


class MonitorTaskTest(SingleCourseTestMixin, TestCase):
    # test views.monitor_task
    def mock_task(self, name, state, result, traceback=None):
        return {
            "id": uuid(), "name": name, "state": state,
            "result": result, "traceback": traceback,
        }

    def save_result(self, app, task):
        traceback = task.get("traceback") or "Some traceback"
        state = task["state"]
        if state == states.SUCCESS:
            app.backend.mark_as_done(task["id"], task["result"])
        elif state == states.RETRY:
            app.backend.mark_as_retry(
                task["id"], task["result"], traceback=traceback,
            )
        elif state == states.FAILURE:
            app.backend.mark_as_failure(
                task["id"], task["result"], traceback=traceback)
        elif state == states.REVOKED:
            app.backend.mark_as_revoked(
                task_id=task["id"], reason="blabla", state=state)
        elif state == states.STARTED:
            app.backend.mark_as_started(task["id"], **task["result"])
        else:
            app.backend.store_result(
                task["id"], task["result"], state,
            )

    def get_monitor_url(self, task_id):
        from django.urls import reverse
        return reverse("relate-monitor_task", kwargs={"task_id": task_id})

    def get_monitor_view(self, task_id):
        return self.client.get(self.get_monitor_url(task_id))

    def test_user_not_authenticated(self):
        message = "This is good!"
        task = self.mock_task("task", states.SUCCESS, {"message": message})
        self.save_result(app, task)
        with self.temporarily_switch_to_user(None):
            resp = self.get_monitor_view(task["id"])
        self.assertEqual(resp.status_code, 302)

    def test_state_success(self):
        message = "This is good!"
        task = self.mock_task("task", states.SUCCESS, {"message": message})
        self.save_result(app, task)
        resp = self.get_monitor_view(task["id"])
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(resp, "state", task["state"])
        self.assertResponseContextEqual(resp, "progress_statement", message)
        self.assertResponseContextIsNone(resp, "progress_percent")
        self.assertResponseContextIsNone(resp, "traceback")

    def test_state_success_result_not_dict(self):
        task = self.mock_task("task", states.SUCCESS, "This is good!")
        self.save_result(app, task)
        resp = self.get_monitor_view(task["id"])
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(resp, "state", task["state"])
        self.assertResponseContextIsNone(resp, "progress_percent")
        self.assertResponseContextIsNone(resp, "progress_statement")
        self.assertResponseContextIsNone(resp, "traceback")

    def test_state_success_result_contains_no_message(self):
        task = self.mock_task("task", states.SUCCESS, {"log": "This is good!"})
        self.save_result(app, task)
        resp = self.get_monitor_view(task["id"])
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(resp, "state", task["state"])
        self.assertResponseContextIsNone(resp, "progress_percent")
        self.assertResponseContextIsNone(resp, "progress_statement")
        self.assertResponseContextIsNone(resp, "traceback")

    def test_state_progress(self):
        task = self.mock_task("progressing", "PROGRESS",
                         {"current": 20, "total": 40})
        self.save_result(app, task)
        resp = self.get_monitor_view(task["id"])
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(resp, "state", task["state"])
        self.assertResponseContextEqual(resp, "progress_percent", 50)
        self.assertResponseContextEqual(
            resp, "progress_statement", "20 out of 40 items processed.")
        self.assertResponseContextIsNone(resp, "traceback")

    def test_state_progress_total_zero(self):
        task = self.mock_task("progressing", "PROGRESS",
                         {"current": 0, "total": 0})
        self.save_result(app, task)
        resp = self.get_monitor_view(task["id"])
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(resp, "state", task["state"])
        self.assertResponseContextIsNone(resp, "progress_percent")
        self.assertResponseContextEqual(
            resp, "progress_statement", "0 out of 0 items processed.")
        self.assertResponseContextIsNone(resp, "traceback")

    def test_state_failure(self):
        self.instructor_participation.user.is_staff = True
        self.instructor_participation.user.save()
        task = self.mock_task("failure", states.FAILURE,
                              KeyError("foo"),
                              PYTRACEBACK)
        self.save_result(app, task)
        with self.temporarily_switch_to_user(self.superuser):
            resp = self.get_monitor_view(task["id"])
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(resp, "state", task["state"])
        self.assertResponseContextIsNone(resp, "progress_percent")
        self.assertResponseContextIsNone(resp, "progress_statement")
        # Broken by django-results-backend 2.4.0
        # self.assertResponseContextEqual(resp, "traceback", PYTRACEBACK)

    def test_state_failure_request_user_not_staff(self):
        task = self.mock_task("failure", states.FAILURE,
                              KeyError("foo"),
                              PYTRACEBACK)
        self.save_result(app, task)
        resp = self.get_monitor_view(task["id"])

        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(resp, "state", task["state"])
        self.assertResponseContextIsNone(resp, "progress_percent")
        self.assertResponseContextIsNone(resp, "progress_statement")
        self.assertResponseContextIsNone(resp, "traceback")

    def test_pending(self):
        state = states.PENDING
        task = self.mock_task("task", state,
                              {"current": 20, "total": 40})
        self.save_result(app, task)
        resp = self.get_monitor_view(task["id"])
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(resp, "state", state)
        self.assertResponseContextIsNone(resp, "progress_percent")
        self.assertResponseContextIsNone(resp, "progress_statement")
        self.assertResponseContextIsNone(resp, "traceback")

    def test_received(self):
        state = states.RECEIVED
        task = self.mock_task("task", state,
                              {"current": 20, "total": 40})
        self.save_result(app, task)
        resp = self.get_monitor_view(task["id"])
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(resp, "state", state)
        self.assertResponseContextIsNone(resp, "progress_percent")
        self.assertResponseContextIsNone(resp, "progress_statement")
        self.assertResponseContextIsNone(resp, "traceback")

    def test_started(self):
        state = states.STARTED
        task = self.mock_task("task", state,
                              {"foo": "foo", "bar": "bar"})
        self.save_result(app, task)
        resp = self.get_monitor_view(task["id"])
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(resp, "state", state)
        self.assertResponseContextIsNone(resp, "progress_percent")
        self.assertResponseContextIsNone(resp, "progress_statement")
        self.assertResponseContextIsNone(resp, "traceback")

    def test_retry(self):
        state = states.RETRY
        task = self.mock_task("task", state,
                              KeyError())
        self.save_result(app, task)
        resp = self.get_monitor_view(task["id"])
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(resp, "state", state)
        self.assertResponseContextIsNone(resp, "progress_percent")
        self.assertResponseContextIsNone(resp, "progress_statement")
        self.assertResponseContextIsNone(resp, "traceback")

    def test_revoked(self):
        state = states.REVOKED
        task = self.mock_task("task", state, {})
        self.save_result(app, task)
        resp = self.get_monitor_view(task["id"])
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(resp, "state", state)
        self.assertResponseContextIsNone(resp, "progress_percent")
        self.assertResponseContextIsNone(resp, "progress_statement")
        self.assertResponseContextIsNone(resp, "traceback")

# }}}

# vim: fdm=marker
