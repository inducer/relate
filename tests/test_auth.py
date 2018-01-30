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

import six
from six.moves.urllib.parse import ParseResult, quote, urlparse
from djangosaml2.urls import urlpatterns as djsaml2_urlpatterns
from django.test import TestCase, override_settings, RequestFactory
from django.contrib import messages
from django.conf import settings
from django.core import mail
from django.contrib.auth import (
    REDIRECT_FIELD_NAME, SESSION_KEY,
)
from django.http import QueryDict, HttpResponse
from django.urls import NoReverseMatch, reverse
from unittest import skipIf
from course.auth import get_impersonable_user_qset, get_user_model
from course.models import FlowPageVisit, ParticipationPermission

from tests.base_test_mixins import (
    CoursesTestMixinBase, SingleCoursePageTestMixin, TwoCourseTestMixin,
    FallBackStorageMessageTestMixin, TWO_COURSE_SETUP_LIST,
    NONE_PARTICIPATION_USER_CREATE_KWARG_LIST)

from tests.utils import (
    LocmemBackendTestsMixin, load_url_pattern_names, reload_urlconf, mock)
from tests.factories import UserFactory

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


class AuthTestMixin(object):
    _user_create_kwargs = {
        "username": "test_user", "password": "mypassword",
        "email": "my_email@example.com"
    }

    @classmethod
    def setUpTestData(cls):  # noqa
        super(AuthTestMixin, cls).setUpTestData()
        cls.test_user = (
            get_user_model().objects.create_user(**cls._user_create_kwargs))
        cls.existing_user_count = get_user_model().objects.count()

    def setUp(self):
        super(AuthTestMixin, self).setUp()
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
            if parse_qs and attr == 'query':
                x, y = QueryDict(x), QueryDict(y)
            if x and y and x != y:
                self.fail("%r != %r (%s doesn't match)" % (url, expected, attr))

    def do_test_security_check(self, url_name):
        url = reverse(url_name)

        with override_settings(ALLOWED_HOSTS=["testserver"]):
            # These URLs should not pass the security check.
            bad_urls = (
                'http://example.com',
                'http:///example.com',
                'https://example.com',
                'ftp://example.com',
                '///example.com',
                '//example.com',
                'javascript:alert("XSS")',
            )
            for bad_url in bad_urls:
                with self.temporarily_switch_to_user(None):
                    with self.subTest(bad_url=bad_url):
                        nasty_url = self.concatenate_redirect_url(url, bad_url)
                        response = self.c.post(nasty_url, self.get_sign_in_data())
                        self.assertEqual(response.status_code, 302)
                        self.assertNotIn(bad_url, response.url,
                                         '%s should be blocked' % bad_url)

            # These URLs should pass the security check.
            good_urls = (
                '/view/?param=http://example.com',
                '/view/?param=https://example.com',
                '/view?param=ftp://example.com',
                'view/?param=//example.com',
                'https://testserver/',
                'HTTPS://testserver/',
                '//testserver/',
                '/url%20with%20spaces/',
            )
            for good_url in good_urls:
                with self.temporarily_switch_to_user(None):
                    with self.subTest(good_url=good_url):
                        safe_url = self.concatenate_redirect_url(url, good_url)
                        response = self.c.post(safe_url, self.get_sign_in_data())
                        self.assertEqual(response.status_code, 302)
                        self.assertIn(good_url, response.url,
                                      '%s should be allowed' % good_url)

    def assertSessionHasUserLoggedIn(self):  # noqa
        self.assertIn(SESSION_KEY, self.c.session)

    def assertSessionHasNoUserLoggedIn(self):  # noqa
        self.assertNotIn(SESSION_KEY, self.c.session)

    def concatenate_redirect_url(self, url, redirect_to=None):
        if not redirect_to:
            return url
        return ('%(url)s?%(next)s=%(bad_url)s' % {
                    'url': url,
                    'next': REDIRECT_FIELD_NAME,
                    'bad_url': quote(redirect_to),
                })

    def get_sign_up_view_url(self, redirect_to=None):
        return self.concatenate_redirect_url(
            reverse("relate-sign_up"), redirect_to
        )

    def get_sign_up(self, redirect_to=None, follow=False):
        return self.c.get(self.get_sign_up_view_url(redirect_to),
                          follow=follow)

    def post_sign_up(self, data, redirect_to=None, follow=False):
        return self.c.post(self.get_sign_up_view_url(redirect_to), data,
                           follow=follow)

    def get_sign_in_choice_url(self, redirect_to=None):
        return self.concatenate_redirect_url(
            reverse("relate-sign_in_choice"), redirect_to)

    def get_sign_in_by_user_pw_url(self, redirect_to=None):
        return self.concatenate_redirect_url(
            reverse("relate-sign_in_by_user_pw"), redirect_to)

    def get_sign_in_by_user_pw(self, redirect_to=None, follow=False):
        return self.c.get(self.get_sign_in_by_user_pw_url(redirect_to),
                          follow=follow)

    def post_sign_in_by_user_pw(self, data, redirect_to=None, follow=False):
        return self.c.post(self.get_sign_in_by_user_pw_url(redirect_to), data,
                           follow=follow)

    def get_sign_in_by_email_url(self, redirect_to=None):
        return self.concatenate_redirect_url(
            reverse("relate-sign_in_by_email"), redirect_to)

    def get_sign_in_by_email(self, redirect_to=None, follow=False):
        return self.c.get(self.get_sign_in_by_email_url(redirect_to),
                          follow=follow)

    def post_sign_in_by_email(self, data, redirect_to=None, follow=False):
        return self.c.post(self.get_sign_in_by_email_url(redirect_to), data,
                           follow=follow)

    def get_sign_out_view_url(self, redirect_to=None):
        return self.concatenate_redirect_url(
            reverse("relate-logout"), redirect_to)

    def get_sign_out(self, redirect_to=None, follow=False):
        return self.c.get(self.get_sign_out_view_url(redirect_to),
                          follow=follow)

    def post_sign_out(self, data, redirect_to=None, follow=False):
        # Though RELATE and django are using GET to sign out
        return self.c.post(self.get_sign_out_view_url(redirect_to), data,
                           follow=follow)

    def get_sign_out_confirmation_view_url(self, redirect_to=None):
        return self.concatenate_redirect_url(
            reverse("relate-logout-confirmation"), redirect_to
        )

    def get_sign_out_confirmation(self, redirect_to=None, follow=False):
        return self.c.get(self.get_sign_out_confirmation_view_url(redirect_to),
                          follow=follow)

    def post_sign_out_confirmation(self, data, redirect_to=None, follow=False):
        return self.c.post(self.get_sign_out_confirmation_view_url(redirect_to),
                           data,
                           follow=follow)

    def get_user_profile_url(self, redirect_to=None):
        return self.concatenate_redirect_url(
            reverse("relate-user_profile"), redirect_to)

    def get_user_profile(self, redirect_to=None, follow=False):
        return self.c.get(self.get_user_profile_url(redirect_to),
                          follow=follow)

    def post_user_profile(self, data, redirect_to=None, follow=False):
        return self.c.post(self.get_user_profile_url(redirect_to),
                           data=data, follow=follow)


