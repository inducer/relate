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

from django.test import SimpleTestCase, mock
from django.test.utils import override_settings
from course.utils import get_course_specific_language_choices


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

            with mock.patch(
                    "django.utils.translation.trans_real.do_translate"
            ) as mock_do_translate:
                mock_do_translate.side_effect = lambda x, y: x
                choices = get_course_specific_language_choices()

                # The language description is the language_code, because it can't
                # be found in django.conf.locale.LANG_INFO
                self.assertEqual(choices[1][1], "user_customized_lang_code")

        with override_settings(USE_I18N=False, LANGUAGES=self.LANGUAGES_CONF2,
                               LANGUAGE_CODE='user_customized_lang_code'):
            with mock.patch(
                    "django.utils.translation.trans_real.do_translate"
            ) as mock_do_translate:
                mock_do_translate.side_effect = lambda x, y: x
                choices = get_course_specific_language_choices()

                # The language description is the language_code, because it can't
                # be found in django.conf.locale.LANG_INFO
                self.assertIn("user_customized_lang_code", choices[0][1])

# vim: foldmethod=marker
