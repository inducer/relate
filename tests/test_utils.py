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
from datetime import datetime
from copy import deepcopy

import unittest
from unittest import skipUnless
from django.test import SimpleTestCase, TestCase, RequestFactory
from django.utils.timezone import now, timedelta
from django.test.utils import override_settings
from django import VERSION as DJANGO_VERSION
from django.utils import translation
from django.utils.translation import ugettext_noop
from django.conf import settings

from relate.utils import (
    localize_datetime, format_datetime_local,
    struct_to_dict, dict_to_struct)

from course import utils
from course.content import parse_date_spec
from course import constants  # noqa
from course.constants import flow_permission as fperm

from tests.constants import QUIZ_FLOW_ID
from tests.base_test_mixins import (
    CoursesTestMixinBase,
    SingleCoursePageTestMixin, SubprocessRunpyContainerMixin,
    SingleCourseTestMixin, FallBackStorageMessageTestMixin,
)
from tests.utils import mock
from tests import factories


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
        choices = utils.get_course_specific_language_choices()
        self.assertTrue(choices[0][1].startswith("Default:"))
        self.assertNotIn("disabled", choices[0][1])
        self.assertEqual(len(choices), 4)
        self.assertIn("(ko)", choices[0][1])

    @override_settings(USE_I18N=False, LANGUAGES=LANGUAGES_CONF1,
                       LANGUAGE_CODE='en')
    def test_i18n_disabled_lang_items_has_same_lang_code_with_language_code(self):
        choices = utils.get_course_specific_language_choices()
        self.assertTrue(choices[0][1].startswith("Default:"))
        self.assertNotIn("disabled", choices[0][1])
        self.assertEqual(len(choices), 3)

    @override_settings(USE_I18N=False, LANGUAGES=LANGUAGES_CONF2,
                       LANGUAGE_CODE='en-us')
    def test_i18n_disabled_lang_items_having_duplicated_lang_code(self):
        choices = utils.get_course_specific_language_choices()
        self.assertTrue(choices[0][1].startswith("Default:"))
        self.assertNotIn("disabled", choices[0][1])
        self.assertEqual(len(choices), 4)

    @override_settings(USE_I18N=True, LANGUAGES=LANGUAGES_CONF1,
                       LANGUAGE_CODE='ko')
    def test_i18n_enabled(self):
        choices = utils.get_course_specific_language_choices()
        self.assertTrue(choices[0][1].startswith("Default: disabled"))
        self.assertEqual(len(choices), 5)
        self.assertIn("(ko)", choices[1][1])

    @override_settings(USE_I18N=True, LANGUAGES=LANGUAGES_CONF1,
                       LANGUAGE_CODE='en')
    def test_i18n_enabled_lang_items_has_same_lang_code_with_language_code(self):
        choices = utils.get_course_specific_language_choices()
        self.assertTrue(choices[0][1].startswith("Default: disabled"))
        self.assertEqual(len(choices), 4)

    @override_settings(USE_I18N=True, LANGUAGES=LANGUAGES_CONF2,
                       LANGUAGE_CODE='en-us')
    def test_i18n_enabled_lang_items_having_duplicated_lang_code(self):
        choices = utils.get_course_specific_language_choices()
        self.assertEqual(len(choices), 5)
        self.assertTrue(choices[0][1].startswith("Default: disabled"))

    def lang_descr_get_translated(self, choice_count):
        with mock.patch("course.utils._") as mock_ugettext, \
                mock.patch("django.utils.translation.ugettext_lazy") \
                as mock_ugettext_lazy:
            mock_ugettext.side_effect = lambda x: x
            mock_ugettext_lazy.side_effect = lambda x: x
            choices = utils.get_course_specific_language_choices()
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
                utils.get_course_specific_language_choices()

            with mock.patch(REAL_TRANSLATION_FUNCTION_TO_MOCK) as mock_gettext:
                mock_gettext.side_effect = real_trans_side_effect
                choices = utils.get_course_specific_language_choices()

                # The language description is the language_code, because it can't
                # be found in django.conf.locale.LANG_INFO
                self.assertEqual(choices[1][1], "user_customized_lang_code")

        with override_settings(USE_I18N=False, LANGUAGES=self.LANGUAGES_CONF2,
                               LANGUAGE_CODE='user_customized_lang_code'):
            with mock.patch(REAL_TRANSLATION_FUNCTION_TO_MOCK) as mock_gettext:
                mock_gettext.side_effect = real_trans_side_effect
                choices = utils.get_course_specific_language_choices()

                # The language description is the language_code, because it can't
                # be found in django.conf.locale.LANG_INFO
                self.assertIn("user_customized_lang_code", choices[0][1])


class LanguageOverrideTest(SingleCoursePageTestMixin,
                           SubprocessRunpyContainerMixin, TestCase):
    # test course.utils.LanguageOverride

    force_login_student_for_each_test = False

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
        with utils.LanguageOverride(course=self.course):
            self.assertEqual(translation.get_language(), "de")
            self.assertEqual(translation.ugettext("user"), u"Benutzer")

        self.assertEqual(translation.get_language(), "ko")
        self.assertEqual(translation.ugettext("user"), u"사용자")

    @override_settings(RELATE_ADMIN_EMAIL_LOCALE="de", LANGUAGE_CODE="ko")
    def test_language_override_course_has_force_lang(self):
        self.course.force_lang = "zh-hans"
        self.course.save()

        with utils.LanguageOverride(course=self.course):
            self.assertEqual(translation.get_language(), "zh-hans")

        self.assertEqual(translation.get_language(), "ko")

    @override_settings(RELATE_ADMIN_EMAIL_LOCALE=None)
    def test_language_override_no_course_force_lang_no_admin_lang(self):
        if self.course.force_lang:
            self.course.force_lang = ""
            self.course.save()

        with utils.LanguageOverride(course=self.course):
            self.assertEqual(translation.get_language(), None)
            self.assertEqual(translation.ugettext("whatever"), "whatever")

        self.assertEqual(translation.get_language(), "en-us")

    @override_settings(RELATE_ADMIN_EMAIL_LOCALE="de")
    def test_language_override_no_course_force_lang_no_langcode(self):
        if self.course.force_lang:
            self.course.force_lang = ""
            self.course.save()

        translation.deactivate_all()
        with utils.LanguageOverride(course=self.course):
            self.assertEqual(translation.get_language(), "de")
            self.assertEqual(translation.ugettext("user"), u"Benutzer")

        self.assertEqual(translation.get_language(), None)
        self.assertEqual(translation.ugettext("whatever"), "whatever")

    @override_settings(RELATE_ADMIN_EMAIL_LOCALE="de")
    def test_language_override_deactivate(self):
        self.course.force_lang = "zh-hans"
        self.course.save()

        with utils.LanguageOverride(course=self.course, deactivate=True):
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


class GetCustomPageTypesStopSupportDeadlineTest(unittest.TestCase):
    # test course.utils.get_custom_page_types_stop_support_deadline

    force_deadline = datetime(2019, 1, 1, 0, 0, 0, 0)

    def test_custom_deadline_before_force_deadline(self):
        deadline = datetime(2017, 1, 1, 0, 0, 0, 0)
        with override_settings(
                RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE=deadline):
            self.assertEqual(
                utils.get_custom_page_types_stop_support_deadline(),
                localize_datetime(deadline))

    def test_custom_deadline_after_force_deadline(self):
        deadline = datetime(2019, 1, 1, 1, 0, 0, 0)
        with override_settings(
                RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE=deadline):
            self.assertEqual(
                utils.get_custom_page_types_stop_support_deadline(),
                localize_datetime(self.force_deadline))

    def test_custom_deadline_not_configured(self):
        with override_settings():
            del settings.RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE
            self.assertEqual(
                utils.get_custom_page_types_stop_support_deadline(),
                localize_datetime(self.force_deadline))


