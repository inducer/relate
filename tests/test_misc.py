# -*- coding: utf-8 -*-

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
import re
import datetime
from django.test import TestCase
from django.test.utils import override_settings
from django.utils.translation import ugettext_lazy as _

from course.models import Course
from course.views import EditCourseForm
from course.versioning import CourseCreationForm

from tests.base_test_mixins import SingleCourseTestMixin
from tests.utils import LocmemBackendTestsMixin, mail, mock
from tests.test_views import DATE_TIME_PICKER_TIME_FORMAT
from tests.test_utils import (
    REAL_TRANSLATION_FUNCTION_TO_MOCK, real_trans_side_effect)

LANGUAGES = [
    ('en', _('English')),
    ('ko', _('Korean')),
    ('fr', _('French')),
]

ASSERSION_ERROR_LANGUAGE_PATTERN = (
    "%s page visiting results don't match in terms of "
    "whether the response contains Korean characters."
)

ASSERSION_ERROR_CONTENT_LANGUAGE_PATTERN = (
    "%s page visiting result don't match in terms of "
    "whether the response content-language are restored."
)

VALIDATION_ERROR_LANG_NOT_SUPPORTED_PATTERN = (
    "'%s' is currently not supported as a course specific language at "
    "this site."
)


class CourseSpecificLangTestMixin(SingleCourseTestMixin, TestCase):
    # {{{ assertion method
    def response_contains_korean(self, resp):
        # Korean literals for 12th month (December)
        return "12월" in resp.content.decode("utf-8")

    def assertResponseContainsChinese(self, resp):  # noqa
        self.assertTrue(self.response_contains_korean(resp))

    def assertResponseNotContainsChinese(self, resp):  # noqa
        self.assertFalse(self.response_contains_korean(resp))

    # }}}

    # {{{ common tests
    def resp_info_with_diff_settings(self, url):
        contains_korean_result = []
        response_content_language_result = []

        with override_settings(USE_I18N=True, LANGUAGE_CODE='en-us'):
            resp = self.c.get(url)
            self.assertEqual(resp.status_code, 200)
            contains_korean_result.append(self.response_contains_korean(resp))
            response_content_language_result.append(resp['content-language'])

            resp = self.c.get(url, HTTP_ACCEPT_LANGUAGE='ko')
            self.assertEqual(resp.status_code, 200)
            contains_korean_result.append(self.response_contains_korean(resp))
            response_content_language_result.append(resp['content-language'])

        with override_settings(USE_I18N=False):
            resp = self.c.get(url)
            self.assertEqual(resp.status_code, 200)
            contains_korean_result.append(self.response_contains_korean(resp))
            response_content_language_result.append(resp['content-language'])

            resp = self.c.get(url, HTTP_ACCEPT_LANGUAGE='ko')
            self.assertEqual(resp.status_code, 200)
            contains_korean_result.append(self.response_contains_korean(resp))
            response_content_language_result.append(resp['content-language'])

        return contains_korean_result, response_content_language_result

    def home_resp_contains_korean_with_diff_settings(self):
        return self.resp_info_with_diff_settings("/")

    def course_resp_contains_korean_with_diff_settings(self):
        return self.resp_info_with_diff_settings(self.course_page_url)

    # }}}


