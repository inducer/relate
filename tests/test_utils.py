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
from unittest import skipUnless
from django.test import SimpleTestCase, TestCase
from django.test.utils import override_settings
from django import VERSION as DJANGO_VERSION
from django.utils import translation
from django.utils.translation import ugettext_noop

from course.utils import (
    get_course_specific_language_choices, LanguageOverride)

from tests.base_test_mixins import (
    SingleCoursePageTestMixin, SubprocessRunpyContainerMixin)
from tests.utils import mock


if DJANGO_VERSION < (2, 0):
    REAL_TRANSLATION_FUNCTION_TO_MOCK = (
        "django.utils.translation.trans_real.do_translate")
    real_trans_side_effect = lambda x, y: x  # noqa
else:
    # "do_translate(message, translation_function)" was refactored to
    # "gettext(message)" since Django >= 2.0
    REAL_TRANSLATION_FUNCTION_TO_MOCK = (
        "django.utils.translation._trans.gettext")
    real_trans_side_effect = lambda x: x  # noqa


def is_travis_py3():
    import os

    if "RL_TRAVIS_TEST" not in os.environ:
        return False

    if six.PY2:
        return False

    return True


class GetCourseSpecificLanguageChoicesTest(SimpleTestCase):
    # test course.utils.get_course_specific_language_choices

    LANGUAGES_CONF1 = [
        ('en', 'English'),
        ('zh-hans', 'Simplified Chinese'),
        ('de', 'German')]
    LANGUAGES_CONF2 = [
        ('en', 'English'),
        ('zh-hans', 'Simplified Chinese'),
        ('zh-hans', 'my Simplified Chinese'),
        ('de', 'German')]

    @override_settings(USE_I18N=False, LANGUAGES=LANGUAGES_CONF1,
                       LANGUAGE_CODE='ko')
    def test_i18n_disabled(self):
        choices = get_course_specific_language_choices()
        self.assertTrue(choices[0][1].startswith("Default:"))
        self.assertNotIn("disabled", choices[0][1])
        self.assertEqual(len(choices), 4)
        self.assertIn("(ko)", choices[0][1])

    @override_settings(USE_I18N=False, LANGUAGES=LANGUAGES_CONF1,
                       LANGUAGE_CODE='en')
    def test_i18n_disabled_lang_items_has_same_lang_code_with_language_code(self):
        choices = get_course_specific_language_choices()
        self.assertTrue(choices[0][1].startswith("Default:"))
        self.assertNotIn("disabled", choices[0][1])
        self.assertEqual(len(choices), 3)

    @override_settings(USE_I18N=False, LANGUAGES=LANGUAGES_CONF2,
                       LANGUAGE_CODE='en-us')
    def test_i18n_disabled_lang_items_having_duplicated_lang_code(self):
        choices = get_course_specific_language_choices()
        self.assertTrue(choices[0][1].startswith("Default:"))
        self.assertNotIn("disabled", choices[0][1])
        self.assertEqual(len(choices), 4)

    @override_settings(USE_I18N=True, LANGUAGES=LANGUAGES_CONF1,
                       LANGUAGE_CODE='ko')
    def test_i18n_enabled(self):
        choices = get_course_specific_language_choices()
        self.assertTrue(choices[0][1].startswith("Default: disabled"))
        self.assertEqual(len(choices), 5)
        self.assertIn("(ko)", choices[1][1])

    @override_settings(USE_I18N=True, LANGUAGES=LANGUAGES_CONF1,
                       LANGUAGE_CODE='en')
    def test_i18n_enabled_lang_items_has_same_lang_code_with_language_code(self):
        choices = get_course_specific_language_choices()
        self.assertTrue(choices[0][1].startswith("Default: disabled"))
        self.assertEqual(len(choices), 4)

    @override_settings(USE_I18N=True, LANGUAGES=LANGUAGES_CONF2,
                       LANGUAGE_CODE='en-us')
    def test_i18n_enabled_lang_items_having_duplicated_lang_code(self):
        choices = get_course_specific_language_choices()
        self.assertEqual(len(choices), 5)
        self.assertTrue(choices[0][1].startswith("Default: disabled"))

    def lang_descr_get_translated(self, choice_count):
        with mock.patch("course.utils._") as mock_ugettext, \
                mock.patch("django.utils.translation.ugettext_lazy") \
                as mock_ugettext_lazy:
            mock_ugettext.side_effect = lambda x: x
            mock_ugettext_lazy.side_effect = lambda x: x
            choices = get_course_specific_language_choices()
            self.assertEqual(len(choices), choice_count)

            # "English", "Default", "my Simplified Chinese" and "German" are
            # called by django.utils.translation.ugettext, for at least once.
            # Another language description literals (especially "Simplified Chinese")
            # are not called by it.
            self.assertTrue(mock_ugettext.call_count >= 4)
            simplified_chinese_as_arg_count = 0
            my_simplified_chinese_as_arg_count = 0
            for call in mock_ugettext.call_args_list:
                arg, kwargs = call
                if "my Simplified Chinese" in arg:
                    my_simplified_chinese_as_arg_count += 1
                if "Simplified Chinese" in arg:
                    simplified_chinese_as_arg_count += 1
            self.assertEqual(simplified_chinese_as_arg_count, 0)
            self.assertTrue(my_simplified_chinese_as_arg_count > 0)

    def test_lang_descr_translated(self):
        with override_settings(USE_I18N=True, LANGUAGES=self.LANGUAGES_CONF2,
                       LANGUAGE_CODE='en-us'):
            self.lang_descr_get_translated(choice_count=5)

        with override_settings(USE_I18N=True, LANGUAGES=self.LANGUAGES_CONF2,
                       LANGUAGE_CODE='en-us'):
            self.lang_descr_get_translated(choice_count=5)

    def test_user_customized_lang_code_as_settings_language_code(self):
        with override_settings(USE_I18N=True, LANGUAGES=self.LANGUAGES_CONF2,
                       LANGUAGE_CODE='user_customized_lang_code'):
            with self.assertRaises(IOError):
                # because there's no file named "user_customized_lang_code.mo"
                get_course_specific_language_choices()

            with mock.patch(REAL_TRANSLATION_FUNCTION_TO_MOCK) as mock_gettext:
                mock_gettext.side_effect = real_trans_side_effect
                choices = get_course_specific_language_choices()

                # The language description is the language_code, because it can't
                # be found in django.conf.locale.LANG_INFO
                self.assertEqual(choices[1][1], "user_customized_lang_code")

        with override_settings(USE_I18N=False, LANGUAGES=self.LANGUAGES_CONF2,
                               LANGUAGE_CODE='user_customized_lang_code'):
            with mock.patch(REAL_TRANSLATION_FUNCTION_TO_MOCK) as mock_gettext:
                mock_gettext.side_effect = real_trans_side_effect
                choices = get_course_specific_language_choices()

                # The language description is the language_code, because it can't
                # be found in django.conf.locale.LANG_INFO
                self.assertIn("user_customized_lang_code", choices[0][1])


