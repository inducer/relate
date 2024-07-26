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

import re
import unittest
from datetime import timedelta
from urllib.parse import ParseResult, quote, urlparse

import pytest
from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME, SESSION_KEY
from django.contrib.auth.hashers import check_password
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse, QueryDict
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import NoReverseMatch, re_path, reverse
from django.utils.timezone import now
from djangosaml2.urls import urlpatterns as djsaml2_urlpatterns

from course import constants
from course.auth import (
    APIBearerTokenBackend,
    APIContext,
    APIError,
    EmailedTokenBackend,
    get_impersonable_user_qset,
    get_user_model,
    with_course_api_auth,
)
from course.models import AuthenticationToken, FlowPageVisit, ParticipationPermission
from relate.urls import COURSE_ID_REGEX, urlpatterns as base_urlpatterns
from tests import factories
from tests.base_test_mixins import (
    APITestMixin,
    CoursesTestMixinBase,
    MockAddMessageMixing,
    SingleCoursePageTestMixin,
)
from tests.utils import (
    LocmemBackendTestsMixin,
    load_url_pattern_names,
    mock,
    reload_urlconf,
)


# settings names
EDITABLE_INST_ID_BEFORE_VERI = "RELATE_EDITABLE_INST_ID_BEFORE_VERIFICATION"
SHOW_INST_ID_FORM = "RELATE_SHOW_INST_ID_FORM"
SHOW_EDITOR_FORM = "RELATE_SHOW_EDITOR_FORM"

NOT_IMPERSONATING_MESSAGE = "Not currently impersonating anyone."
NO_LONGER_IMPERSONATING_MESSAGE = "No longer impersonating anyone."
ALREADY_IMPERSONATING_SOMEONE_MESSAGE = "Already impersonating someone."
ERROR_WHILE_IMPERSONATING_MESSAGE = "Error while impersonating."
IMPERSONATE_FORM_ERROR_NOT_VALID_USER_MSG = (
    "Select a valid choice. That choice is "
    "not one of the available choices.")


_TOKEN_AUTH_DATA_RE = re.compile(
    r"[^0-9]+(?P<token_id>[0-9]+)_(?P<token_hash>[a-z0-9]+).+")