class CourseSpecificLangConfigureTest(CourseSpecificLangTestMixin, TestCase):
    # By default, self.course.force_lang is None

    def setUp(self):
        super(CourseSpecificLangConfigureTest, self).setUp()
        # We use faked time header to find out whether the expected Chinese
        # characters are rendered
        self.c.force_login(self.instructor_participation.user)
        fake_time = datetime.datetime(2038, 12, 31, 0, 0, 0, 0)
        set_fake_time_data = {
            "time": fake_time.strftime(DATE_TIME_PICKER_TIME_FORMAT),
            "set": ['']}
        self.post_set_fake_time(set_fake_time_data)

    def assertResponseBehaveLikeUnconfigured(self):  # noqa
        # For each setting combinations, the response behaves the same
        # as before this functionality was introduced
        expected_result = ([False, True, False, True],
                           ['en', 'ko', 'en', 'ko'])
        self.assertEqual(
            self.home_resp_contains_korean_with_diff_settings()[0],
            expected_result[0],
            ASSERSION_ERROR_LANGUAGE_PATTERN % "Home"
        )

        self.assertEqual(
            self.home_resp_contains_korean_with_diff_settings()[1],
            expected_result[1],
            ASSERSION_ERROR_CONTENT_LANGUAGE_PATTERN % "Home"
        )

        expected_result = ([False, True, False, True],
                           ['en', 'ko', 'en', 'ko'])
        self.assertEqual(
            self.course_resp_contains_korean_with_diff_settings()[0],
            expected_result[0],
            ASSERSION_ERROR_LANGUAGE_PATTERN % "Course"
        )
        self.assertEqual(
            self.course_resp_contains_korean_with_diff_settings()[1],
            expected_result[1],
            ASSERSION_ERROR_CONTENT_LANGUAGE_PATTERN % "Course"
        )

    def assertResponseBehaveAsExpectedForCourseWithForceLang(self):  # noqa
        # For each setting combinations, the response behaves as expected
        expected_result = ([False, True, False, True],
                           ['en', 'ko', 'en', 'ko'])
        self.assertEqual(
            self.home_resp_contains_korean_with_diff_settings()[0],
            expected_result[0],
            ASSERSION_ERROR_LANGUAGE_PATTERN % "Home"
        )

        self.assertEqual(
            self.home_resp_contains_korean_with_diff_settings()[1],
            expected_result[1],
            ASSERSION_ERROR_CONTENT_LANGUAGE_PATTERN % "Home"
        )

        expected_result = ([True, True, True, True],
                           ['en', 'ko', 'en', 'ko'])
        self.assertEqual(
            self.course_resp_contains_korean_with_diff_settings()[0],
            expected_result[0],
            ASSERSION_ERROR_LANGUAGE_PATTERN % "Course"
        )
        self.assertEqual(
            self.course_resp_contains_korean_with_diff_settings()[1],
            expected_result[1],
            ASSERSION_ERROR_CONTENT_LANGUAGE_PATTERN % "Course"
        )

    def set_course_lang_to_ko(self):
        self.course.force_lang = "ko"
        self.course.save()
        self.course.refresh_from_db()

    def test_languages_not_configured(self):
        self.assertResponseBehaveLikeUnconfigured()

    def test_languages_not_configured_course_has_force_lang(self):
        self.set_course_lang_to_ko()
        self.assertResponseBehaveAsExpectedForCourseWithForceLang()

    @override_settings(LANGUAGES=LANGUAGES)
    def test_languages_configured(self):
        # because self.course.force_lang is None
        self.assertResponseBehaveLikeUnconfigured()

    @override_settings(LANGUAGES=LANGUAGES)
    def test_languages_configured_course_has_force_lang(self):
        self.set_course_lang_to_ko()
        self.assertResponseBehaveAsExpectedForCourseWithForceLang()

    @override_settings(LANGUAGES=LANGUAGES)
    def test_languages_configured_course_has_force_lang_get_language_none(self):
        self.set_course_lang_to_ko()
        with mock.patch("course.utils.translation.get_language")\
                as mock_get_language,\
                mock.patch("course.utils.translation.deactivate_all")\
                        as mock_deactivate_all:
            mock_get_language.return_value = None
            home_visit_result = self.home_resp_contains_korean_with_diff_settings()
            self.assertEqual(
                # Display Korean according to i18n, language_code and browser
                home_visit_result[0], [False, True, False, True])
            self.assertEqual(mock_deactivate_all.call_count, 0)

            mock_deactivate_all.reset_mock()
            course_page_visit_result = (
                self.course_resp_contains_korean_with_diff_settings())
            self.assertEqual(
                # All display Korean
                course_page_visit_result[0], [True, True, True, True])

            # There are 4 visit, each will call deactivate_all()
            self.assertEqual(mock_deactivate_all.call_count, 4)


class CourseSpecificLangFormTest(SingleCourseTestMixin, TestCase):

    def test_edit_course_force_lang_invalid(self):
        course_kwargs = self.copy_course_dict_and_set_attrs_for_post(
            {"force_lang": "foo"})
        form = EditCourseForm(course_kwargs, instance=self.course)
        self.assertTrue("force_lang" in form.fields)
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["force_lang"][0],
                         VALIDATION_ERROR_LANG_NOT_SUPPORTED_PATTERN % "foo")

    def test_edit_course_force_lang_valid(self):
        course_kwargs = self.copy_course_dict_and_set_attrs_for_post(
            {"force_lang": "de"})
        form = EditCourseForm(course_kwargs, instance=self.course)
        self.assertTrue(form.is_valid())

    def test_create_course_force_lang_invalid(self):
        course_kwargs = self.copy_course_dict_and_set_attrs_for_post(
            {"force_lang": "foo"})
        course_kwargs["identifier"] = "another-test-course"
        expected_course_count = Course.objects.count()
        form = CourseCreationForm(course_kwargs)
        self.assertTrue("force_lang" in form.fields)
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["force_lang"][0],
                         VALIDATION_ERROR_LANG_NOT_SUPPORTED_PATTERN % "foo")
        self.assertEqual(Course.objects.count(), expected_course_count)