class CustomRepoPageStopSupportTest(SingleCourseTestMixin,
                                    FallBackStorageMessageTestMixin, TestCase):

    def setUp(self):
        super(CustomRepoPageStopSupportTest, self).setUp()
        self.current_commit_sha = self.get_course_commit_sha(
            self.instructor_participation)

    force_deadline = datetime(2019, 1, 1, 0, 0, 0, 0)

    custom_page_type = "repo:simple_questions.MyTextQuestion"

    commit_sha_deprecated = b"593a1cdcecc6f4759fd5cadaacec0ba9dd0715a7"

    deprecate_warning_message_pattern = (
        "Custom page type '%(page_type)s' specified. "
        "Custom page types will stop being supported in "
        "RELATE at %(date_time)s.")

    expired_error_message_pattern = (
        "Custom page type '%(page_type)s' specified. "
        "Custom page types were no longer supported in "
        "RELATE since %(date_time)s.")

    def test_custom_page_types_deprecate(self):
        deadline = datetime(2039, 1, 1, 0, 0, 0, 0)

        with override_settings(
                RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE=deadline):
            resp = self.post_update_course_content(
                commit_sha=self.commit_sha_deprecated)
            self.assertEqual(resp.status_code, 200)

            if datetime.now() <= self.force_deadline:
                expected_message = (
                    self.deprecate_warning_message_pattern
                    % {"page_type": self.custom_page_type,
                       "date_time": format_datetime_local(self.force_deadline)}
                )
                self.assertEqual(
                    self.get_course_commit_sha(self.instructor_participation),
                    self.commit_sha_deprecated)
            else:
                expected_message = (
                    self.expired_error_message_pattern
                    % {"page_type": self.custom_page_type,
                       "date_time": format_datetime_local(self.force_deadline)}
                )
                self.assertEqual(
                    self.get_course_commit_sha(self.instructor_participation),
                    self.current_commit_sha)
            self.assertResponseMessagesContains(resp, expected_message, loose=True)

    def test_custom_page_types_not_supported(self):
        deadline = datetime(2017, 1, 1, 0, 0, 0, 0)
        with override_settings(
                RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE=deadline):
            resp = self.post_update_course_content(
                commit_sha=self.commit_sha_deprecated)
            self.assertEqual(resp.status_code, 200)
            expected_message = (
                self.expired_error_message_pattern
                % {"page_type": self.custom_page_type,
                   "date_time": format_datetime_local(deadline)}
            )
            self.assertResponseMessagesContains(resp, expected_message, loose=True)
            self.assertEqual(
                self.get_course_commit_sha(self.instructor_participation),
                self.current_commit_sha)

    def test_custom_page_types_deadline_configured_none(self):
        with override_settings(
                RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE=None):
            resp = self.post_update_course_content(
                commit_sha=self.commit_sha_deprecated)
            self.assertEqual(resp.status_code, 200)

            if datetime.now() <= self.force_deadline:
                expected_message = (
                    self.deprecate_warning_message_pattern
                    % {"page_type": self.custom_page_type,
                       "date_time": format_datetime_local(self.force_deadline)}
                )
                self.assertEqual(
                    self.get_course_commit_sha(self.instructor_participation),
                    self.commit_sha_deprecated)
            else:
                expected_message = (
                    self.expired_error_message_pattern
                    % {"page_type": self.custom_page_type,
                       "date_time": format_datetime_local(self.force_deadline)}
                )
                self.assertEqual(
                    self.get_course_commit_sha(self.instructor_participation),
                    self.current_commit_sha)
            self.assertResponseMessagesContains(resp, expected_message, loose=True)


class Foo(object):
    def __init__(self, a=None):
        self.a = a


class GetattrWithFallbackTest(unittest.TestCase):
    # test utils.getattr_with_fallback
    def test_result_found(self):
        aggregates = [Foo(), Foo(1), Foo(None)]
        self.assertEqual(utils.getattr_with_fallback(aggregates, "a", None), 1)

    def test_fallbacked(self):
        aggregates = [Foo(), Foo(), Foo(None)]
        self.assertEqual(utils.getattr_with_fallback(aggregates, "a", 2), 2)


class FlowSessionAccessRuleText(unittest.TestCase):
    # test utils.FlowSessionAccessRule
    def test_human_readable_permissions(self):
        arule = utils.FlowSessionAccessRule(
            permissions=frozenset([fperm.end_session, fperm.see_correctness])
        )
        result = arule.human_readable_permissions()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)


class EvalGenericConditionsTest(unittest.TestCase):
    # test utils._eval_generic_conditions
    def setUp(self):
        self.course = mock.MagicMock()
        self.participation = mock.MagicMock()
        self.login_exam_ticket = mock.MagicMock()
        self.flow_id = mock.MagicMock()

        fake_parse_date_spec = mock.patch("course.utils.parse_date_spec")
        self.mock_parse_date_spec = fake_parse_date_spec.start()
        self.mock_parse_date_spec.return_value = now() - timedelta(days=1)
        self.addCleanup(fake_parse_date_spec.stop)

        fake_get_participation_role_identifiers = mock.patch(
            "course.enrollment.get_participation_role_identifiers")
        self.mock_get_participation_role_identifiers = (
            fake_get_participation_role_identifiers.start()
        )
        self.mock_get_participation_role_identifiers.return_value = (
            ["student", "ta"])

        self.addCleanup(fake_get_participation_role_identifiers.stop)

    def test_if_before(self):
        rule = utils.FlowSessionRuleBase()
        rule.if_before = mock.MagicMock()

        now_datetime = now() + timedelta(days=2)
        self.assertFalse(
            utils._eval_generic_conditions(
                rule, self.course, self.participation,
                now_datetime, self.flow_id, self.login_exam_ticket))

        now_datetime = now() - timedelta(days=2)
        self.assertTrue(
            utils._eval_generic_conditions(
                rule, self.course, self.participation,
                now_datetime, self.flow_id, self.login_exam_ticket))

    def test_if_after(self):
        rule = utils.FlowSessionRuleBase()
        rule.if_after = mock.MagicMock()

        now_datetime = now() - timedelta(days=2)
        self.assertFalse(
            utils._eval_generic_conditions(
                rule, self.course, self.participation,
                now_datetime, self.flow_id, self.login_exam_ticket))

        now_datetime = now() + timedelta(days=2)
        self.assertTrue(
            utils._eval_generic_conditions(
                rule, self.course, self.participation,
                now_datetime, self.flow_id, self.login_exam_ticket))

    def test_if_has_role(self):
        rule = utils.FlowSessionRuleBase()
        rule.if_has_role = ["instructor"]
        now_datetime = now() - timedelta(days=2)

        self.assertFalse(
            utils._eval_generic_conditions(
                rule, self.course, self.participation,
                now_datetime, self.flow_id, self.login_exam_ticket))

        rule.if_has_role = ["student"]
        self.assertTrue(
            utils._eval_generic_conditions(
                rule, self.course, self.participation,
                now_datetime, self.flow_id, self.login_exam_ticket))

    def test_if_signed_in_with_matching_exam_ticket(self):
        rule = utils.FlowSessionRuleBase()
        rule.if_signed_in_with_matching_exam_ticket = True
        now_datetime = now() - timedelta(days=2)

        # login_exam_ticket is None
        self.assertFalse(
            utils._eval_generic_conditions(
                rule, self.course, self.participation,
                now_datetime, self.flow_id, None))

        # flow_id not match
        self.flow_id = "bar"
        self.login_exam_ticket.exam = mock.MagicMock()
        self.login_exam_ticket.exam.flow_id = "foo"
        self.assertFalse(
            utils._eval_generic_conditions(
                rule, self.course, self.participation,
                now_datetime, self.flow_id, self.login_exam_ticket))

        # flow_id matched
        self.flow_id = "foo"
        self.login_exam_ticket.exam = mock.MagicMock()
        self.login_exam_ticket.exam.flow_id = "foo"
        self.assertTrue(
            utils._eval_generic_conditions(
                rule, self.course, self.participation,
                now_datetime, self.flow_id, self.login_exam_ticket))