@skipIf(six.PY2, "PY2 doesn't support subTest")
class AuthViewNamedURLTests(AuthTestMixin, TestCase):
    need_logout_confirmation_named_urls = [
        ('relate-sign_in_choice', [], {}),
        ('relate-sign_in_by_user_pw', [], {}),
        ('relate-sign_in_by_email', [], {}),
        ('relate-sign_up', [], {}),
        ('relate-reset_password', [], {}),
        ('relate-reset_password', [], {"field": "instid"}),
        ('relate-reset_password_stage2',
         [], {"user_id": 0, "sign_in_key": "abcd"}),
        ('relate-sign_in_stage2_with_token',
         [], {"user_id": 0, "sign_in_key": "abcd"})]

    djsaml2_urls = [
        (name, [], {})
        for name in load_url_pattern_names(djsaml2_urlpatterns)
    ]

    need_login_named_urls = [
        ('relate-logout', [], {}),
        ('relate-logout-confirmation', [], {}),
        ('relate-user_profile', [], {}),
        ('relate-manage_authentication_tokens', [],
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


class SignInByPasswordTest(CoursesTestMixinBase, FallBackStorageMessageTestMixin,
                           AuthTestMixin, TestCase):
    courses_setup_list = []

    @override_settings(RELATE_SIGN_IN_BY_USERNAME_ENABLED=True)
    def test_user_pw_enabled_sign_in_view_anonymous(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_sign_in_by_user_pw()
            self.assertEqual(resp.status_code, 200)
            self.assertSessionHasNoUserLoggedIn()

            resp = self.post_sign_in_by_user_pw(data=self.get_sign_in_data())
            self.assertSessionHasUserLoggedIn()
            self.assertEqual(resp.status_code, 302)
            self.assertRedirects(resp, settings.LOGIN_REDIRECT_URL,
                                 fetch_redirect_response=False)

    @override_settings(RELATE_SIGN_IN_BY_USERNAME_ENABLED=False)
    @mock.patch("course.auth.messages.add_message")
    def test_username_pw_not_enabled_sign_in_view_anonymous(self, mock_add_msg):
        expected_msg = "Username-based sign-in is not being used"
        with self.temporarily_switch_to_user(None):
            resp = self.get_sign_in_by_user_pw(follow=True)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionHasNoUserLoggedIn()
            self.assertEqual(mock_add_msg.call_count, 1)
            self.assertIn(expected_msg, mock_add_msg.call_args[0])

            mock_add_msg.reset_mock()
            resp = self.post_sign_in_by_user_pw(data=self.get_sign_in_data(),
                                                follow=False)
            self.assertEqual(resp.status_code, 302)
            self.assertRedirects(resp, self.get_sign_in_choice_url(),
                                 fetch_redirect_response=False)
            self.assertSessionHasNoUserLoggedIn()
            self.assertEqual(mock_add_msg.call_count, 1)
            self.assertIn(expected_msg, mock_add_msg.call_args[0])

    @skipIf(six.PY2, "PY2 doesn't support subTest")
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
class SignInByEmailTest(CoursesTestMixinBase, FallBackStorageMessageTestMixin,
                        AuthTestMixin, LocmemBackendTestsMixin, TestCase):
    courses_setup_list = []

    @classmethod
    def setUpTestData(cls):  # noqa
        super(SignInByEmailTest, cls).setUpTestData()

        new_email = "somebody@example.com"
        data = {"email": new_email}

        # first login attempt
        resp = cls.c.post(reverse("relate-sign_in_by_email"), data=data)

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
        resp = cls.c.post(reverse("relate-sign_in_by_email"), data=data)

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
        super(SignInByEmailTest, self).setUp()
        self.user.refresh_from_db()
        self.flush_mailbox()

    @mock.patch("course.auth.messages.add_message")
    def test_email_login_enabled_sign_in_view_anonymous(self, mock_add_msg):
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
            self.assertEqual(mock_add_msg.call_count, 1)
            self.assertIn(expected_msg, mock_add_msg.call_args[0])
            self.assertEqual(len(mail.outbox), 1)

    @override_settings()
    @mock.patch("course.auth.messages.add_message")
    def test_email_login_not_enabled_sign_in_view_anonymous(self, mock_add_msg):
        expected_msg = "Email-based sign-in is not being used"
        settings.RELATE_SIGN_IN_BY_EMAIL_ENABLED = False
        with self.temporarily_switch_to_user(None):
            resp = self.get_sign_in_by_email(follow=True)
            self.assertEqual(resp.status_code, 200)
            self.assertSessionHasNoUserLoggedIn()
            self.assertEqual(mock_add_msg.call_count, 1)
            self.assertIn(expected_msg, mock_add_msg.call_args[0])
            self.assertEqual(len(mail.outbox), 0)

            mock_add_msg.reset_mock()
            resp = self.post_sign_in_by_email(data=self.get_sign_in_data(),
                                              follow=False)
            self.assertEqual(resp.status_code, 302)
            self.assertRedirects(resp, self.get_sign_in_choice_url(),
                                 fetch_redirect_response=False)
            self.assertSessionHasNoUserLoggedIn()
            self.assertEqual(mock_add_msg.call_count, 1)
            self.assertIn(expected_msg, mock_add_msg.call_args[0])
            self.assertEqual(len(mail.outbox), 0)

    def test_email_login_form_invalid(self):
        with self.temporarily_switch_to_user(None):
            data = {"email": "not a email"}
            resp = self.post_sign_in_by_email(data=data,
                                              follow=False)
            self.assertEqual(resp.status_code, 200)
            self.assertFormErrorLoose(resp, 'Enter a valid email address.')
            self.assertSessionHasNoUserLoggedIn()
            self.assertEqual(len(mail.outbox), 0)

    @override_settings()
    @mock.patch("course.auth.messages.add_message")
    def test_stage2_login_email_login_not_enabled(self, mock_add_msg):
        settings.RELATE_SIGN_IN_BY_EMAIL_ENABLED = False
        expected_msg = "Email-based sign-in is not being used"
        with self.temporarily_switch_to_user(None):
            resp = self.c.get(self.second_sign_in_url)
            self.assertIn(expected_msg, mock_add_msg.call_args[0])
            self.assertEqual(resp.status_code, 302)
            self.assertRedirects(resp, self.get_sign_in_choice_url(),
                                 fetch_redirect_response=False)
            self.assertSessionHasNoUserLoggedIn()

    @mock.patch("course.auth.messages.add_message")
    def test_stage2_login_with_staled_signing_key(self, mock_add_msg):
        with self.temporarily_switch_to_user(None):
            expected_msg = ("Invalid sign-in token. Perhaps you've used "
                            "an old token email?")
            resp = self.c.get(self.first_sign_in_url)
            self.assertIn(expected_msg, mock_add_msg.call_args[0])
            self.assertEqual(resp.status_code, 403)
            self.assertSessionHasNoUserLoggedIn()

    @mock.patch("course.auth.messages.add_message")
    def test_stage2_login_user_inactive(self, mock_add_msg):
        self.user.is_active = False
        self.user.save()
        self.user.refresh_from_db()

        with self.temporarily_switch_to_user(None):
            expected_msg = ("Account disabled.")
            resp = self.c.get(self.second_sign_in_url)
            self.assertIn(expected_msg, mock_add_msg.call_args[0])
            self.assertEqual(resp.status_code, 403)
            self.assertSessionHasNoUserLoggedIn()

    @mock.patch("course.auth.messages.add_message")
    def login_stage2_without_profile(self, user, mock_add_msg):
        with self.temporarily_switch_to_user(None):
            expected_msg = (
                "Successfully signed in. "
                "Please complete your registration information below.")
            resp = self.c.get(self.second_sign_in_url)
            self.assertIn(expected_msg, mock_add_msg.call_args[0])
            self.assertEqual(resp.status_code, 302)

            self.assertRedirects(resp, self.get_user_profile_url()+"?first_login=1",
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

    @mock.patch("course.auth.messages.add_message")
    def test_stage2_login_with_first_name_and_last_name(self, mock_add_msg):
        self.user.first_name = "foo"
        self.user.last_name = "bar"
        self.user.save()
        with self.temporarily_switch_to_user(None):
            expected_msg = (
                "Successfully signed in.")
            resp = self.c.get(self.second_sign_in_url)
            self.assertIn(expected_msg, mock_add_msg.call_args[0])
            self.assertEqual(resp.status_code, 302)

            self.assertRedirects(resp, reverse("relate-home"),
                                 fetch_redirect_response=False)
            self.assertSessionHasUserLoggedIn()

    @mock.patch("course.auth.messages.add_message")
    def test_stage2_login_non_existing_user(self, mock_add_msg):
        user = get_user_model().objects.get(pk=self.user.pk)
        user.delete()
        expected_msg = (
            "Account does not exist.")
        with self.temporarily_switch_to_user(None):
            resp = self.c.get(self.second_sign_in_url)
            self.assertIn(expected_msg, mock_add_msg.call_args[0])
            self.assertEqual(resp.status_code, 403)


@override_settings(RELATE_REGISTRATION_ENABLED=True)
class SignUpTest(CoursesTestMixinBase, AuthTestMixin, LocmemBackendTestsMixin,
                 FallBackStorageMessageTestMixin, TestCase):

    sign_up_user_dict = {
        "username": "test_sign_up_user", "password": "mypassword",
        "email": "test_sign_up@example.com"
    }

    def setUp(self):
        super(SignUpTest, self).setUp()
        self.c.logout()

    @override_settings()
    def test_signup_registeration_not_enabled(self):
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
            self.assertFormErrorLoose(resp, 'Enter a valid email address.')
            self.assertNoNewUserCreated()
            self.assertEqual(len(mail.outbox), 0)

    @mock.patch("course.auth.messages.add_message")
    def test_signup_existing_user_name(self, mock_add_msg):
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
        self.assertIn(expected_msg, mock_add_msg.call_args[0])

    @mock.patch("course.auth.messages.add_message")
    def test_signup_existing_email(self, mock_add_msg):
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
        self.assertIn(expected_msg, mock_add_msg.call_args[0])

    @mock.patch("course.auth.messages.add_message")
    def test_signup_success(self, mock_add_msg):
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
        self.assertIn(expected_msg, mock_add_msg.call_args[0])


class SignOutTest(CoursesTestMixinBase,
                  AuthTestMixin, FallBackStorageMessageTestMixin, TestCase):

    @mock.patch("course.auth.messages.add_message")
    def test_sign_out_anonymous(self, mock_add_msg):
        with self.temporarily_switch_to_user(None):
            expected_msg = "You've already signed out."
            resp = self.get_sign_out(follow=False)
            self.assertEqual(resp.status_code, 302)
            self.assertRedirects(resp, reverse("relate-home"),
                                 fetch_redirect_response=False)
            self.assertSessionHasNoUserLoggedIn()
            self.assertIn(expected_msg, mock_add_msg.call_args[0])

    @override_settings(RELATE_SIGN_IN_BY_SAML2_ENABLED=False)
    def test_sign_out_by_get(self):
        with mock.patch("djangosaml2.views._get_subject_id")\
                as mock_get_subject_id,\
                mock.patch("djangosaml2.views.logout") as mock_saml2_logout:
            mock_get_subject_id.return_value = "some_id"
            with self.temporarily_switch_to_user(self.test_user):
                resp = self.get_sign_out()
                self.assertRedirects(resp, reverse("relate-home"),
                                     target_status_code=200,
                                     fetch_redirect_response=False)
                self.assertSessionHasNoUserLoggedIn()
            self.assertEqual(mock_saml2_logout.call_count, 0)

    @override_settings(RELATE_SIGN_IN_BY_SAML2_ENABLED=False)
    def test_sign_out_by_post(self):
        with mock.patch("djangosaml2.views._get_subject_id")\
                as mock_get_subject_id,\
                mock.patch("djangosaml2.views.logout") as mock_saml2_logout:
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
        with mock.patch("djangosaml2.views._get_subject_id")\
                as mock_get_subject_id,\
                mock.patch("djangosaml2.views.logout") as mock_saml2_logout:
            mock_get_subject_id.return_value = None
            with self.temporarily_switch_to_user(self.test_user):
                resp = self.get_sign_out()
                self.assertEqual(resp.status_code, 302)
                self.assertSessionHasNoUserLoggedIn()
            self.assertEqual(mock_saml2_logout.call_count, 0)

    @override_settings(RELATE_SIGN_IN_BY_SAML2_ENABLED=True)
    def test_sign_out_with_saml2_enabled_with_subject_id(self):
        self.c.force_login(self.test_user)
        with mock.patch("djangosaml2.views._get_subject_id")\
                as mock_get_subject_id,\
                mock.patch("djangosaml2.views.logout") as mock_saml2_logout:
            mock_get_subject_id.return_value = "some_id"
            mock_saml2_logout.return_value = HttpResponse()
            resp = self.get_sign_out()
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(mock_saml2_logout.call_count, 1)

    @mock.patch("course.auth.messages.add_message")
    def test_sign_out_confirmation_anonymous(self, mock_add_msg):
        with self.temporarily_switch_to_user(None):
            expected_msg = "You've already signed out."
            resp = self.get_sign_out_confirmation(follow=False)
            self.assertEqual(resp.status_code, 302)
            self.assertRedirects(resp, reverse("relate-home"),
                                 fetch_redirect_response=False)
            self.assertSessionHasNoUserLoggedIn()
            self.assertIn(expected_msg, mock_add_msg.call_args[0])

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
                      FallBackStorageMessageTestMixin, TestCase):

    def setUp(self):
        super(UserProfileTest, self).setUp()
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
                "%s?%s" % (
                    url,
                    "&".join(["%s=%s" % (k, v)
                              for k, v in six.iteritems(query_string_dict)])))
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
        # Only POST with 'submit_user' works
        with self.temporarily_switch_to_user(self.test_user):
            resp = self.get_profile()
            self.assertTrue(resp.status_code, 200)
            data = self.generate_profile_form_data(first_name="foo")

            # No 'submit_user' in POST
            resp = self.c.post(self.get_profile_view_url(), data)
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

    @skipIf(six.PY2, "Python2 doesn't support subTest")
    def test_update_profile_with_different_settings(self):
        disabled_inst_id_html_pattern = (
            '<input type="text" name="institutional_id" value="%s" '
            'class="textinput textInput form-control" id="id_institutional_id" '
            'maxlength="100" disabled />')

        enabled_inst_id_html_pattern = (
            '<input type="text" name="institutional_id" value="%s" '
            'class="textinput textInput form-control" id="id_institutional_id" '
            'maxlength="100" />')

        expected_success_msg = "Profile data updated."
        expected_unchanged_msg = "No change was made on your profile."
        from collections import namedtuple
        Conf = namedtuple(
            'Conf', [
                'id',
                'override_settings_dict',
                'user_profile_dict',
                'update_profile_dict',
                'expected_result_dict',
                'assert_in_html_kwargs_list',
                'expected_msg',
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

        with mock.patch("course.auth.messages.add_message") as mock_add_msg:
            for conf in test_confs:
                with self.subTest(conf.id):
                    with override_settings(**conf.override_settings_dict):
                        resp = self.update_profile_by_post_form(
                            conf.user_profile_dict,
                            conf.update_profile_dict)

                        self.assertTrue(resp.status_code, 200)
                        self.test_user.refresh_from_db()
                        for k, v in six.iteritems(conf.expected_result_dict):
                            self.assertEqual(self.test_user.__dict__[k], v)

                        if conf.assert_in_html_kwargs_list:
                            kwargs_list = conf.assert_in_html_kwargs_list
                            for kwargs in kwargs_list:
                                self.assertInHTML(haystack=resp.content.decode(),
                                                  **kwargs)

                        if conf.expected_msg is not None:
                            self.assertIn(conf.expected_msg,
                                          mock_add_msg.call_args[0])
                        else:
                            if mock_add_msg.call_count > 0:
                                self.fail("Message was actually called with %s."
                                          % repr(mock_add_msg.call_args[0][2]))

                        mock_add_msg.reset_mock()

    def test_profile_page_hide_institutional_id_or_editor_mode(self):
        """
        Test whether the response content contains <input type="hidden"
        for specific field
        """
        field_div_with_id_pattern = (
            ".*(<div\s+[^\>]*id\s*=\s*['\"]div_id_%s['\"][^>]*\/?>).*")

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
        with mock.patch("course.auth.messages.add_message") as mock_add_msg:
            resp = self.post_profile_by_request_factory(
                data, query_string_dict={"first_login": "1"})
            self.assertRedirects(resp, reverse("relate-home"),
                                 fetch_redirect_response=False)
            self.assertIn(expected_msg,
                          mock_add_msg.call_args[0])

    def test_update_profile_for_referer(self):
        data = self.generate_profile_data(first_name="foo")
        with mock.patch("course.auth.messages.add_message") as mock_add_msg:
            expected_msg = "Profile data updated."
            resp = self.post_profile_by_request_factory(
                data, query_string_dict={"referer": "/some/where/",
                                         "set_inst_id": "1"})
            self.assertRedirects(resp, "/some/where/",
                                 fetch_redirect_response=False)
            self.assertIn(expected_msg,
                          mock_add_msg.call_args[0])

    def test_update_profile_for_referer_wrong_spell(self):
        data = self.generate_profile_data(first_name="foo")
        with mock.patch("course.auth.messages.add_message") as mock_add_msg:
            expected_msg = "Profile data updated."

            # "Wrong" spell of referer, no redirect
            resp = self.post_profile_by_request_factory(
                data, query_string_dict={"referrer": "/some/where/",
                                         "set_inst_id": "1"})
            self.assertTrue(resp.status_code, 200)
            self.assertIn(expected_msg,
                          mock_add_msg.call_args[0])


class ResetPasswordStageOneTest(CoursesTestMixinBase, LocmemBackendTestsMixin,
                                TestCase):
    @classmethod
    def setUpTestData(cls):  # noqa
        super(ResetPasswordStageOneTest, cls).setUpTestData()
        cls.user_email = "a_very_looooooong_email@somehost.com"
        cls.user_inst_id = "1234"
        cls.user = UserFactory.create(email=cls.user_email,
                                      institutional_id=cls.user_inst_id)

    def setUp(self):
        super(ResetPasswordStageOneTest, self).setUp()
        self.registration_override_setting = override_settings(
            RELATE_REGISTRATION_ENABLED=True)
        self.registration_override_setting.enable()
        self.addCleanup(self.registration_override_setting.disable)
        self.user.refresh_from_db()
        self.c.logout()

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
        with mock.patch("course.auth.messages.add_message") as mock_add_msg:
            expected_msg = (
                "That %s doesn't have an "
                "associated user account. Are you "
                "sure you've registered?" % "email address")
            resp = self.post_reset_password(
                data={"email": "some_email@example.com"})
            self.assertTrue(resp.status_code, 200)
            self.assertIn(expected_msg, mock_add_msg.call_args[0])
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_by_instid_non_exist(self):
        with mock.patch("course.auth.messages.add_message") as mock_add_msg:
            expected_msg = (
                "That %s doesn't have an "
                "associated user account. Are you "
                "sure you've registered?" % "institutional ID")
            resp = self.post_reset_password(
                data={"instid": "2345"}, use_instid=True)
            self.assertTrue(resp.status_code, 200)
            self.assertIn(expected_msg, mock_add_msg.call_args[0])
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(resp.status_code, 200)

    def test_reset_by_email_have_multiple_user_with_same_email(self):
        with mock.patch("accounts.models.User.objects.get") as mock_get_user:
            from django.core.exceptions import MultipleObjectsReturned
            mock_get_user.side_effect = MultipleObjectsReturned()
            with mock.patch("course.auth.messages.add_message") as mock_add_msg:
                expected_msg = (
                    "Failed to send an email: multiple users were "
                    "unexpectedly using that same "
                    "email address. Please "
                    "contact site staffs.")
                resp = self.post_reset_password(
                    data={"email": "some_email@example.com"})
                self.assertTrue(resp.status_code, 200)
                self.assertIn(expected_msg, mock_add_msg.call_args[0])
            self.assertEqual(len(mail.outbox), 0)

    def test_reset_by_email_post_success(self):
        with mock.patch("course.auth.messages.add_message") as mock_add_msg:
            expected_msg = (
                "Email sent. Please check your email and "
                "click the link."
            )
            resp = self.post_reset_password(data={"email": self.user_email})
            self.assertTrue(resp.status_code, 200)
            self.assertEqual(mock_add_msg.call_count, 1)
            self.assertIn(expected_msg, mock_add_msg.call_args[0])
        self.assertEqual(len(mail.outbox), 1)
        self.assertTemplateUsed("course/sign-in-email.txt", count=1)

    def test_reset_by_istid_post_success(self):
        from course.auth import masked_email
        masked = masked_email(self.user_email)
        self.assertNotEqual(masked, self.user_email)

        with mock.patch("course.auth.messages.add_message") as mock_add_msg, \
                mock.patch("course.auth.masked_email") as mock_mask_email:
            expected_msg = (
                "Email sent. Please check your email and "
                "click the link."
            )
            resp = self.post_reset_password(data={"instid": self.user_inst_id},
                                            use_instid=True)
            self.assertTrue(resp.status_code, 200)
            self.assertEqual(mock_add_msg.call_count, 2)
            self.assertEqual(mock_mask_email.call_count, 1)
            self.assertIn(expected_msg, mock_add_msg.call_args[0])
        self.assertEqual(len(mail.outbox), 1)
        self.assertTemplateUsed("course/sign-in-email.txt", count=1)


# vim: foldmethod=marker