class GetCurrentLanguageJsLangNameTest(TestCase):
    def setUp(self):
        super(GetCurrentLanguageJsLangNameTest, self).setUp()

        from django.template.utils import EngineHandler
        self.engines = EngineHandler()

    def test_get_current_js_lang_name_tag(self):
        with override_settings(LANGUAGE_CODE="en-us"):
            template = self.engines["django"].from_string(
                "{% get_current_js_lang_name as LANG %}{{LANG}}")
            text = template.render()
            self.assertEqual(text, "en-US")

        with override_settings(LANGUAGE_CODE="de"):
            template = self.engines["django"].from_string(
                "{% get_current_js_lang_name as LANG %}{{LANG}}")
            text = template.render()
            self.assertEqual(text, "de")

        with override_settings(LANGUAGE_CODE="zh-hans"):
            template = self.engines["django"].from_string(
                "{% get_current_js_lang_name as LANG %}{{LANG}}")
            text = template.render()
            self.assertEqual(text, "zh-Hans")

        with override_settings(LANGUAGE_CODE="zh-hant"):
            template = self.engines["django"].from_string(
                "{% get_current_js_lang_name as LANG %}{{LANG}}")
            text = template.render()
            self.assertEqual(text, "zh-Hant")

    def test_get_current_js_lang_name_tag_failed(self):
        from django.template import TemplateSyntaxError
        msg = ("'get_current_js_lang_name' requires 'as variable' "
               "(got [u'get_current_js_lang_name'])")

        if six.PY3:
            msg = msg.replace("u'", "'")

        with self.assertRaisesMessage(TemplateSyntaxError, expected_message=msg):
            self.engines["django"].from_string(
                "{% get_current_js_lang_name %}")

        msg = ("'get_current_js_lang_name' requires 'as variable' "
               "(got [u'get_current_js_lang_name', u'AS', u'LANG'])")

        if six.PY3:
            msg = msg.replace("u'", "'")

        with self.assertRaisesMessage(TemplateSyntaxError, expected_message=msg):
            self.engines["django"].from_string(
                "{% get_current_js_lang_name AS LANG %}{{LANG}}")

    def test_js_lang_fallback(self):
        with override_settings(LANGUAGE_CODE="en-us"):
            template = self.engines["django"].from_string(
                "{% get_current_js_lang_name as LANG %}"
                "{{LANG|js_lang_fallback}}")
            text = template.render()
            self.assertEqual(text, "en-US")

        with override_settings(LANGUAGE_CODE="en-us"):
            template = self.engines["django"].from_string(
                "{% get_current_js_lang_name as LANG %}"
                "{{LANG|js_lang_fallback:'fullcalendar'}}")
            text = template.render()
            self.assertEqual(text, "en-us")

        with override_settings(LANGUAGE_CODE="zh-cn"):
            template = self.engines["django"].from_string(
                "{% get_current_js_lang_name as LANG %}"
                "{{LANG|js_lang_fallback:'fullcalendar'}}")
            text = template.render()
            self.assertEqual(text, "zh-cn")

        with override_settings(LANGUAGE_CODE="zh-cn"):
            template = self.engines["django"].from_string(
                "{% get_current_js_lang_name as LANG %}"
                "{{LANG|js_lang_fallback}}")
            text = template.render()
            self.assertEqual(text, "zh-CN")

        with override_settings(LANGUAGE_CODE="zh-hans"):
            template = self.engines["django"].from_string(
                "{% get_current_js_lang_name as LANG %}"
                "{{LANG|js_lang_fallback}}")
            text = template.render()
            self.assertEqual(text, "zh-Hans")

        with override_settings(LANGUAGE_CODE="zh-hans"):
            template = self.engines["django"].from_string(
                "{% get_current_js_lang_name as LANG %}"
                "{{LANG|js_lang_fallback:'fullcalendar'}}")
            text = template.render()
            self.assertEqual(text, "zh-cn")