class EvalGenericSessionConditionsTest(unittest.TestCase):
    def setUp(self):
        self.session = mock.MagicMock()
        fake_parse_date_spec = mock.patch("course.utils.parse_date_spec")
        self.mock_parse_date_spec = fake_parse_date_spec.start()
        self.mock_parse_date_spec.return_value = now() + timedelta(days=1)
        self.addCleanup(fake_parse_date_spec.stop)

    def test_true(self):
        rule = utils.FlowSessionRuleBase()
        self.assertTrue(
            utils._eval_generic_session_conditions(rule, self.session, now()))

    def test_if_has_tag(self):
        rule = utils.FlowSessionRuleBase()
        rule.if_has_tag = "foo"
        now_datetime = now()

        self.session.access_rules_tag = "bar"
        self.assertFalse(
            utils._eval_generic_session_conditions(rule, self.session, now_datetime)
        )

        self.session.access_rules_tag = "foo"
        self.assertTrue(
            utils._eval_generic_session_conditions(rule, self.session, now_datetime)
        )

    def test_if_started_before(self):
        rule = utils.FlowSessionRuleBase()
        rule.if_started_before = mock.MagicMock()
        now_datetime = now()

        self.session.start_time = now()
        self.assertTrue(
            utils._eval_generic_session_conditions(rule, self.session, now_datetime)
        )

        self.session.start_time = now() + timedelta(days=2)
        self.assertFalse(
            utils._eval_generic_session_conditions(rule, self.session, now_datetime)
        )


class EvalParticipationTagsConditionsTest(CoursesTestMixinBase, TestCase):
    # test utils._eval_participation_tags_conditions
    @classmethod
    def setUpTestData(cls):  # noqa
        course = factories.CourseFactory()
        cls.participation1 = factories.ParticipationFactory(
            course=course)

        tag1 = factories.ParticipationTagFactory(
            course=course,
            name="tag1")
        tag2 = factories.ParticipationTagFactory(
            course=course,
            name="tag2")
        tag3 = factories.ParticipationTagFactory(
            course=course,
            name="tag3")

        cls.participation2 = factories.ParticipationFactory(
            course=course)
        cls.participation2.tags.set([tag1, tag2])

        cls.participation3 = factories.ParticipationFactory(
            course=course)
        cls.participation3.tags.set([tag1, tag2, tag3])

    def test_no_participation(self):
        rule = utils.FlowSessionRuleBase()
        rule.if_has_participation_tags_any = ["tag1"]
        self.assertFalse(
            utils._eval_participation_tags_conditions(rule, None))

    def test_true(self):
        rule = utils.FlowSessionRuleBase()
        self.assertTrue(
            utils._eval_participation_tags_conditions(rule, None))
        self.assertTrue(
            utils._eval_participation_tags_conditions(rule, self.participation1))
        self.assertTrue(
            utils._eval_participation_tags_conditions(rule, self.participation2))
        self.assertTrue(
            utils._eval_participation_tags_conditions(rule, self.participation3))

    def test_if_has_participation_tags_any(self):
        rule = utils.FlowSessionRuleBase()
        rule.if_has_participation_tags_any = ["tag1", "tag3"]

        self.assertFalse(
            utils._eval_participation_tags_conditions(rule, self.participation1))

        self.assertTrue(
            utils._eval_participation_tags_conditions(rule, self.participation2))

        self.assertTrue(
            utils._eval_participation_tags_conditions(rule, self.participation3))

        rule.if_has_participation_tags_any = ["foo"]
        self.assertFalse(
            utils._eval_participation_tags_conditions(rule, self.participation3))

    def test_if_has_participation_tags_all(self):
        rule = utils.FlowSessionRuleBase()
        rule.if_has_participation_tags_all = ["tag1", "tag3"]

        self.assertFalse(
            utils._eval_participation_tags_conditions(rule, self.participation1))

        self.assertFalse(
            utils._eval_participation_tags_conditions(rule, self.participation2))

        self.assertTrue(
            utils._eval_participation_tags_conditions(rule, self.participation3))