class LanguageOverrideTest(SingleCoursePageTestMixin,
                           SubprocessRunpyContainerMixin, TestCase):
    # test course.utils.LanguageOverride

    @classmethod
    def setUpTestData(cls):  # noqa
        super(LanguageOverrideTest, cls).setUpTestData()
        cls.c.force_login(cls.instructor_participation.user)
        cls.start_flow(cls.flow_id)

    @override_settings(RELATE_ADMIN_EMAIL_LOCALE="de", LANGUAGE_CODE="ko")
    def test_language_override_no_course_force_lang(self):
        if self.course.force_lang:
            self.course.force_lang = ""
            self.course.save()
        with LanguageOverride(course=self.course):
            self.assertEqual(translation.get_language(), "de")
            self.assertEqual(translation.ugettext("user"), u"Benutzer")

        self.assertEqual(translation.get_language(), "ko")
        self.assertEqual(translation.ugettext("user"), u"사용자")

    @override_settings(RELATE_ADMIN_EMAIL_LOCALE="de", LANGUAGE_CODE="ko")
    def test_language_override_course_has_force_lang(self):
        self.course.force_lang = "zh-hans"
        self.course.save()

        with LanguageOverride(course=self.course):
            self.assertEqual(translation.get_language(), "zh-hans")

        self.assertEqual(translation.get_language(), "ko")

    @override_settings(RELATE_ADMIN_EMAIL_LOCALE=None)
    def test_language_override_no_course_force_lang_no_admin_lang(self):
        if self.course.force_lang:
            self.course.force_lang = ""
            self.course.save()

        with LanguageOverride(course=self.course):
            self.assertEqual(translation.get_language(), None)
            self.assertEqual(translation.ugettext("whatever"), "whatever")

        self.assertEqual(translation.get_language(), "en-us")

    @override_settings(RELATE_ADMIN_EMAIL_LOCALE="de")
    def test_language_override_no_course_force_lang_no_langcode(self):
        if self.course.force_lang:
            self.course.force_lang = ""
            self.course.save()

        translation.deactivate_all()
        with LanguageOverride(course=self.course):
            self.assertEqual(translation.get_language(), "de")
            self.assertEqual(translation.ugettext("user"), u"Benutzer")

        self.assertEqual(translation.get_language(), None)
        self.assertEqual(translation.ugettext("whatever"), "whatever")

    @override_settings(RELATE_ADMIN_EMAIL_LOCALE="de")
    def test_language_override_deactivate(self):
        self.course.force_lang = "zh-hans"
        self.course.save()

        with LanguageOverride(course=self.course, deactivate=True):
            self.assertEqual(translation.get_language(), "zh-hans")
            self.assertEqual(translation.ugettext("user"), u"用户")

        self.assertEqual(translation.get_language(), "en-us")

    page_id_literal_dict = {
        "half": {"literals": [ugettext_noop("No answer provided.")]},
        "krylov": {"literals": [ugettext_noop("No answer provided."), ]},
        "ice_cream_toppings": {
            "literals": [ugettext_noop("No answer provided."), ]},
        "inlinemulti": {
            "literals":
                [ugettext_noop("No answer provided."), ]},
        "hgtext": {
            "literals": [ugettext_noop("No answer provided.")]},
        "quarter": {
            "literals": [ugettext_noop("No answer provided."), ]},
        "pymult": {
            "answer": {"answer": "c = ..."},
            "literals": [
                ugettext_noop("Autograder feedback"),
                ugettext_noop("Your answer is not correct.")
            ]},
        "addition": {
            "answer": {"answer": "c = a + b"},
            "literals": [
                ugettext_noop("Your answer is correct."),
                ugettext_noop("It looks like you submitted code that is "
                              "identical to the reference solution. "
                              "This is not allowed."),
                ugettext_noop("Here is some feedback on your code"),
            ]},
        "anyup": {"literals": [ugettext_noop("No answer provided.")]},
    }

    def feedback_test(self, course_force_lang):
        self.course.force_lang = course_force_lang
        self.course.save()

        for page_id, v in six.iteritems(self.page_id_literal_dict):
            if "answer" not in v:
                continue
            self.post_answer_by_page_id(page_id, answer_data=v["answer"])

        self.end_flow()

        for page_id, v in six.iteritems(self.page_id_literal_dict):
            with self.subTest(page_id=page_id, course_force_lang=course_force_lang):
                resp = self.c.get(self.get_page_url_by_page_id(page_id))
                for literal in v["literals"]:
                    if not course_force_lang:
                        self.assertContains(resp, literal)
                    else:
                        with translation.override(course_force_lang):
                            translated_literal = translation.ugettext(literal)
                        self.assertContains(resp, translated_literal)

    @skipUnless(is_travis_py3(), "This is tested only on Travis with PY3.5")
    @override_settings(RELATE_ADMIN_EMAIL_LOCALE="en-us")
    def test_course_no_force_lang_feedback(self):
        self.feedback_test(course_force_lang="")

    @skipUnless(is_travis_py3(), "This is tested only on Travis with PY3.5")
    @override_settings(RELATE_ADMIN_EMAIL_LOCALE="en-us")
    def test_course_force_lang_zh_hans_feedback(self):
        self.feedback_test(course_force_lang="zh-hans")


# vim: foldmethod=marker