class ImpersonateTest(SingleCoursePageTestMixin, MockAddMessageMixing, TestCase):
    def test_impersonate_by_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_impersonate_view()
            self.assertEqual(resp.status_code, 403)

            resp = self.post_impersonate_view(
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
            resp = self.get_impersonate_view()
            self.assertEqual(resp.status_code, 403)

            resp = self.post_impersonate_view(
                impersonatee=self.student_participation.user)
            self.assertEqual(resp.status_code, 403)
            resp = self.get_stop_impersonate()
            self.assertEqual(resp.status_code, 403)
            self.assertIsNone(self.client.session.get("impersonate_id"))

            resp = self.post_stop_impersonate()
            self.assertEqual(resp.status_code, 403)

    def test_impersonate_by_ta(self):
        user = self.ta_participation.user
        impersonatable = get_impersonable_user_qset(user)
        self.assertEqual(impersonatable.count(), 1)

        # create 2 participations, on is not active,
        # impersonatable count should be 2, not 3
        factories.ParticipationFactory.create(
            course=self.course,
            status=constants.participation_status.active)
        factories.ParticipationFactory.create(
            course=self.course,
            status=constants.participation_status.requested)
        impersonatable = get_impersonable_user_qset(user)
        self.assertEqual(impersonatable.count(), 2)
        self.assertNotIn(self.instructor_participation.user, impersonatable)

        with self.temporarily_switch_to_user(user):
            resp = self.get_impersonate_view()
            self.assertEqual(resp.status_code, 200)

            resp = self.post_impersonate_view(
                impersonatee=self.student_participation.user)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(self.client.session["impersonate_id"],
                             self.student_participation.user.pk)

            # re-impersonate without stop_impersonating
            resp = self.post_impersonate_view(
                impersonatee=self.student_participation.user)
            # because the request.user is the impernatee (student)
            # who has no pperm
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(self.client.session["impersonate_id"],
                             self.student_participation.user.pk)

            # stop_impersonating
            self.post_stop_impersonate()
            self.assertIsNone(self.client.session.get("impersonate_id"))
            self.assertAddMessageCalledWith(NO_LONGER_IMPERSONATING_MESSAGE)

            # fail re-stop_impersonating
            resp = self.post_stop_impersonate()
            self.assertEqual(resp.status_code, 200)
            self.assertAddMessageCalledWith(NOT_IMPERSONATING_MESSAGE)

            # not allowed to impersonate instructor
            resp = self.post_impersonate_view(
                impersonatee=self.instructor_participation.user)

            self.assertEqual(resp.status_code, 200)
            self.assertFormError(resp.context["form"], "user",
                                 IMPERSONATE_FORM_ERROR_NOT_VALID_USER_MSG)
            self.assertIsNone(self.client.session.get("impersonate_id"))

            # not allowed to impersonate self
            resp = self.post_impersonate_view(
                impersonatee=user)
            self.assertEqual(resp.status_code, 200)
            self.assertFormError(resp.context["form"], "user",
                                 IMPERSONATE_FORM_ERROR_NOT_VALID_USER_MSG)
            self.assertIsNone(self.client.session.get("impersonate_id"))

    def test_impersonate_by_superuser(self):
        user = self.superuser
        impersonatable = get_impersonable_user_qset(user)
        self.assertEqual(impersonatable.count(), 3)

        with self.temporarily_switch_to_user(user):
            resp = self.post_impersonate_view(
                impersonatee=self.instructor_participation.user)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(self.client.session["impersonate_id"],
                             self.instructor_participation.user.pk)

    def test_impersonate_by_instructor(self):
        user = self.instructor_participation.user
        impersonatable = get_impersonable_user_qset(user)
        self.assertEqual(impersonatable.count(), 2)

        with self.temporarily_switch_to_user(user):
            resp = self.get_impersonate_view()
            self.assertEqual(resp.status_code, 200)

            # first impersonate ta who has pperm
            resp = self.post_impersonate_view(
                impersonatee=self.ta_participation.user)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(self.client.session["impersonate_id"],
                             self.ta_participation.user.pk)

            # then impersonate student without stop_impersonating,
            # this will fail
            resp = self.post_impersonate_view(
                impersonatee=self.student_participation.user)
            self.assertEqual(resp.status_code, 200)
            self.assertAddMessageCalledWith(ALREADY_IMPERSONATING_SOMEONE_MESSAGE)
            self.assertEqual(self.client.session["impersonate_id"],
                             self.ta_participation.user.pk)

            # stop_impersonating
            resp = self.post_stop_impersonate()
            self.assertEqual(resp.status_code, 200)
            self.assertAddMessageCalledWith(NO_LONGER_IMPERSONATING_MESSAGE)

            # re-stop_impersonating
            resp = self.post_stop_impersonate()
            self.assertEqual(resp.status_code, 200)
            self.assertAddMessageCalledWith(NOT_IMPERSONATING_MESSAGE)

    def test_impersonate_error_none_user(self):
        with self.temporarily_switch_to_user(self.ta_participation.user):
            self.post_impersonate_view(
                impersonatee=self.student_participation.user)
            session = self.client.session
            session["impersonate_id"] = None
            session.save()

            resp = self.client.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertAddMessageCalledWith(ERROR_WHILE_IMPERSONATING_MESSAGE)

    def test_impersonatee_error_none_existing_user(self):
        with self.temporarily_switch_to_user(self.ta_participation.user):
            self.post_impersonate_view(
                impersonatee=self.student_participation.user)
            session = self.client.session
            session["impersonate_id"] = 100
            session.save()

            resp = self.client.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertAddMessageCalledWith(ERROR_WHILE_IMPERSONATING_MESSAGE)

    def test_impersonate_error_no_impersonatable(self):
        with self.temporarily_switch_to_user(self.ta_participation.user):
            self.post_impersonate_view(
                impersonatee=self.student_participation.user)

            # drop the only impersonatable participation
            from course.constants import participation_status
            self.student_participation.status = participation_status.dropped
            self.student_participation.save()

            resp = self.client.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)
            self.assertAddMessageCalledWith(ERROR_WHILE_IMPERSONATING_MESSAGE)

    def test_impersonator_flow_page_visit(self):
        session = factories.FlowSessionFactory(
            course=self.course, participation=self.student_participation)
        page_data = factories.FlowPageDataFactory(flow_session=session)
        factories.FlowPageVisitFactory(page_data=page_data)

        with self.temporarily_switch_to_user(self.ta_participation.user):
            resp = self.client.get(self.get_page_url_by_ordinal(page_ordinal=0))
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(FlowPageVisit.objects.count(), 2)
            second_visit = FlowPageVisit.objects.all().order_by("-pk")[0]

            # this visit is not impersonated
            self.assertFalse(second_visit.is_impersonated())
            self.assertIsNone(second_visit.impersonated_by)

            # this visit is not impersonated
            self.post_impersonate_view(impersonatee=self.student_participation.user)
            resp = self.client.get(self.get_page_url_by_ordinal(page_ordinal=0))
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(FlowPageVisit.objects.count(), 3)
            second_visit = FlowPageVisit.objects.all().order_by("-pk")[0]
            self.assertTrue(second_visit.is_impersonated())
            self.assertEqual(second_visit.impersonated_by,
                             self.ta_participation.user)

    def test_stop_impersonate_by_get_or_non_ajax_post_while_not_impersonating(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            # request by get
            resp = self.get_stop_impersonate()
            self.assertEqual(resp.status_code, 403)

    def test_stop_impersonate_by_get_or_non_ajax_post_while_impersonating(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            # first impersonate a user
            self.post_impersonate_view(
                impersonatee=self.student_participation.user)

            # request by get
            resp = self.get_stop_impersonate()
            self.assertEqual(resp.status_code, 403)
            self.assertIsNotNone(self.client.session.get("impersonate_id"))

    def test_stop_impersonate_suspicious_post(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            # first impersonate a user
            self.post_impersonate_view(
                impersonatee=self.student_participation.user)

            resp = self.post_stop_impersonate(data={"foo": "bar"})
            self.assertEqual(resp.status_code, 400)
            self.assertIsNotNone(self.client.session.get("impersonate_id"))

    # {{{ ImpersonateForm select2 result test

    def test_impersonate_select2_user_search_widget_instructor(self):

        p = factories.ParticipationFactory.create(course=self.course)
        # make sure user have/don't have first_name and last_name get
        # rendered in UserSearchWidget when requested.
        if p.user.last_name:
            p.user.last_name = ""
            p.user.save()

        user = self.instructor_participation.user

        with self.temporarily_switch_to_user(user):
            impersonatable = get_impersonable_user_qset(user)

            resp = self.get_impersonate_view()
            field_id = self.get_select2_field_id_from_response(resp)

            # With no search term, should display all impersonatable users
            term = None
            resp = self.select2_get_request(field_id=field_id, term=term)
            self.assertEqual(resp.status_code, 200)
            result = self.get_select2_response_data(resp)
            self.assertEqual(len(result), impersonatable.count())
            all_ids = [int(r["id"]) for r in result]

            # impersonator and superuser not in result
            self.assertNotIn(user.pk, all_ids)
            self.assertNotIn(self.superuser.pk, all_ids)

            impersonatable_pks = list(impersonatable.values_list("pk", flat=True))
            self.assertSetEqual(set(impersonatable_pks), set(all_ids))

            all_text = [r["text"] for r in result]
            for s in all_text:
                for bad_string in ["(), None, none"]:
                    if bad_string in s:
                        self.fail("label_from_instance method in "
                                  "course.auth.UserSearchWidget should not "
                                  "return %s" % bad_string)

            # Search ta by ta's last name
            impersonatee = self.ta_participation.user
            term = impersonatee.last_name
            resp = self.select2_get_request(field_id=field_id, term=term)
            self.assertEqual(resp.status_code, 200)
            result = self.get_select2_response_data(resp)
            self.assertEqual(len(result), 1)
            self.assertEqual(impersonatee.pk, int(result[0]["id"]))

            # Search student by his email
            impersonatee = self.student_participation.user
            term = impersonatee.email
            resp = self.select2_get_request(field_id=field_id, term=term)
            self.assertEqual(resp.status_code, 200)
            result = self.get_select2_response_data(resp)
            self.assertEqual(len(result), 1)
            self.assertEqual(impersonatee.pk, int(result[0]["id"]))

    def test_impersonate_select2_user_search_widget_ta(self):

        user = self.ta_participation.user

        with self.temporarily_switch_to_user(user):
            impersonatable = get_impersonable_user_qset(user)

            resp = self.get_impersonate_view()
            field_id = self.get_select2_field_id_from_response(resp)

            # With no search term
            term = None
            resp = self.select2_get_request(field_id=field_id, term=term)
            self.assertEqual(resp.status_code, 200)
            result = self.get_select2_response_data(resp)
            self.assertEqual(len(result), impersonatable.count())
            all_ids = [int(r["id"]) for r in result]

            # impersonator and superuser not in result
            self.assertNotIn(user.pk, all_ids)
            self.assertNotIn(self.superuser.pk, all_ids)

            impersonatable_pks = list(impersonatable.values_list("pk", flat=True))
            self.assertSetEqual(set(impersonatable_pks), set(all_ids))

            all_text = [r["text"] for r in result]
            for s in all_text:
                for bad_string in ["(), None, none"]:
                    if bad_string in s:
                        self.fail("label_from_instance method in "
                                  "course.auth.UserSearchWidget should not "
                                  "return %s" % bad_string)

            # Search student by his email
            impersonatee = self.student_participation.user
            term = impersonatee.email
            resp = self.select2_get_request(field_id=field_id, term=term)
            self.assertEqual(resp.status_code, 200)
            result = self.get_select2_response_data(resp)
            self.assertEqual(len(result), 1)
            self.assertEqual(impersonatee.pk, int(result[0]["id"]))

    # }}}


class CrossCourseImpersonateTest(CoursesTestMixinBase, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        course1 = factories.CourseFactory()
        course2 = factories.CourseFactory(identifier="another-course")

        cls.ta = factories.UserFactory()

        # create 2 ta with the same user in 2 courses
        cls.course1_ta_participation = factories.ParticipationFactory.create(
            user=cls.ta, course=course1, roles=["ta"])
        cls.course1_ta_participation = factories.ParticipationFactory.create(
            user=cls.ta, course=course2, roles=["ta"])

        # create a student in each courses
        factories.ParticipationFactory(course=course1)
        factories.ParticipationFactory(course=course2)

    def test_impersonate_across_courses(self):
        user = self.ta
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

        user = self.ta
        impersonatable = get_impersonable_user_qset(user)
        self.assertEqual(impersonatable.count(), 0)

        with self.temporarily_switch_to_user(user):
            resp = self.get_impersonate_view()
            self.assertEqual(resp.status_code, 403)


class AuthTestMixin:
    _user_create_kwargs = {
        "username": "test_user", "password": "mypassword",
        "email": "my_email@example.com"
    }

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.test_user = (
            get_user_model().objects.create_user(**cls._user_create_kwargs))
        cls.existing_user_count = get_user_model().objects.count()

    def setUp(self):
        super().setUp()
        self.test_user.refresh_from_db()

    def get_sign_in_data(self):
        return self._user_create_kwargs.copy()

    def assertNewUserCreated(self, count=1):  # noqa
        self.assertEqual(get_user_model().objects.count(),
                         self.existing_user_count + count)

    def assertNoNewUserCreated(self):  # noqa
        self.assertEqual(self.existing_user_count, get_user_model().objects.count())

    def assertURLEqual(self, url, expected, parse_qs=False):  # noqa
        """
        Given two URLs, make sure all their components (the ones given by
        urlparse) are equal, only comparing components that are present in both
        URLs.
        If `parse_qs` is True, then the querystrings are parsed with QueryDict.
        This is useful if you don't want the order of parameters to matter.
        Otherwise, the query strings are compared as-is.
        """
        fields = ParseResult._fields

        for attr, x, y in zip(fields, urlparse(url), urlparse(expected)):
            if parse_qs and attr == "query":
                x, y = QueryDict(x), QueryDict(y)
            if x and y and x != y:
                self.fail(f"{url!r} != {expected!r} ({attr} doesn't match)")

    def do_test_security_check(self, url_name):
        url = reverse(url_name)

        with override_settings(ALLOWED_HOSTS=["testserver"]):
            # These URLs should not pass the security check.
            bad_urls = (
                "http://example.com",
                "http:///example.com",
                "https://example.com",
                "ftp://example.com",
                "///example.com",
                "//example.com",
                'javascript:alert("XSS")',
            )
            for bad_url in bad_urls:
                with self.temporarily_switch_to_user(None):
                    with self.subTest(bad_url=bad_url):
                        nasty_url = self.concatenate_redirect_url(url, bad_url)
                        response = self.client.post(
                                nasty_url, self.get_sign_in_data())
                        self.assertEqual(response.status_code, 302)
                        self.assertNotIn(bad_url, response.url,
                                         "%s should be blocked" % bad_url)

            # These URLs should pass the security check.
            good_urls = (
                "/view/?param=http://example.com",
                "/view/?param=https://example.com",
                "/view?param=ftp://example.com",
                "view/?param=//example.com",
                "https://testserver/",
                "HTTPS://testserver/",
                "//testserver/",
                "/url%20with%20spaces/",
            )
            for good_url in good_urls:
                with self.temporarily_switch_to_user(None):
                    with self.subTest(good_url=good_url):
                        safe_url = self.concatenate_redirect_url(url, good_url)
                        response = self.client.post(
                                safe_url, self.get_sign_in_data())
                        self.assertEqual(response.status_code, 302)
                        self.assertIn(good_url, response.url,
                                      "%s should be allowed" % good_url)

    def assertSessionHasUserLoggedIn(self):  # noqa
        self.assertIn(SESSION_KEY, self.client.session)

    def assertSessionHasNoUserLoggedIn(self):  # noqa
        self.assertNotIn(SESSION_KEY, self.client.session)

    def concatenate_redirect_url(self, url, redirect_to=None):
        if not redirect_to:
            return url
        return ("{url}?{next}={bad_url}".format(
            url=url,
            next=REDIRECT_FIELD_NAME,
            bad_url=quote(redirect_to),
        ))

    def get_sign_up_view_url(self, redirect_to=None):
        return self.concatenate_redirect_url(
            reverse("relate-sign_up"), redirect_to
        )

    def get_sign_up(self, redirect_to=None, follow=False):
        return self.client.get(self.get_sign_up_view_url(redirect_to),
                          follow=follow)

    def post_sign_up(self, data, redirect_to=None, follow=False):
        return self.client.post(self.get_sign_up_view_url(redirect_to), data,
                           follow=follow)

    def get_sign_in_choice_url(self, redirect_to=None):
        return self.concatenate_redirect_url(
            reverse("relate-sign_in_choice"), redirect_to)

    def get_sign_in_by_user_pw_url(self, redirect_to=None):
        return self.concatenate_redirect_url(
            reverse("relate-sign_in_by_user_pw"), redirect_to)

    def get_sign_in_by_user_pw(self, redirect_to=None, follow=False):
        return self.client.get(self.get_sign_in_by_user_pw_url(redirect_to),
                          follow=follow)

    def post_sign_in_by_user_pw(self, data, redirect_to=None, follow=False):
        return self.client.post(self.get_sign_in_by_user_pw_url(redirect_to), data,
                           follow=follow)

    def get_sign_in_by_email_url(self, redirect_to=None):
        return self.concatenate_redirect_url(
            reverse("relate-sign_in_by_email"), redirect_to)

    def get_sign_in_by_email(self, redirect_to=None, follow=False):
        return self.client.get(self.get_sign_in_by_email_url(redirect_to),
                          follow=follow)

    def post_sign_in_by_email(self, data, redirect_to=None, follow=False):
        return self.client.post(self.get_sign_in_by_email_url(redirect_to), data,
                           follow=follow)

    def get_sign_out_view_url(self, redirect_to=None):
        return self.concatenate_redirect_url(
            reverse("relate-logout"), redirect_to)

    def get_sign_out(self, redirect_to=None, follow=False):
        return self.client.get(self.get_sign_out_view_url(redirect_to),
                          follow=follow)

    def post_sign_out(self, data, redirect_to=None, follow=False):
        # Though RELATE and django are using GET to sign out
        return self.client.post(self.get_sign_out_view_url(redirect_to), data,
                           follow=follow)

    def get_sign_out_confirmation_view_url(self, redirect_to=None):
        return self.concatenate_redirect_url(
            reverse("relate-logout-confirmation"), redirect_to
        )

    def get_sign_out_confirmation(self, redirect_to=None, follow=False):
        return self.client.get(self.get_sign_out_confirmation_view_url(redirect_to),
                          follow=follow)

    def post_sign_out_confirmation(self, data, redirect_to=None, follow=False):
        return self.client.post(self.get_sign_out_confirmation_view_url(redirect_to),
                           data,
                           follow=follow)

    def get_user_profile_url(self, redirect_to=None):
        return self.concatenate_redirect_url(
            reverse("relate-user_profile"), redirect_to)

    def get_user_profile(self, redirect_to=None, follow=False):
        return self.client.get(self.get_user_profile_url(redirect_to),
                          follow=follow)

    def post_user_profile(self, data, redirect_to=None, follow=False):
        return self.client.post(self.get_user_profile_url(redirect_to),
                           data=data, follow=follow)


class AuthViewNamedURLTests(AuthTestMixin, TestCase):
    need_logout_confirmation_named_urls = [
        ("relate-sign_in_choice", [], {}),
        ("relate-sign_in_by_user_pw", [], {}),
        ("relate-sign_in_by_email", [], {}),
        ("relate-sign_up", [], {}),
        ("relate-reset_password", [], {}),
        ("relate-reset_password", [], {"field": "instid"}),
        ("relate-reset_password_stage2",
         [], {"user_id": 0, "sign_in_key": "abcd"}),
        ("relate-sign_in_stage2_with_token",
         [], {"user_id": 0, "sign_in_key": "abcd"})]

    djsaml2_urls = [
        (name, [], {})
        for name in load_url_pattern_names(djsaml2_urlpatterns)
    ]

    need_login_named_urls = [
        ("relate-logout", [], {}),
        ("relate-logout-confirmation", [], {}),
        ("relate-user_profile", [], {}),
        ("relate-manage_authentication_tokens", [],
         {"course_identifier": "test-course"}),
    ]

    @override_settings(RELATE_SIGN_IN_BY_SAML2_ENABLED=True)
    def test_named_urls(self):
        # Named URLs should be reversible

        # Because RELATE_SIGN_IN_BY_SAML2_ENABLED is not enabled in test settings.
        # djangosaml2 url patterns should be included in this way.
        reload_urlconf()

        all_expected_named_urls = (
                self.need_logout_confirmation_named_urls
                + self.djsaml2_urls + self.need_login_named_urls)
        for name, args, kwargs in all_expected_named_urls:
            with self.subTest(name=name):
                try:
                    reverse(name, args=args, kwargs=kwargs)
                except NoReverseMatch:
                    self.fail(
                        "Reversal of url named '%s' failed with "
                        "NoReverseMatch" % name)

    @override_settings(RELATE_SIGN_IN_BY_USERNAME_ENABLED=True,
                       RELATE_SIGN_IN_BY_EMAIL_ENABLED=True)
    def test_need_logout_urls(self):
        # These URLs should be redirected to relate-logout-confirmation when
        # there're user sessions
        for name, args, kwargs in self.need_logout_confirmation_named_urls:
            self.client.force_login(get_user_model().objects.last())
            with self.subTest(name=name):
                url = reverse(name, args=args, kwargs=kwargs)
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 302,
                                 "The response should be redirected to "
                                 "'relate-logout-confirmation'")
                expected_redirect_url = (
                    self.concatenate_redirect_url(
                        reverse("relate-logout-confirmation"), url))
                self.assertRedirects(resp, expected_redirect_url,
                                     fetch_redirect_response=False)


@pytest.mark.slow
class SignInByPasswordTest(CoursesTestMixinBase,
                           AuthTestMixin, MockAddMessageMixing, TestCase):
    @override_settings(RELATE_SIGN_IN_BY_USERNAME_ENABLED=True)
    def test_user_pw_enabled_sign_in_view_anonymous(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_sign_in_by_user_pw()
            self.assertEqual(resp.status_code, 200)
            self.assertSessionHasNoUserLoggedIn()

            resp = self.post_sign_in_by_user_pw(data=self.get_sign_in_data())
            self.assertSessionHasUserLoggedIn()
            self.assertEqual(resp.status_code, 302)
            self.assertRedirects(resp, reverse("relate-home"),
                                 fetch_redirect_response=False)

    @override_settings(RELATE_SIGN_IN_BY_USERNAME_ENABLED=False)
    def test_username_pw_not_enabled_sign_in_view_anonymous(self):
        expected_msg = "Username-based sign-in is not being used"
        with self.temporarily_switch_to_user(None):
            resp = self.get_sign_in_by_user_pw(follow=True)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionHasNoUserLoggedIn()
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith(expected_msg)

            resp = self.post_sign_in_by_user_pw(data=self.get_sign_in_data(),
                                                follow=False)
            self.assertEqual(resp.status_code, 302)
            self.assertRedirects(resp, self.get_sign_in_choice_url(),
                                 fetch_redirect_response=False)
            self.assertSessionHasNoUserLoggedIn()
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith(expected_msg)

    def test_security_check(self):
        self.do_test_security_check(url_name="relate-sign_in_by_user_pw")

    def test_login_form_invalid(self):
        with self.temporarily_switch_to_user(None):
            invalid_data = self.get_sign_in_data()
            invalid_data["password"] = "invalid_pw"
            resp = self.post_sign_in_by_user_pw(data=invalid_data)
            self.assertSessionHasNoUserLoggedIn()
            self.assertEqual(resp.status_code, 200)
            self.assertFormErrorLoose(resp,
                                      "Please enter a correct username and "
                                      "password. Note that both fields may "
                                      "be case-sensitive.")

    def test_login_form_invalid_with_redirect_url_remains(self):
        with self.temporarily_switch_to_user(None):
            invalid_data = self.get_sign_in_data()
            invalid_data["password"] = "invalid_pw"
            redirect_to = "http:\\somedomain"
            resp = self.post_sign_in_by_user_pw(data=invalid_data,
                                                redirect_to=redirect_to)
            self.assertSessionHasNoUserLoggedIn()
            self.assertEqual(resp.status_code, 200)

            # We don't use assertIn(url, resp.url) because the response
            # can be a TemplateResponse
            self.assertResponseContextContains(
                resp, REDIRECT_FIELD_NAME, redirect_to)


@override_settings(RELATE_SIGN_IN_BY_EMAIL_ENABLED=True)
class SignInByEmailTest(CoursesTestMixinBase, MockAddMessageMixing,
                        AuthTestMixin, LocmemBackendTestsMixin, TestCase):
    courses_setup_list = []

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        new_email = "somebody@example.com"
        data = {"email": new_email}

        client = Client()
        # first login attempt
        resp = client.post(reverse("relate-sign_in_by_email"), data=data)

        first_request = resp.wsgi_request
        assert resp.status_code == 302
        assert get_user_model().objects.count() == cls.existing_user_count + 1
        user = get_user_model().objects.get(email=new_email)
        first_sign_in_key = user.sign_in_key
        cls.first_sign_in_url = first_request.build_absolute_uri(
            reverse(
                "relate-sign_in_stage2_with_token",
                args=(user.id, user.sign_in_key,)))

        assert len(mail.outbox) == 1
        assert cls.first_sign_in_url in mail.outbox[0].body

        # second login attempt
        resp = client.post(reverse("relate-sign_in_by_email"), data=data)

        second_request = resp.wsgi_request
        assert resp.status_code == 302
        assert get_user_model().objects.count() == cls.existing_user_count + 1
        user = get_user_model().objects.get(email=new_email)
        second_sign_in_key = user.sign_in_key
        cls.second_sign_in_url = second_request.build_absolute_uri(
            reverse(
                "relate-sign_in_stage2_with_token",
                args=(user.id, user.sign_in_key,)))

        assert len(mail.outbox) == 2
        assert cls.second_sign_in_url in mail.outbox[1].body

        assert first_sign_in_key != second_sign_in_key
        cls.user = user

    def setUp(self):
        super().setUp()
        self.user.refresh_from_db()
        self.flush_mailbox()

    def test_email_login_enabled_sign_in_view_anonymous(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_sign_in_by_email()
            self.assertEqual(resp.status_code, 200)
            self.assertSessionHasNoUserLoggedIn()
            self.assertEqual(len(mail.outbox), 0)

            resp = self.post_sign_in_by_email(data=self.get_sign_in_data())
            self.assertSessionHasNoUserLoggedIn()
            self.assertEqual(resp.status_code, 302)
            self.assertRedirects(resp, reverse("relate-home"),
                                 fetch_redirect_response=False)
            expected_msg = (
                "Email sent. Please check your email and click the link.")
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith(expected_msg)
            self.assertEqual(len(mail.outbox), 1)

    @override_settings()
    def test_email_login_not_enabled_sign_in_view_anonymous(self):
        expected_msg = "Email-based sign-in is not being used"
        settings.RELATE_SIGN_IN_BY_EMAIL_ENABLED = False
        with self.temporarily_switch_to_user(None):
            resp = self.get_sign_in_by_email(follow=True)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionHasNoUserLoggedIn()
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith(expected_msg)
            self.assertEqual(len(mail.outbox), 0)

            resp = self.post_sign_in_by_email(data=self.get_sign_in_data(),
                                              follow=False)
            self.assertEqual(resp.status_code, 302)
            self.assertRedirects(resp, self.get_sign_in_choice_url(),
                                 fetch_redirect_response=False)
            self.assertSessionHasNoUserLoggedIn()
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith(expected_msg)
            self.assertEqual(len(mail.outbox), 0)

    def test_email_login_form_invalid(self):
        with self.temporarily_switch_to_user(None):
            data = {"email": "not a email"}
            resp = self.post_sign_in_by_email(data=data,
                                              follow=False)
            self.assertEqual(resp.status_code, 200)
            self.assertFormErrorLoose(resp, "Enter a valid email address.")
            self.assertSessionHasNoUserLoggedIn()
            self.assertEqual(len(mail.outbox), 0)

    @override_settings()
    def test_stage2_login_email_login_not_enabled(self):
        settings.RELATE_SIGN_IN_BY_EMAIL_ENABLED = False
        expected_msg = "Email-based sign-in is not being used"
        with self.temporarily_switch_to_user(None):
            resp = self.client.get(self.second_sign_in_url)
            self.assertAddMessageCalledWith(expected_msg)
            self.assertEqual(resp.status_code, 302)
            self.assertRedirects(resp, self.get_sign_in_choice_url(),
                                 fetch_redirect_response=False)
            self.assertSessionHasNoUserLoggedIn()

    def test_stage2_login_with_staled_signing_key(self):
        with self.temporarily_switch_to_user(None):
            expected_msg = ("Invalid sign-in token. Perhaps you've used "
                            "an old token email?")
            resp = self.client.get(self.first_sign_in_url)
            self.assertAddMessageCalledWith(expected_msg)
            self.assertEqual(resp.status_code, 403)
            self.assertSessionHasNoUserLoggedIn()

    def test_stage2_login_user_inactive(self):
        self.user.is_active = False
        self.user.save()
        self.user.refresh_from_db()

        with self.temporarily_switch_to_user(None):
            expected_msg = ("Account disabled.")
            resp = self.client.get(self.second_sign_in_url)
            self.assertAddMessageCalledWith(expected_msg)
            self.assertEqual(resp.status_code, 403)
            self.assertSessionHasNoUserLoggedIn()

    def login_stage2_without_profile(self, user):
        with self.temporarily_switch_to_user(None):
            expected_msg = (
                "Successfully signed in. "
                "Please complete your registration information below.")
            resp = self.client.get(self.second_sign_in_url)
            self.assertAddMessageCalledWith(expected_msg)
            self.assertEqual(resp.status_code, 302)

            self.assertRedirects(resp,
                                 self.get_user_profile_url() + "?first_login=1",
                                 fetch_redirect_response=False)
            self.assertSessionHasUserLoggedIn()

    def test_stage2_login_without_first_name_last_name(self):
        self.login_stage2_without_profile(self.user)

    def test_stage2_login_without_first_name(self):
        self.user.first_name = "foo"
        self.user.save()
        self.login_stage2_without_profile(self.user)

    def test_stage2_login_without_last_name(self):
        self.user.last_name = "bar"
        self.user.save()
        self.login_stage2_without_profile(self.user)

    def test_stage2_login_with_first_name_and_last_name(self):
        self.user.first_name = "foo"
        self.user.last_name = "bar"
        self.user.save()
        with self.temporarily_switch_to_user(None):
            expected_msg = (
                "Successfully signed in.")
            resp = self.client.get(self.second_sign_in_url)
            self.assertAddMessageCalledWith(expected_msg)
            self.assertEqual(resp.status_code, 302)

            self.assertRedirects(resp, reverse("relate-home"),
                                 fetch_redirect_response=False)
            self.assertSessionHasUserLoggedIn()

    def test_stage2_login_non_existing_user(self):
        user = get_user_model().objects.get(pk=self.user.pk)
        user.delete()
        expected_msg = (
            "Account does not exist.")
        with self.temporarily_switch_to_user(None):
            resp = self.client.get(self.second_sign_in_url)
            self.assertAddMessageCalledWith(expected_msg)
            self.assertEqual(resp.status_code, 403)


@override_settings(RELATE_REGISTRATION_ENABLED=True)
class SignUpTest(CoursesTestMixinBase, MockAddMessageMixing,
                 AuthTestMixin, LocmemBackendTestsMixin, TestCase):
    sign_up_user_dict = {
        "username": "test_sign_up_user", "password": "mypassword",
        "email": "test_sign_up@example.com"
    }

    def setUp(self):
        super().setUp()
        self.client.logout()

    @override_settings()
    def test_signup_registration_not_enabled(self):
        settings.RELATE_REGISTRATION_ENABLED = False
        resp = self.get_sign_up()
        self.assertEqual(resp.status_code, 400)
        self.assertNoNewUserCreated()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("self-registration is not enabled", mail.outbox[0].body)

        self.flush_mailbox()

        resp = self.post_sign_up({})
        self.assertEqual(resp.status_code, 400)
        self.assertNoNewUserCreated()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("self-registration is not enabled", mail.outbox[0].body)

    def get_sign_up_user_dict(self):
        return self.sign_up_user_dict.copy()

    def test_sign_up_form_invalid(self):
        with self.temporarily_switch_to_user(None):
            data = self.get_sign_up_user_dict()
            data["email"] = "not a email"
            resp = self.post_sign_up(data=data,
                                     follow=False)
            self.assertEqual(resp.status_code, 200)
            self.assertFormErrorLoose(resp, "Enter a valid email address.")
            self.assertNoNewUserCreated()
            self.assertEqual(len(mail.outbox), 0)

    def test_signup_existing_user_name(self):
        resp = self.get_sign_up()
        self.assertEqual(resp.status_code, 200)
        self.assertNoNewUserCreated()

        expected_msg = "A user with that username already exists."

        data = self.get_sign_up_user_dict()
        data["username"] = self.test_user.username
        resp = self.post_sign_up(data=data, follow=False)

        self.assertEqual(resp.status_code, 200)
        self.assertNoNewUserCreated()
        self.assertEqual(len(mail.outbox), 0)
        self.assertAddMessageCalledWith(expected_msg)

    def test_signup_existing_email(self):
        expected_msg = (
                "That email address is already in use. "
                "Would you like to "
                "<a href='%s'>reset your password</a> instead?"
                % reverse("relate-reset_password"))

        data = self.get_sign_up_user_dict()
        data["email"] = self.test_user.email
        resp = self.post_sign_up(data=data, follow=False)

        self.assertEqual(resp.status_code, 200)
        self.assertNoNewUserCreated()
        self.assertEqual(len(mail.outbox), 0)
        self.assertAddMessageCalledWith(expected_msg)

    def test_signup_success(self):
        expected_msg = (
            "Email sent. Please check your email and click "
            "the link.")

        data = self.get_sign_up_user_dict()
        resp = self.post_sign_up(data=data, follow=False)
        self.assertRedirects(resp, reverse("relate-home"),
                             fetch_redirect_response=False)

        sent_request = resp.wsgi_request

        self.assertEqual(resp.status_code, 302)
        self.assertNewUserCreated()
        self.assertEqual(len(mail.outbox), 1)

        new_user = get_user_model().objects.last()
        sign_in_url = sent_request.build_absolute_uri(
            reverse(
                "relate-reset_password_stage2",
                args=(new_user.id, new_user.sign_in_key,))
            + "?to_profile=1")
        self.assertIn(sign_in_url, mail.outbox[0].body)
        self.assertAddMessageCalledWith(expected_msg)


class SignOutTest(CoursesTestMixinBase, AuthTestMixin,
                  MockAddMessageMixing, TestCase):

    def test_sign_out_anonymous(self):
        with self.temporarily_switch_to_user(None):
            expected_msg = "You've already signed out."
            resp = self.get_sign_out(follow=False)
            self.assertEqual(resp.status_code, 302)
            self.assertRedirects(resp, reverse("relate-home"),
                                 fetch_redirect_response=False)
            self.assertSessionHasNoUserLoggedIn()
            self.assertAddMessageCalledWith(expected_msg)

    @override_settings(RELATE_SIGN_IN_BY_SAML2_ENABLED=False)
    def test_sign_out_by_get(self):
        with mock.patch("djangosaml2.views._get_subject_id") \
                as mock_get_subject_id, \
                mock.patch("djangosaml2.views.LogoutInitView.get") \
                as mock_saml2_logout:
            mock_get_subject_id.return_value = "some_id"
            with self.temporarily_switch_to_user(self.test_user):
                resp = self.get_sign_out(follow=True)
                self.assertRedirects(resp, reverse("relate-home"),
                                     target_status_code=200,
                                     fetch_redirect_response=False)
                self.assertSessionHasNoUserLoggedIn()
            self.assertEqual(mock_saml2_logout.call_count, 0)

    @override_settings(RELATE_SIGN_IN_BY_SAML2_ENABLED=False)
    def test_sign_out_by_post(self):
        with mock.patch("djangosaml2.views._get_subject_id") \
                as mock_get_subject_id, \
                mock.patch("djangosaml2.views.LogoutInitView.get") \
                as mock_saml2_logout:
            mock_get_subject_id.return_value = "some_id"
            with self.temporarily_switch_to_user(self.test_user):
                resp = self.post_sign_out({})
                self.assertRedirects(resp, reverse("relate-home"),
                                     target_status_code=200,
                                     fetch_redirect_response=False)
                self.assertSessionHasNoUserLoggedIn()
            self.assertEqual(mock_saml2_logout.call_count, 0)

    @override_settings(RELATE_SIGN_IN_BY_SAML2_ENABLED=False)
    def test_sign_out_with_redirect_to(self):
        with self.temporarily_switch_to_user(self.test_user):
            resp = self.get_sign_out(redirect_to="/some_where/")
            self.assertRedirects(resp, "/some_where/",
                                 target_status_code=200,
                                 fetch_redirect_response=False)
            self.assertSessionHasNoUserLoggedIn()

    @override_settings(RELATE_SIGN_IN_BY_SAML2_ENABLED=True)
    def test_sign_out_with_saml2_enabled_no_subject_id(self):
        with mock.patch("djangosaml2.views._get_subject_id") \
                as mock_get_subject_id, \
                mock.patch("djangosaml2.views.LogoutInitView.get") \
                as mock_saml2_logout:
            mock_get_subject_id.return_value = None
            with self.temporarily_switch_to_user(self.test_user):
                resp = self.get_sign_out(follow=True)
                self.assertEqual(resp.status_code, 200)
                self.assertSessionHasNoUserLoggedIn()
            self.assertEqual(mock_saml2_logout.call_count, 0)

    @override_settings(RELATE_SIGN_IN_BY_SAML2_ENABLED=True)
    def test_sign_out_with_saml2_enabled_with_subject_id(self):
        self.client.force_login(self.test_user)
        with mock.patch("djangosaml2.views._get_subject_id") \
                as mock_get_subject_id, \
                mock.patch("djangosaml2.views.LogoutInitView.get") \
                as mock_saml2_logout:
            mock_get_subject_id.return_value = "some_id"
            mock_saml2_logout.return_value = HttpResponse()

            resp = self.get_sign_out(follow=True)

            self.assertEqual(resp.status_code, 200)
            self.assertEqual(mock_saml2_logout.call_count, 1)

    def test_sign_out_confirmation_anonymous(self):
        with self.temporarily_switch_to_user(None):
            expected_msg = "You've already signed out."
            resp = self.get_sign_out_confirmation(follow=False)
            self.assertEqual(resp.status_code, 302)
            self.assertRedirects(resp, reverse("relate-home"),
                                 fetch_redirect_response=False)
            self.assertSessionHasNoUserLoggedIn()
            self.assertAddMessageCalledWith(expected_msg)

    @override_settings(RELATE_SIGN_IN_BY_SAML2_ENABLED=True)
    def test_sign_out_confirmation(self):
        with self.temporarily_switch_to_user(self.test_user):
            resp = self.get_sign_out_confirmation(follow=False)
            self.assertEqual(resp.status_code, 200)

    @override_settings(RELATE_SIGN_IN_BY_SAML2_ENABLED=True)
    def test_sign_out_confirmation_with_redirect_to(self):
        with self.temporarily_switch_to_user(self.test_user):
            redirect_to = "/some_where/"
            resp = self.get_sign_out_confirmation(
                redirect_to=redirect_to, follow=False)
            self.assertEqual(resp.status_code, 200)
            self.assertIn(
                self.concatenate_redirect_url(
                    self.get_sign_out_view_url(), redirect_to
                ),
                resp.content.decode())


class UserProfileTest(CoursesTestMixinBase, AuthTestMixin,
                      MockAddMessageMixing, TestCase):

    def setUp(self):
        super().setUp()
        self.rf = RequestFactory()

    def generate_profile_data(self, **kwargs):
        profile_data = {
            "first_name": "",
            "last_name": "",
            "institutional_id": "",
            "editor_mode": "default"}
        profile_data.update(kwargs)
        return profile_data

    def post_profile_by_request_factory(self, data, query_string_dict=None):
        data.update({"submit_user": [""]})
        url = self.get_profile_view_url()
        if query_string_dict is not None:
            url = (
                "{}?{}".format(
                    url,
                    "&".join([f"{k}={v}"
                              for k, v in query_string_dict.items()])))
        request = self.rf.post(url, data)
        request.user = self.test_user
        request.session = mock.MagicMock()

        from course.auth import user_profile
        response = user_profile(request)
        return response

    def get_profile_by_request_factory(self):
        request = self.rf.get(self.get_profile_view_url())
        request.user = self.test_user
        request.session = mock.MagicMock()

        from course.auth import user_profile
        response = user_profile(request)
        return response

    def generate_profile_form_data(self, **kwargs):
        form_data = {
            "first_name": "",
            "last_name": "",
            "institutional_id": "",
            "institutional_id_confirm": "",
            "no_institutional_id": True,
            "editor_mode": "default"}
        form_data.update(kwargs)
        return form_data

    def test_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_profile()
            self.assertTrue(resp.status_code, 403)

            data = self.generate_profile_form_data()
            resp = self.post_profile(data)
            self.assertTrue(resp.status_code, 403)

    def test_get_profile(self):
        with self.temporarily_switch_to_user(self.test_user):
            resp = self.get_profile()
            self.assertTrue(resp.status_code, 200)

    def test_post_profile_without_submit_user(self):
        # Only POST with "submit_user" works
        with self.temporarily_switch_to_user(self.test_user):
            resp = self.get_profile()
            self.assertTrue(resp.status_code, 200)
            data = self.generate_profile_form_data(first_name="foo")

            # No "submit_user" in POST
            resp = self.client.post(self.get_profile_view_url(), data)
            self.test_user.refresh_from_db()
            self.assertEqual(self.test_user.first_name, "")

    def update_profile_by_post_form(self, user_profile_dict=None,
                                    update_profile_dict=None,
                                    query_string_dict=None):
        if user_profile_dict:
            assert isinstance(user_profile_dict, dict)
        else:
            user_profile_dict = {}

        if update_profile_dict:
            assert isinstance(update_profile_dict, dict)
        else:
            update_profile_dict = {}

        user_profile = self.generate_profile_data(**user_profile_dict)
        get_user_model().objects.filter(pk=self.test_user.pk).update(**user_profile)
        self.test_user.refresh_from_db()
        form_data = self.generate_profile_form_data(**update_profile_dict)
        return self.post_profile_by_request_factory(form_data, query_string_dict)

    def test_update_profile_with_different_settings(self):
        disabled_inst_id_html_pattern = (
            '<input type="text" name="institutional_id" value="%s" '
            'maxlength="100" class="textinput form-control" '
            'disabled id="id_institutional_id">')

        enabled_inst_id_html_pattern = (
            '<input type="text" name="institutional_id" value="%s" '
            'maxlength="100" class="textinput form-control" '
            'id="id_institutional_id">')

        expected_success_msg = "Profile data updated."
        expected_unchanged_msg = "No change was made on your profile."
        from collections import namedtuple
        Conf = namedtuple(
            "Conf", [
                "id",
                "override_settings_dict",
                "user_profile_dict",
                "update_profile_dict",
                "expected_result_dict",
                "assert_in_html_kwargs_list",
                "expected_msg",
            ])

        test_confs = (
            # {{{ basic test
            Conf("basic_1",
                 {EDITABLE_INST_ID_BEFORE_VERI: True, SHOW_INST_ID_FORM: True}, {},
                 {}, {}, [], expected_unchanged_msg),

            Conf("basic_2",
                 {EDITABLE_INST_ID_BEFORE_VERI: True, SHOW_INST_ID_FORM: False}, {},
                 {}, {}, [], expected_unchanged_msg),

            Conf("basic_3",
                 {EDITABLE_INST_ID_BEFORE_VERI: False, SHOW_INST_ID_FORM: True}, {},
                 {}, {}, [], expected_unchanged_msg),

            Conf("basic_4",
                 {EDITABLE_INST_ID_BEFORE_VERI: False, SHOW_INST_ID_FORM: False},
                 {}, {}, {}, [], expected_unchanged_msg),
            # }}}

            # {{{ update first_name
            Conf("first_name_1",
                 {},
                 {"first_name": "foo", "name_verified": False},
                 {"first_name": "bar"},
                 {"first_name": "bar"},
                 [],
                 expected_success_msg),

            Conf("first_name_2", {},
                 {"first_name": "foo", "name_verified": True},
                 {"first_name": "bar"},
                 {"first_name": "foo"},
                 [],
                 expected_unchanged_msg),

            # test strip
            Conf("first_name_3", {},
                 {"first_name": "foo", "name_verified": False},
                 {"first_name": "   bar  "},
                 {"first_name": "bar"},
                 [],
                 expected_success_msg),

            # }}}

            # {{{ update last_name
            Conf("last_name_1", {},
                 {"last_name": "foo", "name_verified": False},
                 {"last_name": "bar"},
                 {"last_name": "bar"},
                 [],
                 expected_success_msg),

            Conf("last_name_2", {},
                 {"last_name": "foo", "name_verified": True},
                 {"last_name": "bar"},
                 {"last_name": "foo"},
                 [],
                 expected_unchanged_msg),

            # test strip
            Conf("last_name_3", {},
                 {"last_name": "foo", "name_verified": False},
                 {"last_name": "  bar  "},
                 {"last_name": "bar"},
                 [],
                 expected_success_msg),

            # }}}

            # {{{ update institutional_id update
            Conf("institutional_id_update_1",
                 {EDITABLE_INST_ID_BEFORE_VERI: True, SHOW_INST_ID_FORM: True},
                 {"institutional_id": "1234", "institutional_id_verified": False},
                 {"institutional_id": "1234", "institutional_id_confirm": "1234"},
                 {"institutional_id": "1234"},
                 [{"needle": enabled_inst_id_html_pattern % "1234", "count": 1}],
                 expected_unchanged_msg),

            Conf("institutional_id_update_2",
                 {EDITABLE_INST_ID_BEFORE_VERI: True, SHOW_INST_ID_FORM: True},
                 {"institutional_id": "1234", "institutional_id_verified": False},
                 {"institutional_id": "123", "institutional_id_confirm": "123"},
                 {"institutional_id": "123"},
                 [{"needle": enabled_inst_id_html_pattern % "123", "count": 1}],
                 expected_success_msg),

            Conf("institutional_id_update_3",
                 {EDITABLE_INST_ID_BEFORE_VERI: True, SHOW_INST_ID_FORM: False},
                 {"institutional_id": "1234", "institutional_id_verified": False},
                 {"institutional_id": "1234", "institutional_id_confirm": "1234"},
                 {"institutional_id": "1234"},
                 [],
                 expected_unchanged_msg),

            Conf("institutional_id_update_4",
                 {EDITABLE_INST_ID_BEFORE_VERI: True, SHOW_INST_ID_FORM: False},
                 {"institutional_id": "1234", "institutional_id_verified": False},
                 {"institutional_id": "123", "institutional_id_confirm": "123"},
                 {"institutional_id": "123"},
                 [],
                 expected_success_msg),

            Conf("institutional_id_update_5",
                 {EDITABLE_INST_ID_BEFORE_VERI: True, SHOW_INST_ID_FORM: True},
                 {"institutional_id": "1234", "institutional_id_verified": True},
                 {"institutional_id": "1234", "institutional_id_confirm": "1234"},
                 {"institutional_id": "1234"},
                 [{"needle": disabled_inst_id_html_pattern % "1234", "count": 1}],
                 expected_unchanged_msg),

            Conf("institutional_id_update_6",
                 {EDITABLE_INST_ID_BEFORE_VERI: True, SHOW_INST_ID_FORM: True},
                 {"institutional_id": "1234", "institutional_id_verified": True},
                 {"institutional_id": "123", "institutional_id_confirm": "123"},
                 {"institutional_id": "1234"},
                 [{"needle": disabled_inst_id_html_pattern % "1234", "count": 1}],
                 expected_unchanged_msg),

            Conf("institutional_id_update_7",
                 {EDITABLE_INST_ID_BEFORE_VERI: True, SHOW_INST_ID_FORM: False},
                 {"institutional_id": "1234", "institutional_id_verified": True},
                 {"institutional_id": "1234", "institutional_id_confirm": "1234"},
                 {"institutional_id": "1234"},
                 [],
                 expected_unchanged_msg),

            Conf("institutional_id_update_8",
                 {EDITABLE_INST_ID_BEFORE_VERI: True, SHOW_INST_ID_FORM: False},
                 {"institutional_id": "1234", "institutional_id_verified": True},
                 {"institutional_id": "123", "institutional_id_confirm": "123"},
                 {"institutional_id": "1234"},
                 [{"needle": enabled_inst_id_html_pattern % "1234", "count": 0}],
                 expected_unchanged_msg),

            Conf("institutional_id_update_9",
                 {EDITABLE_INST_ID_BEFORE_VERI: False, SHOW_INST_ID_FORM: True},
                 {"institutional_id": "1234", "institutional_id_verified": False},
                 {"institutional_id": "1234", "institutional_id_confirm": "1234"},
                 {"institutional_id": "1234"},
                 [{"needle": disabled_inst_id_html_pattern % "1234", "count": 1}],
                 expected_unchanged_msg),

            Conf("institutional_id_update_10",
                 {EDITABLE_INST_ID_BEFORE_VERI: False, SHOW_INST_ID_FORM: True},
                 {"institutional_id": "1234", "institutional_id_verified": False},
                 {"institutional_id": "123", "institutional_id_confirm": "123"},
                 {"institutional_id": "1234"},
                 [{"needle": disabled_inst_id_html_pattern % "1234", "count": 1}],
                 expected_unchanged_msg),
            # }}}

            # {{{ institutional_id clean
            Conf("institutional_id_clean_1",
                 {EDITABLE_INST_ID_BEFORE_VERI: True, SHOW_INST_ID_FORM: True},
                 {"institutional_id": "1234", "institutional_id_verified": False},
                 {"institutional_id": "123", "institutional_id_confirm": "1234"},
                 {"institutional_id": "1234"},
                 [{"needle": "Inputs do not match.", "count": 1}],
                 None),

            Conf("institutional_id_clean_2",
                 {EDITABLE_INST_ID_BEFORE_VERI: True, SHOW_INST_ID_FORM: True},
                 {"institutional_id": "1234", "institutional_id_verified": False},
                 {"institutional_id": "123"},
                 {"institutional_id": "1234"},
                 [{"needle": "This field is required.", "count": 1}],
                 None),
            # }}}

            # Update with blank value
            # https://github.com/inducer/relate/pull/145
            Conf("clear_institutional_id",
                 {EDITABLE_INST_ID_BEFORE_VERI: True, SHOW_INST_ID_FORM: True},
                 {"institutional_id": "1234", "institutional_id_verified": False},
                 {"institutional_id": "", "institutional_id_confirm": ""},
                 {"institutional_id": None},
                 [],
                 expected_success_msg),

            # test post value with leading/trailing spaces (striped when saving)
            Conf("strip_institutional_id",
                 {EDITABLE_INST_ID_BEFORE_VERI: True, SHOW_INST_ID_FORM: True},
                 {},
                 {"institutional_id": "123   ",
                  "institutional_id_confirm": "   123"},
                 {"institutional_id": "123"},
                 [],
                 expected_success_msg),

        )

        for conf in test_confs:
            with self.subTest(conf.id):
                with override_settings(**conf.override_settings_dict):
                    resp = self.update_profile_by_post_form(
                        conf.user_profile_dict,
                        conf.update_profile_dict)

                    self.assertTrue(resp.status_code, 200)
                    self.test_user.refresh_from_db()
                    for k, v in conf.expected_result_dict.items():
                        self.assertEqual(self.test_user.__dict__[k], v)

                    if conf.assert_in_html_kwargs_list:
                        kwargs_list = conf.assert_in_html_kwargs_list
                        for kwargs in kwargs_list:
                            self.assertInHTML(haystack=resp.content.decode(),
                                              **kwargs)

                    if conf.expected_msg is not None:
                        self.assertAddMessageCalledWith(conf.expected_msg)

    def test_profile_page_hide_institutional_id_or_editor_mode(self):
        """
        Test whether the response content contains <input type="hidden"
        for specific field
        """
        field_div_with_id_pattern = (
            r".*(<div\s+[^\>]*id\s*=\s*['\"]div_id_%s['\"][^>]*\/?>).*")

        def assertFieldDiv(field_name, exist=True):  # noqa
            resp = self.get_profile_by_request_factory()
            self.assertEqual(resp.status_code, 200)
            pattern = field_div_with_id_pattern % field_name
            if exist:
                self.assertRegex(resp.content.decode(), pattern,
                                 msg=("Field Div of '%s' is expected to exist."
                                      % field_name))
            else:
                self.assertNotRegex(resp.content.decode(), pattern,
                                    msg=("Field Div of '%s' is not expected "
                                         "to exist." % field_name))

        with override_settings(
                RELATE_SHOW_INST_ID_FORM=True, RELATE_SHOW_EDITOR_FORM=True):
            assertFieldDiv("institutional_id", True)
            assertFieldDiv("editor_mode", True)

        with override_settings(
                RELATE_SHOW_INST_ID_FORM=False, RELATE_SHOW_EDITOR_FORM=True):
            assertFieldDiv("institutional_id", False)
            assertFieldDiv("editor_mode", True)

        with override_settings(
                RELATE_SHOW_INST_ID_FORM=True, RELATE_SHOW_EDITOR_FORM=False):
            assertFieldDiv("institutional_id", True)
            assertFieldDiv("editor_mode", False)

        with override_settings(
                RELATE_SHOW_INST_ID_FORM=False, RELATE_SHOW_EDITOR_FORM=False):
            assertFieldDiv("institutional_id", False)
            assertFieldDiv("editor_mode", False)

    def test_update_profile_for_first_login(self):
        data = self.generate_profile_data(first_name="foo")
        expected_msg = "Profile data updated."
        resp = self.post_profile_by_request_factory(
            data, query_string_dict={"first_login": "1"})
        self.assertRedirects(resp, reverse("relate-home"),
                             fetch_redirect_response=False)
        self.assertAddMessageCalledWith(expected_msg)

    def test_update_profile_for_referer(self):
        data = self.generate_profile_data(first_name="foo")
        expected_msg = "Profile data updated."
        resp = self.post_profile_by_request_factory(
            data, query_string_dict={"referer": "/some/where/",
                                     "set_inst_id": "1"})
        self.assertRedirects(resp, "/some/where/",
                             fetch_redirect_response=False)
        self.assertAddMessageCalledWith(expected_msg)

    def test_update_profile_for_referer_wrong_spell(self):
        data = self.generate_profile_data(first_name="foo")
        expected_msg = "Profile data updated."

        # "Wrong" spell of referer, no redirect
        resp = self.post_profile_by_request_factory(
            data, query_string_dict={"referrer": "/some/where/",
                                     "set_inst_id": "1"})
        self.assertTrue(resp.status_code, 200)
        self.assertAddMessageCalledWith(expected_msg)


class ResetPasswordStageOneTest(CoursesTestMixinBase, MockAddMessageMixing,
                                LocmemBackendTestsMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user_email = "a_very_looooooong_email@somehost.com"
        cls.user_inst_id = "1234"
        cls.user = factories.UserFactory.create(email=cls.user_email,
                                      institutional_id=cls.user_inst_id)

    def setUp(self):
        super().setUp()
        self.registration_override_setting = override_settings(
            RELATE_REGISTRATION_ENABLED=True)
        self.registration_override_setting.enable()
        self.addCleanup(self.registration_override_setting.disable)
        self.user.refresh_from_db()
        self.client.logout()

    def test_reset_get(self):
        resp = self.get_reset_password()
        self.assertEqual(resp.status_code, 200)
        resp = self.get_reset_password(use_instid=True)
        self.assertEqual(resp.status_code, 200)

    @override_settings(RELATE_REGISTRATION_ENABLED=False)
    def test_reset_with_registration_disabled(self):
        resp = self.get_reset_password()
        self.assertEqual(resp.status_code, 400)

        resp = self.get_reset_password(use_instid=True)
        self.assertEqual(resp.status_code, 400)

        resp = self.post_reset_password(data={})
        self.assertEqual(resp.status_code, 400)

        resp = self.post_reset_password(use_instid=True, data={})
        self.assertEqual(resp.status_code, 400)

    def test_reset_form_invalid(self):
        resp = self.post_reset_password(
            data={"email": "some/email"})
        self.assertTrue(resp.status_code, 200)
        self.assertFormErrorLoose(resp, "Enter a valid email address.")
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_by_email_non_exist(self):
        expected_msg = (
                "That %s doesn't have an "
                "associated user account. Are you "
                "sure you've registered?" % "email address")
        resp = self.post_reset_password(
            data={"email": "some_email@example.com"})
        self.assertTrue(resp.status_code, 200)
        self.assertAddMessageCalledWith(expected_msg)
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_by_instid_non_exist(self):
        expected_msg = (
                "That %s doesn't have an "
                "associated user account. Are you "
                "sure you've registered?" % "institutional ID")
        resp = self.post_reset_password(
            data={"instid": "2345"}, use_instid=True)
        self.assertTrue(resp.status_code, 200)
        self.assertAddMessageCalledWith(expected_msg)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(resp.status_code, 200)

    def test_reset_user_has_no_email(self):
        self.user.email = ""
        self.user.save()
        expected_msg = (
            "The account with that institution ID "
            "doesn't have an associated email.")
        resp = self.post_reset_password(data={"instid": self.user_inst_id},
                                        use_instid=True)
        self.assertTrue(resp.status_code, 200)
        self.assertAddMessageCalledWith(expected_msg)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(resp.status_code, 200)

    def test_reset_by_email_have_multiple_user_with_same_email(self):
        with mock.patch("accounts.models.User.objects.get") as mock_get_user:
            from django.core.exceptions import MultipleObjectsReturned
            mock_get_user.side_effect = MultipleObjectsReturned()
            expected_msg = (
                "Failed to send an email: multiple users were "
                "unexpectedly using that same "
                "email address. Please "
                "contact site staff.")
            resp = self.post_reset_password(
                data={"email": "some_email@example.com"})
            self.assertTrue(resp.status_code, 200)
            self.assertAddMessageCalledWith(expected_msg)
            self.assertEqual(len(mail.outbox), 0)

    def test_reset_by_email_post_success(self):
        expected_msg = (
            "Email sent. Please check your email and "
            "click the link."
        )
        resp = self.post_reset_password(data={"email": self.user_email})
        self.assertTrue(resp.status_code, 200)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(expected_msg)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTemplateUsed("course/sign-in-email.txt", count=1)

    def test_reset_by_istid_post_success(self):
        from course.auth import masked_email
        masked = masked_email(self.user_email)
        self.assertNotEqual(masked, self.user_email)

        with mock.patch("course.auth.masked_email") as mock_mask_email:
            expected_msg = (
                "Email sent. Please check your email and "
                "click the link."
            )
            resp = self.post_reset_password(data={"instid": self.user_inst_id},
                                            use_instid=True)
            self.assertTrue(resp.status_code, 200)
            self.assertAddMessageCallCount(2)
            self.assertAddMessageCalledWith(
                "'The email address associated with that account is",
                reset=False)
            self.assertAddMessageCalledWith(expected_msg)
            self.assertEqual(mock_mask_email.call_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTemplateUsed("course/sign-in-email.txt", count=1)


class ResetPasswordStageTwoTest(CoursesTestMixinBase, MockAddMessageMixing,
                                LocmemBackendTestsMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        user = factories.UserFactory()

        client = Client()
        with override_settings(RELATE_REGISTRATION_ENABLED=True):
            cls.post_reset_password(client, data={"email": user.email})

        user.refresh_from_db()
        assert user.sign_in_key is not None
        cls.user = user

    def setUp(self):
        super().setUp()
        self.registration_override_setting = override_settings(
            RELATE_REGISTRATION_ENABLED=True)
        self.registration_override_setting.enable()
        self.addCleanup(self.registration_override_setting.disable)
        self.client.logout()
        self.user.refresh_from_db()

    def assertHasUserLoggedIn(self, user):  # noqa
        self.assertEqual(self.get_logged_in_user(), user)

    def assertHasNoUserLoggedIn(self):  # noqa
        self.assertIsNone(self.get_logged_in_user())

    @override_settings(RELATE_REGISTRATION_ENABLED=False)
    def test_reset_stage2_with_registration_disabled(self):
        resp = self.get_reset_password_stage2(self.user.pk, self.user.sign_in_key)
        self.assertEqual(resp.status_code, 400)

        resp = self.post_reset_password_stage2(
            self.user.pk, self.user.sign_in_key, data={})
        self.assertEqual(resp.status_code, 400)
        self.assertHasNoUserLoggedIn()

    def test_reset_stage2_invalid_user(self):
        expected_msg = ("Account does not exist.")
        resp = self.get_reset_password_stage2(user_id=1000,  # no exist
                                              sign_in_key=self.user.sign_in_key)
        self.assertTrue(resp.status_code, 403)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(expected_msg)
        self.assertHasNoUserLoggedIn()

        resp = self.post_reset_password_stage2(
            user_id=1000,  # no exist
            sign_in_key=self.user.sign_in_key,
            data={})
        self.assertTrue(resp.status_code, 403)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(expected_msg)
        self.assertHasNoUserLoggedIn()

    def test_reset_stage2_invalid_token(self):
        expected_msg = ("Invalid sign-in token. Perhaps you've used an "
                        "old token email?")
        resp = self.get_reset_password_stage2(user_id=self.user.id,
                                              sign_in_key="some_invalid_token")
        self.assertTrue(resp.status_code, 403)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(expected_msg)
        self.assertHasNoUserLoggedIn()

        resp = self.post_reset_password_stage2(
            user_id=self.user.id,
            sign_in_key="some_invalid_token", data={})
        self.assertTrue(resp.status_code, 403)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(expected_msg)
        self.assertHasNoUserLoggedIn()

    def test_reset_stage2_get_success(self):
        resp = self.get_reset_password_stage2(self.user.id, self.user.sign_in_key)
        self.assertEqual(resp.status_code, 200)
        self.assertHasNoUserLoggedIn()

    def test_reset_stage2_post_form_not_valid(self):
        data = {"password": "my_pass", "password_repeat": ""}
        resp = self.post_reset_password_stage2(self.user.id,
                                               self.user.sign_in_key, data)
        self.assertEqual(resp.status_code, 200)
        self.assertFormErrorLoose(resp, "This field is required.")
        self.assertFormErrorLoose(resp, "The two password fields didn't match.")
        self.assertHasNoUserLoggedIn()

    def test_reset_stage2_post_success_redirect_profile_no_real_name(self):
        assert not (self.user.first_name or self.user.last_name)
        expected_msg = ("Successfully signed in. "
                        "Please complete your registration information below.")
        data = {"password": "my_pass", "password_repeat": "my_pass"}
        resp = self.post_reset_password_stage2(self.user.id,
                                               self.user.sign_in_key, data)
        self.assertRedirects(resp,
                             self.get_profile_view_url() + "?first_login=1",
                             fetch_redirect_response=False)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(expected_msg)
        self.assertHasUserLoggedIn(self.user)

    def test_reset_stage2_post_success_redirect_profile_no_full_name(self):
        self.user.first_name = "testuser"
        self.user.save()

        expected_msg = ("Successfully signed in. "
                        "Please complete your registration information below.")
        data = {"password": "my_pass", "password_repeat": "my_pass"}
        resp = self.post_reset_password_stage2(self.user.id,
                                               self.user.sign_in_key, data)
        self.assertRedirects(resp,
                             self.get_profile_view_url() + "?first_login=1",
                             fetch_redirect_response=False)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(expected_msg)
        self.assertHasUserLoggedIn(self.user)

    def test_reset_stage2_post_success_redirect_home(self):
        self.user.first_name = "test"
        self.user.last_name = "user"
        self.user.save()

        expected_msg = ("Successfully signed in.")
        data = {"password": "my_pass", "password_repeat": "my_pass"}
        resp = self.post_reset_password_stage2(self.user.id,
                                               self.user.sign_in_key, data)
        self.assertEqual(resp.status_code, 302)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(expected_msg)
        self.assertHasUserLoggedIn(self.user)

    def test_reset_stage2_post_success_redirect_profile_requesting_profile(self):
        self.user.first_name = "testuser"
        self.user.last_name = "user"
        self.user.save()
        expected_msg = ("Successfully signed in. "
                        "Please complete your registration information below.")
        data = {"password": "my_pass", "password_repeat": "my_pass"}
        resp = self.post_reset_password_stage2(self.user.id,
                                               self.user.sign_in_key, data,
                                               querystring={"to_profile": "-1"})
        self.assertRedirects(resp,
                             self.get_profile_view_url() + "?first_login=1",
                             fetch_redirect_response=False)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(expected_msg)
        self.assertHasUserLoggedIn(self.user)

    def test_reset_stage2_post_user_not_active(self):
        self.user.is_active = False
        self.user.save()
        expected_msg = ("Account disabled.")
        data = {"password": "my_pass", "password_repeat": "my_pass"}
        resp = self.post_reset_password_stage2(self.user.id,
                                               self.user.sign_in_key, data)
        self.assertEqual(resp.status_code, 403)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(expected_msg)
        self.assertHasNoUserLoggedIn()

    def test_reset_stage2_invalid_token_when_post_form(self):
        with mock.patch("django.contrib.auth.authenticate") as mock_auth:
            mock_auth.return_value = None
            data = {"password": "my_pass", "password_repeat": "my_pass"}
            expected_msg = ("Invalid sign-in token. Perhaps you've used an "
                            "old token email?")

            resp = self.post_reset_password_stage2(self.user.id,
                                                   self.user.sign_in_key, data)
            self.assertTrue(resp.status_code, 403)
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith(expected_msg)
            self.assertHasNoUserLoggedIn()


class EmailedTokenBackendTest(CoursesTestMixinBase, TestCase):
    def test_authenticate(self):
        user = factories.UserFactory()
        self.client.logout()

        with override_settings(RELATE_REGISTRATION_ENABLED=True):
            self.post_reset_password(data={"email": user.email})

        user.refresh_from_db()
        assert user.sign_in_key is not None

        backend = EmailedTokenBackend()
        self.assertEqual(
            backend.authenticate(None, user.pk, token=user.sign_in_key), user)

        self.assertIsNone(
            backend.authenticate(None, user.pk, token="non_exist_sign_in_key"))

    def test_get_user(self):
        user = factories.UserFactory()
        self.client.logout()

        backend = EmailedTokenBackend()
        self.assertEqual(backend.get_user(user.pk), user)
        self.assertIsNone(backend.get_user(10000))


@pytest.mark.django_db
class LogoutConfirmationRequiredDecoratorTest(unittest.TestCase):
    def setUp(self):
        self.user = factories.UserFactory()

    def test_logout_confirmation_required_as_callable(self):
        from course.auth import logout_confirmation_required
        self.assertTrue(callable(logout_confirmation_required()))
        self.assertTrue(logout_confirmation_required()(self.user))

        from django.contrib.auth.models import AnonymousUser
        self.assertTrue(logout_confirmation_required()(AnonymousUser))


class TestSaml2AttributeMapping(TestCase):
    def test_update_user(self):
        user = factories.UserFactory(first_name="", last_name="",
                                     institutional_id="",
                                     institutional_id_verified=False,
                                     name_verified=False,
                                     status=constants.user_status.unconfirmed)

        from course.auth import RelateSaml2Backend
        backend = RelateSaml2Backend()

        saml_attribute_mapping = {
            "PrincipalName": ("username",),
            "iTrustUIN": ("institutional_id",),
            "mail": ("email",),
            "givenName": ("first_name",),
            "sn": ("last_name",),
        }

        with override_settings(SAML_ATTRIBUTE_MAPPING=saml_attribute_mapping):
            user_attribute = {
                "PrincipalName": (user.username,),
            }

            with mock.patch("accounts.models.User.save") as mock_save:
                # no changes
                user = backend._rl_update_user(user, user_attribute,
                        saml_attribute_mapping)
                self.assertEqual(mock_save.call_count, 0)

            # not set as part of _rl_update_user
            # self.assertEqual(user.first_name, "")
            # self.assertEqual(user.last_name, "")
            self.assertFalse(user.name_verified)
            self.assertEqual(user.status, constants.user_status.unconfirmed)
            self.assertFalse(user.institutional_id_verified)

            expected_first = "my_first"
            expected_last = "my_last"
            expected_inst_id = "123321"
            expected_email = "yoink@illinois.edu"

            user_attribute = {
                "PrincipalName": (user.username,),
                "iTrustUIN": (expected_inst_id,),
                "givenName": (expected_first,),
                "sn": (expected_last,),
            }

            with mock.patch("accounts.models.User.save") as mock_save:
                user = backend._rl_update_user(user, user_attribute,
                        saml_attribute_mapping)
                self.assertEqual(mock_save.call_count, 1)

            user = backend._rl_update_user(
                    user, user_attribute, saml_attribute_mapping)
            # not set as part of _rl_update_user
            # self.assertEqual(user.first_name, expected_first)
            # self.assertEqual(user.last_name, expected_last)
            self.assertTrue(user.name_verified)
            self.assertEqual(user.status, constants.user_status.unconfirmed)
            self.assertTrue(user.institutional_id_verified)

            user_attribute = {
                "PrincipalName": (user.username,),
                "iTrustUIN": (expected_inst_id,),
                "mail": (expected_email),
                "givenName": (expected_first,),
                "sn": (expected_last,),
            }
            user = backend._rl_update_user(
                    user, user_attribute, saml_attribute_mapping)
            # not set as part of _rl_update_user
            # self.assertEqual(user.first_name, expected_first)
            # self.assertEqual(user.last_name, expected_last)
            self.assertTrue(user.name_verified)
            self.assertEqual(user.status, constants.user_status.active)
            self.assertTrue(user.institutional_id_verified)

            with mock.patch("accounts.models.User.save") as mock_save:
                # no changes
                backend._rl_update_user(user, user_attribute, saml_attribute_mapping)
                self.assertEqual(mock_save.call_count, 0)


@with_course_api_auth("Token")
def api_test_func_token(api_ctx, course_identifier):
    return JsonResponse({})


@with_course_api_auth("Token")
def api_test_func_raise_api_error(api_ctx, course_identifier):
    raise APIError()


@with_course_api_auth("Basic")
def api_test_func_basic(api_ctx, course_identifier):
    return JsonResponse({})


@with_course_api_auth("Not_allowed_method")
def api_test_func_not_allowed(api_ctx, course_identifier):
    return JsonResponse({})


urlpatterns = [
    *base_urlpatterns,
    re_path("^course" "/" + COURSE_ID_REGEX + "/api/test_token$",
            api_test_func_token, name="test_api_token_method"),
    re_path("^course" "/" + COURSE_ID_REGEX + "/api/test_basic$",
            api_test_func_basic, name="test_api_basic_method"),
    re_path("^course" "/" + COURSE_ID_REGEX + "/api/test_not_allowed$",
            api_test_func_not_allowed, name="test_api_not_allowed_method"),
    re_path("^course" "/" + COURSE_ID_REGEX + "/api/test_api_error$",
            api_test_func_raise_api_error, name="test_api_with_api_error")]


@override_settings(ROOT_URLCONF=__name__)
class AuthCourseWithTokenTest(APITestMixin, TestCase):
    # test auth_course_with_token

    def setUp(self):
        super().setUp()
        self.client.force_login(self.instructor_participation.user)

    def get_test_token_url(self, course_identifier=None):
        course_identifier = (
            course_identifier or self.get_default_course_identifier())
        kwargs = {"course_identifier": course_identifier}

        return reverse("test_api_token_method", kwargs=kwargs)

    def get_test_basic_url(self, course_identifier=None):
        course_identifier = (
            course_identifier or self.get_default_course_identifier())
        kwargs = {"course_identifier": course_identifier}

        return reverse("test_api_basic_method", kwargs=kwargs)

    def get_test_not_allowed_method_url(self, course_identifier=None):
        course_identifier = (
            course_identifier or self.get_default_course_identifier())
        kwargs = {"course_identifier": course_identifier}

        return reverse("test_api_not_allowed_method", kwargs=kwargs)

    def get_test_api_error_url(self, course_identifier=None):
        course_identifier = (
            course_identifier or self.get_default_course_identifier())
        kwargs = {"course_identifier": course_identifier}

        return reverse("test_api_with_api_error", kwargs=kwargs)

    def test_no_auth_headers(self):
        resp = self.client.get(
            self.get_test_token_url())
        self.assertEqual(resp.status_code, 403)

        resp = self.client.get(
            self.get_test_basic_url())
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp["WWW-Authenticate"],
                         'Basic realm="Relate direct git access for test-course"')

    # {{{ method = "Token"

    def test_invalid_token_case_not_matched(self):
        token = self.create_token()
        resp = self.client.get(
            self.get_test_token_url(),

            # case not matched
            HTTP_AUTHORIZATION="token %i_%s" % (
                token.id, self.default_token_hash_str))
        self.assertEqual(resp.status_code, 403)

    def test_invalid_token_no_space_in_auth_str(self):
        token = self.create_token()
        resp = self.client.get(
            self.get_test_token_url(),

            # no space between "Token" and auth_data
            HTTP_AUTHORIZATION="Token%i_%s" % (
                token.id, self.default_token_hash_str))
        self.assertEqual(resp.status_code, 403)

    def test_invalid_token_wrong_format(self):
        # underscores are not allowed
        token = self.create_token(token_hash_str="an_invalid_token")
        resp = self.client.get(
            self.get_test_token_url(),
            HTTP_AUTHORIZATION="Token %i_%s" % (
                token.id, self.default_token_hash_str))
        self.assertEqual(resp.status_code, 403)

    def test_none_exist_token(self):
        resp = self.client.get(
            self.get_test_token_url(),
            HTTP_AUTHORIZATION="Token %i_%s" % (
                1, "nonexisttokenstr"))
        self.assertEqual(resp.status_code, 403)

    def test_revoked_token(self):
        token = self.create_token(
            revocation_time=now() - timedelta(minutes=1))
        resp = self.client.get(
            self.get_test_token_url(),
            HTTP_AUTHORIZATION="Token %i_%s" % (
                token.id, self.default_token_hash_str))
        self.assertEqual(resp.status_code, 403)

    def test_expired_token(self):
        token = self.create_token(
            valid_until=now() - timedelta(minutes=1))
        resp = self.client.get(
            self.get_test_token_url(),
            HTTP_AUTHORIZATION="Token %i_%s" % (
                token.id, self.default_token_hash_str))
        self.assertEqual(resp.status_code, 403)

    def test_token_auth_success(self):
        token = self.create_token()
        resp = self.client.get(
            self.get_test_token_url(),
            HTTP_AUTHORIZATION="Token %i_%s" % (
                token.id, self.default_token_hash_str))
        self.assertEqual(resp.status_code, 200)

    # }}}

    # {{{ method = "Basic"

    def test_basic_auth_success(self):
        resp = self.client.get(
            self.get_test_basic_url(),
            HTTP_AUTHORIZATION="Basic %s" % self.create_basic_auth())
        self.assertEqual(resp.status_code, 200)

    def test_basic_auth_ill_formed(self):
        resp = self.client.get(
            self.get_test_basic_url(),
            HTTP_AUTHORIZATION="Basic %s" % "foo:barbar")
        self.assertEqual(resp.status_code, 401)

    def test_basic_auth_no_match(self):
        from base64 import b64encode
        bad_auth_data = b64encode(b"foobar").decode()

        resp = self.client.get(
            self.get_test_basic_url(),
            HTTP_AUTHORIZATION="Basic %s" % bad_auth_data)
        self.assertEqual(resp.status_code, 401)

    def test_basic_auth_user_not_matched(self):
        basic_auth_user_not_matched = self.create_basic_auth(
            participation=self.instructor_participation,
            user=self.ta_participation.user
        )

        resp = self.client.get(
            self.get_test_basic_url(),
            HTTP_AUTHORIZATION="Basic %s" % basic_auth_user_not_matched)
        self.assertEqual(resp.status_code, 401)

    # }}}

    # {{{ method not allowed

    def test_auth_method_not_allowed(self):
        with self.assertRaises(AssertionError):
            self.client.get(
                self.get_test_not_allowed_method_url(),
                HTTP_AUTHORIZATION="Not_allowed_method blabla")

    def test_auth_method_not_allowed_method_not_matched(self):
        token = self.create_token()
        with self.assertRaises(AssertionError):
            self.client.get(
                self.get_test_not_allowed_method_url(),
                HTTP_AUTHORIZATION="Token %i_%s" % (
                    token.id, self.default_token_hash_str))

    # }}}

    def test_raise_api_error(self):
        token = self.create_token()
        resp = self.client.get(
            self.get_test_api_error_url(),
            HTTP_AUTHORIZATION="Token %i_%s" % (
                token.id, self.default_token_hash_str))
        self.assertEqual(resp.status_code, 400)


class ManageAuthenticationTokensTest(
        SingleCoursePageTestMixin, MockAddMessageMixing, TestCase):
    # test manage_authentication_tokens

    def setUp(self):
        super().setUp()
        self.client.force_login(self.instructor_participation.user)

    def test_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.client.get(self.get_manage_authentication_token_url())
        self.assertEqual(resp.status_code, 403)

    def test_no_permission_authenticated(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.client.get(self.get_manage_authentication_token_url())
        self.assertEqual(resp.status_code, 403)

    def test_get_success(self):
        resp = self.client.get(self.get_manage_authentication_token_url())
        self.assertEqual(resp.status_code, 200)

        tokens = self.get_response_context_value_by_name(resp, "tokens")
        self.assertEqual(tokens.count(), 0)

    def get_manage_authentication_tokens_post_data(
            self, restrict_to_participation_role=None,
            description="test", valid_until=None,
            create=True, revoke_id=None, **kwargs):

        data = {}
        if create:
            assert revoke_id is None
            if restrict_to_participation_role is None:
                prole_kwargs = {
                    "identifier": "instructor",
                    "course": self.course
                }
                role = factories.ParticipationRoleFactory(**prole_kwargs)
                restrict_to_participation_role = role.pk

            if not valid_until:
                valid_until = (now() + timedelta(weeks=2)
                               ).replace(tzinfo=None).strftime("%Y-%m-%d")

            data.update({
                "restrict_to_participation_role": restrict_to_participation_role,
                "valid_until": valid_until,
                "description": description,
                "create": ""
            })

        if revoke_id:
            assert isinstance(revoke_id, int)
            data["revoke_%i" % revoke_id] = ""

        data.update(kwargs)
        return data

    def test_get_tokens_with_revocation_time_within_a_week(self):
        factories.AuthenticationTokenFactory.create_batch(
            size=1,
            user=self.ta_participation.user,
            participation=self.ta_participation,
        )

        factories.AuthenticationTokenFactory.create_batch(
            size=5,
            user=self.instructor_participation.user,
            participation=self.instructor_participation,
        )

        factories.AuthenticationTokenFactory.create_batch(
            size=3, revocation_time=now() - timedelta(weeks=2),
            user=self.instructor_participation.user,
            participation=self.instructor_participation,
        )
        factories.AuthenticationTokenFactory.create_batch(
            size=2, revocation_time=now() - timedelta(days=2),
            user=self.instructor_participation.user,
            participation=self.instructor_participation,
        )

        resp = self.client.get(self.get_manage_authentication_token_url())
        self.assertEqual(resp.status_code, 200)

        tokens = self.get_response_context_value_by_name(resp, "tokens")
        self.assertEqual(tokens.count(), 7)

    def test_post_create_success(self):
        n_exist_tokens = 3

        factories.AuthenticationTokenFactory.create_batch(
            size=n_exist_tokens,
            user=self.instructor_participation.user,
            participation=self.instructor_participation,
        )

        resp = self.client.post(
            self.get_manage_authentication_token_url(),
            data=self.get_manage_authentication_tokens_post_data()
        )
        self.assertEqual(resp.status_code, 200)

        tokens = self.get_response_context_value_by_name(resp, "tokens")
        self.assertEqual(tokens.count(), n_exist_tokens + 1)

        added_token = AuthenticationToken.objects.last()
        added_message = self._get_added_messages()

        match = _TOKEN_AUTH_DATA_RE.match(added_message)
        self.assertIsNotNone(match)

        token_id = int(match.group("token_id"))
        self.assertEqual(added_token.id, token_id)

        token_hash_str = match.group("token_hash")
        self.assertTrue(check_password(token_hash_str, added_token.token_hash))

    def test_post_create_form_invalid(self):
        resp = self.client.post(
            self.get_manage_authentication_token_url(),
            data=self.get_manage_authentication_tokens_post_data(
                description=""
            )
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(AuthenticationToken.objects.count(), 0)

        self.assertFormError(
                resp.context["form"], "description", "This field is required.")

    def test_post_revoke(self):
        n_exist_tokens = 3

        tokens = factories.AuthenticationTokenFactory.create_batch(
            size=n_exist_tokens,
            user=self.instructor_participation.user,
            participation=self.instructor_participation,
        )

        resp = self.client.post(
            self.get_manage_authentication_token_url(),
            data=self.get_manage_authentication_tokens_post_data(
                create=False,
                revoke_id=tokens[0].id)
        )
        self.assertEqual(resp.status_code, 200)

        active_tokens = AuthenticationToken.objects.filter(
            revocation_time__isnull=True)
        self.assertEqual(active_tokens.count(), n_exist_tokens - 1)

    def test_post_create_unknown_button_pressed(self):
        resp = self.client.post(
            self.get_manage_authentication_token_url(),
            data=self.get_manage_authentication_tokens_post_data(
                create=False
            )
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(AuthenticationToken.objects.count(), 0)
        self.assertAddMessageCallCount(1)


class APIBearerTokenBackendTest(APITestMixin, TestCase):
    # test APIBearerTokenBackend

    def test_authenticate_success(self):
        token = self.create_token()
        self.client.logout()

        backend = APIBearerTokenBackend()
        self.assertEqual(
            backend.authenticate(
                None, self.course.identifier, token.id, self.default_token_hash_str),
            self.instructor_participation.user
        )

    def test_authenticate_fail_no_matching_token(self):
        self.client.logout()

        backend = APIBearerTokenBackend()
        self.assertIsNone(
            backend.authenticate(
                None, self.course.identifier, 1, "foobar"))

    def test_get_user(self):
        self.client.logout()

        backend = APIBearerTokenBackend()
        self.assertEqual(
            backend.get_user(
                self.instructor_participation.user.id),
            self.instructor_participation.user)
        self.assertIsNone(
            backend.get_user(10000))


class APIContextTest(APITestMixin, TestCase):
    # test APIContext

    def test_restrict_to_role_is_not_none(self):
        token = self.create_token()
        api_context = APIContext(None, token)
        self.assertIsNotNone(api_context.restrict_to_role)

    def test_restrict_to_role_is_none(self):
        token = self.create_token()
        token.restrict_to_participation_role = None
        token.save()

        api_context = APIContext(None, token)
        self.assertIsNone(api_context.restrict_to_role)

    def test_restrict_to_role_not_in_participation_roles(self):
        token = self.create_token(participation=self.student_participation)

        prole_kwargs = {
            "course": self.course, "identifier": "ta"}
        role = factories.ParticipationRoleFactory(**prole_kwargs)
        token.restrict_to_participation_role = role
        token.save()

        with self.assertRaises(PermissionDenied):
            APIContext(None, token)

    def test_restrict_to_role_not_in_participation_roles_but_may_impersonate(self):
        token = self.create_token(participation=self.ta_participation)

        prole_kwargs = {
            "course": self.course, "identifier": "student"}
        role = factories.ParticipationRoleFactory(**prole_kwargs)
        token.restrict_to_participation_role = role
        token.save()

        api_context = APIContext(None, token)
        self.assertIsNotNone(api_context.restrict_to_role)

    def test_api_context_has_permission_true(self):
        token = self.create_token()
        api_context = APIContext(None, token)

        from course.constants import participation_permission as pperm
        self.assertTrue(api_context.has_permission(
            pperm.access_files_for, "instructor"))

    def test_api_context_has_permission_restrict_to_role_is_none_true(self):
        token = self.create_token()
        token.restrict_to_participation_role = None
        token.save()

        api_context = APIContext(None, token)

        from course.constants import participation_permission as pperm
        self.assertTrue(api_context.has_permission(
            pperm.access_files_for, "instructor"))

    def test_api_context_has_permission_false(self):
        token = self.create_token(participation=self.ta_participation)
        api_context = APIContext(None, token)

        from course.constants import participation_permission as pperm
        self.assertFalse(api_context.has_permission(
            pperm.access_files_for, "instructor"))

    def test_api_context_has_permission_restrict_to_role_is_none_false(self):
        token = self.create_token(participation=self.ta_participation)
        token.restrict_to_participation_role = None
        token.save()

        api_context = APIContext(None, token)

        from course.constants import participation_permission as pperm
        self.assertFalse(api_context.has_permission(
            pperm.access_files_for, "instructor"))


# vim: foldmethod=marker