class GetFlowRulesTest(SingleCourseTestMixin, TestCase):
    # test utils.get_flow_rules

    flow_id = QUIZ_FLOW_ID

    def test_no_rules(self):

        # emtpy rules
        flow_desc = self.get_hacked_flow_desc(del_rules=True)

        default_rules_desc = [mock.MagicMock(), mock.MagicMock()]

        result = utils.get_flow_rules(
            flow_desc, constants.flow_rule_kind.start,
            self.student_participation,
            self.flow_id,
            now(),
            consider_exceptions=False,
            default_rules_desc=default_rules_desc
        )

        self.assertListEqual(result, default_rules_desc)

        result = utils.get_flow_rules(
            flow_desc, constants.flow_rule_kind.start,
            self.student_participation,
            self.flow_id,
            now(),
            consider_exceptions=True,
            default_rules_desc=default_rules_desc
        )

        self.assertListEqual(result, default_rules_desc)

    @unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_rules_with_given_kind(self):

        # use real rules
        flow_desc = self.get_hacked_flow_desc()

        default_rules_desc = [mock.MagicMock(), mock.MagicMock()]

        for kind in dict(constants.FLOW_RULE_KIND_CHOICES).keys():
            with self.subTest(missing_kind=kind):
                result = utils.get_flow_rules(
                    flow_desc, kind,
                    self.student_participation,
                    self.flow_id,
                    now(),
                    consider_exceptions=False,
                    default_rules_desc=default_rules_desc
                )

                # there are existing rule for those kind
                self.assertNotEqual(result, default_rules_desc)

    @unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_rules_with_no_given_kind(self):
        flow_desc_dict = self.get_hacked_flow_desc(as_dict=True)

        default_rules_desc = [mock.MagicMock(), mock.MagicMock()]

        for kind in dict(constants.FLOW_RULE_KIND_CHOICES).keys():
            flow_desc_dict_copy = deepcopy(flow_desc_dict)
            rules_dict = struct_to_dict(flow_desc_dict_copy["rules"])

            # delete kind from flow_desc
            rules_dict.pop(kind)
            flow_desc_dict_copy["rules"] = dict_to_struct(rules_dict)
            flow_desc = dict_to_struct(flow_desc_dict_copy)

            assert not hasattr(flow_desc.rules, kind)

            with self.subTest(missing_kind=kind):
                result = utils.get_flow_rules(
                    flow_desc, kind,
                    self.student_participation,
                    self.flow_id,
                    now(),
                    consider_exceptions=False,
                    default_rules_desc=default_rules_desc
                )

                self.assertListEqual(result, default_rules_desc)

    def test_not_consider_exist_exceptions(self):
        # use real rules
        flow_desc = self.get_hacked_flow_desc()

        default_rules_desc = [mock.MagicMock(), mock.MagicMock()]

        factories.FlowRuleExceptionFactory(
            flow_id=self.flow_id,
            participation=self.student_participation,
            kind=constants.flow_rule_kind.start,
            rule={
                "if_after": "end_week 1"
            }
        )

        result = utils.get_flow_rules(
            flow_desc, constants.flow_rule_kind.start,
            self.student_participation,
            self.flow_id,
            now(),
            consider_exceptions=False,  # NOT consider
            default_rules_desc=default_rules_desc
        )

        exist_start_rule = flow_desc.rules.start

        self.assertNotEqual(result, default_rules_desc)
        self.assertEqual(exist_start_rule, result)

    def test_consider_exist_exceptions_is_default_to_true(self):

        # use real rules
        flow_desc = self.get_hacked_flow_desc()
        exist_start_rule = flow_desc.rules.start

        default_rules_desc = [mock.MagicMock(), mock.MagicMock()]

        # creating 1 rules without expiration
        factories.FlowRuleExceptionFactory(
            flow_id=self.flow_id,
            participation=self.student_participation,
            kind=constants.flow_rule_kind.start,
            creation_time=now() - timedelta(days=1),
            rule={
                "if_after": "end_week 1"
            }
        )

        # consider_exceptions not specified
        result = utils.get_flow_rules(
            flow_desc, constants.flow_rule_kind.start,
            self.student_participation,
            self.flow_id,
            now(),
            default_rules_desc=default_rules_desc
        )

        self.assertNotEqual(result, default_rules_desc)
        self.assertEqual(len(result), len(exist_start_rule) + 1)

    def test_consider_exist_exceptions(self):

        # use real rules
        flow_desc = self.get_hacked_flow_desc()

        default_rules_desc = [mock.MagicMock(), mock.MagicMock()]

        # creating 2 rules without expiration
        factories.FlowRuleExceptionFactory(
            flow_id=self.flow_id,
            participation=self.student_participation,
            kind=constants.flow_rule_kind.start,
            creation_time=now() - timedelta(days=1),
            rule={
                "if_after": "end_week 1"
            }
        )

        factories.FlowRuleExceptionFactory(
            flow_id=self.flow_id,
            participation=self.student_participation,
            kind=constants.flow_rule_kind.start,
            rule={
                "if_before": "end_week 2"
            },
            creation_time=now() - timedelta(minutes=3),
        )

        result = utils.get_flow_rules(
            flow_desc, constants.flow_rule_kind.start,
            self.student_participation,
            self.flow_id,
            now(),
            consider_exceptions=True,
            default_rules_desc=default_rules_desc
        )

        exist_start_rule = flow_desc.rules.start

        self.assertNotEqual(result, default_rules_desc)
        self.assertEqual(len(result), len(exist_start_rule) + 2)
        self.assertEqual(exist_start_rule, result[2:])

        # last create ordered first
        self.assertEqual(result[0].if_before, "end_week 2")

    def test_consider_exist_exceptions_rule_expiration(self):

        # use real rules
        flow_desc = self.get_hacked_flow_desc()
        exist_start_rule = flow_desc.rules.start

        default_rules_desc = [mock.MagicMock(), mock.MagicMock()]

        # creating 2 rules without expiration
        factories.FlowRuleExceptionFactory(
            flow_id=self.flow_id,
            participation=self.student_participation,
            expiration=now() - timedelta(hours=12),
            kind=constants.flow_rule_kind.start,
            creation_time=now() - timedelta(days=1),
            rule={
                "if_after": "end_week 1"
            }
        )

        factories.FlowRuleExceptionFactory(
            flow_id=self.flow_id,
            participation=self.student_participation,
            expiration=now() + timedelta(hours=12),
            kind=constants.flow_rule_kind.start,
            rule={
                "if_before": "end_week 2"
            },
            creation_time=now() - timedelta(minutes=3),
        )

        # {{{ all exceptions not due
        now_datetime = now() - timedelta(days=3)

        result = utils.get_flow_rules(
            flow_desc, constants.flow_rule_kind.start,
            self.student_participation,
            self.flow_id,
            now_datetime,
            consider_exceptions=True,
            default_rules_desc=default_rules_desc
        )

        self.assertEqual(len(result), len(exist_start_rule) + 2)
        self.assertEqual(exist_start_rule, result[2:])

        # last create ordered first
        self.assertEqual(result[0].if_before, "end_week 2")
        # }}}

        # {{{ one exception expired
        now_datetime = now()

        result = utils.get_flow_rules(
            flow_desc, constants.flow_rule_kind.start,
            self.student_participation,
            self.flow_id,
            now_datetime,
            consider_exceptions=True,
            default_rules_desc=default_rules_desc
        )

        self.assertEqual(len(result), len(exist_start_rule) + 1)
        self.assertEqual(exist_start_rule, result[1:])

        # last create ordered first
        self.assertEqual(result[0].if_before, "end_week 2")
        # }}}

        # {{{ all exceptions expired
        now_datetime = now() + timedelta(days=5)

        result = utils.get_flow_rules(
            flow_desc, constants.flow_rule_kind.start,
            self.student_participation,
            self.flow_id,
            now_datetime,
            consider_exceptions=True,
            default_rules_desc=default_rules_desc
        )

        self.assertEqual(len(result), len(exist_start_rule))
        self.assertEqual(exist_start_rule, result)

        # }}}


my_mock_event_time = mock.MagicMock()
my_test_event_1_time = now() - timedelta(days=2)
my_test_event_2_time = now()
my_test_event_3_time = now() + timedelta(days=1)


def parse_date_spec_get_rule_test_side_effect(
        course, datespec, vctx=None, location=None):
    if datespec == "my_mock_event_time":
        return my_mock_event_time
    if datespec == "my_test_event 1":
        return my_test_event_1_time
    if datespec == "my_test_event 2":
        return my_test_event_2_time
    if datespec == "my_test_event 3":
        return my_test_event_3_time
    return parse_date_spec(course, datespec, vctx, location)


class GetSessionRuleMixin(object):

    flow_id = QUIZ_FLOW_ID

    @property
    def call_func(self):
        raise NotImplementedError()

    def get_updated_kwargs(self, **extra_kwargs):
        kwargs = deepcopy(self.default_kwargs)
        kwargs.update(extra_kwargs)
        return kwargs

    @property
    def default_kwargs(self):
        raise NotImplementedError()

    @property
    def fallback_rule(self):
        raise NotImplementedError()

    def get_result(self, **extra_kwargs):
        raise NotImplementedError()

    def assertRuleEqual(self, rule, expected_rule):  # noqa
        self.assertIsInstance(rule, self.rule_klass)
        rule_dict = struct_to_dict(rule)

        if isinstance(expected_rule, dict):
            expected_rule_dict = expected_rule
        else:
            self.assertIsInstance(expected_rule, self.rule_klass)
            expected_rule_dict = struct_to_dict(expected_rule)

        self.assertDictEqual(rule_dict, expected_rule_dict)

    def setUp(self):
        super(GetSessionRuleMixin, self).setUp()

        fake_get_flow_rules = mock.patch("course.utils.get_flow_rules")
        self.mock_get_flow_rules = fake_get_flow_rules.start()
        self.addCleanup(fake_get_flow_rules.stop)

        fake_eval_generic_conditions = mock.patch(
            "course.utils._eval_generic_conditions")
        self.mock_eval_generic_conditions = fake_eval_generic_conditions.start()
        self.addCleanup(fake_eval_generic_conditions.stop)

        fake_eval_participation_tags_conditions = mock.patch(
            "course.utils._eval_participation_tags_conditions")
        self.mock_eval_participation_tags_conditions = (
            fake_eval_participation_tags_conditions.start())
        self.addCleanup(fake_eval_participation_tags_conditions.stop)

        fake_eval_generic_session_conditions = mock.patch(
            "course.utils._eval_generic_session_conditions")
        self.mock_eval_generic_session_conditions = (
            fake_eval_generic_session_conditions.start())
        self.addCleanup(fake_eval_generic_session_conditions.stop)

        fake_get_participation_role_identifiers = mock.patch(
            "course.enrollment.get_participation_role_identifiers")
        self.mock_get_participation_role_identifiers = (
            fake_get_participation_role_identifiers.start())
        self.mock_get_participation_role_identifiers.return_value = ["student"]
        self.addCleanup(fake_get_participation_role_identifiers.stop)

        fake_parse_date_spec = mock.patch("course.utils.parse_date_spec")
        self.mock_parse_date_spec = fake_parse_date_spec.start()
        self.mock_parse_date_spec.side_effect = (
            parse_date_spec_get_rule_test_side_effect)
        self.addCleanup(fake_parse_date_spec.stop)