class HasPermissionTemplateFilterTest(SingleCourseTestMixin, TestCase):
    def setUp(self):
        super(HasPermissionTemplateFilterTest, self).setUp()

        from django.template.utils import EngineHandler
        self.engines = EngineHandler()

    def test_has_permission_with_no_arg(self):
        template = self.engines["django"].from_string(
            "{% if participation|has_permission:'view_gradebook' %}"
            "YES{% else %}NO{% endif %}")
        text = template.render({"participation": self.student_participation})
        self.assertEqual(text, "NO")

    def test_has_permission_with_arg(self):
        # with spaces in filter value
        template = self.engines["django"].from_string(
            "{% if participation|has_permission:'access_files_for , student ' %}"
            "YES{% else %}NO{% endif %}")
        text = template.render({"participation": self.student_participation})
        self.assertEqual(text, "YES")

        # with no spaces in filter value
        template = self.engines["django"].from_string(
            "{% if participation|has_permission:'access_files_for,student' %}"
            "YES{% else %}NO{% endif %}")
        text = template.render({"participation": self.student_participation})
        self.assertEqual(text, "YES")

    def test_has_permission_fail_silently(self):
        with mock.patch(
                "course.models.Participation.has_permission") as mock_has_pperm:
            mock_has_pperm.side_effect = RuntimeError

            template = self.engines["django"].from_string(
                "{% if participation|has_permission:'access_files_for,public' %}"
                "YES{% else %}NO{% endif %}")
            text = template.render({"participation": self.student_participation})
            self.assertEqual(text, "NO")


class RelateSiteNameTest(SingleCourseTestMixin, LocmemBackendTestsMixin, TestCase):
    def setUp(self):
        super(RelateSiteNameTest, self).setUp()

    def get_translation_count(self, mocked_method, literal):

        return len(
            [arg[0] for arg, kwarg in [
                args for args in mocked_method.call_args_list]
             if arg[0] == literal])

    def verify_result_with_configure(self, my_site_name):
        # home page
        with mock.patch(REAL_TRANSLATION_FUNCTION_TO_MOCK) as mock_gettext:
            mock_gettext.side_effect = real_trans_side_effect
            resp = self.c.get("/")
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "<title>%s</title>" % my_site_name, html=True)

            # Three translations in nav_bar brand, html title and
            # "Welcome to RELATE", respectively
            self.assertEqual(
                self.get_translation_count(mock_gettext, my_site_name), 3)
            mock_gettext.reset_mock()

            # course page
            resp = self.c.get(self.get_course_page_url())
            self.assertEqual(resp.status_code, 200)

            test_site_name_re = re.compile(
                ".+<title>.+-.+%s.+</title>.+" % my_site_name, re.DOTALL)
            self.assertRegex(resp.content.decode(), test_site_name_re)

            # One translation in html title
            self.assertEqual(
                self.get_translation_count(mock_gettext, my_site_name), 1)

        # email
        with override_settings(RELATE_REGISTRATION_ENABLED=True, USE_I18N=True):
            # render() is mocked so as to count string translated in email rendering
            with mock.patch(REAL_TRANSLATION_FUNCTION_TO_MOCK) as mock_gettext,\
                    mock.patch("course.auth._") as mock_ugettext,\
                    mock.patch('course.auth.messages'),\
                    mock.patch('course.auth.render'):
                mock_gettext.return_value = "foo"
                with self.temporarily_switch_to_user(None):
                    resp = self.post_sign_up(
                        data={"username": "Jack", "email": "jack@exmaple.com"},
                        follow=False
                    )
                    self.assertTrue(resp.status_code, 200)
                    self.assertEqual(len(mail.outbox), 1)

                    # In the view, tranlating RELATE for email title.
                    self.assertEqual(
                        self.get_translation_count(mock_ugettext, my_site_name), 1)

                    # Three RELATE in the email template
                    self.assertEqual(
                        self.get_translation_count(mock_gettext, my_site_name), 3)

    @override_settings()
    def test_default_configure(self):
        self.verify_result_with_configure("RELATE")

    @override_settings(RELATE_SITE_NAME="My RELATE")
    def test_custom_configure(self):
        self.verify_result_with_configure("My RELATE")

# vim: foldmethod=marker
