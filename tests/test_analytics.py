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

import unittest
from django.test import TestCase
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse

from relate.utils import dict_to_struct

from course.models import FlowSession
from course import analytics

from tests.base_test_mixins import (  # noqa
    SingleCourseTestMixin, CoursesTestMixinBase, SingleCoursePageTestMixin,
    SingleCourseQuizPageTestMixin, MockAddMessageMixing, HackRepoMixin)
from tests.utils import mock, may_run_expensive_tests, SKIP_EXPENSIVE_TESTS_REASON
from tests import factories


@unittest.skipUnless(may_run_expensive_tests(), SKIP_EXPENSIVE_TESTS_REASON)
class FlowListTest(SingleCourseTestMixin, TestCase):
    """test analytics.flow_list"""
    def get_flow_list_url(self, course_identifier=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        kwargs = {"course_identifier": course_identifier}
        return reverse("relate-flow_list", kwargs=kwargs)

    def get_flow_list_view(self, course_identifier=None,
                           force_login_instructor=True):
        course_identifier = course_identifier or self.get_default_course_identifier()
        if not force_login_instructor:
            user = self.get_logged_in_user()
        else:
            user = self.instructor_participation.user

        with self.temporarily_switch_to_user(user):
            return self.c.get(
                self.get_flow_list_url(course_identifier))

    def test_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_flow_list_view(force_login_instructor=False)
            self.assertEqual(resp.status_code, 302)

    def test_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_flow_list_view(force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

    def test_result(self):
        flow_ids = ["c", "b", "a"]

        for flow_id in flow_ids:
            factories.FlowSessionFactory.create_batch(
                size=2,
                participation=self.student_participation,
                flow_id=flow_id)

        another_course = factories.CourseFactory(identifier="another-course")
        another_participation = factories.ParticipationFactory(course=another_course)

        # This make sure other courses' flow_id won't be included
        factories.FlowSessionFactory(participation=another_participation,
                                     flow_id="d")

        resp = self.get_flow_list_view()
        self.assertEqual(resp.status_code, 200)

        self.assertResponseContextEqual(resp, "flow_ids", sorted(flow_ids))


class HistogramTest(CoursesTestMixinBase, TestCase):
    """test analytics.Histogram (for cases not covered by other tests)"""
    def test_add_data_point_num_max_value(self):
        """self.num_max_value is not None and value > self.num_max_value"""
        his = analytics.Histogram(num_max_value=100)
        his.add_data_point(value=110, weight=1.1)
        self.assertEqual(his.string_weights["(value greater than max)"], 1.1)

    def test_add_data_point_num_min_value(self):
        """self.num_min_value is not None and value < self.num_min_value"""
        his = analytics.Histogram(num_min_value=60)
        his.add_data_point(value=50, weight=1.2)
        self.assertEqual(his.string_weights["(value smaller than min)"], 1.2)

    def test_get_bin_info_list_num_bin_starts_is_not_none(self):
        # just make sure it works
        his = analytics.Histogram(num_bin_starts=[2])
        his.get_bin_info_list()

    def test_get_bin_info_nothing_configured(self):
        # just make sure it works
        his = analytics.Histogram()
        his.get_bin_info_list()
        his.html()
        self.assertTemplateUsed("course/histogram-wide.html")

    def test_non_wide_html_template_render(self):
        his = analytics.Histogram()
        faked_get_bin_info_list = [analytics.BinInfo(
            title="foo"*30, raw_weight="bar", percentage=100)]
        with mock.patch(
                "course.analytics.Histogram.get_bin_info_list"
        ) as mock_get_bin_info_list:
            mock_get_bin_info_list.return_value = faked_get_bin_info_list

            his.html()
            self.assertTemplateUsed("course/histogram.html")


@unittest.skipUnless(may_run_expensive_tests(), SKIP_EXPENSIVE_TESTS_REASON)
class IsFlowMultipleSubmitTest(SingleCourseTestMixin, TestCase):
    """test course.analytics.is_flow_multiple_submit"""
    def test_flow_desc_has_no_rule(self):
        flow_desc = self.get_hacked_flow_desc(del_rules=True)
        self.assertFalse(analytics.is_flow_multiple_submit(flow_desc))

    def test_flow_desc_access_rule_has_no_change_answer_perm(self):
        flow_desc_dict = self.get_hacked_flow_desc(as_dict=True)
        rules = flow_desc_dict["rules"]
        rules.access = [dict_to_struct(
            {"permissions": ["submit_answer"]})]
        flow_desc = dict_to_struct(flow_desc_dict)
        self.assertFalse(analytics.is_flow_multiple_submit(flow_desc))

    def test_flow_desc_access_rule_has_change_answer_perm(self):
        flow_desc_dict = self.get_hacked_flow_desc(as_dict=True)
        rules = flow_desc_dict["rules"]
        rules.access = [dict_to_struct(
            {"permissions": ["submit_answer", "change_answer"]})]
        flow_desc = dict_to_struct(flow_desc_dict)
        self.assertTrue(analytics.is_flow_multiple_submit(flow_desc))


@unittest.skipUnless(may_run_expensive_tests(), SKIP_EXPENSIVE_TESTS_REASON)
class IsPageMultipleSubmitTest(SingleCoursePageTestMixin, HackRepoMixin, TestCase):
    """test course.analytics.is_page_multiple_submit"""
    @classmethod
    def setUpTestData(cls):  # noqa
        super(IsPageMultipleSubmitTest, cls).setUpTestData()
        cls.course.active_git_commit_sha = "my_fake_commit_sha_for_page_analytics"
        cls.course.save()

        # cache the page_descs
        cls.start_flow(cls.flow_id)
        cls.flow_desc = cls.get_hacked_flow_desc()

    def setUp(self):
        super(IsPageMultipleSubmitTest, self).setUp()
        faked_is_flow_multiple_submit = \
            mock.patch("course.analytics.is_flow_multiple_submit")
        self.mock_is_flow_multiple_submit = faked_is_flow_multiple_submit.start()
        self.mock_is_flow_multiple_submit.return_value = False
        self.addCleanup(faked_is_flow_multiple_submit.stop)

    def get_page_desc_by_page_id(self, page_id):
        for group_desc in self.flow_desc.groups:
            for page_desc in group_desc.pages:
                if page_desc.id == page_id:
                    return page_desc

    def test_page_has_no_access_rules(self):
        page_id = "fear"
        page_desc = self.get_page_desc_by_page_id(page_id)

        self.assertFalse(analytics.is_page_multiple_submit(
            self.flow_desc, page_desc))

        self.mock_is_flow_multiple_submit.return_value = True
        self.assertTrue(analytics.is_page_multiple_submit(
            self.flow_desc, page_desc))

    def test_page_access_rules_remove_permissions_not_remove_change_permission(self):
        page_id = "half"
        page_desc = self.get_page_desc_by_page_id(page_id)

        self.mock_is_flow_multiple_submit.return_value = True
        self.assertTrue(analytics.is_page_multiple_submit(
            self.flow_desc, page_desc))

    def test_page_access_rules_remove_permissions_removed_change_permission(self):
        page_id = "ice_cream_toppings"
        page_desc = self.get_page_desc_by_page_id(page_id)

        self.mock_is_flow_multiple_submit.return_value = True
        self.assertFalse(analytics.is_page_multiple_submit(
            self.flow_desc, page_desc))

    def test_page_access_rules_add_permissions_not_add_change_permission(self):
        page_id = "lsq"
        page_desc = self.get_page_desc_by_page_id(page_id)
        self.assertFalse(analytics.is_page_multiple_submit(
            self.flow_desc, page_desc))

    def test_page_access_rules_add_permissions_added_change_permission(self):
        page_id = "krylov"
        page_desc = self.get_page_desc_by_page_id(page_id)
        self.assertTrue(analytics.is_page_multiple_submit(
            self.flow_desc, page_desc))

    def test_page_access_rules_neither_add_nor_remove_permission(self):
        page_id = "age_group"
        page_desc = self.get_page_desc_by_page_id(page_id)
        self.assertFalse(analytics.is_page_multiple_submit(
            self.flow_desc, page_desc))

        self.mock_is_flow_multiple_submit.return_value = True
        page_desc = self.get_page_desc_by_page_id(page_id)
        self.assertTrue(analytics.is_page_multiple_submit(
            self.flow_desc, page_desc))


@unittest.skipUnless(may_run_expensive_tests(), SKIP_EXPENSIVE_TESTS_REASON)
class PageAnalyticsTest(SingleCourseTestMixin, TestCase):
    """test analytics.page_analytics, (for cases not covered by other tests)"""
    def test_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_flow_page_analytics(
                flow_id="blabla", group_id="foo", page_id="bar")
            self.assertEqual(resp.status_code, 302)

    def test_no_pperm(self):
        # student user is logged in
        resp = self.get_flow_page_analytics(
            flow_id="blabla", group_id="foo", page_id="bar")
        self.assertEqual(resp.status_code, 403)


@unittest.skipUnless(may_run_expensive_tests(), SKIP_EXPENSIVE_TESTS_REASON)
class FlowAnalyticsTest(SingleCourseQuizPageTestMixin, HackRepoMixin,
                        MockAddMessageMixing, TestCase):
    """analytics.flow_analytics"""

    @classmethod
    def setUpTestData(cls):  # noqa
        super(FlowAnalyticsTest, cls).setUpTestData()
        cls.course.active_git_commit_sha = "my_fake_commit_sha_for_flow_analytics"
        cls.course.save()
        cls.start_flow(cls.flow_id)
        fs = FlowSession.objects.last()
        for page_ordinal in range(fs.page_count):
            cls.submit_page_answer_by_ordinal_and_test(
                page_ordinal=page_ordinal, do_grading=False, do_human_grade=False)
        cls.end_flow()

        # start another in-progress session with answers
        cls.start_flow(cls.flow_id)
        fs = FlowSession.objects.last()
        for page_ordinal in range(fs.page_count):
            cls.submit_page_answer_by_ordinal_and_test(
                page_ordinal=page_ordinal, do_grading=False, do_human_grade=False)

        # start another ended session with out answers
        cls.start_flow(cls.flow_id)
        cls.end_flow()

        # create another participation and with a flow session
        another_partcpt = factories.ParticipationFactory(course=cls.course)
        with cls.temporarily_switch_to_user(another_partcpt.user):
            cls.start_flow(cls.flow_id)
            cls.end_flow()

    def get_flow_analytics_url(self, flow_id, course_identifier,
                               restrict_to_first_attempt=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        kwargs = {
            "flow_id": flow_id,
            "course_identifier": course_identifier}
        result = reverse("relate-flow_analytics", kwargs=kwargs)
        if restrict_to_first_attempt:
            result += "?restrict_to_first_attempt=%s" % restrict_to_first_attempt
        return result

    def get_flow_analytics_view(self, flow_id, course_identifier=None,
                                restrict_to_first_attempt=None,
                                force_login_instructor=True):
        course_identifier = course_identifier or self.get_default_course_identifier()
        if not force_login_instructor:
            user = self.get_logged_in_user()
        else:
            user = self.instructor_participation.user

        with self.temporarily_switch_to_user(user):
            return self.c.get(
                self.get_flow_analytics_url(
                    flow_id, course_identifier=course_identifier,
                    restrict_to_first_attempt=restrict_to_first_attempt))

    def test_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_flow_analytics_view(
                flow_id="blabla", force_login_instructor=False)
            self.assertEqual(resp.status_code, 302)

    def test_no_pperm(self):
        # student user is logged in
        resp = self.get_flow_analytics_view(
            flow_id="blabla", force_login_instructor=False)
        self.assertEqual(resp.status_code, 403)

    def test_success(self):
        resp = self.get_flow_analytics_view(flow_id=self.flow_id)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "flow_identifier", self.flow_id)

        resp = self.get_flow_analytics_view(flow_id=self.flow_id,
                                            restrict_to_first_attempt=1)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "flow_identifier", self.flow_id)

    def test_success_check_func_call(self):
        with mock.patch(
                "course.analytics.make_grade_histogram"
        ) as mock_make_g_his, mock.patch(
            "course.analytics.make_page_answer_stats_list"
        ) as mock_make_stats_list, mock.patch(
            "course.analytics.make_time_histogram"
        ) as mock_make_t_his, mock.patch(
            "course.analytics.count_participants"
        ) as mock_count_particpt:
            resp = self.get_flow_analytics_view(flow_id=self.flow_id)
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(
                resp, "flow_identifier", self.flow_id)
            self.assertResponseContextEqual(resp, "participant_count", 2)
            self.assertResponseContextEqual(resp, "restrict_to_first_attempt", 0)

            self.assertEqual(mock_make_g_his.call_count, 1)
            self.assertEqual(mock_make_stats_list.call_count, 1)
            self.assertEqual(mock_make_t_his.call_count, 1)
            self.assertEqual(mock_count_particpt.call_count, 1)

    def test_success_test_restrict_to_first_attempt(self):
        with mock.patch(
                "course.analytics.make_grade_histogram"
        ) as mock_make_g_his, mock.patch(
            "course.analytics.make_page_answer_stats_list"
        ) as mock_make_stats_list, mock.patch(
            "course.analytics.make_time_histogram"
        ) as mock_make_t_his, mock.patch(
            "course.analytics.count_participants"
        ) as mock_count_particpt:
            resp = self.get_flow_analytics_view(flow_id=self.flow_id,
                                                restrict_to_first_attempt=1)
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(
                resp, "flow_identifier", self.flow_id)
            self.assertResponseContextEqual(resp, "participant_count", 2)

            # make_page_answer_stats_list is called
            # using restrict_to_first_attempt = 1
            self.assertIn(1, mock_make_stats_list.call_args[0])
            self.assertResponseContextEqual(resp, "restrict_to_first_attempt", 1)

            self.assertEqual(mock_make_g_his.call_count, 1)
            self.assertEqual(mock_make_stats_list.call_count, 1)
            self.assertEqual(mock_make_t_his.call_count, 1)
            self.assertEqual(mock_count_particpt.call_count, 1)

    def test_success_test_restrict_to_first_attempt_invalid(self):
        with mock.patch(
                "course.analytics.make_grade_histogram"
        ) as mock_make_g_his, mock.patch(
            "course.analytics.make_page_answer_stats_list"
        ) as mock_make_stats_list, mock.patch(
            "course.analytics.make_time_histogram"
        ) as mock_make_t_his, mock.patch(
            "course.analytics.count_participants"
        ) as mock_count_particpt:
            resp = self.get_flow_analytics_view(flow_id=self.flow_id,
                                                restrict_to_first_attempt="foo")
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(
                resp, "flow_identifier", self.flow_id)

            # make_page_answer_stats_list is called
            # using restrict_to_first_attempt = 0
            self.assertIn(0, mock_make_stats_list.call_args[0])
            self.assertResponseContextEqual(resp, "restrict_to_first_attempt", 0)

            self.assertEqual(mock_make_g_his.call_count, 1)
            self.assertEqual(mock_make_stats_list.call_count, 1)
            self.assertEqual(mock_make_t_his.call_count, 1)
            self.assertEqual(mock_count_particpt.call_count, 1)

    def test_flow_id_does_not_exist(self):
        with mock.patch(
            "course.analytics.make_page_answer_stats_list"
        ) as mock_make_stats_list:
            mock_make_stats_list.side_effect = ObjectDoesNotExist()
            resp = self.get_flow_analytics_view(flow_id=self.flow_id)
            self.assertEqual(resp.status_code, 404)
            self.assertAddMessageCalledWith(
                ("Flow '%s' was not found in the repository, but it exists in "
                    "the database--maybe it was deleted?")
                % self.flow_id)

# vim: fdm=marker