class GetSessionStartRuleTest(GetSessionRuleMixin, SingleCourseTestMixin, TestCase):
    # test utils.get_session_start_rule
    call_func = utils.get_session_start_rule
    rule_klass = utils.FlowSessionStartRule

    fallback_rule = utils.FlowSessionStartRule(
            may_list_existing_sessions=False,
            may_start_new_session=False)

    @property
    def default_kwargs(self):
        return {
            "course": self.course,
            "participation": self.student_participation,
            "flow_id": self.flow_id,
            "flow_desc": mock.MagicMock(),
            "now_datetime": now(),
            "facilities": None,
            "for_rollover": False,
            "login_exam_ticket": None,
        }

    def get_result(self, **extra_kwargs):
        kwargs = self.get_updated_kwargs(**extra_kwargs)
        return utils.get_session_start_rule(**kwargs)

    def get_default_rule(self, **kwargs):
        defaults = {
            "tag_session": None,
            "may_start_new_session": True,
            "may_list_existing_sessions": True,
            "default_expiration_mode": None,
        }
        defaults.update(kwargs)
        return utils.FlowSessionStartRule(**defaults)

    def test_no_rules(self):
        self.mock_get_flow_rules.return_value = []
        result = self.get_result()
        self.assertRuleEqual(self.fallback_rule, result)

        # make sure get_flow_rules is called with expected default_rules_desc
        self.assertEqual(self.mock_get_flow_rules.call_count, 1)
        self.assertIn("default_rules_desc", self.mock_get_flow_rules.call_args[1])

        default_rules_desc = (
            self.mock_get_flow_rules.call_args[1]["default_rules_desc"])
        self.assertTrue(default_rules_desc[0].may_start_new_session)
        self.assertFalse(default_rules_desc[0].may_list_existing_sessions)

    def test_not_passing_eval_generic_conditions(self):
        self.mock_get_flow_rules.return_value = [mock.MagicMock()]
        self.mock_eval_generic_conditions.return_value = False

        fake_login_exam_ticket = mock.MagicMock()
        result = self.get_result(login_exam_ticket=fake_login_exam_ticket)
        self.assertRuleEqual(self.fallback_rule, result)

        # make sure _eval_generic_conditions is called with expected
        # login_exam_ticket
        self.assertEqual(self.mock_eval_generic_conditions.call_count, 1)
        self.assertIn("login_exam_ticket",
                      self.mock_eval_generic_conditions.call_args[1])

        self.assertEqual(
            self.mock_eval_generic_conditions.call_args[1]["login_exam_ticket"],
            fake_login_exam_ticket
        )

    def test_not_passing_eval_participation_tags_conditions(self):
        self.mock_get_flow_rules.return_value = [mock.MagicMock()]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = False
        result = self.get_result()
        self.assertRuleEqual(self.fallback_rule, result)

    def test_not_passing_not_for_rollover_and_if_in_facility(self):
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({"if_in_facility": "f1"})]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result(facilities=frozenset(["f2"]))
        self.assertRuleEqual(self.fallback_rule, result)

    def test_not_passing_not_for_rollover_and_if_has_in_progress_session(self):
        factories.FlowSessionFactory(
            participation=self.student_participation, flow_id=self.flow_id)
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({"if_in_facility": "f1",
                            "if_has_in_progress_session": 2})]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result(facilities=frozenset(["f1", "f2"]))
        self.assertRuleEqual(self.fallback_rule, result)

    def test_not_passing_not_for_rollover_and_if_has_session_tagged(self):
        factories.FlowSessionFactory(
            participation=self.student_participation, flow_id=self.flow_id,
            in_progress=True)
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({"if_has_in_progress_session": 1,
                            "if_has_session_tagged": "atag1"})]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result()
        self.assertRuleEqual(self.fallback_rule, result)

    def test_not_passing_not_for_rollover_and_if_has_fewer_sessions_than(self):
        factories.FlowSessionFactory(
            participation=self.student_participation, flow_id=self.flow_id,
            access_rules_tag="atag1"
        )
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({"if_has_session_tagged": "atag1",
                            "if_has_fewer_sessions_than": 1})]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result()
        self.assertRuleEqual(self.fallback_rule, result)

    def test_not_passing_not_for_rollover_and_if_has_fewer_tagged_sessions_than(self):  # noqa
        factories.FlowSessionFactory.create_batch(size=2,
            participation=self.student_participation, flow_id=self.flow_id,
            access_rules_tag="atag1")
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({"if_has_fewer_sessions_than": 3,
                            "if_has_fewer_tagged_sessions_than": 1})]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result()
        self.assertRuleEqual(self.fallback_rule, result)

    def test_passing_not_for_rollover_and_if_has_fewer_tagged_sessions_than(self):  # noqa
        factories.FlowSessionFactory.create_batch(size=2,
            participation=self.student_participation, flow_id=self.flow_id,
            access_rules_tag="atag1")
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({"if_has_fewer_tagged_sessions_than": 3})]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result()
        self.assertRuleEqual(
            result,
            {"tag_session": None,
            "may_start_new_session": True,
            "may_list_existing_sessions": True,
            "default_expiration_mode": None}
        )

    def test_passing_not_for_rollover(self):
        factories.FlowSessionFactory.create_batch(size=2,
            participation=self.student_participation, flow_id=self.flow_id)
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({})]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result()
        self.assertRuleEqual(
            result,
            {"tag_session": None,
            "may_start_new_session": True,
            "may_list_existing_sessions": True,
            "default_expiration_mode": None}
        )

    def test_passing_for_rollover(self):
        factories.FlowSessionFactory.create_batch(size=2,
            participation=self.student_participation, flow_id=self.flow_id)
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({})]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result(for_rollover=True)
        self.assertRuleEqual(
            result,
            {"tag_session": None,
            "may_start_new_session": True,
            "may_list_existing_sessions": True,
            "default_expiration_mode": None}
        )

    def test_get_expected_rule(self):
        tag_session = mock.MagicMock()
        default_expiration_mode = mock.MagicMock()
        may_start_new_session = mock.MagicMock()
        may_list_existing_sessions = mock.MagicMock()
        self.mock_get_flow_rules.return_value = [
            dict_to_struct(
                {"tag_session": tag_session,
                 "default_expiration_mode": default_expiration_mode,
                 "may_start_new_session": may_start_new_session,
                 "may_list_existing_sessions": may_list_existing_sessions
                 })]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True

        # simplified
        result = self.get_result(for_rollover=True)
        self.assertRuleEqual(
            result,
            {"tag_session": tag_session,
             "may_start_new_session": may_start_new_session,
             "may_list_existing_sessions": may_list_existing_sessions,
             "default_expiration_mode": default_expiration_mode}
        )


class GetSessionAccessRuleTest(GetSessionRuleMixin, SingleCourseTestMixin, TestCase):
    # test utils.get_session_access_rule
    call_func = utils.get_session_access_rule
    rule_klass = utils.FlowSessionAccessRule

    fallback_rule = utils.FlowSessionAccessRule(permissions=frozenset())
    default_permissions = [fperm.view]

    @property
    def default_kwargs(self):
        return {
            "session": self.fs1,
            "flow_desc": mock.MagicMock(),
            "now_datetime": self.now,
            "facilities": None,
            "login_exam_ticket": None,
        }

    @classmethod
    def setUpTestData(cls):  # noqa
        super(GetSessionAccessRuleTest, cls).setUpTestData()

        cls.now = now() - timedelta(days=1)

        start_time = cls.now - timedelta(minutes=60)

        cls.ta_participation.time_factor = 1.1
        cls.ta_participation.save()

        cls.fs1 = factories.FlowSessionFactory(
            participation=cls.student_participation, in_progress=False,
            expiration_mode=constants.flow_session_expiration_mode.end,
            start_time=start_time
        )
        cls.fs2 = factories.FlowSessionFactory(
            participation=cls.ta_participation, in_progress=True,
            expiration_mode=constants.flow_session_expiration_mode.roll_over,
            start_time=start_time
        )
        cls.fs3 = factories.FlowSessionFactory(
            course=cls.course,
            participation=None, in_progress=True, user=None,
            expiration_mode=constants.flow_session_expiration_mode.roll_over,
            start_time=start_time
        )

    def get_result(self, **extra_kwargs):
        kwargs = self.get_updated_kwargs(**extra_kwargs)
        return utils.get_session_access_rule(**kwargs)

    def get_default_rule(self, **kwargs):
        defaults = {
            "permissions": self.default_permissions[:],
            "message": None,
        }
        defaults.update(kwargs)
        return utils.FlowSessionAccessRule(**defaults)

    def test_no_rules(self):
        self.mock_get_flow_rules.return_value = []
        result = self.get_result()
        self.assertRuleEqual(self.fallback_rule, result)

        # make sure get_flow_rules is called with expected default_rules_desc
        self.assertEqual(self.mock_get_flow_rules.call_count, 1)
        self.assertIn("default_rules_desc", self.mock_get_flow_rules.call_args[1])

        default_rules_desc = (
            self.mock_get_flow_rules.call_args[1]["default_rules_desc"])
        self.assertEqual(
            default_rules_desc[0].permissions, self.default_permissions)

    def test_not_passing_eval_generic_conditions(self):
        self.mock_get_flow_rules.return_value = [mock.MagicMock()]
        self.mock_eval_generic_conditions.return_value = False

        fake_login_exam_ticket = mock.MagicMock()
        result = self.get_result(login_exam_ticket=fake_login_exam_ticket)
        self.assertRuleEqual(self.fallback_rule, result)

        # make sure _eval_generic_conditions is called with expected
        # login_exam_ticket
        self.assertEqual(self.mock_eval_generic_conditions.call_count, 1)
        self.assertIn("login_exam_ticket",
                      self.mock_eval_generic_conditions.call_args[1])

        self.assertEqual(
            self.mock_eval_generic_conditions.call_args[1]["login_exam_ticket"],
            fake_login_exam_ticket
        )

    def test_not_passing_eval_participation_tags_conditions(self):
        self.mock_get_flow_rules.return_value = [mock.MagicMock()]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = False
        result = self.get_result()
        self.assertRuleEqual(self.fallback_rule, result)

    def test_not_passing_eval_generic_session_conditions(self):
        self.mock_get_flow_rules.return_value = [mock.MagicMock()]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        self.mock_eval_generic_session_conditions.return_value = False
        result = self.get_result()
        self.assertRuleEqual(self.fallback_rule, result)

    def test_not_passing_if_in_facility(self):
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({"if_in_facility": "f1",
                            "permissions": mock.MagicMock()
                            })]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result(facilities=frozenset(["f2"]))
        self.assertRuleEqual(self.fallback_rule, result)

    def test_not_passing_if_in_progress(self):
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({"if_in_facility": "f1",
                            "if_in_progress": True,
                            "permissions": mock.MagicMock()
                            })]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result(facilities=frozenset(["f1", "f2"]))
        self.assertRuleEqual(self.fallback_rule, result)

    def test_not_passing_if_expiration_mode(self):
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({"if_in_progress": True,
                            "if_expiration_mode":
                                constants.flow_session_expiration_mode.end,
                            "permissions": mock.MagicMock()
                            })]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result(session=self.fs2)
        self.assertRuleEqual(self.fallback_rule, result)

    def test_not_passing_if_session_duration_shorter_than_minutes(self):
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({"if_expiration_mode":
                                constants.flow_session_expiration_mode.end,
                            "if_session_duration_shorter_than_minutes": 59,
                            "permissions": mock.MagicMock()
                            })]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result()
        self.assertRuleEqual(self.fallback_rule, result)

    def test_not_passing_if_session_duration_shorter_than_minutes_anonymous(self):
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({"if_session_duration_shorter_than_minutes": 59,
                            "permissions": mock.MagicMock()
                            })]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result(session=self.fs3)
        self.assertRuleEqual(self.fallback_rule, result)

    def test_passed_session_duration_shorter_than_minutes(self):
        faked_permissions = frozenset([mock.MagicMock()])
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({"if_session_duration_shorter_than_minutes": 59,
                            "permissions": faked_permissions})]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result(session=self.fs2)
        self.assertRuleEqual(
            result,
            {"message": None,
             "permissions": faked_permissions})

    def test_with_above_not_considiered(self):
        faked_permissions = frozenset([mock.MagicMock()])
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({"permissions": faked_permissions})]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result(session=self.fs2)
        self.assertRuleEqual(
            result,
            {"message": None,
             "permissions": faked_permissions})

    def test_deal_with_deprecated_modify(self):
        faked_permission = mock.MagicMock()
        self.mock_get_flow_rules.return_value = [
            dict_to_struct(
                {"permissions": frozenset(["modify", faked_permission])})]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result(session=self.fs2)

        self.assertRuleEqual(
            result,
            {"message": None,
             "permissions": frozenset(
                 [fperm.submit_answer, fperm.end_session, faked_permission])})

    def test_deal_with_deprecated_see_answer(self):
        faked_permission = mock.MagicMock()
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({
                "permissions": frozenset([
                    "see_answer", faked_permission])})]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result(session=self.fs2)
        self.assertRuleEqual(
            result,
            {"message": None,
             "permissions": frozenset(
                 [faked_permission, fperm.see_answer_after_submission])})

    def test_removing_access_permissions_for_non_in_progress_sessions(self):
        faked_permission = mock.MagicMock()
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({
                "permissions": frozenset([
                    "modify", faked_permission])})]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result()
        self.assertRuleEqual(
            result,
            {"message": None,
             "permissions": frozenset(
                 [faked_permission])})

        self.mock_get_flow_rules.return_value = [
            dict_to_struct({
                "permissions": frozenset([
                    "end_session", faked_permission])})]
        self.mock_eval_generic_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = True
        result = self.get_result()
        self.assertRuleEqual(
            result,
            {"message": None,
             "permissions": frozenset(
                 [faked_permission])})


class GetSessionGradingRuleTest(GetSessionRuleMixin,
                                SingleCourseTestMixin, TestCase):
    # test utils.get_session_grading_rule
    call_func = utils.get_session_grading_rule
    rule_klass = utils.FlowSessionGradingRule

    no_g_rule_exception_msg = (
        "grading rule determination was unable to find a grading rule")

    fallback_rule = None
    default_rule = {"generates_grade": False}

    @property
    def default_kwargs(self):
        return {
            "session": self.fs1,
            "flow_desc": mock.MagicMock(),
            "now_datetime": self.now,
        }

    @classmethod
    def setUpTestData(cls):  # noqa
        super(GetSessionGradingRuleTest, cls).setUpTestData()

        cls.now = now() - timedelta(days=1)

        start_time = cls.now - timedelta(minutes=60)

        cls.fs1 = factories.FlowSessionFactory(
            participation=cls.student_participation, in_progress=False,
            expiration_mode=constants.flow_session_expiration_mode.end,
            start_time=start_time, completion_time=cls.now
        )
        cls.fs2 = factories.FlowSessionFactory(
            participation=cls.ta_participation, in_progress=True,
            expiration_mode=constants.flow_session_expiration_mode.roll_over,
            start_time=start_time
        )
        cls.fs3 = factories.FlowSessionFactory(
            course=cls.course,
            participation=None, in_progress=True, user=None,
            expiration_mode=constants.flow_session_expiration_mode.roll_over,
            start_time=start_time, completion_time=cls.now
        )

    def get_result(self, **extra_kwargs):
        kwargs = self.get_updated_kwargs(**extra_kwargs)
        return utils.get_session_grading_rule(**kwargs)

    def get_default_rule(self, **kwargs):
        defaults = {
            "grade_identifier": "la_quiz",
            "grade_aggregation_strategy":
                constants.grade_aggregation_strategy.use_latest,
            "due": None,
            "generates_grade": True,
            "description": None,
            "credit_percent": 100,
            "use_last_activity_as_completion_time": False,
            "max_points": None,
            "max_points_enforced_cap": None,
            "bonus_points": 0
        }
        defaults.update(kwargs)
        return utils.FlowSessionGradingRule(**defaults)

    def test_no_rules(self):
        self.mock_get_flow_rules.return_value = []

        with self.assertRaises(RuntimeError) as cm:
            self.get_result()
        self.assertIn(self.no_g_rule_exception_msg, str(cm.exception))

        # make sure get_flow_rules is called with expected default_rules_desc
        self.assertEqual(self.mock_get_flow_rules.call_count, 1)
        self.assertIn("default_rules_desc", self.mock_get_flow_rules.call_args[1])

        default_rules_desc = (
            self.mock_get_flow_rules.call_args[1]["default_rules_desc"])
        self.assertFalse(default_rules_desc[0].generates_grade)

    def test_skip_if_has_role(self):
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({"if_has_role": ["instructor", "ta"]})]

        with self.assertRaises(RuntimeError) as cm:
            self.get_result()
        self.assertIn(self.no_g_rule_exception_msg, str(cm.exception))

    def test_passed_if_has_role(self):
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({"if_has_role": ["instructor", "ta"]}),
            dict_to_struct({"if_has_role": ["instructor", "ta", "student"]})]

        result = self.get_result(flow_desc=self.get_hacked_flow_desc())
        self.assertRuleEqual(result, self.get_default_rule())

    def test_not_passing_eval_generic_session_conditions(self):
        self.mock_get_flow_rules.return_value = [dict_to_struct({})]
        self.mock_eval_generic_session_conditions.return_value = False
        self.mock_eval_participation_tags_conditions.return_value = True
        with self.assertRaises(RuntimeError) as cm:
            self.get_result(flow_desc=self.get_hacked_flow_desc())
        self.assertIn(self.no_g_rule_exception_msg, str(cm.exception))

    def test_not_passing_eval_participation_tags_conditions(self):
        self.mock_get_flow_rules.return_value = [dict_to_struct({})]
        self.mock_eval_generic_session_conditions.return_value = True
        self.mock_eval_participation_tags_conditions.return_value = False
        with self.assertRaises(RuntimeError) as cm:
            self.get_result(flow_desc=self.get_hacked_flow_desc())
        self.assertIn(self.no_g_rule_exception_msg, str(cm.exception))

    def test_if_completed_before_skipped(self):
        self.mock_get_flow_rules.return_value = [dict_to_struct({
            "if_completed_before": "my_test_event 1"
        })]
        with self.assertRaises(RuntimeError) as cm:
            self.get_result(flow_desc=self.get_hacked_flow_desc())
        self.assertIn(self.no_g_rule_exception_msg, str(cm.exception))

    def test_if_completed_before_in_progress_session_skipped(self):
        self.mock_get_flow_rules.return_value = [dict_to_struct({
            "if_completed_before": "my_test_event 1"
        })]
        with self.assertRaises(RuntimeError) as cm:
            self.get_result(
                session=self.fs2,
                flow_desc=self.get_hacked_flow_desc())
        self.assertIn(self.no_g_rule_exception_msg, str(cm.exception))

    def test_if_completed_before_passed_not_using_last_activity(self):
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({"if_completed_before": "my_test_event 1"}),
            dict_to_struct({"if_completed_before": "my_test_event 2"}),
        ]
        result = self.get_result(flow_desc=self.get_hacked_flow_desc())
        self.assertRuleEqual(result, self.get_default_rule())

    def test_if_completed_before_using_last_activity_with_last_activity_none_skipped(self):  # noqa
        self.mock_get_flow_rules.return_value = [
            dict_to_struct(
                {"if_completed_before": "my_test_event 1",
                 "use_last_activity_as_completion_time": True
                 }),
        ]
        with self.assertRaises(RuntimeError) as cm:
            self.get_result(flow_desc=self.get_hacked_flow_desc())
        self.assertIn(self.no_g_rule_exception_msg, str(cm.exception))

    def test_if_completed_before_using_last_activity_exist_but_skipped(self):
        # create last_activity
        page_data = factories.FlowPageDataFactory(flow_session=self.fs1)
        factories.FlowPageVisitFactory(
            page_data=page_data,
            visit_time=my_test_event_1_time + timedelta(hours=1),
            answer={"answer": "hi"})

        self.mock_get_flow_rules.return_value = [
            dict_to_struct(
                {"if_completed_before": "my_test_event 1",
                 "use_last_activity_as_completion_time": True
                 }),
        ]
        with self.assertRaises(RuntimeError) as cm:
            self.get_result(flow_desc=self.get_hacked_flow_desc())
        self.assertIn(self.no_g_rule_exception_msg, str(cm.exception))

    def test_if_completed_before_using_last_activity_exist_passed(self):
        # create last_activity
        page_data = factories.FlowPageDataFactory(flow_session=self.fs1)
        factories.FlowPageVisitFactory(
            page_data=page_data,
            visit_time=my_test_event_1_time - timedelta(hours=1),
            answer={"answer": "hi"})

        self.mock_get_flow_rules.return_value = [
            dict_to_struct(
                {"if_completed_before": "my_test_event 1",
                 "use_last_activity_as_completion_time": True
                 }),
        ]
        result = self.get_result(flow_desc=self.get_hacked_flow_desc())
        self.assertRuleEqual(
            result, self.get_default_rule(
                use_last_activity_as_completion_time=True))

    def test_params_in_passed_to_result(self):
        # rule params
        mock_bonus_points = mock.MagicMock()
        mock_max_points = mock.MagicMock()
        mock_max_points_enforced_cap = mock.MagicMock()

        mock_generates_grade = mock.MagicMock()
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({
                "generates_grade": mock_generates_grade,
                "bonus_poinsts": mock_bonus_points,
                "max_points": mock_max_points,
                "max_points_enforced_cap": mock_max_points_enforced_cap,
                "due": "my_mock_event_time"
            })]

        # flow_desc_params
        mock_flow_desc_grade_identifier = mock.MagicMock()
        mock_flow_desc_grade_aggregation_strategy = mock.MagicMock()

        result = self.get_result(flow_desc=self.get_hacked_flow_desc(
            rules=dict_to_struct({
                "grade_identifier": mock_flow_desc_grade_identifier,
                "grade_aggregation_strategy":
                    mock_flow_desc_grade_aggregation_strategy})))

        self.assertRuleEqual(result, self.get_default_rule(
            max_points=mock_max_points,
            max_points_enforced_cap=mock_max_points_enforced_cap,
            generates_grade=mock_generates_grade,
            grade_identifier=mock_flow_desc_grade_identifier,
            grade_aggregation_strategy=mock_flow_desc_grade_aggregation_strategy,
            due=my_mock_event_time
        ))

    def test_no_flow_desc_rule(self):
        self.mock_get_flow_rules.return_value = [
            dict_to_struct({})]

        result = self.get_result(
            flow_desc=self.get_hacked_flow_desc(del_rules=True))
        self.assertRuleEqual(result, self.get_default_rule(
            grade_identifier=None,
            grade_aggregation_strategy=None,
            bonus_points=0,
            max_points=None,
            max_points_enforced_cap=None,
        ))


class CoursePageContextTest(SingleCourseTestMixin, TestCase):
    # test utils.CoursePageContext (for cases not covered by other tests)

    def setUp(self):
        super(CoursePageContextTest, self).setUp()
        rf = RequestFactory()
        self.request = rf.get(self.get_course_page_url())

        fake_add_message = mock.patch('django.contrib.messages.add_message')
        self.mock_add_message = fake_add_message.start()
        self.addCleanup(fake_add_message.stop)

    def test_preview_commit_sha(self):
        # commit_sha of https://github.com/inducer/relate-sample/pull/11
        commit_sha = "ec41a2de73a99e6022060518cb5c5c162b88cdf5"
        self.ta_participation.preview_git_commit_sha = commit_sha
        self.ta_participation.save()
        self.request.user = self.ta_participation.user
        pctx = utils.CoursePageContext(self.request, self.course.identifier)

        self.assertEqual(
            pctx.course_commit_sha,
            commit_sha.encode())

        self.assertEqual(self.mock_add_message.call_count, 0)

    def test_invalid_preview_commit_sha(self):
        commit_sha = "invalid_commit_sha"
        self.ta_participation.preview_git_commit_sha = commit_sha
        self.ta_participation.save()
        self.request.user = self.ta_participation.user
        pctx = utils.CoursePageContext(self.request, self.course.identifier)

        self.assertEqual(
            pctx.course_commit_sha,
            self.course.active_git_commit_sha.encode())

        self.assertEqual(self.mock_add_message.call_count, 1)
        expected_error_msg = (
                "Preview revision '%s' does not exist--"
                "showing active course content instead." % commit_sha)

        self.assertIn(expected_error_msg, self.mock_add_message.call_args[0])

    def test_role_identifiers(self):
        self.request.user = self.ta_participation.user
        pctx = utils.CoursePageContext(self.request, self.course.identifier)
        self.assertEqual(pctx.role_identifiers(), ['ta'])

        with mock.patch(
                "course.enrollment.get_participation_role_identifiers"
        ) as mock_get_prole_identifiers:
            self.assertEqual(pctx.role_identifiers(), ['ta'])

            # This is to ensure _role_identifiers_cache is working
            self.assertEqual(mock_get_prole_identifiers.call_count, 0)

    def test_error_when_nestedly_use_pctx_as_context_manager(self):
        self.request.user = self.ta_participation.user
        pctx = utils.CoursePageContext(self.request, self.course.identifier)

        with self.assertRaises(RuntimeError) as cm:
            with pctx:
                with pctx:
                    pass

        expected_error_msg = (
            "Nested use of 'course_view' as context manager "
            "is not allowed.")

        self.assertIn(expected_error_msg, str(cm.exception))


class FlowContextTest(unittest.TestCase):
    # test utils.FlowContext (for cases not covered by other tests)
    def test_404(self):
        repo = mock.MagicMock()
        course = mock.MagicMock()
        flow_id = "some_id"
        participation = mock.MagicMock()

        with mock.patch(
                "course.utils.get_course_commit_sha"), mock.patch(
                "course.utils.get_flow_desc") as mock_get_flow_desc:
            from django.core.exceptions import ObjectDoesNotExist
            mock_get_flow_desc.side_effect = ObjectDoesNotExist

            from django import http
            with self.assertRaises(http.Http404):
                utils.FlowContext(repo, course, flow_id, participation)


class ParticipationPermissionWrapperTest(SingleCourseTestMixin, TestCase):
    # test utils.ParticipationPermissionWrapper (for cases not covered
    # by other tests)

    def setUp(self):
        super(ParticipationPermissionWrapperTest, self).setUp()
        rf = RequestFactory()
        request = rf.get(self.get_course_page_url())
        request.user = self.ta_participation.user
        self.pctx = utils.CoursePageContext(request, self.course.identifier)

    def test_get_invalid_permission(self):
        ppwraper = utils.ParticipationPermissionWrapper(self.pctx)
        invalid_perm = "invalid_perm"
        with self.assertRaises(ValueError) as cm:
            ppwraper[invalid_perm]

        expected_error_msg = (
            "permission name '%s' not valid" % invalid_perm)

        self.assertIn(expected_error_msg, str(cm.exception))

    def test_not_iterale(self):
        ppwraper = utils.ParticipationPermissionWrapper(self.pctx)
        with self.assertRaises(TypeError) as cm:
            iter(ppwraper)

        expected_error_msg = (
            "ParticipationPermissionWrapper is not iterable.")

        self.assertIn(expected_error_msg, str(cm.exception))


class GetCodemirrorWidgetTest(unittest.TestCase):
    # test utils.get_codemirror_widget (for cases not covered by other tests)
    def setUp(self):
        self.language_mode = "python"
        fake_code_mirror_textarea = mock.patch("codemirror.CodeMirrorTextarea")
        self.mock_code_mirror_textarea = fake_code_mirror_textarea.start()
        self.addCleanup(fake_code_mirror_textarea.stop)

    def test_interaction_mode_vim(self):
        interaction_mode = "vim"
        utils.get_codemirror_widget(
            self.language_mode, interaction_mode=interaction_mode)

        addon_js = self.mock_code_mirror_textarea.call_args[1]["addon_js"]
        self.assertIn("../keymap/vim", addon_js)

        config = self.mock_code_mirror_textarea.call_args[1]["config"]
        self.assertEqual(config["vimMode"], True)

    def test_interaction_mode_emacs(self):
        interaction_mode = "emacs"
        utils.get_codemirror_widget(
            self.language_mode, interaction_mode=interaction_mode)

        addon_js = self.mock_code_mirror_textarea.call_args[1]["addon_js"]
        self.assertIn("../keymap/emacs", addon_js)

        config = self.mock_code_mirror_textarea.call_args[1]["config"]
        self.assertEqual(config["keyMap"], "emacs")

    def test_interaction_mode_sublime(self):
        interaction_mode = "sublime"
        utils.get_codemirror_widget(
            self.language_mode, interaction_mode=interaction_mode)

        addon_js = self.mock_code_mirror_textarea.call_args[1]["addon_js"]
        self.assertIn("../keymap/sublime", addon_js)

        config = self.mock_code_mirror_textarea.call_args[1]["config"]
        self.assertEqual(config["keyMap"], "sublime")

    def test_interaction_mode_other(self):
        # just ensure no errors
        interaction_mode = "other"
        utils.get_codemirror_widget(
            self.language_mode, interaction_mode=interaction_mode)

    def test_update_config(self):
        interaction_mode = "vim"
        utils.get_codemirror_widget(
            self.language_mode, interaction_mode=interaction_mode,
            config={"foo": "bar"})

        addon_js = self.mock_code_mirror_textarea.call_args[1]["addon_js"]
        self.assertIn("../keymap/vim", addon_js)

        config = self.mock_code_mirror_textarea.call_args[1]["config"]
        self.assertEqual(config["vimMode"], True)
        self.assertEqual(config["foo"], "bar")


class WillUseMaskedProfileForEmailTest(SingleCourseTestMixin, TestCase):
    # test utils.will_use_masked_profile_for_email
    def test_no_recipient_email(self):
        self.assertFalse(utils.will_use_masked_profile_for_email(None))
        self.assertFalse(utils.will_use_masked_profile_for_email([]))

    def test_check_single_email(self):
        self.assertFalse(
            utils.will_use_masked_profile_for_email(
                "foo@bar.com"))
        self.assertFalse(
            utils.will_use_masked_profile_for_email(
                ["foo@bar.com"]))

    def test_any(self):
        from course.models import ParticipationPermission
        from course.constants import participation_permission as pperm

        pp = ParticipationPermission(
            participation=self.ta_participation,
            permission=pperm.view_participant_masked_profile)
        pp.save()
        self.assertTrue(
            utils.will_use_masked_profile_for_email(
                self.ta_participation.user.email))

        self.assertFalse(
            utils.will_use_masked_profile_for_email(
                self.instructor_participation.user.email))

        # any participation in the list have that permission, then True
        self.assertTrue(
            utils.will_use_masked_profile_for_email(
                [self.ta_participation.user.email,
                 self.instructor_participation.user.email]))


class GetFacilitiesConfigTest(unittest.TestCase):
    # utils.get_facilities_config (for cases not covered by other tests)
    def test_none(self):
        with override_settings():
            del settings.RELATE_FACILITIES
            self.assertIsNone(utils.get_facilities_config())

        with override_settings(RELATE_FACILITIES=None):
            self.assertIsNone(utils.get_facilities_config())

# vim: foldmethod=marker
