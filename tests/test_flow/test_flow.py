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

import os
import six
from collections import OrderedDict
import itertools

import unittest
from django import http
from django.urls import reverse
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import TestCase, RequestFactory
from django.utils.timezone import now, timedelta
from django.core import mail

from relate.utils import dict_to_struct, StyledForm

from course.content import get_repo_blob
from course import models, flow
from course import constants
from course.constants import grade_aggregation_strategy as g_strategy
from course.constants import flow_permission as fperm
from course.utils import FlowSessionStartRule, FlowSessionGradingRule

from tests.base_test_mixins import (
    CoursesTestMixinBase, SingleCourseQuizPageTestMixin, SingleCourseTestMixin)
from tests.constants import QUIZ_FLOW_ID
from tests.utils import mock
from tests import factories

YAML_PATH = os.path.join(os.path.dirname(__file__), 'resource')


def get_flow_permissions_list(excluded=None):
    if not isinstance(excluded, list):
        excluded = [excluded]
    all_flow_permissions = dict(constants.FLOW_PERMISSION_CHOICES).keys()
    return [fp for fp in all_flow_permissions if fp not in excluded]


COMMIT_SHA_MAP = {
    "flows/%s.yml" % QUIZ_FLOW_ID: [

        # key: commit_sha, value: attributes
        {"my_fake_commit_sha_1": {"path": "fake-quiz-test1.yml"}},
        {"my_fake_commit_sha_2": {"path": "fake-quiz-test2.yml"}},

        {"my_fake_commit_sha_for_grades1": {
            "path": "fake-quiz-test-for-grade1.yml",
            "page_ids": ["half", "krylov", "quarter"]}},
        {"my_fake_commit_sha_for_grades2": {
            "path": "fake-quiz-test-for-grade2.yml",
            "page_ids": ["krylov", "quarter"]}},

        {"my_fake_commit_sha_for_finish_flow_session": {
            "path": "fake-quiz-test-for-finish_flow_session.yml",
            "page_ids": ["half", "krylov", "matrix_props", "age_group",
                         "anyup", "proof", "neumann"]
        }},

        {"my_fake_commit_sha_for_grade_flow_session": {
            "path": "fake-quiz-test-for-grade_flow_session.yml",
            "page_ids": ["anyup"]}},
        {"my_fake_commit_sha_for_grade_flow_session2": {
            "path": "fake-quiz-test-for-grade_flow_session2.yml",
            "page_ids": ["anyup"]}},
        {"my_fake_commit_sha_for_view_flow_page": {
            "path": "fake-quiz-test-for-view_flow_page.yml",
            "page_ids": ["anyup"]}},
    ],
}


class HackRepoMixin(object):

    # This is need to for correctly getting other blobs
    fallback_commit_sha = b"4124e0c23e369d6709a670398167cb9c2fe52d35"

    @classmethod
    def setUpTestData(cls):  # noqa
        super(HackRepoMixin, cls).setUpTestData()

        class Blob(object):
            def __init__(self, yaml_file_name):
                with open(os.path.join(YAML_PATH, yaml_file_name), "rb") as f:
                    data = f.read()
                self.data = data

        def get_repo_side_effect(repo, full_name, commit_sha, allow_tree=True):
            commit_sha_path_maps = COMMIT_SHA_MAP.get(full_name)
            if commit_sha_path_maps:
                assert isinstance(commit_sha_path_maps, list)
                for cs_map in commit_sha_path_maps:
                    if commit_sha.decode() in cs_map:
                        path = cs_map[commit_sha.decode()]["path"]
                        return Blob(path)

            return get_repo_blob(repo, full_name, cls.fallback_commit_sha,
                                 allow_tree=allow_tree)

        cls.batch_fake_get_repo_blob = mock.patch("course.content.get_repo_blob")
        cls.mock_get_repo_blob = cls.batch_fake_get_repo_blob.start()
        cls.mock_get_repo_blob.side_effect = get_repo_side_effect

    @classmethod
    def tearDownClass(cls):  # noqa
        # This must be done to avoid inconsistency
        super(HackRepoMixin, cls).tearDownClass()
        cls.batch_fake_get_repo_blob.stop()

    def get_current_page_ids(self):
        current_sha = self.course.active_git_commit_sha
        for commit_sha_path_maps in COMMIT_SHA_MAP.values():
            for cs_map in commit_sha_path_maps:
                if current_sha in cs_map:
                    return cs_map[current_sha]["page_ids"]

        raise ValueError("Page_ids for that commit_sha doesn't exist")

    def assertGradeInfoEqual(self, resp, expected_grade_info_dict=None):  # noqa
        grade_info = resp.context["grade_info"]

        assert isinstance(grade_info, flow.GradeInfo)
        if not expected_grade_info_dict:
            import json
            error_msg = ("\n%s" % json.dumps(OrderedDict(
                sorted(
                    [(k, v) for (k, v) in six.iteritems(grade_info.__dict__)])),
                indent=4))
            error_msg = error_msg.replace("null", "None")
            self.fail(error_msg)

        assert isinstance(expected_grade_info_dict, dict)

        grade_info_dict = grade_info.__dict__
        not_match_infos = []
        for k in grade_info_dict.keys():
            if grade_info_dict[k] != expected_grade_info_dict[k]:
                not_match_infos.append(
                    "'%s' is expected to be %s, while got %s"
                    % (k, str(expected_grade_info_dict[k]),
                       str(grade_info_dict[k])))

        if not_match_infos:
            self.fail("\n".join(not_match_infos))


#{{{ test flow.adjust_flow_session_page_data

def flow_page_data_save_side_effect(self, *args, **kwargs):
    if self.page_id == "half1":
        raise RuntimeError("this error should not have been raised!")


class AdjustFlowSessionPageDataTest(
        SingleCourseQuizPageTestMixin, HackRepoMixin, TestCase):
    # test flow.adjust_flow_session_page_data

    initial_commit_sha = "my_fake_commit_sha_1"

    @classmethod
    def setUpTestData(cls):  # noqa
        super(AdjustFlowSessionPageDataTest, cls).setUpTestData()
        cls.start_flow(flow_id=cls.flow_id)

    def test_remove_rename_and_revive(self):
        # {{{ 1st round: do a visit
        resp = self.c.get(self.get_page_url_by_ordinal(0))
        self.assertEqual(resp.status_code, 200)

        fpds_1st = models.FlowPageData.objects.all()
        fpd_ids_1st = list(fpds_1st.values_list("page_id", flat=True))
        welcome_page_title_1st = fpds_1st.get(page_id="welcome").title
        # }}}

        # {{{ 2nd round: change sha
        self.course.active_git_commit_sha = "my_fake_commit_sha_2"
        self.course.save()

        resp = self.c.get(self.get_page_url_by_ordinal(0))
        self.assertEqual(resp.status_code, 200)

        fpds_2nd = models.FlowPageData.objects.all()
        welcome_page_title_2nd = fpds_2nd.get(page_id="welcome").title
        fpd_ids_2nd = list(fpds_2nd.values_list("page_id", flat=True))

        # the page (with page_id "welcome") has changed title
        self.assertNotEqual(welcome_page_title_1st, welcome_page_title_2nd)

        # these two pages have removed page_ordinal
        # (those in group2 are not considered)
        page_ids_removed_in_2nd = {"half1", "lsq2"}
        self.assertTrue(
            page_ids_removed_in_2nd
            < set(list(
                fpds_2nd.filter(
                    page_ordinal=None).values_list("page_id", flat=True)))
        )

        page_ids_introduced_in_2nd = {"half1_id_renamed", "half_again2"}
        self.assertNotIn(page_ids_introduced_in_2nd, fpd_ids_1st)
        self.assertTrue(page_ids_introduced_in_2nd < set(fpd_ids_2nd))

        self.assertTrue(set(fpd_ids_2nd) > set(fpd_ids_1st))
        # }}}

        # {{{ 3rd round: revive back
        self.course.active_git_commit_sha = "my_fake_commit_sha_1"
        self.course.save()

        resp = self.c.get(self.get_page_url_by_ordinal(0))
        self.assertEqual(resp.status_code, 200)

        fpds_3rd = models.FlowPageData.objects.all()
        fpd_ids_3rd = list(fpds_3rd.values_list("page_id", flat=True))
        welcome_page_title_3rd = fpds_2nd.get(page_id="welcome").title
        self.assertEqual(welcome_page_title_1st, welcome_page_title_3rd)

        # no page_data instances are removed
        self.assertSetEqual(set(fpd_ids_2nd), set(fpd_ids_3rd))
        self.assertSetEqual(
            page_ids_introduced_in_2nd,
            set(list(
                fpds_3rd.filter(
                    page_ordinal=None).values_list("page_id", flat=True))))
        for page_id in page_ids_removed_in_2nd:
            self.assertIsNotNone(
                models.FlowPageData.objects.get(page_id=page_id).page_ordinal)
            # }}}

    def test_remove_page_with_non_ordinal(self):
        resp = self.c.get(self.get_page_url_by_ordinal(0))
        self.assertEqual(resp.status_code, 200)

        # change this page's ordinal to None before change the commit_sha,
        # so that no save is needed when update course, for this page
        fpd = models.FlowPageData.objects.get(page_id="half1")
        fpd.page_ordinal = None
        fpd.save()

        with mock.patch(
                "course.models.FlowPageData.save",
                autospec=True) as mock_fpd_save:
            mock_fpd_save.side_effect = flow_page_data_save_side_effect

            self.course.active_git_commit_sha = "my_fake_commit_sha_2"
            self.course.save()

            resp = self.c.get(self.get_page_url_by_ordinal(0))
            self.assertEqual(resp.status_code, 200)

# }}}


class GradePageVisitTest(SingleCourseQuizPageTestMixin, TestCase):
    # patching tests for flow.grade_page_visits
    def test_not_is_submitted_answer(self):
        visit = mock.MagicMock()
        visit_grade_model = mock.MagicMock()
        visit.is_submitted_answer = False

        expected_error_msg = "cannot grade ungraded answer"
        with self.assertRaises(RuntimeError) as cm:
            flow.grade_page_visit(visit, visit_grade_model)
        self.assertIn(expected_error_msg, str(cm.exception))

        with self.assertRaises(RuntimeError) as cm:
            flow.grade_page_visit(visit, visit_grade_model, {"key": "value"})
        self.assertIn(expected_error_msg, str(cm.exception))

        with self.assertRaises(RuntimeError) as cm:
            flow.grade_page_visit(visit, visit_grade_model, {"key": "value"}, False)
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_page_answer_not_gradable(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            self.start_flow(self.flow_id)
            fpvgs = models.FlowPageVisitGrade.objects.all()
            self.assertEqual(fpvgs.count(), 0)

            page_id = "age_group"

            self.submit_page_answer_by_page_id_and_test(
                page_id, do_grading=True, expected_grades=0)

            fpvgs = models.FlowPageVisitGrade.objects.filter(
                visit__page_data__page_id=page_id, grade_data__isnull=False)
            self.assertEqual(
                fpvgs.count(), 0,
                "Unexpectedly created FlowPageVisitGrade objects for "
                "ungradedable questions which expects answer.")

    def test_answer_feeback_is_none(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            with mock.patch(
                    "course.page.upload.FileUploadQuestion.grade") as mock_grade:
                mock_grade.return_value = None
                self.start_flow(self.flow_id)
                fpvgs = models.FlowPageVisitGrade.objects.all()
                self.assertEqual(fpvgs.count(), 0)

                page_id = "anyup"

                self.submit_page_answer_by_page_id_and_test(
                    page_id, do_grading=False)
                self.end_flow()

                self.post_grade_by_page_id(
                    page_id=page_id, grade_data={})

                fpvgs = models.FlowPageVisitGrade.objects.filter(
                    visit__page_data__page_id=page_id, grade_data__isnull=False)
                self.assertEqual(fpvgs.count(), 1)
                fpvg, = fpvgs
                self.assertEqual(fpvg.max_points, 5)
                self.assertIsNone(fpvg.correctness)


class StartFlowTest(CoursesTestMixinBase, unittest.TestCase):
    # test flow.start_flow
    def setUp(self):
        super(StartFlowTest, self).setUp()
        self.repo = mock.MagicMock()

        self.course = factories.CourseFactory()
        self.user = factories.UserFactory()
        self.participation = factories.ParticipationFactory(
            course=self.course, user=self.user
        )

        fake_adjust_flow_session_page_data = mock.patch(
            "course.flow.adjust_flow_session_page_data")
        self.mock_adjust_flow_session_page_data = (
            fake_adjust_flow_session_page_data.start())
        self.mock_adjust_flow_session_page_data.return_value = None
        self.addCleanup(fake_adjust_flow_session_page_data.stop)

        fake_get_flow_grading_opportunity = mock.patch(
            "course.models.get_flow_grading_opportunity")
        self.mock_get_flow_grading_opportunity = (
            fake_get_flow_grading_opportunity.start())
        self.addCleanup(fake_get_flow_grading_opportunity.stop)

        self.flow_id = "some_flow_id"
        self.now_datetime = now()

        def remove_all_course():
            for course in models.Course.objects.all():
                course.delete()

        self.addCleanup(remove_all_course)

    def test_start_flow_anonymous(self):
        self.assertEqual(models.FlowSession.objects.count(), 0)

        session_start_rule = FlowSessionStartRule(
            tag_session="my_tag",
            default_expiration_mode=constants.flow_session_expiration_mode.roll_over)

        flow_desc = dict_to_struct(
            {"rules": dict_to_struct(
                {"grade_identifier": "g_identifier",
                 "grade_aggregation_strategy": g_strategy.use_earliest})})

        session = flow.start_flow(
            repo=self.repo,
            course=self.course,
            participation=None,
            user=None,
            flow_id=self.flow_id,
            flow_desc=flow_desc,
            session_start_rule=session_start_rule,
            now_datetime=self.now_datetime)

        self.assertIsInstance(session, models.FlowSession)

        self.assertEqual(models.FlowSession.objects.count(), 1)
        fs = models.FlowSession.objects.last()
        self.assertIsNone(fs.participation)
        self.assertIsNone(fs.user)
        self.assertEqual(fs.flow_id, self.flow_id)
        self.assertEqual(fs.start_time, self.now_datetime)
        self.assertTrue(fs.in_progress)
        self.assertEqual(fs.expiration_mode,
                         session_start_rule.default_expiration_mode)
        self.assertEqual(fs.access_rules_tag,
                         session_start_rule.tag_session)

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 1)
        self.assertEqual(self.mock_get_flow_grading_opportunity.call_count, 1)

    def test_start_flow_with_no_rule(self):
        self.assertEqual(models.FlowSession.objects.count(), 0)

        # no exp_mode
        session_start_rule = FlowSessionStartRule()

        # flow_desc no rules
        flow_desc = dict_to_struct({})

        session = flow.start_flow(
            repo=self.repo,
            course=self.course,
            participation=None,
            user=None,
            flow_id=self.flow_id,
            flow_desc=flow_desc,
            session_start_rule=session_start_rule,
            now_datetime=self.now_datetime)

        self.assertIsInstance(session, models.FlowSession)

        self.assertEqual(models.FlowSession.objects.count(), 1)
        fs = models.FlowSession.objects.last()
        self.assertIsNone(fs.participation)
        self.assertIsNone(fs.user)
        self.assertEqual(fs.flow_id, self.flow_id)
        self.assertEqual(fs.start_time, self.now_datetime)
        self.assertTrue(fs.in_progress)
        self.assertEqual(fs.expiration_mode,
                         constants.flow_session_expiration_mode.end)
        self.assertIsNone(fs.access_rules_tag)

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 1)
        self.assertEqual(self.mock_get_flow_grading_opportunity.call_count, 0)

    def test_start_flow_with_grade_identifier_null(self):
        self.assertEqual(models.FlowSession.objects.count(), 0)

        # no exp_mode
        session_start_rule = FlowSessionStartRule()

        flow_desc = dict_to_struct(
            {"rules": dict_to_struct({"grade_identifier": None})})

        session = flow.start_flow(
            repo=self.repo,
            course=self.course,
            participation=None,
            user=None,
            flow_id=self.flow_id,
            flow_desc=flow_desc,
            session_start_rule=session_start_rule,
            now_datetime=self.now_datetime)

        self.assertIsInstance(session, models.FlowSession)

        self.assertEqual(models.FlowSession.objects.count(), 1)
        fs = models.FlowSession.objects.last()
        self.assertIsNone(fs.participation)
        self.assertIsNone(fs.user)
        self.assertEqual(fs.flow_id, self.flow_id)
        self.assertEqual(fs.start_time, self.now_datetime)
        self.assertTrue(fs.in_progress)
        self.assertEqual(fs.expiration_mode,
                         constants.flow_session_expiration_mode.end)
        self.assertIsNone(fs.access_rules_tag)

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 1)
        self.assertEqual(self.mock_get_flow_grading_opportunity.call_count, 0)


class AssemblePageGradesTest(HackRepoMixin,
                             SingleCourseQuizPageTestMixin, TestCase):
    # This is actually test course.flow.assemble_page_grades

    initial_commit_sha = "my_fake_commit_sha_for_grades1"

    def setUp(self):
        super(AssemblePageGradesTest, self).setUp()
        self.student = self.student_participation.user

        # start_flow is done per tests instead of class level
        # because we'll modify page_data in some test
        self.start_flow(self.flow_id)

    def get_grades_of_opps(self, opp_identifiers=None, as_dict=False,
                           with_grade_time=False):
        if opp_identifiers is not None:
            assert isinstance(opp_identifiers, (list, tuple))
        resp = self.get_my_grades_view()
        self.assertEqual(resp.status_code, 200)
        grade_tables = resp.context["grade_table"]

        if opp_identifiers is not None:
            self.assertGreaterEqual(len(grade_tables), len(opp_identifiers))
        else:
            opp_identifiers = [
                grade_info.opportunity.identifier for grade_info in grade_tables]

        grades = {}

        if with_grade_time:
            as_dict = True

        for opp in opp_identifiers:
            for grade_info in grade_tables:
                if grade_info.opportunity.identifier == opp:
                    if as_dict:
                        grades[opp] = {
                            "grade":
                                grade_info.grade_state_machine.stringify_state(),
                            "last_grade_time":
                                grade_info.grade_state_machine.last_grade_time}
                    else:
                        grades[opp] = \
                            grade_info.grade_state_machine.stringify_state()
                    break

        if as_dict:
            return grades
        else:
            return list(grades.values())

    def get_page_grades_of_opp(self, opp_identifier):
        resp = self.get_gradebook_by_opp_view(opp_identifier,
                                              view_page_grades=True)
        self.assertEqual(resp.status_code, 200)
        grade_table = resp.context["grade_table"]

        user_grades_dict = {}
        for participation, grade_info in grade_table:
            grades = []
            for _, grade in grade_info.grades:
                if grade is not None:
                    grades.append(grade.percentage())
                else:
                    grades.append(None)
            user_grades_dict[participation.user.username] = grades

        return user_grades_dict

    def test_view_gradebook_single_submission(self):
        # submit correct answers
        page_ids = self.get_current_page_ids()
        for page_id in page_ids:
            self.submit_page_answer_by_page_id_and_test(page_id)

        self.end_flow()

        self.assertSessionScoreEqual(7)

        self.assertListEqual(list(self.get_grades_of_opps()), ["100.00%"])
        self.assertListEqual(
            self.get_page_grades_of_opp("la_quiz")[self.student.username],
            [None, 100, 100, 100])

    def test_view_gradebook_two_submissions(self):
        page_ids = self.get_current_page_ids()

        # submit correct answers
        for page_id in page_ids:
            self.submit_page_answer_by_page_id_and_test(page_id)
        self.end_flow()

        # second submission
        self.start_flow(self.flow_id)
        for page_id in page_ids:
            answer_data = None
            if page_id == "half":
                # wrong answer
                answer_data = {"answer": "1/4"}
            self.submit_page_answer_by_page_id_and_test(
                page_id, answer_data=answer_data)
        self.end_flow()

        self.assertSessionScoreEqual(2)

        self.assertListEqual(list(self.get_grades_of_opps()), ['28.57% (/2)'])
        self.assertListEqual(
            self.get_page_grades_of_opp("la_quiz")[self.student.username],
            [None, 0, 100, 100])

    def test_view_gradebook_with_question_deleted(self):
        page_ids = self.get_current_page_ids()

        # submit correct answers
        for page_id in page_ids:
            answer_data = None
            if page_id == "half":
                # wrong answer
                answer_data = {"answer": "1/4"}
            self.submit_page_answer_by_page_id_and_test(
                page_id, answer_data=answer_data)
        self.end_flow()

        self.assertListEqual(list(self.get_grades_of_opps()), ['28.57%'])
        self.assertListEqual(
            self.get_page_grades_of_opp("la_quiz")[self.student.username],
            [None, 0, 100, 100])

        # second submission, another commit_sha
        self.course.active_git_commit_sha = "my_fake_commit_sha_for_grades2"
        self.course.save()
        self.start_flow(self.flow_id)

        page_ids = self.get_current_page_ids()
        for page_id in page_ids:
            self.submit_page_answer_by_page_id_and_test(page_id)
        self.end_flow()

        self.assertSessionScoreEqual(2)

        self.assertListEqual(list(self.get_grades_of_opps()), ['100.00% (/2)'])
        self.assertListEqual(
            self.get_page_grades_of_opp("la_quiz")[self.student.username],
            [None, 100, 100, None])

    def test_view_gradebook_with_question_deleted_page_data_adjusted(self):
        page_ids = self.get_current_page_ids()

        # submit correct answers
        for page_id in page_ids:
            answer_data = None
            if page_id == "half":
                # wrong answer
                answer_data = {"answer": "1/4"}
            self.submit_page_answer_by_page_id_and_test(
                page_id, answer_data=answer_data)
        self.end_flow()

        self.assertListEqual(list(self.get_grades_of_opps()), ['28.57%'])
        self.assertListEqual(
            self.get_page_grades_of_opp("la_quiz")[self.student.username],
            [None, 0, 100, 100])

        # second submission, another commit_sha
        self.course.active_git_commit_sha = "my_fake_commit_sha_for_grades2"
        self.course.save()
        self.start_flow(self.flow_id)

        # This will adjust the flow_page_data of the first session
        self.c.get(self.get_page_url_by_ordinal(0, flow_session_id=1))

        page_ids = self.get_current_page_ids()
        for page_id in page_ids:
            self.submit_page_answer_by_page_id_and_test(page_id)
        self.end_flow()

        self.assertSessionScoreEqual(2)

        self.assertListEqual(list(self.get_grades_of_opps()), ['100.00% (/2)'])
        self.assertListEqual(
            self.get_page_grades_of_opp("la_quiz")[self.student.username],
            [None, 100, 100])

    def test_view_gradebook_with_question_when_session_reopened(self):
        page_ids = self.get_current_page_ids()

        # submit correct answers
        for page_id in page_ids:
            answer_data = None
            if page_id == "half":
                # wrong answer
                answer_data = {"answer": "1/4"}
            self.submit_page_answer_by_page_id_and_test(
                page_id, answer_data=answer_data)
        self.end_flow()

        self.assertListEqual(list(self.get_grades_of_opps()), ['28.57%'])
        self.assertListEqual(
            self.get_page_grades_of_opp("la_quiz")[self.student.username],
            [None, 0, 100, 100])

        # second submission, another commit_sha
        self.course.active_git_commit_sha = "my_fake_commit_sha_for_grades2"
        self.course.save()
        self.start_flow(self.flow_id)

        # This will adjust the flow_page_data of the first session
        self.c.get(self.get_page_url_by_ordinal(0, flow_session_id=1))

        page_ids = self.get_current_page_ids()
        for page_id in page_ids:
            self.submit_page_answer_by_page_id_and_test(page_id)
        self.end_flow()

        latest_fs = models.FlowSession.objects.get(pk=2)
        latest_fs.in_progress = True
        latest_fs.save()

        self.assertSessionScoreEqual(2)

        # This should fail after fixing Issue # 263 and #417, or there will
        # be inconsistencies
        self.assertListEqual(list(self.get_grades_of_opps()), ['100.00% (/2)'])
        self.assertListEqual(
            self.get_page_grades_of_opp("la_quiz")[self.student.username],
            [None, 100, 100])


class AssembleAnswerVisitsTest(unittest.TestCase):
    # test flow.assemble_answer_visits (flowsession.answer_visits())

    def setUp(self):
        super(AssembleAnswerVisitsTest, self).setUp()
        self.course = factories.CourseFactory()
        self.participation = factories.ParticipationFactory(course=self.course)

        # an in-progress session
        self.flow_session = factories.FlowSessionFactory(
            course=self.course,
            participation=self.participation,
            in_progress=True,
            page_count=5)

        def remove_all_course():
            for course in models.Course.objects.all():
                course.delete()

        self.addCleanup(remove_all_course)

    def create_visits(self):
        self.page_data = factories.FlowPageDataFactory(
            flow_session=self.flow_session, page_ordinal=1)

        time = now() - timedelta(days=1)
        factories.FlowPageVisitFactory(
            page_data=self.page_data, visit_time=time)

        time = time + timedelta(minutes=10)
        visit1 = factories.FlowPageVisitFactory(
            page_data=self.page_data,
            answer={"answer": "first answer"},
            is_submitted_answer=True,
            visit_time=time)
        factories.FlowPageVisitGradeFactory(visit=visit1, correctness=1)

        time = time + timedelta(minutes=10)
        visit2 = factories.FlowPageVisitFactory(
            page_data=self.page_data,
            answer={"answer": "second answer"},
            is_submitted_answer=True,
            visit_time=time)
        factories.FlowPageVisitGradeFactory(visit=visit2, correctness=0.815)

        time = time + timedelta(minutes=10)
        factories.FlowPageVisitFactory(
            page_data=self.page_data,
            answer={"answer": "third answer (just saved)"},
            is_submitted_answer=False,
            visit_time=time)

    def test_generic(self):
        self.create_visits()
        answer_visits = self.flow_session.answer_visits()
        self.assertEqual(len(answer_visits), 5)
        self.assertEqual(len([v for v in answer_visits if v is not None]), 1)

        for page_visit in answer_visits:
            if page_visit is not None:
                page_visit.correctness = 0.815

    def test_session_not_in_progress(self):
        self.flow_session.in_progress = False
        self.flow_session.save()

        self.create_visits()
        answer_visits = self.flow_session.answer_visits()
        self.assertEqual(len(answer_visits), 5)
        self.assertEqual(len([v for v in answer_visits if v is not None]), 1)
        for page_visit in answer_visits:
            if page_visit is not None:
                page_visit.correctness = 0.815

    def test_page_ordinal_none(self):
        self.flow_session.in_progress = False
        self.flow_session.save()
        self.create_visits()

        self.page_data.page_ordinal = None
        self.page_data.save()

        answer_visits = self.flow_session.answer_visits()
        self.assertEqual(len(answer_visits), 5)
        self.assertEqual(len([v for v in answer_visits if v is not None]), 0)


class MockPage(object):
    def __init__(self, expects_answer, is_answer_gradable):
        self._is_answer_gradable = is_answer_gradable
        self._expects_answer = expects_answer

    def is_answer_gradable(self):
        return self._is_answer_gradable

    def expects_answer(self):
        return self._expects_answer


class FakePageData(object):
    def __init__(self, page_ordinal, expects_answer, is_answer_gradable):
        self.page_ordinal = page_ordinal
        self._is_answer_gradable = is_answer_gradable
        self._expects_answer = expects_answer

    def mock_page_attribute(self):
        return MockPage(self._is_answer_gradable, self._expects_answer)


def instantiate_flow_page_with_ctx_get_interaction_kind_side_effect(fctx,
                                                                    page_data):  # noqa
    # side effect when testing get_interaction_kind
    return page_data.mock_page_attribute()


class GetInteractionKindTest(unittest.TestCase):
    # test flow.get_interaction_kind
    def setUp(self):
        fake_instantiate_flow_page_with_ctx = mock.patch(
            "course.flow.instantiate_flow_page_with_ctx")
        mock_instantiate_flow_page_with_ctx = \
            fake_instantiate_flow_page_with_ctx.start()
        mock_instantiate_flow_page_with_ctx.side_effect = \
            instantiate_flow_page_with_ctx_get_interaction_kind_side_effect
        self.addCleanup(fake_instantiate_flow_page_with_ctx.stop)

        self.fctx = mock.MagicMock()
        self.flow_session = mock.MagicMock()

        def remove_all_course():
            for course in models.Course.objects.all():
                course.delete()

        self.addCleanup(remove_all_course)

    def test_permanent_grade(self):
        all_page_data = [
            FakePageData(page_ordinal=0,
                         expects_answer=False, is_answer_gradable=False),
            FakePageData(page_ordinal=1,
                         expects_answer=True, is_answer_gradable=True),
            FakePageData(page_ordinal=2,
                         expects_answer=False, is_answer_gradable=False)
        ]
        self.assertEqual(
            flow.get_interaction_kind(
                self.fctx, self.flow_session, flow_generates_grade=True,
                all_page_data=all_page_data),
            constants.flow_session_interaction_kind.permanent_grade)

    def test_practice_grade(self):
        all_page_data = [
            FakePageData(page_ordinal=0,
                         expects_answer=False, is_answer_gradable=False),
            FakePageData(page_ordinal=1,
                         expects_answer=True, is_answer_gradable=True),
            FakePageData(page_ordinal=2,
                         expects_answer=False, is_answer_gradable=False)
        ]
        self.assertEqual(
            flow.get_interaction_kind(
                self.fctx, self.flow_session, flow_generates_grade=False,
                all_page_data=all_page_data),
            constants.flow_session_interaction_kind.practice_grade)

    def test_ungraded(self):
        all_page_data = [
            FakePageData(page_ordinal=0,
                         expects_answer=False, is_answer_gradable=True),
            FakePageData(page_ordinal=1,
                         expects_answer=True, is_answer_gradable=False),
            FakePageData(page_ordinal=2,
                         expects_answer=False, is_answer_gradable=False)
        ]

        for flow_generates_grade in [True, False]:
            self.assertEqual(
                flow.get_interaction_kind(
                    self.fctx, self.flow_session,
                    flow_generates_grade=flow_generates_grade,
                    all_page_data=all_page_data),
                constants.flow_session_interaction_kind.ungraded)

    def test_noninteractive(self):
        all_page_data = [
            FakePageData(page_ordinal=0,
                         expects_answer=False, is_answer_gradable=False),
            FakePageData(page_ordinal=1,
                         expects_answer=False, is_answer_gradable=False)
        ]

        for flow_generates_grade in [True, False]:
            self.assertEqual(
                flow.get_interaction_kind(
                    self.fctx, self.flow_session,
                    flow_generates_grade=flow_generates_grade,
                    all_page_data=all_page_data),
                constants.flow_session_interaction_kind.noninteractive)


class GradeInfoTest(unittest.TestCase):
    # tests for flow.GradeInfo (for coverage, not complete)
    def test_points_percent_full(self):
        g_info = flow.GradeInfo(
            points=20,
            provisional_points=20,
            max_points=20,
            max_reachable_points=20,
            fully_correct_count=5,
            partially_correct_count=0,
            incorrect_count=0,
            unknown_count=0
        )

        # for visualization purposes
        self.assertTrue(99 < g_info.points_percent() < 100)

    def test_points_percent_max_points_none(self):
        g_info = flow.GradeInfo(
            points=0,
            provisional_points=20,
            max_points=None,
            max_reachable_points=20,
            fully_correct_count=5,
            partially_correct_count=0,
            incorrect_count=0,
            unknown_count=0
        )
        self.assertEqual(g_info.points_percent(), 100)

        g_info = flow.GradeInfo(
            points=1,
            provisional_points=20,
            max_points=None,
            max_reachable_points=20,
            fully_correct_count=5,
            partially_correct_count=0,
            incorrect_count=0,
            unknown_count=0
        )
        self.assertEqual(g_info.points_percent(), 0)

    def test_points_percent_max_points_zero(self):
        g_info = flow.GradeInfo(
            points=0,
            provisional_points=20,
            max_points=0,
            max_reachable_points=20,
            fully_correct_count=5,
            partially_correct_count=0,
            incorrect_count=0,
            unknown_count=0
        )
        self.assertEqual(g_info.points_percent(), 100)

        g_info = flow.GradeInfo(
            points=1,
            provisional_points=20,
            max_points=0,
            max_reachable_points=20,
            fully_correct_count=5,
            partially_correct_count=0,
            incorrect_count=0,
            unknown_count=0
        )
        self.assertEqual(g_info.points_percent(), 0)

    def test_unreachable_points_percent_max_points_none(self):
        g_info = flow.GradeInfo(
            points=1,
            provisional_points=20,
            max_points=None,
            max_reachable_points=20,
            fully_correct_count=5,
            partially_correct_count=0,
            incorrect_count=0,
            unknown_count=0
        )
        self.assertEqual(g_info.unreachable_points_percent(), 0)

    def test_unreachable_points_percent_max_points_zero(self):
        g_info = flow.GradeInfo(
            points=1,
            provisional_points=20,
            max_points=0,
            max_reachable_points=20,
            fully_correct_count=5,
            partially_correct_count=0,
            incorrect_count=0,
            unknown_count=0
        )
        self.assertEqual(g_info.unreachable_points_percent(), 0)

    def test_unreachable_points_percent_max_reachable_points_zero(self):
        g_info = flow.GradeInfo(
            points=1,
            provisional_points=20,
            max_points=20,
            max_reachable_points=None,
            fully_correct_count=5,
            partially_correct_count=0,
            incorrect_count=0,
            unknown_count=0
        )
        self.assertEqual(g_info.unreachable_points_percent(), 0)

    def test_unreachable_points_percent_full(self):
        g_info = flow.GradeInfo(
            points=1,
            provisional_points=20,
            max_points=20,
            max_reachable_points=0,
            fully_correct_count=5,
            partially_correct_count=0,
            incorrect_count=0,
            unknown_count=0
        )

        # for visualization purposes
        self.assertTrue(
            99 < g_info.unreachable_points_percent() < 100)


class FinishFlowSessionViewTest(HackRepoMixin,
                                SingleCourseQuizPageTestMixin, TestCase):
    # test flow.finish_flow_session_view

    initial_commit_sha = "my_fake_commit_sha_for_finish_flow_session"

    def setUp(self):
        super(FinishFlowSessionViewTest, self).setUp()
        self.student = self.student_participation.user
        self.start_flow(self.flow_id)

        fake_add_message = mock.patch("course.flow.messages.add_message")
        self.mock_add_message = fake_add_message.start()
        self.addCleanup(fake_add_message.stop)

        fake_will_use_masked_profile_for_email = mock.patch(
            "course.utils.will_use_masked_profile_for_email")
        self.mock_will_use_masked_profile_for_email = (
            fake_will_use_masked_profile_for_email.start())
        self.mock_will_use_masked_profile_for_email.return_value = False
        self.addCleanup(fake_will_use_masked_profile_for_email.stop)

    def test_submit_all_correct(self):
        # with human graded questions not graded
        page_ids = self.get_current_page_ids()
        for page_id in page_ids:
            self.submit_page_answer_by_page_id_and_test(page_id)

        resp = self.end_flow()

        expected_grade_info_dict = {
            "fully_correct_count": 2,
            "incorrect_count": 0,
            "max_points": 12.0,
            "max_reachable_points": 7.0,
            "optional_fully_correct_count": 1,
            "optional_incorrect_count": 0,
            "optional_partially_correct_count": 0,
            "optional_unknown_count": 1,
            "partially_correct_count": 0,
            "points": None,
            "provisional_points": 7.0,
            "unknown_count": 1
        }

        self.assertGradeInfoEqual(resp, expected_grade_info_dict)

        resp = self.c.get(self.get_finish_flow_session_view_url())
        self.assertGradeInfoEqual(resp, expected_grade_info_dict)

    def test_submit_all_correct_all_graded(self):
        # with human graded questions graded

        page_ids = self.get_current_page_ids()
        for page_id in page_ids:
            self.submit_page_answer_by_page_id_and_test(page_id)

        self.end_flow()

        for page_id in page_ids:
            self.submit_page_human_grading_by_page_id_and_test(
                page_id, do_session_score_equal_assersion=False)

        expected_grade_info_dict = {
            "fully_correct_count": 3,
            "incorrect_count": 0,
            "max_points": 12.0,
            "max_reachable_points": 12.0,
            "optional_fully_correct_count": 2,
            "optional_incorrect_count": 0,
            "optional_partially_correct_count": 0,
            "optional_unknown_count": 0,
            "partially_correct_count": 0,
            "points": 12.0,
            "provisional_points": 12.0,
            "unknown_count": 0
        }
        resp = self.c.get(self.get_finish_flow_session_view_url())
        self.assertEqual(resp.status_code, 200)
        self.assertGradeInfoEqual(resp, expected_grade_info_dict)

    def test_submit_with_partial_correct_or_incorrect_and_all_graded(self):
        page_ids = self.get_current_page_ids()
        for page_id in page_ids:
            if page_id not in ["matrix_props", "half"]:
                self.submit_page_answer_by_page_id_and_test(page_id)

        self.submit_page_answer_by_page_id_and_test(
            "matrix_props", answer_data={"choice": ['0']}, expected_grades=0.5
        )

        self.submit_page_answer_by_page_id_and_test(
            "half", answer_data={"answer": ['1']}, expected_grades=0
        )

        resp = self.end_flow()

        expected_grade_info_dict = {
            "fully_correct_count": 1,
            "incorrect_count": 1,
            "max_points": 12.0,
            "max_reachable_points": 7.0,
            "optional_fully_correct_count": 0,
            "optional_incorrect_count": 0,
            "optional_partially_correct_count": 1,
            "optional_unknown_count": 1,
            "partially_correct_count": 0,
            "points": None,
            "provisional_points": 2.0,
            "unknown_count": 1
        }
        self.assertGradeInfoEqual(resp, expected_grade_info_dict)

        for page_id in page_ids:
            if page_id == "anyup":
                self.submit_page_human_grading_by_page_id_and_test(
                    page_id, grade_data={"grade_percent": "0", "released": "on"},
                    do_session_score_equal_assersion=False)
            if page_id == "proof":
                self.submit_page_human_grading_by_page_id_and_test(
                    page_id,
                    grade_data={"grade_percent": "70", "released": "on"},
                    do_session_score_equal_assersion=False)
            else:
                self.submit_page_human_grading_by_page_id_and_test(
                    page_id, do_session_score_equal_assersion=False)

        expected_grade_info_dict = {
            "fully_correct_count": 1,
            "incorrect_count": 1,
            "max_points": 12.0,
            "max_reachable_points": 12.0,
            "optional_fully_correct_count": 1,
            "optional_incorrect_count": 0,
            "optional_partially_correct_count": 1,
            "optional_unknown_count": 0,
            "partially_correct_count": 1,
            "points": 5.5,
            "provisional_points": 5.5,
            "unknown_count": 0
        }
        resp = self.c.get(self.get_finish_flow_session_view_url())
        self.assertEqual(resp.status_code, 200)
        self.assertGradeInfoEqual(resp, expected_grade_info_dict)

    def test_submit_with_bonus(self):  # noqa
        with mock.patch(
                "course.flow.get_session_grading_rule") as mock_get_grule:
            mock_get_grule.return_value = \
                self.get_hacked_session_grading_rule(bonus_points=2)

            page_ids = self.get_current_page_ids()
            for page_id in page_ids:
                if page_id not in ["matrix_props", "half"]:
                    self.submit_page_answer_by_page_id_and_test(page_id)

            self.submit_page_answer_by_page_id_and_test(
                "matrix_props", answer_data={"choice": ['0']},
                expected_grades=0.5
            )

            self.submit_page_answer_by_page_id_and_test(
                "half", answer_data={"answer": ['1']}, expected_grades=0
            )

            self.end_flow()

            for page_id in page_ids:
                if page_id == "anyup":
                    self.submit_page_human_grading_by_page_id_and_test(
                        page_id,
                        grade_data={"grade_percent": "0", "released": "on"},
                        do_session_score_equal_assersion=False)
                if page_id == "proof":
                    self.submit_page_human_grading_by_page_id_and_test(
                        page_id,
                        grade_data={"grade_percent": "70", "released": "on"},
                        do_session_score_equal_assersion=False)
                else:
                    self.submit_page_human_grading_by_page_id_and_test(
                        page_id, do_session_score_equal_assersion=False)

            expected_grade_info_dict = {
                "fully_correct_count": 1,
                "incorrect_count": 1,
                "max_points": 14.0,
                "max_reachable_points": 14.0,
                "optional_fully_correct_count": 1,
                "optional_incorrect_count": 0,
                "optional_partially_correct_count": 1,
                "optional_unknown_count": 0,
                "partially_correct_count": 1,
                "points": 7.5,
                "provisional_points": 7.5,
                "unknown_count": 0
            }
            resp = self.c.get(self.get_finish_flow_session_view_url())
            self.assertEqual(resp.status_code, 200)
            self.assertGradeInfoEqual(resp, expected_grade_info_dict)

    def test_submit_with_max_points_enforced_cap_no_answers(self):
        with mock.patch(
                "course.flow.get_session_grading_rule") as mock_get_grule:
            mock_get_grule.return_value = mock_get_grule.return_value = \
                self.get_hacked_session_grading_rule(max_points_enforced_cap=10)

            # {{{ no answers
            resp = self.end_flow()

            expected_grade_info_dict = {
                "fully_correct_count": 0,
                "incorrect_count": 3,
                "max_points": 12.0,
                "max_reachable_points": 10,
                "optional_fully_correct_count": 0,
                "optional_incorrect_count": 2,
                "optional_partially_correct_count": 0,
                "optional_unknown_count": 0,
                "partially_correct_count": 0,
                "points": 0.0,
                "provisional_points": 0.0,
                "unknown_count": 0
            }
            self.assertGradeInfoEqual(resp, expected_grade_info_dict)
            # }}}

    def test_submit_with_max_points_enforced_cap(self):
        with mock.patch(
                "course.flow.get_session_grading_rule") as mock_get_grule:
            mock_get_grule.return_value = mock_get_grule.return_value = \
                self.get_hacked_session_grading_rule(
                    max_points_enforced_cap=10)

            # answer all questions
            page_ids = self.get_current_page_ids()
            for page_id in page_ids:
                self.submit_page_answer_by_page_id_and_test(page_id)

            resp = self.end_flow()

            expected_grade_info_dict = {
                "fully_correct_count": 2,
                "incorrect_count": 0,
                "max_points": 12.0,
                "max_reachable_points": 7.0,
                "optional_fully_correct_count": 1,
                "optional_incorrect_count": 0,
                "optional_partially_correct_count": 0,
                "optional_unknown_count": 1,
                "partially_correct_count": 0,
                "points": None,
                "provisional_points": 7.0,
                "unknown_count": 1
            }
            self.assertGradeInfoEqual(resp, expected_grade_info_dict)

    def test_submit_with_max_points_enforced_cap2(self):
        with mock.patch(
                "course.flow.get_session_grading_rule") as mock_get_grule:
            mock_get_grule.return_value = mock_get_grule.return_value = \
                self.get_hacked_session_grading_rule(
                    # lower than provisional_points
                    max_points_enforced_cap=6)

            # answer all questions
            page_ids = self.get_current_page_ids()
            for page_id in page_ids:
                self.submit_page_answer_by_page_id_and_test(page_id)
            #
            resp = self.end_flow()

            expected_grade_info_dict = {
                "fully_correct_count": 2,
                "incorrect_count": 0,
                "max_points": 12.0,
                "max_reachable_points": 6.0,
                "optional_fully_correct_count": 1,
                "optional_incorrect_count": 0,
                "optional_partially_correct_count": 0,
                "optional_unknown_count": 1,
                "partially_correct_count": 0,
                "points": None,
                "provisional_points": 6.0,
                "unknown_count": 1
            }
            self.assertGradeInfoEqual(resp, expected_grade_info_dict)

    def test_submit_with_max_points(self):
        with mock.patch(
                "course.flow.get_session_grading_rule") as mock_get_grule:
            mock_get_grule.return_value = mock_get_grule.return_value = \
                self.get_hacked_session_grading_rule(max_points=11)

            # no answers
            resp = self.end_flow()

            expected_grade_info_dict = {
                "fully_correct_count": 0,
                "incorrect_count": 3,
                "max_points": 11,
                "max_reachable_points": 12.0,
                "optional_fully_correct_count": 0,
                "optional_incorrect_count": 2,
                "optional_partially_correct_count": 0,
                "optional_unknown_count": 0,
                "partially_correct_count": 0,
                "points": 0.0,
                "provisional_points": 0.0,
                "unknown_count": 0
            }
            self.assertGradeInfoEqual(resp, expected_grade_info_dict)

    def test_no_view_fperm(self):
        with mock.patch(
                "course.flow.get_session_access_rule") as mock_get_arule:
            mock_get_arule.return_value = (
                self.get_hacked_session_access_rule(
                    permissions=[fperm.end_session]))

            # fail for get
            resp = self.c.get(self.get_finish_flow_session_view_url())
            self.assertEqual(resp.status_code, 403)

            # fail for post
            resp = self.end_flow()
            self.assertEqual(resp.status_code, 403)

    def test_no_end_session_fperm(self):
        with mock.patch(
                "course.flow.get_session_access_rule") as mock_get_arule:
            mock_get_arule.return_value = (
                self.get_hacked_session_access_rule(
                    permissions=[fperm.view]))

            resp = self.end_flow()
            self.assertEqual(resp.status_code, 403)

    def test_odd_post_parameter(self):
        resp = self.end_flow(post_parameter="unknown")
        self.assertEqual(resp.status_code, 400)

    def test_finish_non_in_progress_session(self):
        fs = factories.FlowSessionFactory(
            course=self.course, participation=self.student_participation,
            in_progress=False
        )
        # re-submit finish flow
        resp = self.end_flow(
            course_identifier=self.course.identifier,
            flow_session_id=fs.pk)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertIn(
            "Cannot end a session that's already ended",
            self.mock_add_message.call_args[0])

    def test_notify_on_submit_emtpy(self):
        with mock.patch("course.utils.get_flow_desc") as mock_get_flow_desc:
            mock_get_flow_desc.return_value = (
                self.get_hacked_flow_desc(
                    # no recepient
                    notify_on_submit=[])
            )
            self.start_flow(self.flow_id)
            self.end_flow()

            self.assertEqual(len(mail.outbox), 0)

    def test_notify_on_submit_no_grade_identifier(self):
        with mock.patch(
                "course.flow.get_session_grading_rule") as mock_get_grule:
            mock_get_grule.return_value = \
                self.get_hacked_session_grading_rule(grade_identifier=None)
            notify_on_submit_emails = ["test_notif@example.com"]
            with mock.patch("course.utils.get_flow_desc") as mock_get_flow_desc:
                mock_get_flow_desc.return_value = (
                    self.get_hacked_flow_desc(
                        notify_on_submit=notify_on_submit_emails)
                )
                self.start_flow(self.flow_id)

                fs = models.FlowSession.objects.first()
                fs.participation = None
                fs.user = None
                fs.save()

                self.end_flow()

            self.assertEqual(len(mail.outbox), 1)
            expected_review_uri = reverse("relate-view_flow_page",
                                          args=(
                                              self.course.identifier,
                                              fs.id, 0))

            self.assertIn(
                expected_review_uri,
                mail.outbox[0].body)

    def test_notify_on_submit_no_participation(self):
        notify_on_submit_emails = ["test_notif@example.com"]
        with mock.patch("course.utils.get_flow_desc") as mock_get_flow_desc:
            mock_get_flow_desc.return_value = (
                self.get_hacked_flow_desc(
                    notify_on_submit=notify_on_submit_emails)
            )
            fs = models.FlowSession.objects.first()
            fs.participation = None
            fs.user = None
            fs.save()

            self.end_flow()

        self.assertEqual(len(mail.outbox), 1)
        expected_review_uri = reverse("relate-view_flow_page",
                                      args=(
                                          self.course.identifier,
                                          fs.id, 0))

        self.assertIn(
            expected_review_uri,
            mail.outbox[0].body)

    def test_notify_on_submit(self):
        notify_on_submit_emails = ["test_notif@example.com"]
        with mock.patch("course.utils.get_flow_desc") as mock_get_flow_desc:
            mock_get_flow_desc.return_value = (
                self.get_hacked_flow_desc(
                    notify_on_submit=notify_on_submit_emails)
            )
            self.start_flow(self.flow_id)
            self.end_flow()

        gopp = models.GradingOpportunity.objects.first()

        expected_review_uri = reverse("relate-view_single_grade",
                                      args=(
                                          self.course.identifier,
                                          self.student_participation.pk,
                                          gopp.pk
                                      ))

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            mail.outbox[0].recipients(),
            notify_on_submit_emails + [self.course.notify_email])

        self.assertIn(
            self.student_participation.user.username,
            mail.outbox[0].body)
        self.assertIn(
            expected_review_uri,
            mail.outbox[0].body)
        self.assertIn(
            self.student_participation.user.username,
            mail.outbox[0].subject)

    def test_notify_on_submit_use_masked_profile(self):
        self.mock_will_use_masked_profile_for_email.return_value = True
        notify_on_submit_emails = [
            "test_notif@example.com", self.ta_participation.user.email]
        with mock.patch("course.utils.get_flow_desc") as mock_get_flow_desc:
            mock_get_flow_desc.return_value = (
                self.get_hacked_flow_desc(
                    notify_on_submit=notify_on_submit_emails)
            )
            self.end_flow()

        gopp = models.GradingOpportunity.objects.first()
        expected_review_uri = reverse("relate-view_single_grade",
                                      args=(
                                          self.course.identifier,
                                          self.student_participation.pk,
                                          gopp.pk
                                      ))

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(
            expected_review_uri,
            mail.outbox[0].body)

        self.assertNotIn(
            self.student_participation.user.username,
            mail.outbox[0].body)
        self.assertNotIn(
            self.student_participation.user.username,
            mail.outbox[0].subject)

        self.assertNotIn(
            self.student_participation.user.get_full_name(),
            mail.outbox[0].body)
        self.assertNotIn(
            self.student_participation.user.get_full_name(),
            mail.outbox[0].subject)

    def test_notify_on_submit_no_participation_use_masked_profile(self):
        self.mock_will_use_masked_profile_for_email.return_value = True
        notify_on_submit_emails = ["test_notif@example.com"]
        with mock.patch("course.utils.get_flow_desc") as mock_get_flow_desc:
            mock_get_flow_desc.return_value = (
                self.get_hacked_flow_desc(
                    notify_on_submit=notify_on_submit_emails)
            )
            fs = models.FlowSession.objects.first()
            fs.participation = None
            fs.user = None
            fs.save()

            self.end_flow()

        self.assertEqual(len(mail.outbox), 1)
        expected_review_uri = reverse("relate-view_flow_page",
                                      args=(
                                          self.course.identifier,
                                          fs.id, 0))

        self.assertIn(expected_review_uri, mail.outbox[0].body)

    def test_get_finish_non_interactive_flow(self):
        resp = self.start_flow(flow_id="001-linalg-recap")
        self.assertEqual(resp.status_code, 302)
        resp = self.c.get(self.get_finish_flow_session_view_url())
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "course/flow-completion.html")

    def test_get_finish_interactive_flow_with_unfinished_pages(self):
        self.start_flow(flow_id=self.flow_id)
        resp = self.c.get(self.get_finish_flow_session_view_url())
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "course/flow-confirm-completion.html")
        self.assertResponseHasNoContext(resp, "grade_info")
        self.assertResponseContextEqual(resp, "answered_count", 3)

    def test_post_finish_non_interactive_flow(self):
        with mock.patch(
                "course.flow.get_session_access_rule") as mock_get_arule:
            # This has to be done, or we won't be able to end the flow session,
            # though the session doesn't need to be ended.
            mock_get_arule.return_value = (
                self.get_hacked_session_access_rule(
                    permissions=[fperm.view, fperm.end_session]))
            resp = self.start_flow(flow_id="001-linalg-recap")
            self.assertEqual(resp.status_code, 302)
            resp = self.end_flow()
            self.assertEqual(resp.status_code, 200)
            self.assertTemplateUsed(resp, "course/flow-completion.html")

    def test_post_finish_with_cannot_see_flow_result_access_rule(self):
        with mock.patch(
                "course.flow.get_session_access_rule") as mock_get_arule:
            # This has to be done, or we won't be able to end the flow session,
            # though the session doesn't need to be ended.
            mock_get_arule.return_value = (
                self.get_hacked_session_access_rule(
                    permissions=[
                        fperm.view, fperm.end_session,
                        fperm.cannot_see_flow_result]))
            resp = self.end_flow()
            self.assertEqual(resp.status_code, 200)
            self.assertTemplateUsed(resp, "course/flow-completion-grade.html")
            self.assertResponseContextIsNone(resp, "grade_info")

            # Then we get the finish page
            resp = self.c.get(self.get_finish_flow_session_view_url())
            self.assertEqual(resp.status_code, 200)
            self.assertTemplateUsed(resp, "course/flow-completion-grade.html")
            self.assertResponseContextIsNone(resp, "grade_info")


class FinishFlowSessionTest(SingleCourseTestMixin, TestCase):
    # test flow.finish_flow_session
    def setUp(self):
        super(FinishFlowSessionTest, self).setUp()
        self.fctx = mock.MagicMock()

    def test_finish_non_in_progress_session(self):
        flow_session = factories.FlowSessionFactory(
            participation=self.student_participation, in_progress=False)
        grading_rule = mock.MagicMock()

        with mock.patch(
                "course.flow.assemble_answer_visits") as mock_asv, mock.patch(
                "course.flow.grade_page_visits") as mock_gpv, mock.patch(
                "course.flow.grade_flow_session") as mock_gfs:
            expected_error_msg = "Can't end a session that's already ended"
            with self.assertRaises(RuntimeError) as cm:
                flow.finish_flow_session(self.fctx, flow_session, grading_rule)

            self.assertIn(expected_error_msg, str(cm.exception))

            self.assertEqual(mock_asv.call_count, 0)
            self.assertEqual(mock_gpv.call_count, 0)
            self.assertEqual(mock_gfs.call_count, 0)

    def test_now_datetime(self):
        flow_session = factories.FlowSessionFactory(
            participation=self.student_participation, in_progress=True)
        grading_rule = FlowSessionGradingRule(
            grade_identifier="la_quiz",
            grade_aggregation_strategy=g_strategy.use_latest,
            due=None,
            generates_grade=True,
            use_last_activity_as_completion_time=False
        )
        force_regrade = mock.MagicMock()
        respect_preview = mock.MagicMock

        now_datetime = now() - timedelta(days=1)
        with mock.patch(
                "course.flow.assemble_answer_visits") as mock_asv, mock.patch(
                "course.flow.grade_page_visits") as mock_gpv, mock.patch(
                "course.flow.grade_flow_session") as mock_gfs:
            flow.finish_flow_session(
                self.fctx, flow_session, grading_rule, force_regrade,
                now_datetime, respect_preview)

            self.assertEqual(flow_session.completion_time, now_datetime)
            self.assertFalse(flow_session.in_progress)

            self.assertEqual(mock_asv.call_count, 1)
            self.assertEqual(mock_gpv.call_count, 1)
            self.assertEqual(mock_gfs.call_count, 1)

            # make sure "answer_visits" is not None when calling
            # grade_flow_session
            self.assertIn(mock_asv.return_value, mock_gfs.call_args[0])

    def test_now_datetime_none(self):
        flow_session = factories.FlowSessionFactory(
            participation=self.student_participation, in_progress=True)
        grading_rule = FlowSessionGradingRule(
            grade_identifier="la_quiz",
            grade_aggregation_strategy=g_strategy.use_latest,  # noqa
            due=None,
            generates_grade=True,
            use_last_activity_as_completion_time=False
        )
        force_regrade = mock.MagicMock()
        respect_preview = mock.MagicMock

        now_datetime = None

        faked_now = now() - timedelta(days=1)

        with mock.patch(
                "course.flow.assemble_answer_visits") as mock_asv, mock.patch(
                "course.flow.grade_page_visits") as mock_gpv, mock.patch(
                "course.flow.grade_flow_session") as mock_gfs, mock.patch(
                "django.utils.timezone.now") as mock_now:
            mock_now.return_value = faked_now
            flow.finish_flow_session(
                self.fctx, flow_session, grading_rule, force_regrade,
                now_datetime, respect_preview)

            self.assertEqual(flow_session.completion_time, faked_now)
            self.assertFalse(flow_session.in_progress)

            self.assertEqual(mock_asv.call_count, 1)
            self.assertEqual(mock_gpv.call_count, 1)
            self.assertEqual(mock_gfs.call_count, 1)

            # make sure "answer_visits" is not None when calling
            # grade_flow_session
            self.assertIn(mock_asv.return_value, mock_gfs.call_args[0])

    def test_rule_use_last_activity_as_completion_time_no_last_activity(self):
        flow_session = factories.FlowSessionFactory(
            participation=self.student_participation, in_progress=True)

        grading_rule = FlowSessionGradingRule(
            grade_identifier="la_quiz",
            grade_aggregation_strategy=g_strategy.use_latest,  # noqa
            due=None,
            generates_grade=True,
            use_last_activity_as_completion_time=True
        )
        force_regrade = mock.MagicMock()
        respect_preview = mock.MagicMock

        now_datetime = None
        faked_now = now() - timedelta(days=1)

        with mock.patch(
                "course.flow.assemble_answer_visits") as mock_asv, mock.patch(
                "course.flow.grade_page_visits") as mock_gpv, mock.patch(
                "course.flow.grade_flow_session") as mock_gfs, mock.patch(
                "django.utils.timezone.now") as mock_now:
            mock_now.return_value = faked_now

            flow.finish_flow_session(
                self.fctx, flow_session, grading_rule, force_regrade,
                now_datetime, respect_preview)

            self.assertIsNotNone(flow_session.completion_time)
            self.assertFalse(flow_session.in_progress)

            self.assertEqual(mock_asv.call_count, 1)
            self.assertEqual(mock_gpv.call_count, 1)
            self.assertEqual(mock_gfs.call_count, 1)

            # make sure "answer_visits" is not None when calling
            # grade_flow_session
            self.assertIn(mock_asv.return_value, mock_gfs.call_args[0])

            self.assertEqual(flow_session.completion_time, faked_now)

    def test_rule_use_last_activity_as_completion_time(self):
        flow_session = factories.FlowSessionFactory(
            participation=self.student_participation, in_progress=True)
        page_data = factories.FlowPageDataFactory(
            flow_session=flow_session
        )

        answer_visit_time = now() - timedelta(days=1)
        factories.FlowPageVisitFactory(
            page_data=page_data, answer={"answer": "hi"},
            visit_time=answer_visit_time)

        null_answer_visit_time = now() + timedelta(minutes=60)

        # this visit happened after the answer visit
        factories.FlowPageVisitFactory(
            page_data=page_data, answer=None,
            visit_time=null_answer_visit_time)

        grading_rule = FlowSessionGradingRule(
            grade_identifier="la_quiz",
            grade_aggregation_strategy=g_strategy.use_latest,  # noqa
            due=None,
            generates_grade=True,
            use_last_activity_as_completion_time=True
        )
        force_regrade = mock.MagicMock()
        respect_preview = mock.MagicMock

        now_datetime = now()

        with mock.patch(
                "course.flow.assemble_answer_visits") as mock_asv, mock.patch(
                "course.flow.grade_page_visits") as mock_gpv, mock.patch(
                "course.flow.grade_flow_session") as mock_gfs:
            flow.finish_flow_session(
                self.fctx, flow_session, grading_rule, force_regrade,
                now_datetime, respect_preview)

            self.assertIsNotNone(flow_session.completion_time)
            self.assertFalse(flow_session.in_progress)

            self.assertEqual(mock_asv.call_count, 1)
            self.assertEqual(mock_gpv.call_count, 1)
            self.assertEqual(mock_gfs.call_count, 1)

            # make sure "answer_visits" is not None when calling
            # grade_flow_session
            self.assertIn(mock_asv.return_value, mock_gfs.call_args[0])

            self.assertEqual(flow_session.completion_time, answer_visit_time)


class ExpireFlowSessionTest(SingleCourseTestMixin, TestCase):
    # test flow.expire_flow_session
    def setUp(self):
        super(ExpireFlowSessionTest, self).setUp()
        self.fctx = mock.MagicMock()

        fake_adjust_flow_session_page_data = mock.patch(
            "course.flow.adjust_flow_session_page_data")
        self.mock_adjust_flow_session_page_data = (
            fake_adjust_flow_session_page_data.start())
        self.mock_adjust_flow_session_page_data.return_value = None
        self.addCleanup(fake_adjust_flow_session_page_data.stop)

        fake_finish_flow_session = mock.patch("course.flow.finish_flow_session")
        self.mock_finish_flow_session = fake_finish_flow_session.start()
        self.addCleanup(fake_finish_flow_session.stop)

        fake_get_session_start_rule = mock.patch(
            "course.flow.get_session_start_rule")
        self.mock_get_session_start_rule = fake_get_session_start_rule.start()
        self.addCleanup(fake_get_session_start_rule.stop)

        self.now_datatime = now()

    def test_expire_non_in_progess_session(self):
        flow_session = factories.FlowSessionFactory(
            participation=self.student_participation, in_progress=False)
        grading_rule = mock.MagicMock()

        expected_error_msg = "Can't expire a session that's not in progress"
        with self.assertRaises(RuntimeError) as cm:
            flow.expire_flow_session(
                self.fctx, flow_session, grading_rule, self.now_datatime)

        self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 0)
        self.assertEqual(self.mock_finish_flow_session.call_count, 0)
        self.assertEqual(self.mock_get_session_start_rule.call_count, 0)

    def test_expire_session_of_anonymous_user(self):
        flow_session = factories.FlowSessionFactory(
            course=self.course, participation=None, user=None, in_progress=True)
        grading_rule = mock.MagicMock()

        expected_error_msg = "Can't expire an anonymous flow session"
        with self.assertRaises(RuntimeError) as cm:
            flow.expire_flow_session(
                self.fctx, flow_session, grading_rule, self.now_datatime)

        self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 0)
        self.assertEqual(self.mock_finish_flow_session.call_count, 0)
        self.assertEqual(self.mock_get_session_start_rule.call_count, 0)

    def test_past_due_only_due_none(self):
        flow_session = factories.FlowSessionFactory(
            participation=self.student_participation, in_progress=True)
        grading_rule = FlowSessionGradingRule(
            grade_identifier="la_quiz",
            grade_aggregation_strategy=g_strategy.use_latest,  # noqa
            due=None,
            generates_grade=True,
            use_last_activity_as_completion_time=False
        )

        self.assertFalse(flow.expire_flow_session(
            self.fctx, flow_session, grading_rule, self.now_datatime,
            past_due_only=True))

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 0)
        self.assertEqual(self.mock_finish_flow_session.call_count, 0)
        self.assertEqual(self.mock_get_session_start_rule.call_count, 0)

    def test_past_due_only_now_datetime_not_due(self):
        flow_session = factories.FlowSessionFactory(
            participation=self.student_participation, in_progress=True)

        due = self.now_datatime + timedelta(hours=1)

        grading_rule = FlowSessionGradingRule(
            grade_identifier="la_quiz",
            grade_aggregation_strategy=g_strategy.use_latest,
            due=due,
            generates_grade=True,
            use_last_activity_as_completion_time=False
        )

        self.assertFalse(flow.expire_flow_session(
            self.fctx, flow_session, grading_rule, self.now_datatime,
            past_due_only=True))

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 0)
        self.assertEqual(self.mock_finish_flow_session.call_count, 0)
        self.assertEqual(self.mock_get_session_start_rule.call_count, 0)

    def test_past_due_only_now_datetime_other_case(self):
        flow_session = factories.FlowSessionFactory(
            participation=self.student_participation, in_progress=True)

        due = self.now_datatime - timedelta(hours=1)

        grading_rule = FlowSessionGradingRule(
            grade_identifier="la_quiz",
            grade_aggregation_strategy=g_strategy.use_latest,
            due=due,
            generates_grade=True,
            use_last_activity_as_completion_time=False
        )

        flow.expire_flow_session(
            self.fctx, flow_session, grading_rule, self.now_datatime,
            past_due_only=True)

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 1)
        self.assertEqual(self.mock_finish_flow_session.call_count, 1)
        self.assertEqual(self.mock_get_session_start_rule.call_count, 0)

    def test_expiration_mode_rollover_not_may_start_new_session(self):
        flow_session = factories.FlowSessionFactory(
            participation=self.student_participation, in_progress=True,
            expiration_mode=constants.flow_session_expiration_mode.roll_over
        )

        self.mock_get_session_start_rule.return_value = (
            FlowSessionStartRule(
                tag_session="roll_over_tag",
                may_start_new_session=False
            ))

        grading_rule = FlowSessionGradingRule(
            grade_identifier="la_quiz",
            grade_aggregation_strategy=g_strategy.use_latest,
            due=None,
            generates_grade=True,
            use_last_activity_as_completion_time=False
        )

        self.assertTrue(flow.expire_flow_session(
            self.fctx, flow_session, grading_rule, self.now_datatime))

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 1)
        self.assertEqual(self.mock_finish_flow_session.call_count, 1)
        self.assertEqual(self.mock_get_session_start_rule.call_count, 1)
        self.assertTrue(
            self.mock_get_session_start_rule.call_args[1]["for_rollover"])

    def test_expiration_mode_end(self):
        flow_session = factories.FlowSessionFactory(
            participation=self.student_participation, in_progress=True,
            expiration_mode=constants.flow_session_expiration_mode.end
        )

        grading_rule = FlowSessionGradingRule(
            grade_identifier="la_quiz",
            grade_aggregation_strategy=g_strategy.use_latest,
            due=None,
            generates_grade=True,
            use_last_activity_as_completion_time=False
        )

        self.assertTrue(flow.expire_flow_session(
            self.fctx, flow_session, grading_rule, self.now_datatime))

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 1)
        self.assertEqual(self.mock_finish_flow_session.call_count, 1)
        self.assertEqual(self.mock_get_session_start_rule.call_count, 0)

    def test_invalid_expiration_mode(self):
        flow_session = factories.FlowSessionFactory(
            participation=self.student_participation, in_progress=True,
            expiration_mode="unknown"
        )

        due = self.now_datatime - timedelta(hours=1)

        grading_rule = FlowSessionGradingRule(
            grade_identifier="la_quiz",
            grade_aggregation_strategy=g_strategy.use_latest,
            due=due,
            generates_grade=True,
            use_last_activity_as_completion_time=False
        )

        expected_error_msg = ("invalid expiration mode 'unknown' "
                              "on flow session ID 1")
        with self.assertRaises(ValueError) as cm:
            flow.expire_flow_session(
                self.fctx, flow_session, grading_rule, self.now_datatime)

        self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 1)
        self.assertEqual(self.mock_finish_flow_session.call_count, 0)
        self.assertEqual(self.mock_get_session_start_rule.call_count, 0)


class GetFlowSessionAttemptIdTest(unittest.TestCase):
    # test flow.get_flow_session_attempt_id

    def setUp(self):
        def remove_all_course():
            for course in models.Course.objects.all():
                course.delete()

        self.addCleanup(remove_all_course)

    def test(self):
        course = factories.CourseFactory()
        participation = factories.ParticipationFactory(course=course)
        fs1 = factories.FlowSessionFactory(participation=participation)
        fs2 = factories.FlowSessionFactory(participation=participation)

        self.assertNotEqual(
            flow.get_flow_session_attempt_id(fs1),
            flow.get_flow_session_attempt_id(fs2))

        self.assertNotEqual(flow.get_flow_session_attempt_id(fs1), "main")
        self.assertNotEqual(flow.get_flow_session_attempt_id(fs2), "main")


class GradeFlowSessionTest(SingleCourseQuizPageTestMixin,
                           HackRepoMixin, TestCase):
    # test flow.grade_flow_session

    initial_commit_sha = "my_fake_commit_sha_for_grade_flow_session"

    def setUp(self):
        super(GradeFlowSessionTest, self).setUp()

        self.fctx = mock.MagicMock()
        self.fctx.title = "my flow session title"

        fake_gather_grade_info = mock.patch("course.flow.gather_grade_info")
        self.mock_gather_grade_info = fake_gather_grade_info.start()
        self.addCleanup(fake_gather_grade_info.stop)

        fake_assemble_answer_visits = mock.patch(
            "course.flow.assemble_answer_visits")
        self.mock_assemble_answer_visits = fake_assemble_answer_visits.start()
        self.addCleanup(fake_assemble_answer_visits.stop)

        fake_get_flow_grading_opportunity = mock.patch(
            "course.models.get_flow_grading_opportunity")
        self.mock_get_flow_grading_opportunity = \
            fake_get_flow_grading_opportunity.start()
        self.gopp = factories.GradingOpportunityFactory(course=self.course)
        self.mock_get_flow_grading_opportunity.return_value = (self.gopp)
        self.addCleanup(fake_get_flow_grading_opportunity.stop)

    def get_test_grade_info(self, **kwargs):
        defaults = {
            "fully_correct_count": 0,
            "incorrect_count": 0,
            "max_points": 10.0,
            "max_reachable_points": 8.0,
            "optional_fully_correct_count": 0,
            "optional_incorrect_count": 0,
            "optional_partially_correct_count": 0,
            "optional_unknown_count": 0,
            "partially_correct_count": 1,
            "points": 5.0,
            "provisional_points": 8.0,
            "unknown_count": 0
        }
        defaults.update(kwargs)
        return flow.GradeInfo(**defaults)

    def get_test_grading_rule(self, **kwargs):
        defaults = {
            "grade_identifier": "la_quiz",
            "grade_aggregation_strategy": g_strategy.use_latest,
            "due": None,
            "generates_grade": True,
            "use_last_activity_as_completion_time": False,
            "credit_percent": 100
        }
        defaults.update(kwargs)
        return FlowSessionGradingRule(**defaults)

    def get_default_test_session(self, **kwargs):
        defaults = {"participation": self.student_participation,
                    "in_progress": False}
        defaults.update(kwargs)
        return factories.FlowSessionFactory(**defaults)

    def test_answer_visits_none(self):
        flow_session = self.get_default_test_session()
        grading_rule = self.get_test_grading_rule()
        answer_visits = None

        grade_info = self.get_test_grade_info()
        self.mock_gather_grade_info.return_value = grade_info

        result = flow.grade_flow_session(
            self.fctx, flow_session, grading_rule, answer_visits)

        # when answer_visits is None, assemble_answer_visits should be called
        self.assertEqual(self.mock_assemble_answer_visits.call_count, 1)

        self.assertEqual(self.mock_get_flow_grading_opportunity.call_count, 1)

        flow_session.refresh_from_db()
        self.assertEqual(flow_session.points, 5)
        self.assertEqual(flow_session.max_points, 10)

        # grading_rule.credit_percent is 100
        self.assertIsNone(flow_session.result_comment)

        # it should return the grade_info calculated
        self.assertEqual(result, grade_info)

        current_grade_changes = models.GradeChange.objects.all()
        self.assertEqual(current_grade_changes.count(), 1)

    def test_not_append_comments_when_no_points(self):
        flow_session = self.get_default_test_session()
        grading_rule = self.get_test_grading_rule(credit_percent=110)
        answer_visits = mock.MagicMock()

        grade_info = self.get_test_grade_info(points=None)
        self.mock_gather_grade_info.return_value = grade_info

        result = flow.grade_flow_session(
            self.fctx, flow_session, grading_rule, answer_visits)

        # when answer_visits is not None, assemble_answer_visits should not be
        # called
        self.assertEqual(self.mock_assemble_answer_visits.call_count, 0)

        self.assertEqual(self.mock_get_flow_grading_opportunity.call_count, 1)

        flow_session.refresh_from_db()
        self.assertEqual(flow_session.points, None)
        self.assertEqual(flow_session.max_points, 10)
        self.assertIsNone(flow_session.result_comment)

        # it should return the grade_info calculated
        self.assertEqual(result, grade_info)

        current_grade_changes = models.GradeChange.objects.all()

        # no points won't result in grade change objects creation.
        self.assertEqual(current_grade_changes.count(), 0)

    def test_not_append_comments_when_no_credit_percent(self):
        flow_session = self.get_default_test_session()
        grading_rule = self.get_test_grading_rule(credit_percent=None)
        answer_visits = mock.MagicMock()

        grade_info = self.get_test_grade_info()
        self.mock_gather_grade_info.return_value = grade_info

        result = flow.grade_flow_session(
            self.fctx, flow_session, grading_rule, answer_visits)

        # when answer_visits is not None, assemble_answer_visits should not be
        # called
        self.assertEqual(self.mock_assemble_answer_visits.call_count, 0)

        self.assertEqual(self.mock_get_flow_grading_opportunity.call_count, 1)

        flow_session.refresh_from_db()
        self.assertEqual(flow_session.points, 5)
        self.assertEqual(flow_session.max_points, 10)
        self.assertIsNone(flow_session.result_comment)

        # it should return the grade_info calculated
        self.assertEqual(result, grade_info)

        current_grade_changes = models.GradeChange.objects.all()
        self.assertEqual(current_grade_changes.count(), 1)

    def test_not_append_comments(self):
        flow_session = self.get_default_test_session()
        grading_rule = self.get_test_grading_rule(credit_percent=110)
        answer_visits = mock.MagicMock()

        grade_info = self.get_test_grade_info()
        self.mock_gather_grade_info.return_value = grade_info

        result = flow.grade_flow_session(
            self.fctx, flow_session, grading_rule, answer_visits)

        # when answer_visits is not None, assemble_answer_visits should not be
        # called
        self.assertEqual(self.mock_assemble_answer_visits.call_count, 0)

        self.assertEqual(self.mock_get_flow_grading_opportunity.call_count, 1)

        flow_session.refresh_from_db()
        self.assertEqual(flow_session.points, 5.5)
        self.assertEqual(flow_session.max_points, 10)
        self.assertEqual(
            flow_session.result_comment, 'Counted at 110.0% of 5.0 points')

        # it should return the grade_info calculated
        self.assertEqual(result, grade_info)

        current_grade_changes = models.GradeChange.objects.all()
        self.assertEqual(current_grade_changes.count(), 1)

    def test_no_grade_identifier(self):
        flow_session = self.get_default_test_session()
        grading_rule = self.get_test_grading_rule(grade_identifier=None)
        answer_visits = mock.MagicMock()

        grade_info = self.get_test_grade_info()
        self.mock_gather_grade_info.return_value = grade_info

        result = flow.grade_flow_session(
            self.fctx, flow_session, grading_rule, answer_visits)

        # when answer_visits is not None, assemble_answer_visits should not be
        # called
        self.assertEqual(self.mock_assemble_answer_visits.call_count, 0)

        self.assertEqual(self.mock_get_flow_grading_opportunity.call_count, 0)

        flow_session.refresh_from_db()
        self.assertEqual(flow_session.points, 5)
        self.assertEqual(flow_session.max_points, 10)
        self.assertIsNone(flow_session.result_comment)

        # it should return the grade_info calculated
        self.assertEqual(result, grade_info)

        current_grade_changes = models.GradeChange.objects.all()
        self.assertEqual(current_grade_changes.count(), 0)

    def test_not_generates_grade(self):
        flow_session = self.get_default_test_session()
        grading_rule = self.get_test_grading_rule(generates_grade=False)
        answer_visits = mock.MagicMock()

        grade_info = self.get_test_grade_info()
        self.mock_gather_grade_info.return_value = grade_info

        result = flow.grade_flow_session(
            self.fctx, flow_session, grading_rule, answer_visits)

        # when answer_visits is not None, assemble_answer_visits should not be
        # called
        self.assertEqual(self.mock_assemble_answer_visits.call_count, 0)

        self.assertEqual(self.mock_get_flow_grading_opportunity.call_count, 0)

        flow_session.refresh_from_db()
        self.assertEqual(flow_session.points, 5)
        self.assertEqual(flow_session.max_points, 10)
        self.assertIsNone(flow_session.result_comment)

        # it should return the grade_info calculated
        self.assertEqual(result, grade_info)

        current_grade_changes = models.GradeChange.objects.all()
        self.assertEqual(current_grade_changes.count(), 0)

    def test_session_has_no_participation(self):
        flow_session = self.get_default_test_session(
            course=self.course,
            participation=None, user=None)
        grading_rule = self.get_test_grading_rule()
        answer_visits = mock.MagicMock()

        grade_info = self.get_test_grade_info()
        self.mock_gather_grade_info.return_value = grade_info

        result = flow.grade_flow_session(
            self.fctx, flow_session, grading_rule, answer_visits)

        # when answer_visits is not None, assemble_answer_visits should not be
        # called
        self.assertEqual(self.mock_assemble_answer_visits.call_count, 0)

        self.assertEqual(self.mock_get_flow_grading_opportunity.call_count, 0)

        flow_session.refresh_from_db()
        self.assertEqual(flow_session.points, 5)
        self.assertEqual(flow_session.max_points, 10)
        self.assertIsNone(flow_session.result_comment)

        # it should return the grade_info calculated
        self.assertEqual(result, grade_info)

        current_grade_changes = models.GradeChange.objects.all()
        self.assertEqual(current_grade_changes.count(), 0)

    def create_grade_change(self, flow_session, **kwargs):
        from course.flow import get_flow_session_attempt_id
        defaults = {
            "flow_session": flow_session,
            "opportunity": self.gopp,
            "participation": self.student_participation,
            "state": constants.grade_state_change_types.graded,
            "attempt_id": get_flow_session_attempt_id(flow_session),
            "points": 5,
            "max_points": 10,
            "comment": None,
            "grade_time": now()
        }
        defaults.update(kwargs)
        factories.GradeChangeFactory(**defaults)

    def test_has_identical_previous_grade_changes(self):
        flow_session = self.get_default_test_session()
        grading_rule = self.get_test_grading_rule()
        answer_visits = mock.MagicMock()

        grade_info = self.get_test_grade_info()
        self.mock_gather_grade_info.return_value = grade_info

        # create an indentical previous_grade_changes
        grade_time1 = now() - timedelta(days=1)
        grade_time2 = grade_time1 + timedelta(hours=1)

        self.create_grade_change(
            flow_session=flow_session,
            grade_time=grade_time1,
            comment="no comments")

        # to ensure the second one is used, it has a different comment with
        # the above one
        self.create_grade_change(
            flow_session=flow_session,
            grade_time=grade_time2,
            comment=None)

        result = flow.grade_flow_session(
            self.fctx, flow_session, grading_rule, answer_visits)

        # when answer_visits is not None, assemble_answer_visits should not be
        # called
        self.assertEqual(self.mock_assemble_answer_visits.call_count, 0)

        self.assertEqual(self.mock_get_flow_grading_opportunity.call_count, 1)

        flow_session.refresh_from_db()
        self.assertEqual(flow_session.points, 5)
        self.assertEqual(flow_session.max_points, 10)
        self.assertIsNone(flow_session.result_comment)

        # it should return the grade_info calculated
        self.assertEqual(result, grade_info)

        current_grade_changes = models.GradeChange.objects.all()

        # no new grade change objects is created
        self.assertEqual(current_grade_changes.count(), 2)

    def test_previous_grade_change_points_changed(self):
        flow_session = self.get_default_test_session()
        grading_rule = self.get_test_grading_rule()
        answer_visits = mock.MagicMock()

        grade_info = self.get_test_grade_info()
        self.mock_gather_grade_info.return_value = grade_info

        grade_time1 = now() - timedelta(days=1)

        self.create_grade_change(
            flow_session=flow_session,
            grade_time=grade_time1,
            points=4)

        result = flow.grade_flow_session(
            self.fctx, flow_session, grading_rule, answer_visits)

        # when answer_visits is not None, assemble_answer_visits should not be
        # called
        self.assertEqual(self.mock_assemble_answer_visits.call_count, 0)

        self.assertEqual(self.mock_get_flow_grading_opportunity.call_count, 1)

        flow_session.refresh_from_db()
        self.assertEqual(flow_session.points, 5)
        self.assertEqual(flow_session.max_points, 10)
        self.assertIsNone(flow_session.result_comment)

        # it should return the grade_info calculated
        self.assertEqual(result, grade_info)

        current_grade_changes = models.GradeChange.objects.all()

        # a new grade change objects is created
        self.assertEqual(current_grade_changes.count(), 2)
        self.assertEqual(current_grade_changes.last().points, 5)

    def test_previous_grade_change_max_points_changed(self):
        flow_session = self.get_default_test_session()
        grading_rule = self.get_test_grading_rule()
        answer_visits = mock.MagicMock()

        grade_info = self.get_test_grade_info()
        self.mock_gather_grade_info.return_value = grade_info

        grade_time1 = now() - timedelta(days=1)

        self.create_grade_change(
            flow_session=flow_session,
            grade_time=grade_time1,
            max_points=12)

        result = flow.grade_flow_session(
            self.fctx, flow_session, grading_rule, answer_visits)

        # when answer_visits is not None, assemble_answer_visits should not be
        # called
        self.assertEqual(self.mock_assemble_answer_visits.call_count, 0)

        self.assertEqual(self.mock_get_flow_grading_opportunity.call_count, 1)

        flow_session.refresh_from_db()
        self.assertEqual(flow_session.points, 5)
        self.assertEqual(flow_session.max_points, 10)
        self.assertIsNone(flow_session.result_comment)

        # it should return the grade_info calculated
        self.assertEqual(result, grade_info)

        current_grade_changes = models.GradeChange.objects.all()

        # a new grade change objects is created
        self.assertEqual(current_grade_changes.count(), 2)
        self.assertEqual(current_grade_changes.last().max_points, 10)

    def test_previous_grade_change_gchange_state_changed(self):
        flow_session = self.get_default_test_session()
        grading_rule = self.get_test_grading_rule()
        answer_visits = mock.MagicMock()

        grade_info = self.get_test_grade_info()
        self.mock_gather_grade_info.return_value = grade_info

        grade_time1 = now() - timedelta(days=1)

        self.create_grade_change(
            flow_session=flow_session,
            grade_time=grade_time1,
            state="other state")

        result = flow.grade_flow_session(
            self.fctx, flow_session, grading_rule, answer_visits)

        # when answer_visits is not None, assemble_answer_visits should not be
        # called
        self.assertEqual(self.mock_assemble_answer_visits.call_count, 0)

        self.assertEqual(self.mock_get_flow_grading_opportunity.call_count, 1)

        flow_session.refresh_from_db()
        self.assertEqual(flow_session.points, 5)
        self.assertEqual(flow_session.max_points, 10)
        self.assertIsNone(flow_session.result_comment)

        # it should return the grade_info calculated
        self.assertEqual(result, grade_info)

        current_grade_changes = models.GradeChange.objects.all()

        # a new grade change objects is created
        self.assertEqual(current_grade_changes.count(), 2)
        self.assertEqual(current_grade_changes.last().state,
                         constants.grade_state_change_types.graded)

    def test_previous_grade_change_comment_different(self):
        flow_session = self.get_default_test_session()
        grading_rule = self.get_test_grading_rule()
        answer_visits = mock.MagicMock()

        grade_info = self.get_test_grade_info()
        self.mock_gather_grade_info.return_value = grade_info

        grade_time1 = now() - timedelta(days=1)

        self.create_grade_change(
            flow_session=flow_session,
            grade_time=grade_time1,
            comment="no comments")

        result = flow.grade_flow_session(
            self.fctx, flow_session, grading_rule, answer_visits)

        # when answer_visits is not None, assemble_answer_visits should not be
        # called
        self.assertEqual(self.mock_assemble_answer_visits.call_count, 0)

        self.assertEqual(self.mock_get_flow_grading_opportunity.call_count, 1)

        flow_session.refresh_from_db()
        self.assertEqual(flow_session.points, 5)
        self.assertEqual(flow_session.max_points, 10)
        self.assertIsNone(flow_session.result_comment)

        # it should return the grade_info calculated
        self.assertEqual(result, grade_info)

        current_grade_changes = models.GradeChange.objects.all()

        # a new grade change objects is created
        self.assertEqual(current_grade_changes.count(), 2)
        self.assertEqual(current_grade_changes.last().comment, None)


class UnsubmitPageTest(unittest.TestCase):
    # test flow.unsubmit_page

    def setUp(self):
        def remove_all_course():
            for course in models.Course.objects.all():
                course.delete()

        self.addCleanup(remove_all_course)

    def test(self):
        now_datetime = now() + timedelta(days=1)
        fpv = factories.FlowPageVisitFactory(is_submitted_answer=True,
                                             remote_address="127.0.0.1",
                                             is_synthetic=False)

        exist_fpv_count = models.FlowPageVisit.objects.count()
        self.assertEqual(exist_fpv_count, 1)
        flow.unsubmit_page(fpv, now_datetime)

        fpvs = models.FlowPageVisit.objects.all()
        self.assertEqual(fpvs.count(), 2)

        new_fpv = fpvs.last()
        self.assertEqual(new_fpv.visit_time, now_datetime)
        self.assertIsNone(new_fpv.remote_address)
        self.assertIsNone(new_fpv.user)
        self.assertTrue(new_fpv.is_synthetic)
        self.assertFalse(new_fpv.is_submitted_answer)


class ReopenSessionTest(SingleCourseTestMixin, TestCase):
    # test flow.reopen_session
    def setUp(self):
        super(ReopenSessionTest, self).setUp()

        fake_assemble_answer_visits = mock.patch(
            "course.flow.assemble_answer_visits")
        self.mock_assemble_answer_visits = fake_assemble_answer_visits.start()
        self.addCleanup(fake_assemble_answer_visits.stop)

        fake_unsubmit_page = mock.patch(
            "course.flow.unsubmit_page")
        self.mock_unsubmit_page = fake_unsubmit_page.start()
        self.addCleanup(fake_unsubmit_page.stop)

        self.default_now_datetime = now()

    def get_test_flow_session(self, **kwargs):
        defaults = {"course": self.course,
                    "participation": self.student_participation,
                    "points": 5,
                    "max_points": 10,
                    "result_comment": "Hi blahblah",
                    "completion_time": now() - timedelta(days=1)
                    }
        defaults.update(kwargs)
        return factories.FlowSessionFactory(**defaults)

    def test_in_progress(self):
        flow_session = self.get_test_flow_session(in_progress=True)
        expected_error_msg = "Cannot reopen a session that's already in progress"
        with self.assertRaises(RuntimeError) as cm:
            flow.reopen_session(now(), flow_session)
        self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(self.mock_assemble_answer_visits.call_count, 0)
        self.assertEqual(self.mock_unsubmit_page.call_count, 0)

    def test_session_without_participation(self):
        flow_session = self.get_test_flow_session(participation=None, user=None)
        expected_error_msg = "Cannot reopen anonymous sessions"
        with self.assertRaises(RuntimeError) as cm:
            flow.reopen_session(self.default_now_datetime, flow_session)
        self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(self.mock_assemble_answer_visits.call_count, 0)
        self.assertEqual(self.mock_unsubmit_page.call_count, 0)

    def test_not_suppress_log(self):
        flow_session = self.get_test_flow_session()

        original_comment = flow_session.result_comment

        flow.reopen_session(self.default_now_datetime, flow_session)

        flow_session.refresh_from_db()
        self.assertTrue(flow_session.in_progress)
        self.assertIsNone(flow_session.points)
        self.assertIsNone(flow_session.max_points)
        self.assertIsNone(flow_session.completion_time)

        self.assertIn(original_comment, flow_session.result_comment)
        self.assertIn("Session reopened at", flow_session.result_comment)
        self.assertIn("previous completion time was", flow_session.result_comment)

        self.assertEqual(self.mock_assemble_answer_visits.call_count, 0)
        self.assertEqual(self.mock_unsubmit_page.call_count, 0)

    def test_suppress_log(self):
        flow_session = self.get_test_flow_session()

        original_comment = flow_session.result_comment

        flow.reopen_session(
            self.default_now_datetime, flow_session, suppress_log=True)

        flow_session.refresh_from_db()
        self.assertTrue(flow_session.in_progress)
        self.assertIsNone(flow_session.points)
        self.assertIsNone(flow_session.max_points)
        self.assertIsNone(flow_session.completion_time)

        self.assertEqual(flow_session.result_comment, original_comment)

        self.assertEqual(self.mock_assemble_answer_visits.call_count, 0)
        self.assertEqual(self.mock_unsubmit_page.call_count, 0)

    def test_unsubmit_pages(self):
        flow_session = self.get_test_flow_session()
        original_comment = flow_session.result_comment

        # three not none faked answer visits
        self.mock_assemble_answer_visits.return_value = [
            None, mock.MagicMock(), None, mock.MagicMock(), mock.MagicMock()
        ]
        flow.reopen_session(
            self.default_now_datetime, flow_session, unsubmit_pages=True)

        flow_session.refresh_from_db()
        self.assertTrue(flow_session.in_progress)
        self.assertIsNone(flow_session.points)
        self.assertIsNone(flow_session.max_points)
        self.assertIsNone(flow_session.completion_time)
        self.assertNotEqual(flow_session.result_comment, original_comment)

        self.assertEqual(self.mock_assemble_answer_visits.call_count, 1)
        self.assertEqual(self.mock_unsubmit_page.call_count, 3)


class FinishFlowSessionStandaloneTest(SingleCourseTestMixin, TestCase):
    # test flow.finish_flow_session_standalone

    def setUp(self):
        super(FinishFlowSessionStandaloneTest, self).setUp()

        fake_get_session_grading_rule = mock.patch(
            "course.flow.get_session_grading_rule")
        self.mock_get_session_grading_rule = fake_get_session_grading_rule.start()
        self.addCleanup(fake_get_session_grading_rule.stop)

        fake_flow_context = mock.patch("course.flow.FlowContext")
        self.mock_flow_context = fake_flow_context.start()
        self.fctx = mock.MagicMock()
        self.mock_flow_context.return_value = self.fctx
        self.addCleanup(fake_flow_context.stop)

        fake_finish_flow_session = mock.patch("course.flow.finish_flow_session")
        self.mock_finish_flow_session = fake_finish_flow_session.start()
        self.addCleanup(fake_finish_flow_session.stop)

        self.default_now_datetime = now()
        self.repo = mock.MagicMock()

    def get_test_flow_session(self, **kwargs):
        defaults = {"course": self.course,
                    "participation": self.student_participation,
                    "points": 5,
                    "max_points": 10,
                    "result_comment": "Hi blahblah",
                    "completion_time": now() - timedelta(days=1),
                    "in_progress": True
                    }
        defaults.update(kwargs)
        return factories.FlowSessionFactory(**defaults)

    def test_no_now_datetime(self):
        flow_session = self.get_test_flow_session()
        fake_grading_rule = self.get_hacked_session_grading_rule()
        self.mock_get_session_grading_rule.return_value = fake_grading_rule

        with mock.patch(
                "django.utils.timezone.now") as mock_now:
            fake_now = mock.MagicMock()
            mock_now.return_value = fake_now
            self.assertTrue(flow.finish_flow_session_standalone(
                self.repo, self.course, flow_session
            ))

        self.assertEqual(self.mock_finish_flow_session.call_count, 1)
        for arg in [self.fctx, fake_grading_rule]:
            self.assertIn(arg, self.mock_finish_flow_session.call_args[0])

        self.assertEqual(
            self.mock_finish_flow_session.call_args[1]["now_datetime"],
            fake_now
        )

    def test_has_now_datetime(self):
        flow_session = self.get_test_flow_session()
        fake_grading_rule = self.get_hacked_session_grading_rule()
        self.mock_get_session_grading_rule.return_value = fake_grading_rule

        self.assertTrue(flow.finish_flow_session_standalone(
            self.repo, self.course, flow_session,
            now_datetime=self.default_now_datetime,
        ))

        self.assertEqual(self.mock_finish_flow_session.call_count, 1)
        for arg in [self.fctx, fake_grading_rule]:
            self.assertIn(arg, self.mock_finish_flow_session.call_args[0])

        self.assertEqual(
            self.mock_finish_flow_session.call_args[1]["now_datetime"],
            self.default_now_datetime
        )

    def test_past_due_only_due_is_none(self):
        flow_session = self.get_test_flow_session()
        fake_grading_rule = self.get_hacked_session_grading_rule()
        self.mock_get_session_grading_rule.return_value = fake_grading_rule

        self.assertFalse(flow.finish_flow_session_standalone(
            self.repo, self.course, flow_session,
            now_datetime=self.default_now_datetime,
            past_due_only=True
        ))

        self.assertEqual(self.mock_finish_flow_session.call_count, 0)

    def test_past_due_only_not_due(self):
        flow_session = self.get_test_flow_session()
        fake_grading_rule = self.get_hacked_session_grading_rule(
            due=now() + timedelta(days=1))
        self.mock_get_session_grading_rule.return_value = fake_grading_rule

        self.assertFalse(flow.finish_flow_session_standalone(
            self.repo, self.course, flow_session,
            now_datetime=self.default_now_datetime,
            past_due_only=True
        ))

        self.assertEqual(self.mock_finish_flow_session.call_count, 0)

    def test_past_due_only_due(self):
        flow_session = self.get_test_flow_session()
        fake_grading_rule = self.get_hacked_session_grading_rule(
            due=now() - timedelta(days=1))
        self.mock_get_session_grading_rule.return_value = fake_grading_rule

        self.assertTrue(flow.finish_flow_session_standalone(
            self.repo, self.course, flow_session,
            now_datetime=self.default_now_datetime,
            past_due_only=True
        ))

        self.assertEqual(self.mock_finish_flow_session.call_count, 1)

    def test_other_kwargs_used_for_call_finish_flow_session(self):
        flow_session = self.get_test_flow_session()
        fake_grading_rule = self.get_hacked_session_grading_rule(
            due=now() - timedelta(days=1))
        self.mock_get_session_grading_rule.return_value = fake_grading_rule

        force_regrade = mock.MagicMock()
        respect_preview = mock.MagicMock()

        self.assertTrue(flow.finish_flow_session_standalone(
            self.repo, self.course, flow_session,
            force_regrade=force_regrade,
            respect_preview=respect_preview
        ))

        self.assertEqual(self.mock_finish_flow_session.call_count, 1)

        self.assertEqual(
            self.mock_finish_flow_session.call_args[1]["force_regrade"],
            force_regrade
        )

        self.assertEqual(
            self.mock_finish_flow_session.call_args[1]["respect_preview"],
            respect_preview
        )


class ExpireFlowSessionStandaloneTest(SingleCourseTestMixin, TestCase):
    # test flow.expire_flow_session_standalone

    def setUp(self):
        super(ExpireFlowSessionStandaloneTest, self).setUp()

        fake_get_session_grading_rule = mock.patch(
            "course.flow.get_session_grading_rule")
        self.mock_get_session_grading_rule = fake_get_session_grading_rule.start()
        self.addCleanup(fake_get_session_grading_rule.stop)

        fake_flow_context = mock.patch("course.flow.FlowContext")
        self.mock_flow_context = fake_flow_context.start()
        self.fctx = mock.MagicMock()
        self.mock_flow_context.return_value = self.fctx
        self.addCleanup(fake_flow_context.stop)

        fake_expire_flow_session = mock.patch("course.flow.expire_flow_session")
        self.mock_expire_flow_session = fake_expire_flow_session.start()
        self.addCleanup(fake_expire_flow_session.stop)

        self.default_now_datetime = now()
        self.repo = mock.MagicMock()

    def get_test_flow_session(self, **kwargs):
        defaults = {"course": self.course,
                    "participation": self.student_participation,
                    "points": 5,
                    "max_points": 10,
                    "result_comment": "Hi blahblah",
                    "completion_time": now() - timedelta(days=1),
                    "in_progress": True
                    }
        defaults.update(kwargs)
        return factories.FlowSessionFactory(**defaults)

    def test_past_due_only_default_false(self):
        flow_session = self.get_test_flow_session()
        fake_grading_rule = self.get_hacked_session_grading_rule()
        self.mock_get_session_grading_rule.return_value = fake_grading_rule

        self.assertTrue(flow.expire_flow_session_standalone(
            self.repo, self.course, flow_session,
            self.default_now_datetime
        ))

        self.assertEqual(self.mock_expire_flow_session.call_count, 1)

        for arg in [fake_grading_rule, self.default_now_datetime]:
            self.assertIn(arg, self.mock_expire_flow_session.call_args[0])

        self.assertEqual(
            self.mock_expire_flow_session.call_args[1]["past_due_only"],
            False
        )

    def test_args_kwargs_used_for_call_expire_flow_session(self):
        flow_session = self.get_test_flow_session()
        fake_grading_rule = self.get_hacked_session_grading_rule(
            due=now() - timedelta(days=1))
        self.mock_get_session_grading_rule.return_value = fake_grading_rule

        past_due_only = mock.MagicMock()

        self.assertTrue(flow.expire_flow_session_standalone(
            self.repo, self.course, flow_session,
            self.default_now_datetime,
            past_due_only=past_due_only
        ))

        self.assertEqual(self.mock_expire_flow_session.call_count, 1)

        for arg in [fake_grading_rule, self.default_now_datetime]:
            self.assertIn(arg, self.mock_expire_flow_session.call_args[0])

        self.assertEqual(
            self.mock_expire_flow_session.call_args[1]["past_due_only"],
            past_due_only
        )


class RegradeSessionTest(SingleCourseTestMixin, TestCase):
    # test flow.regrade_session
    def setUp(self):
        super(RegradeSessionTest, self).setUp()

        fake_adjust_flow_session_page_data = mock.patch(
            "course.flow.adjust_flow_session_page_data")
        self.mock_adjust_flow_session_page_data = (
            fake_adjust_flow_session_page_data.start())
        self.mock_adjust_flow_session_page_data.return_value = None
        self.addCleanup(fake_adjust_flow_session_page_data.stop)

        fake_assemble_answer_visits = mock.patch(
            "course.flow.assemble_answer_visits")
        self.mock_assemble_answer_visits = fake_assemble_answer_visits.start()
        self.addCleanup(fake_assemble_answer_visits.stop)

        fake_finish_flow_session_standalone = mock.patch(
            "course.flow.finish_flow_session_standalone")
        self.mock_finish_flow_session_standalone = (
            fake_finish_flow_session_standalone.start())
        self.addCleanup(fake_finish_flow_session_standalone.stop)

        fake_reopen_session = mock.patch(
            "course.flow.reopen_session")
        self.mock_reopen_session = (
            fake_reopen_session.start())
        self.addCleanup(fake_reopen_session.stop)

        fake_grade_page_visit = mock.patch(
            "course.flow.grade_page_visit")
        self.mock_grade_page_visit = (
            fake_grade_page_visit.start())
        self.addCleanup(fake_grade_page_visit.stop)

        self.repo = mock.MagicMock()

    def get_test_flow_session(self, **kwargs):
        defaults = {"course": self.course,
                    "participation": self.student_participation,
                    "points": 5,
                    "max_points": 10,
                    "completion_time": None,
                    "in_progress": True
                    }
        defaults.update(kwargs)
        return factories.FlowSessionFactory(**defaults)

    def test_session_in_progress(self):
        flow_session = self.get_test_flow_session()

        answer_visit1 = mock.MagicMock()
        answer_visit1.get_most_recent_grade.return_value = mock.MagicMock()

        answer_visit2 = mock.MagicMock()
        answer_visit2.get_most_recent_grade.return_value = None

        self.mock_assemble_answer_visits.return_value = [
            None, answer_visit1, None, answer_visit2]

        flow.regrade_session(self.repo, self.course, flow_session)

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 1)
        self.assertFalse(
            self.mock_adjust_flow_session_page_data.call_args[1]["respect_preview"])

        self.assertEqual(self.mock_assemble_answer_visits.call_count, 1)

        self.assertEqual(self.mock_grade_page_visit.call_count, 1)
        self.assertFalse(
            self.mock_grade_page_visit.call_args[1]["respect_preview"])

        self.assertEqual(self.mock_reopen_session.call_count, 0)
        self.assertEqual(self.mock_finish_flow_session_standalone.call_count, 0)

    def test_session_not_in_progress(self):
        flow_session = self.get_test_flow_session(
            in_progress=False, completion_time=now() - timedelta(days=1))

        flow.regrade_session(self.repo, self.course, flow_session)

        flow_session.refresh_from_db()
        self.assertIn("Session regraded at", flow_session.result_comment)

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 1)
        self.assertFalse(
            self.mock_adjust_flow_session_page_data.call_args[1]["respect_preview"])

        self.assertEqual(self.mock_reopen_session.call_count, 1)
        self.assertTrue(
            self.mock_reopen_session.call_args[1]["force"])
        self.assertTrue(
            self.mock_reopen_session.call_args[1]["suppress_log"])

        self.assertEqual(self.mock_finish_flow_session_standalone.call_count, 1)
        self.assertFalse(
            self.mock_finish_flow_session_standalone.call_args[1][
                "respect_preview"])

        self.assertEqual(self.mock_assemble_answer_visits.call_count, 0)
        self.assertEqual(self.mock_grade_page_visit.call_count, 0)


class RecalculateSessionGradeTest(SingleCourseTestMixin, TestCase):
    def setUp(self):
        super(RecalculateSessionGradeTest, self).setUp()

        fake_adjust_flow_session_page_data = mock.patch(
            "course.flow.adjust_flow_session_page_data")
        self.mock_adjust_flow_session_page_data = (
            fake_adjust_flow_session_page_data.start())
        self.mock_adjust_flow_session_page_data.return_value = None
        self.addCleanup(fake_adjust_flow_session_page_data.stop)

        fake_reopen_session = mock.patch(
            "course.flow.reopen_session")
        self.mock_reopen_session = (
            fake_reopen_session.start())
        self.addCleanup(fake_reopen_session.stop)

        fake_finish_flow_session_standalone = mock.patch(
            "course.flow.finish_flow_session_standalone")
        self.mock_finish_flow_session_standalone = (
            fake_finish_flow_session_standalone.start())
        self.addCleanup(fake_finish_flow_session_standalone.stop)

        self.repo = mock.MagicMock()

    def get_test_flow_session(self, **kwargs):
        defaults = {"course": self.course,
                    "participation": self.student_participation,
                    "points": 5,
                    "max_points": 10,
                    "completion_time": now() - timedelta(days=1),
                    "in_progress": False
                    }
        defaults.update(kwargs)
        return factories.FlowSessionFactory(**defaults)

    def test_session_in_progress(self):
        flow_session = self.get_test_flow_session(
            in_progress=True, completion_time=None)
        expected_error_msg = "cannot recalculate grade on in-progress session"
        with self.assertRaises(RuntimeError) as cm:
            flow.recalculate_session_grade(self.repo, self.course, flow_session)
        self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 0)

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 0)
        self.assertEqual(self.mock_reopen_session.call_count, 0)
        self.assertEqual(self.mock_finish_flow_session_standalone.call_count, 0)

    def test_session_not_in_progress(self):
        flow_session = self.get_test_flow_session()
        flow.recalculate_session_grade(self.repo, self.course, flow_session)

        flow_session.refresh_from_db()
        self.assertIn("Session grade recomputed at", flow_session.result_comment)

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 1)
        self.assertFalse(
            self.mock_adjust_flow_session_page_data.call_args[1]["respect_preview"])

        self.assertEqual(self.mock_reopen_session.call_count, 1)
        self.assertTrue(
            self.mock_reopen_session.call_args[1]["force"])
        self.assertTrue(
            self.mock_reopen_session.call_args[1]["suppress_log"])

        self.assertEqual(self.mock_finish_flow_session_standalone.call_count, 1)
        self.assertFalse(
            self.mock_finish_flow_session_standalone.call_args[1][
                "respect_preview"])


class LockDownIfNeededTest(unittest.TestCase):
    # test flow.lock_down_if_needed
    def setUp(self):
        super(LockDownIfNeededTest, self).setUp()
        self.flow_session = mock.MagicMock()
        self.flow_session.id = 1
        self.flow_session.pk = 1
        self.request = mock.MagicMock()
        self.request.session = dict()

        def remove_all_course():
            for course in models.Course.objects.all():
                course.delete()

        self.addCleanup(remove_all_course)

    def test_no_lock_down_as_exam_session_flow_permission(self):
        flow_permissions = ["other_flow_permission"]
        flow.lock_down_if_needed(self.request, flow_permissions, self.flow_session)

        self.assertIsNone(
            self.request.session.get(
                "relate_session_locked_to_exam_flow_session_pk"))

    def test_has_lock_down_as_exam_session_flow_permission(self):
        flow_permissions = [fperm.lock_down_as_exam_session,
                            "other_flow_permission"]
        flow.lock_down_if_needed(self.request, flow_permissions, self.flow_session)

        self.assertEqual(
            self.request.session.get(
                "relate_session_locked_to_exam_flow_session_pk"),
            self.flow_session.pk
        )


class ViewStartFlowTest(SingleCourseTestMixin, TestCase):
    # test flow.view_start_flow

    flow_id = QUIZ_FLOW_ID

    def setUp(self):
        super(ViewStartFlowTest, self).setUp()

        fake_get_login_exam_ticket = mock.patch("course.flow.get_login_exam_ticket")
        self.mock_get_login_exam_ticket = fake_get_login_exam_ticket.start()
        self.addCleanup(fake_get_login_exam_ticket.stop)

        fake_flow_context = mock.patch("course.flow.FlowContext")
        self.mock_flow_context = fake_flow_context.start()
        self.fctx = mock.MagicMock()
        self.fctx.flow_id = self.flow_id
        self.fctx.flow_desc = dict_to_struct(
            {"title": "test page title", "description_html": "foo bar"})
        self.mock_flow_context.return_value = self.fctx
        self.addCleanup(fake_flow_context.stop)

        fake_post_start_flow = mock.patch("course.flow.post_start_flow")
        self.mock_post_start_flow = fake_post_start_flow.start()
        from django.http import HttpResponse
        self.mock_post_start_flow.return_value = HttpResponse()
        self.addCleanup(fake_post_start_flow.stop)

        fake_get_session_start_rule = mock.patch(
            "course.flow.get_session_start_rule")
        self.mock_get_session_start_rule = fake_get_session_start_rule.start()
        self.addCleanup(fake_get_session_start_rule.stop)

        fake_get_session_access_rule = mock.patch(
            "course.flow.get_session_access_rule")
        self.mock_get_session_access_rule = fake_get_session_access_rule.start()
        self.addCleanup(fake_get_session_access_rule.stop)

        fake_get_session_grading_rule = mock.patch(
            "course.flow.get_session_grading_rule")
        self.mock_get_session_grading_rule = fake_get_session_grading_rule.start()
        self.addCleanup(fake_get_session_grading_rule.stop)

    default_session_access_rule = {"permissions": []}

    def get_test_flow_session(self, **kwargs):
        defaults = {"course": self.course,
                    "participation": self.student_participation,
                    "points": 5,
                    "max_points": 10,
                    "completion_time": now() - timedelta(days=1),
                    "in_progress": False
                    }
        defaults.update(kwargs)
        return factories.FlowSessionFactory(**defaults)

    def test_post(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            self.c.post(self.get_view_start_flow_url(self.flow_id))
            self.assertEqual(self.mock_post_start_flow.call_count, 1)

            self.assertEqual(self.mock_get_login_exam_ticket.call_count, 0)
            self.assertEqual(self.mock_get_session_start_rule.call_count, 0)
            self.assertEqual(self.mock_get_session_access_rule.call_count, 0)
            self.assertEqual(self.mock_get_session_grading_rule.call_count, 0)

    def test_get_may_list_existing_sessions_but_no_session(self):
        session_start_rule = self.get_hacked_session_start_rule()

        self.mock_get_session_grading_rule.return_value = (
            self.get_hacked_session_grading_rule(
                due=now() + timedelta(hours=2), max_points=8))

        self.mock_get_session_start_rule.return_value = session_start_rule

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(self.get_view_start_flow_url(self.flow_id))
            self.assertResponseContextEqual(resp, "may_start", True)
            self.assertResponseContextEqual(
                resp, "start_may_decrease_grade", False)

            past_sessions_and_properties = resp.context[
                "past_sessions_and_properties"]
            self.assertEqual(len(past_sessions_and_properties), 0)

    def test_get_may_list_existing_sessions(self):
        session_start_rule = self.get_hacked_session_start_rule()

        # create 2 session with different access_rule and grading_rule
        fs1 = self.get_test_flow_session(in_progress=False,
                                         start_time=now() - timedelta(days=3))
        fs2 = self.get_test_flow_session(in_progress=True,
                                         start_time=now() - timedelta(days=2),
                                         completion_time=None)

        access_rule_for_session1 = self.get_hacked_session_access_rule(
            permissions=[fperm.cannot_see_flow_result]
        )

        access_rule_for_session2 = self.get_hacked_session_access_rule(
            permissions=[
                fperm.view,
                fperm.submit_answer,
                fperm.end_session,
                fperm.see_answer_after_submission]
        )

        grading_rule_for_session1 = self.get_hacked_session_grading_rule(
            due=None, max_points=10
        )
        grading_rule_for_session2 = self.get_hacked_session_grading_rule(
            due=now() - timedelta(days=1), max_points=9
        )

        new_session_grading_rule = self.get_hacked_session_grading_rule(
            due=now() + timedelta(hours=2), max_points=8
        )

        self.mock_get_session_start_rule.return_value = session_start_rule

        self.mock_get_session_access_rule.side_effect = [
            access_rule_for_session1, access_rule_for_session2
        ]

        self.mock_get_session_grading_rule.side_effect = [
            grading_rule_for_session1, grading_rule_for_session2,
            new_session_grading_rule
        ]

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(self.get_view_start_flow_url(self.flow_id))
            self.assertResponseContextEqual(resp, "may_start", True)
            self.assertResponseContextEqual(
                resp, "start_may_decrease_grade", True)
            past_sessions_and_properties = resp.context[
                "past_sessions_and_properties"]
            self.assertEqual(len(past_sessions_and_properties), 2)

            psap_session1, psap_property1 = past_sessions_and_properties[0]
            self.assertEqual(psap_session1, fs1)
            self.assertEqual(psap_property1.may_view, False)
            self.assertEqual(psap_property1.may_modify, False)
            self.assertEqual(psap_property1.due, None)
            self.assertEqual(psap_property1.grade_shown, False)

            psap_session2, psap_property2 = past_sessions_and_properties[1]
            self.assertEqual(psap_session2, fs2)
            self.assertEqual(psap_property2.may_view, True)
            self.assertEqual(psap_property2.may_modify, True)
            self.assertIsNotNone(psap_property2.due)
            self.assertEqual(psap_property2.grade_shown, True)

    def test_get_not_may_list_existing_sessions(self):
        session_start_rule = self.get_hacked_session_start_rule(
            may_start_new_session=False,
            may_list_existing_sessions=False,
        )

        # create 2 session with different access_rule and grading_rule
        self.get_test_flow_session(in_progress=False,
                                   start_time=now() - timedelta(days=3))
        self.get_test_flow_session(in_progress=True,
                                   start_time=now() - timedelta(days=2),
                                   completion_time=None)

        self.mock_get_session_start_rule.return_value = session_start_rule

        self.mock_get_session_grading_rule.return_value = (
            self.get_hacked_session_grading_rule(
                due=now() + timedelta(hours=2), max_points=8))

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(self.get_view_start_flow_url(self.flow_id))
            self.assertResponseContextEqual(resp, "may_start", False)
            self.assertResponseContextEqual(
                resp, "start_may_decrease_grade", False)

            past_sessions_and_properties = resp.context[
                "past_sessions_and_properties"]

            self.assertEqual(len(past_sessions_and_properties), 0)

        self.assertEqual(self.mock_get_session_grading_rule.call_count, 0)
        self.assertEqual(self.mock_get_session_access_rule.call_count, 0)


class PostStartFlowTest(SingleCourseTestMixin, TestCase):
    # test flow.post_start_flow

    flow_id = QUIZ_FLOW_ID

    def setUp(self):
        super(PostStartFlowTest, self).setUp()

        fake_get_login_exam_ticket = mock.patch("course.flow.get_login_exam_ticket")
        self.mock_get_login_exam_ticket = fake_get_login_exam_ticket.start()
        self.addCleanup(fake_get_login_exam_ticket.stop)

        fake_flow_context = mock.patch("course.flow.FlowContext")
        self.mock_flow_context = fake_flow_context.start()
        self.fctx = mock.MagicMock()
        self.fctx.flow_id = self.flow_id
        self.fctx.flow_desc = dict_to_struct(
            {"title": "test page title", "description_html": "foo bar"})
        self.mock_flow_context.return_value = self.fctx
        self.addCleanup(fake_flow_context.stop)

        fake_get_session_start_rule = mock.patch(
            "course.flow.get_session_start_rule")
        self.mock_get_session_start_rule = fake_get_session_start_rule.start()
        self.addCleanup(fake_get_session_start_rule.stop)

        fake_get_session_access_rule = mock.patch(
            "course.flow.get_session_access_rule")
        self.mock_get_session_access_rule = fake_get_session_access_rule.start()
        self.addCleanup(fake_get_session_access_rule.stop)

        fake_lock_down_if_needed = mock.patch(
            "course.flow.lock_down_if_needed")
        self.mock_lock_down_if_needed = fake_lock_down_if_needed.start()
        self.addCleanup(fake_lock_down_if_needed.stop)

        fake_start_flow = mock.patch("course.flow.start_flow")
        self.mock_start_flow = fake_start_flow.start()
        self.addCleanup(fake_start_flow.stop)

    default_session_access_rule = {"permissions": []}

    def test_cooldown_seconds_worked(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            self.mock_get_session_start_rule.return_value = \
                self.get_hacked_session_start_rule()

            mock_session = mock.MagicMock()
            mock_session.id = 0
            mock_session.pk = 0
            self.mock_start_flow.return_value = mock_session

            # create an exising session started recently
            factories.FlowSessionFactory(participation=self.student_participation)

            self.start_flow(self.flow_id, ignore_cool_down=False,
                            assume_success=False)
            self.assertEqual(self.mock_start_flow.call_count, 0)
            self.assertEqual(self.mock_get_session_access_rule.call_count, 0)
            self.assertEqual(self.mock_get_login_exam_ticket.call_count, 1)
            self.assertEqual(self.mock_lock_down_if_needed.call_count, 0)

    def test_cooldown_seconds_dued(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            self.mock_get_session_start_rule.return_value = (
                self.get_hacked_session_start_rule())

            mock_session = mock.MagicMock()
            mock_session.id = 0
            mock_session.pk = 0
            self.mock_start_flow.return_value = mock_session

            # create an exising session started recently
            factories.FlowSessionFactory(
                participation=self.student_participation,
                start_time=now() - timedelta(seconds=11))

            self.start_flow(self.flow_id, ignore_cool_down=False,
                            assume_success=False)
            self.assertEqual(self.mock_start_flow.call_count, 1)
            self.assertEqual(self.mock_get_session_access_rule.call_count, 1)
            self.assertEqual(self.mock_get_login_exam_ticket.call_count, 1)
            self.assertEqual(self.mock_lock_down_if_needed.call_count, 1)

    def test_not_may_start(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            self.mock_get_session_start_rule.return_value = \
                self.get_hacked_session_start_rule(
                    may_start_new_session=False,
                )
            resp = self.start_flow(self.flow_id, ignore_cool_down=True,
                                   assume_success=False)
            self.assertEqual(resp.status_code, 403)

            self.assertEqual(self.mock_start_flow.call_count, 0)
            self.assertEqual(self.mock_get_session_access_rule.call_count, 0)
            self.assertEqual(self.mock_get_login_exam_ticket.call_count, 1)
            self.assertEqual(self.mock_lock_down_if_needed.call_count, 0)

    def test_start_session_for_anonymous(self):
        self.c.logout()
        self.mock_get_session_start_rule.return_value = \
            self.get_hacked_session_start_rule(
                may_start_new_session=True,
            )

        mock_session = mock.MagicMock()
        mock_session.id = 0
        mock_session.pk = 0
        self.mock_start_flow.return_value = mock_session

        resp = self.start_flow(self.flow_id, ignore_cool_down=True,
                               assume_success=False)
        self.assertEqual(resp.status_code, 302)

        self.assertEqual(self.mock_start_flow.call_count, 1)
        self.assertEqual(self.mock_get_session_access_rule.call_count, 1)
        self.assertEqual(self.mock_get_login_exam_ticket.call_count, 1)
        self.assertEqual(self.mock_lock_down_if_needed.call_count, 1)


class ViewResumeFlowTest(SingleCourseTestMixin, TestCase):
    # test flow.view_resume_flow

    def setUp(self):

        fake_get_now_or_fake_time = mock.patch(
            "course.flow.get_now_or_fake_time")
        self.mock_get_now_or_fake_time = fake_get_now_or_fake_time.start()
        self.addCleanup(fake_get_now_or_fake_time.stop)

        fake_get_and_check_flow_session = mock.patch(
            "course.flow.get_and_check_flow_session")
        self.mock_get_and_check_flow_session = (
            fake_get_and_check_flow_session.start())
        self.addCleanup(fake_get_and_check_flow_session.stop)

        fake_get_login_exam_ticket = mock.patch("course.flow.get_login_exam_ticket")
        self.mock_get_login_exam_ticket = fake_get_login_exam_ticket.start()
        self.addCleanup(fake_get_login_exam_ticket.stop)

        fake_lock_down_if_needed = mock.patch(
            "course.flow.lock_down_if_needed")
        self.mock_lock_down_if_needed = fake_lock_down_if_needed.start()
        self.addCleanup(fake_lock_down_if_needed.stop)

        fake_get_session_access_rule = mock.patch(
            "course.flow.get_session_access_rule")
        self.mock_get_session_access_rule = fake_get_session_access_rule.start()
        self.addCleanup(fake_get_session_access_rule.stop)

    def test(self):
        fs = factories.FlowSessionFactory(participation=self.student_participation)
        faked_now_datetime = mock.MagicMock()
        self.mock_get_now_or_fake_time.return_value = faked_now_datetime

        faked_ticket = mock.MagicMock()
        self.mock_get_login_exam_ticket.return_value = faked_ticket

        self.mock_get_and_check_flow_session.return_value = fs

        resp = self.c.get(self.get_resume_flow_url(
            course_identifier=self.course.identifier, flow_session_id=fs.pk))

        self.assertRedirects(
            resp, self.get_page_url_by_ordinal(
                page_ordinal=0, flow_session_id=fs.pk),
            fetch_redirect_response=False)

        self.assertEqual(self.mock_get_and_check_flow_session.call_count, 1)
        self.assertEqual(self.mock_get_login_exam_ticket.call_count, 1)
        self.assertEqual(self.mock_get_session_access_rule.call_count, 1)
        self.assertIn(
            faked_now_datetime, self.mock_get_session_access_rule.call_args[0])
        self.assertIn(
            "facilities", self.mock_get_session_access_rule.call_args[1])
        self.assertEqual(
            self.mock_get_session_access_rule.call_args[1]["login_exam_ticket"],
            faked_ticket)

        self.assertEqual(self.mock_lock_down_if_needed.call_count, 1)


class GetAndCheckFlowSessionTest(SingleCourseTestMixin, TestCase):
    # test flow.get_and_check_flow_session

    def setUp(self):
        super(GetAndCheckFlowSessionTest, self).setUp()
        self.rf = RequestFactory()

    def get_pctx(self, request_user):
        request = self.rf.get(self.get_course_page_url())
        request.user = request_user

        from course.utils import CoursePageContext
        pctx = CoursePageContext(request, self.course.identifier)
        return pctx

    def test_object_does_not_exist(self):
        pctx = self.get_pctx(self.student_participation.user)

        with self.assertRaises(http.Http404):
            flow.get_and_check_flow_session(pctx, flow_session_id=100)

    def test_flow_session_course_not_match(self):
        another_course = factories.CourseFactory(identifier="another-course")
        another_course_fs = factories.FlowSessionFactory(
            participation=factories.ParticipationFactory(course=another_course)
        )

        pctx = self.get_pctx(self.student_participation.user)

        with self.assertRaises(http.Http404):
            flow.get_and_check_flow_session(
                pctx, flow_session_id=another_course_fs.pk)

    def test_anonymous_session(self):
        anonymous_session = factories.FlowSessionFactory(
            course=self.course, participation=None, user=None
        )

        pctx = self.get_pctx(request_user=AnonymousUser())

        self.assertEqual(
            flow.get_and_check_flow_session(
                pctx, flow_session_id=anonymous_session.pk),
            anonymous_session)

    def test_my_session(self):
        my_session = factories.FlowSessionFactory(
            course=self.course, participation=self.student_participation
        )

        pctx = self.get_pctx(request_user=self.student_participation.user)

        self.assertEqual(
            flow.get_and_check_flow_session(
                pctx, flow_session_id=my_session.pk),
            my_session)

    def test_not_my_session_anonymous(self):
        my_session = factories.FlowSessionFactory(
            course=self.course, participation=self.student_participation
        )

        from django.contrib.auth.models import AnonymousUser
        pctx = self.get_pctx(request_user=AnonymousUser())

        with self.assertRaises(PermissionDenied) as cm:
            flow.get_and_check_flow_session(
                pctx, flow_session_id=my_session.pk)
        expected_error_msg = "may not view other people's sessions"
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_view_student_session(self):
        student_session = factories.FlowSessionFactory(
            course=self.course, participation=self.student_participation
        )

        pctx = self.get_pctx(request_user=self.instructor_participation.user)

        self.assertEqual(
            flow.get_and_check_flow_session(
                pctx, flow_session_id=student_session.pk),
            student_session)


@unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
class WillReceiveFeedbackTest(unittest.TestCase):
    # test flow.will_receive_feedback
    def test_false(self):
        combinations = [(frozenset([fp]), False) for fp in
                        get_flow_permissions_list(
                            excluded=[fperm.see_correctness,
                                      fperm.see_answer_after_submission])]
        combinations.append(([], False))

        for permissions, will_receive in combinations:
            with self.subTest(permissions=permissions):
                self.assertEqual(
                    flow.will_receive_feedback(permissions),
                    will_receive)

    def test_true(self):
        combinations = [
            (frozenset([fp, fperm.see_correctness]), True)
            for fp in get_flow_permissions_list(
                excluded=[fperm.see_correctness])]

        combinations2 = [
            (frozenset([fp, fperm.see_answer_after_submission]), True)
            for fp in get_flow_permissions_list(
                excluded=[fperm.see_answer_after_submission])]
        combinations.extend(combinations2)

        for permissions, will_receive in combinations:
            with self.subTest(permissions=permissions):
                self.assertEqual(
                    flow.will_receive_feedback(permissions),
                    will_receive)


@unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
class MaySendEmailAboutFlowPageTest(unittest.TestCase):
    # test flow.may_send_email_about_flow_page
    @classmethod
    def setUpClass(cls):
        cls.course = course = factories.CourseFactory()
        participation = factories.ParticipationFactory(course=course)
        cls.fs = factories.FlowSessionFactory(
            course=course, participation=participation)
        cls.fs_no_participation_no_user = factories.FlowSessionFactory(
            course=course, participation=None, user=None)
        cls.fs_no_user = factories.FlowSessionFactory(
            course=course, participation=participation, user=None)

    @classmethod
    def tearDownClass(cls):
        cls.course.delete()

    def test_false_has_no_send_email_about_flow_page_fperm(self):
        combinations = [(frozenset([fp]), False) for fp in
                        get_flow_permissions_list(
                            excluded=[fperm.send_email_about_flow_page])]
        combinations.append((frozenset([]), False))

        for session in [self.fs, self.fs_no_user, self.fs_no_participation_no_user]:
            for permissions, may_send in combinations:
                with self.subTest(session=session, permissions=permissions):
                    self.assertEqual(
                        flow.may_send_email_about_flow_page(session, permissions),
                        may_send)

    def test_false_flow_session_has_no_participation_or_no_user(self):
        combinations = [
            (frozenset([fp, fperm.send_email_about_flow_page]), False)
            for fp in get_flow_permissions_list(
                excluded=[fperm.send_email_about_flow_page])]

        for session in [self.fs_no_user, self.fs_no_participation_no_user]:
            for permissions, may_send in combinations:
                with self.subTest(session=session, permissions=permissions):
                    self.assertEqual(
                        flow.may_send_email_about_flow_page(session, permissions),
                        may_send)

    def test_true(self):
        combinations = [
            (frozenset([fp, fperm.send_email_about_flow_page]), True)
            for fp in get_flow_permissions_list(
                excluded=[fperm.send_email_about_flow_page])]
        combinations.append((frozenset([fperm.send_email_about_flow_page]), True))

        for permissions, may_send in combinations:
            with self.subTest(session=self.fs, permissions=permissions):
                self.assertEqual(
                    flow.may_send_email_about_flow_page(self.fs, permissions),
                    may_send)


@unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
class GetPageBehaviorTest(unittest.TestCase):
    # test flow.get_page_behavior
    def setUp(self):
        self.page = mock.MagicMock()

    def assertShowCorrectness(self, behavior, perms, show=True):  # noqa
        self.assertEqual(
            behavior.show_correctness, show,
            "behavior.show_correctness unexpected to be %s with %s"
            % (not show, ", ".join(perms)))

    def assertShowAnswer(self, behavior, perms, show=True):  # noqa
        self.assertEqual(behavior.show_answer, show,
                         "behavior.show_answer unexpected to be %s with %s"
                         % (not show, ", ".join(perms)))

    def assertMayChangeAnswer(self, behavior, perms, may_change=True):  # noqa
        self.assertEqual(behavior.may_change_answer, may_change,
                         "behavior.may_change_answer unexpected to be %s with %s"
                         % (not may_change, ", ".join(perms)))

    def test_show_correctness1(self):
        # not expects_answer
        self.page.expects_answer.return_value = False

        combinations = [(frozenset([fp]), False) for fp in
                        get_flow_permissions_list()]
        combinations.append(([], False))

        params = list(itertools.product([True, False], repeat=5))

        for p in params:
            (session_in_progress, answer_was_graded, generate_grade,
             is_unenrooled_session, viewing_prior_version) = p
            for permissions, show in combinations:
                with self.subTest(
                        permissions=permissions):
                    behavior = flow.get_page_behavior(
                        self.page,
                        permissions=permissions,
                        session_in_progress=session_in_progress,
                        answer_was_graded=answer_was_graded,
                        generates_grade=generate_grade,
                        is_unenrolled_session=is_unenrooled_session,
                        viewing_prior_version=viewing_prior_version,
                    )
                self.assertShowCorrectness(behavior, permissions, show)

    def test_show_correctness2(self):
        # expects_answer, answer_was_graded
        self.page.expects_answer.return_value = True

        combinations = [(frozenset([fp]), False) for fp in
                        get_flow_permissions_list(
                            excluded=fperm.see_correctness)]
        combinations.append(([], False))
        combinations.append((frozenset([fperm.see_correctness]), True))

        params = list(itertools.product([True, False], repeat=4))

        for p in params:
            (session_in_progress, generate_grade,
             is_unenrooled_session, viewing_prior_version) = p

            for permissions, show in combinations:
                with self.subTest(permissions=permissions):
                    behavior = flow.get_page_behavior(
                        self.page,
                        permissions=permissions,
                        session_in_progress=session_in_progress,
                        answer_was_graded=True,
                        generates_grade=generate_grade,
                        is_unenrolled_session=is_unenrooled_session,
                        viewing_prior_version=viewing_prior_version,
                    )
                self.assertShowCorrectness(behavior, permissions, show)

    def test_show_correctness3(self):
        # expects_answer, answer was NOT graded
        self.page.expects_answer.return_value = True

        combinations = [(frozenset([fp]), False) for fp in
                        get_flow_permissions_list()]
        combinations.append(([], False))

        params = list(itertools.product([True, False], repeat=4))

        for p in params:
            (session_in_progress, generate_grade,
             is_unenrooled_session, viewing_prior_version) = p

            for permissions, show in combinations:
                with self.subTest(permissions=permissions):
                    behavior = flow.get_page_behavior(
                        self.page,
                        permissions=permissions,
                        session_in_progress=session_in_progress,
                        answer_was_graded=False,
                        generates_grade=generate_grade,
                        is_unenrolled_session=is_unenrooled_session,
                        viewing_prior_version=viewing_prior_version,
                    )
                self.assertShowCorrectness(behavior, permissions, show)

    def test_show_answer1(self):
        # not expects_answer
        self.page.expects_answer.return_value = False

        combinations = [(frozenset([fp]), False) for fp in
                        get_flow_permissions_list(
                            excluded=[
                                fperm.see_answer_before_submission,
                                fperm.see_answer_after_submission])]
        combinations.append(([], False))
        combinations.append(
            (frozenset([fperm.see_answer_before_submission]), True))
        combinations.append(
            (frozenset([fperm.see_answer_after_submission]), True))
        combinations.append(
            (frozenset([fperm.see_answer_after_submission,
                        fperm.see_answer_before_submission]), True))

        params = list(itertools.product([True, False], repeat=5))

        for p in params:
            (session_in_progress, generate_grade, answer_was_graded,
             is_unenrooled_session, viewing_prior_version) = p

            for permissions, show in combinations:
                with self.subTest(permissions=permissions):
                    behavior = flow.get_page_behavior(
                        self.page,
                        permissions=permissions,
                        session_in_progress=session_in_progress,
                        answer_was_graded=answer_was_graded,
                        generates_grade=generate_grade,
                        is_unenrolled_session=is_unenrooled_session,
                        viewing_prior_version=viewing_prior_version,
                    )
                    self.assertShowAnswer(behavior, permissions, show)

    def test_show_answer2(self):
        # expects_answer, answer was NOT graded
        self.page.expects_answer.return_value = True

        combinations = [(frozenset([fp]), False) for fp in
                        get_flow_permissions_list(
                            excluded=[
                                fperm.see_answer_before_submission])]
        combinations.append(([], False))
        combinations.append(
            (frozenset([fperm.see_answer_before_submission]), True))

        params = list(itertools.product([True, False], repeat=4))

        for p in params:
            (session_in_progress, generate_grade,
             is_unenrooled_session, viewing_prior_version) = p

            for permissions, show in combinations:
                with self.subTest(permissions=permissions):
                    behavior = flow.get_page_behavior(
                        self.page,
                        permissions=permissions,
                        session_in_progress=session_in_progress,
                        answer_was_graded=False,
                        generates_grade=generate_grade,
                        is_unenrolled_session=is_unenrooled_session,
                        viewing_prior_version=viewing_prior_version,
                    )
                    self.assertShowAnswer(behavior, permissions, show)

    def test_show_answer3(self):
        # expects_answer, answer was graded, session not in progress

        self.page.expects_answer.return_value = True

        combinations = [(frozenset([fp]), False) for fp in
                        get_flow_permissions_list(
                            excluded=[
                                fperm.see_answer_before_submission,
                                fperm.see_answer_after_submission])]
        combinations.append(([], False))

        # when session not in_progress, see_answer_after_submission dominates
        combinations.extend(
            [(frozenset([fp, fperm.see_answer_after_submission]), True)
             for fp in get_flow_permissions_list(
                excluded=fperm.see_answer_after_submission)])

        combinations.append(
            (frozenset([fperm.see_answer_before_submission]), True))
        combinations.append(
            (frozenset([fperm.see_answer_after_submission]), True))

        # see_answer_before_submission also dominates
        combinations.extend(
            [(frozenset([fp, fperm.see_answer_before_submission]), True)
             for fp in get_flow_permissions_list(
                excluded=fperm.see_answer_before_submission)])

        params = list(itertools.product([True, False], repeat=3))

        for p in params:
            (generate_grade, is_unenrooled_session, viewing_prior_version) = p

            for permissions, show in combinations:
                with self.subTest(permissions=permissions):
                    behavior = flow.get_page_behavior(
                        self.page,
                        permissions=permissions,
                        session_in_progress=False,
                        answer_was_graded=True,
                        generates_grade=generate_grade,
                        is_unenrolled_session=is_unenrooled_session,
                        viewing_prior_version=viewing_prior_version,
                    )
                    self.assertShowAnswer(behavior, permissions, show)

    def test_show_answer4(self):
        # expects_answer, answer was graded, session in progress

        self.page.expects_answer.return_value = True

        combinations = [(frozenset([fp]), False) for fp in
                        get_flow_permissions_list(
                            excluded=[
                                fperm.see_answer_before_submission,
                                fperm.see_answer_after_submission])]
        combinations.append(([], False))
        combinations.append(
            (frozenset([fperm.see_answer_before_submission]), True))

        combinations.append(
            (frozenset([fperm.see_answer_after_submission]), True))

        # if see_answer_before_submission dominate not present,
        # change_answer dominates
        combinations.extend(
            [(frozenset([fp, fperm.change_answer]), False) for fp in
             get_flow_permissions_list(
                 excluded=fperm.see_answer_before_submission)])

        # see_answer_before_submission dominates
        combinations.extend(
            [(frozenset([fp, fperm.see_answer_before_submission]), True)
             for fp in get_flow_permissions_list(
                excluded=fperm.see_answer_before_submission)])

        params = list(itertools.product([True, False], repeat=3))

        for p in params:
            (generate_grade, is_unenrooled_session, viewing_prior_version) = p

            for permissions, show in combinations:
                with self.subTest(permissions=permissions):
                    behavior = flow.get_page_behavior(
                        self.page,
                        permissions=permissions,
                        session_in_progress=True,
                        answer_was_graded=True,
                        generates_grade=generate_grade,
                        is_unenrolled_session=is_unenrooled_session,
                        viewing_prior_version=viewing_prior_version,
                    )
                    self.assertShowAnswer(behavior, permissions, show)

    def test_may_change_answer1(self):
        # viewing_prior_version dominates

        combinations = [(frozenset([fp]), False) for fp in
                        get_flow_permissions_list()]

        params = list(itertools.product([True, False], repeat=5))

        for p in params:
            (self.page.expects_answer.return_value,
             session_in_progress, answer_was_graded,
             generates_grade,
             is_unenrooled_session) = p

            for permissions, may_change in combinations:
                with self.subTest(permissions=permissions):
                    behavior = flow.get_page_behavior(
                        self.page,
                        permissions=permissions,
                        session_in_progress=session_in_progress,
                        answer_was_graded=answer_was_graded,
                        generates_grade=generates_grade,
                        is_unenrolled_session=is_unenrooled_session,
                        viewing_prior_version=True,
                    )
                    self.assertMayChangeAnswer(behavior, permissions, may_change)

    def test_may_change_answer2(self):
        # session_in_progress dominates

        combinations = [(frozenset([fp]), False) for fp in
                        get_flow_permissions_list()]

        params = list(itertools.product([True, False], repeat=4))

        for p in params:
            (self.page.expects_answer.return_value,
             answer_was_graded, generates_grade,
             is_unenrooled_session) = p

            for permissions, may_change in combinations:
                with self.subTest(permissions=permissions):
                    behavior = flow.get_page_behavior(
                        self.page,
                        permissions=permissions,
                        session_in_progress=False,
                        answer_was_graded=answer_was_graded,
                        generates_grade=generates_grade,
                        is_unenrolled_session=is_unenrooled_session,
                    )
                    self.assertMayChangeAnswer(behavior, permissions, may_change)

    def test_may_change_answer3(self):
        # no submit_answer dominates

        combinations = [(frozenset([fp]), False)
                        for fp in get_flow_permissions_list(
                excluded=fperm.submit_answer)]

        params = list(itertools.product([True, False], repeat=5))

        for p in params:
            (self.page.expects_answer.return_value,
             session_in_progress, answer_was_graded,
             generates_grade,
             is_unenrooled_session) = p

            for permissions, may_change in combinations:
                with self.subTest(permissions=permissions):
                    behavior = flow.get_page_behavior(
                        self.page,
                        permissions=permissions,
                        session_in_progress=session_in_progress,
                        answer_was_graded=answer_was_graded,
                        generates_grade=generates_grade,
                        is_unenrolled_session=is_unenrooled_session,
                    )
                    self.assertMayChangeAnswer(behavior, permissions, may_change)

    def test_may_change_answer4(self):
        # not answer_was_graded or (flow_permission.change_answer in permissions)

        combinations = [(frozenset([fp, fperm.submit_answer]), False)
                        for fp in get_flow_permissions_list(
                excluded=fperm.change_answer)]

        params = list(itertools.product([True, False], repeat=4))

        for p in params:
            (self.page.expects_answer.return_value,
             session_in_progress, generates_grade, is_unenrooled_session) = p

            for permissions, may_change in combinations:
                with self.subTest(permissions=permissions):
                    behavior = flow.get_page_behavior(
                        self.page,
                        permissions=permissions,
                        session_in_progress=session_in_progress,
                        answer_was_graded=True,
                        generates_grade=generates_grade,
                        is_unenrolled_session=is_unenrooled_session,
                    )
                    self.assertMayChangeAnswer(behavior, permissions, may_change)

    def test_may_change_answer6(self):
        # generates_grade and not is_unenrolled_session or (not generates_grade)

        combinations = [
            (frozenset([fp, fperm.submit_answer, fperm.change_answer]), False)
            for fp in get_flow_permissions_list()]

        params = list(itertools.product([True, False], repeat=1))

        for p in params:
            (self.page.expects_answer.return_value) = p

            for permissions, may_change in combinations:
                with self.subTest(permissions=permissions):
                    behavior = flow.get_page_behavior(
                        self.page,
                        permissions=permissions,
                        session_in_progress=True,
                        answer_was_graded=False,
                        generates_grade=True,
                        is_unenrolled_session=True,
                    )
                    self.assertMayChangeAnswer(behavior, permissions, may_change)

    def test_may_change_answer7(self):
        # cases that may_change_answer
        from collections import namedtuple
        Conf = namedtuple(
            "Conf", [
                'extra_fperms',
                'answer_was_graded',
                'generates_grade',
                'is_unenrolled_session',
            ]
        )

        confs = (
            Conf([], False, False, True),
            Conf([], False, False, False),
            Conf([fperm.change_answer], True, False, True),
            Conf([fperm.change_answer], True, False, False),
            Conf([fperm.change_answer], False, False, True),
            Conf([fperm.change_answer], False, False, False),
        )

        params = list(itertools.product([True, False], repeat=1))

        for conf in confs:
            combinations = []
            for fp in get_flow_permissions_list():
                fperms = [fp, fperm.submit_answer]
                if conf.extra_fperms:
                    fperms.extend(conf.extra_fperms)

                combinations.append((frozenset(fperms), True))

                for p in params:
                    (self.page.expects_answer.return_value) = p

                for permissions, may_change in combinations:
                    with self.subTest(
                            permissions=permissions,
                            answer_was_graded=conf.answer_was_graded,
                            generates_grade=conf.generates_grade,
                            is_unenrolled_session=conf.is_unenrolled_session):
                        behavior = flow.get_page_behavior(
                            self.page,
                            permissions=permissions,
                            session_in_progress=True,
                            answer_was_graded=conf.answer_was_graded,
                            generates_grade=conf.generates_grade,
                            is_unenrolled_session=conf.is_unenrolled_session,
                        )
                        self.assertMayChangeAnswer(behavior, permissions, may_change)


class AddButtonsToFormTest(unittest.TestCase):
    # test flow.add_buttons_to_form
    def setUp(self):
        super(AddButtonsToFormTest, self).setUp()
        self.flow_session = mock.MagicMock()
        self.fpctx = mock.MagicMock()

        fake_will_receive_feedback = mock.patch("course.flow.will_receive_feedback")
        self.mock_will_receive_feedback = fake_will_receive_feedback.start()
        self.addCleanup(fake_will_receive_feedback.stop)

    def fake_flow_session_page_count(self, count):
        self.flow_session.page_count = count

    def fake_fpctx_page_data_page_ordinal(self, ordinal):
        self.fpctx.page_data.page_ordinal = ordinal

    def get_form_submit_inputs(self, form):
        from crispy_forms.layout import Submit
        inputs = [
            (input.name, input.value) for input in form.helper.inputs
            if isinstance(input, Submit)
        ]
        names = list(dict(inputs).keys())
        values = list(dict(inputs).values())
        return names, values

    def test_not_add_save_button(self):
        class MyForm(StyledForm):
            show_save_button = False

        form = MyForm()

        self.mock_will_receive_feedback.return_value = True
        flow.add_buttons_to_form(form, self.fpctx, self.flow_session, frozenset())

        names, values = self.get_form_submit_inputs(form)
        self.assertNotIn("save", names)
        self.assertIn("submit", names)
        self.assertIn("Submit final answer", values)

    def test_add_save_button_by_default(self):
        class MyForm(StyledForm):
            pass

        form = MyForm()

        self.mock_will_receive_feedback.return_value = True
        flow.add_buttons_to_form(form, self.fpctx, self.flow_session, frozenset())

        names, values = self.get_form_submit_inputs(form)
        self.assertIn("save", names)
        self.assertIn("submit", names)
        self.assertIn("Submit final answer", values)

    def test_add_submit_answer_for_feedback_button(self):
        form = StyledForm()

        self.mock_will_receive_feedback.return_value = True
        flow.add_buttons_to_form(
            form, self.fpctx, self.flow_session, frozenset([fperm.change_answer]))

        names, values = self.get_form_submit_inputs(form)
        self.assertIn("submit", names)
        self.assertIn("Submit answer for feedback", values)

    @unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_not_add_submit_answer_for_feedback_button(self):

        self.mock_will_receive_feedback.return_value = True
        combinations = [(frozenset([fp]), False) for fp in
                        get_flow_permissions_list(excluded=fperm.change_answer)]
        combinations.append(([], False))

        form = StyledForm()
        for permissions, show in combinations:
            with self.subTest(
                    permissions=permissions):
                flow.add_buttons_to_form(
                    form, self.fpctx, self.flow_session, permissions)

            names, values = self.get_form_submit_inputs(form)
            self.assertNotIn("Submit answer for feedback", values)

    @unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_add_save_and_next(self):

        self.mock_will_receive_feedback.return_value = False

        combinations = [(frozenset([fp]), True) for fp in
                        get_flow_permissions_list()]
        combinations.append(([], True))

        self.fake_flow_session_page_count(3)
        self.fake_fpctx_page_data_page_ordinal(1)

        form = StyledForm()
        for permissions, show in combinations:
            with self.subTest(
                    permissions=permissions):
                flow.add_buttons_to_form(
                    form, self.fpctx, self.flow_session, permissions)

            names, values = self.get_form_submit_inputs(form)
            self.assertIn("save_and_next", names)
            self.assertNotIn("submit", names)
            self.assertNotIn("save_and_finish", names)

    @unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_add_save_and_finish(self):

        self.mock_will_receive_feedback.return_value = False

        combinations = [(frozenset([fp]), True) for fp in
                        get_flow_permissions_list()]
        combinations.append(([], True))

        self.fake_flow_session_page_count(3)
        self.fake_fpctx_page_data_page_ordinal(2)

        form = StyledForm()
        for permissions, show in combinations:
            with self.subTest(
                    permissions=permissions):
                flow.add_buttons_to_form(
                    form, self.fpctx, self.flow_session, permissions)

            names, values = self.get_form_submit_inputs(form)
            self.assertNotIn("save_and_next", names)
            self.assertNotIn("submit", names)
            self.assertIn("save_and_finish", names)


class CreateFlowPageVisitTest(SingleCourseTestMixin, TestCase):
    # test flow.create_flow_page_visit
    def setUp(self):
        super(CreateFlowPageVisitTest, self).setUp()
        rf = RequestFactory()
        self.request = rf.get(self.get_course_page_url())

    def test_anonymous_visit(self):
        self.request.user = AnonymousUser()
        fs = factories.FlowSessionFactory(
            course=self.course, participation=None, user=None)
        page_data = factories.FlowPageDataFactory(flow_session=fs)

        flow.create_flow_page_visit(self.request, fs, page_data)

        fpvs = models.FlowPageVisit.objects.all()
        self.assertEqual(fpvs.count(), 1)
        fpv = fpvs[0]
        self.assertEqual(fpv.user, None)
        self.assertEqual(fpv.is_submitted_answer, None)
        self.assertIsNotNone(fpv.remote_address)

    def test_impersonate(self):
        fs = factories.FlowSessionFactory(
            course=self.course, participation=self.student_participation)
        page_data = factories.FlowPageDataFactory(flow_session=fs)

        self.request.user = self.student_participation.user
        middleware = SessionMiddleware()
        middleware.process_request(self.request)
        self.request.session.save()

        setattr(self.request, "relate_impersonate_original_user",
                self.instructor_participation.user)

        flow.create_flow_page_visit(self.request, fs, page_data)

        fpvs = models.FlowPageVisit.objects.all()
        self.assertEqual(fpvs.count(), 1)
        fpv = fpvs[0]
        self.assertEqual(fpv.user, self.student_participation.user)
        self.assertEqual(fpv.is_submitted_answer, None)
        self.assertIsNotNone(fpv.remote_address)

        self.assertEqual(fpv.impersonated_by, self.instructor_participation.user)


class ViewFlowPageTest(SingleCourseQuizPageTestMixin, HackRepoMixin, TestCase):
    # test flow.view_flow_page for not covered part by other tests

    def setUp(self):
        super(ViewFlowPageTest, self).setUp()

        fake_lock_down_if_needed = mock.patch(
            "course.flow.lock_down_if_needed")
        self.mock_lock_down_if_needed = fake_lock_down_if_needed.start()
        self.addCleanup(fake_lock_down_if_needed.stop)

        fake_create_flow_page_visit = mock.patch(
            "course.flow.create_flow_page_visit")
        self.mock_create_flow_page_visit = fake_create_flow_page_visit.start()
        self.addCleanup(fake_create_flow_page_visit.stop)

    def test_invalid_flow_session_id(self):
        with mock.patch(
                "course.flow.adjust_flow_session_page_data") as mock_adjust_data:
            kwargs = {
                "course_identifier": self.course.identifier,
                "flow_session_id": 100,  # invalid
                "page_ordinal": 0
            }
            resp = self.c.get(
                reverse("relate-view_flow_page", kwargs=kwargs))
            self.assertEqual(resp.status_code, 404)

            # check should happen before adjust session data
            self.assertEqual(mock_adjust_data.call_count, 0)

            self.assertEqual(self.mock_create_flow_page_visit.call_count, 0)

    def test_fpctx_page_is_none(self):
        self.start_flow(self.flow_id)
        with mock.patch("course.content.get_flow_page_desc") as mock_get_page_desc:
            from django.core.exceptions import ObjectDoesNotExist
            mock_get_page_desc.side_effect = ObjectDoesNotExist

            resp = self.c.get(self.get_page_url_by_ordinal(0))
            self.assertEqual(resp.status_code, 404)

            self.assertEqual(self.mock_create_flow_page_visit.call_count, 0)

    default_session_access_rule = {"permissions": []}

    def test_may_not_view(self):
        self.start_flow(self.flow_id)
        with mock.patch(
                "course.page.base.PageBase.get_modified_permissions_for_page"
        ) as mock_perms:
            mock_perms.return_value = []
            resp = self.c.get(self.get_page_url_by_ordinal(0))
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(mock_perms.call_count, 1)

            self.assertTrue(self.mock_lock_down_if_needed.call_count > 0)
            self.assertEqual(self.mock_create_flow_page_visit.call_count, 0)

    def test_post_finish(self):
        self.start_flow(self.flow_id)
        resp = self.c.post(
            self.get_page_url_by_ordinal(0), data={"finish": ""})
        self.assertRedirects(resp, self.get_finish_flow_session_view_url(),
                             fetch_redirect_response=False)
        self.assertEqual(self.mock_create_flow_page_visit.call_count, 0)

    def test_post_result_not_tuple(self):
        self.start_flow(self.flow_id)
        with mock.patch("course.flow.post_flow_page") as mock_post_flow_page:
            mock_post_flow_page.return_value = http.HttpResponse("hello world")
            resp = self.post_answer_by_page_id(
                "half", answer_data={"answer": "ok"})
            self.assertEqual(resp.status_code, 200)

    def test_prev_visit_id_after_post(self):
        self.start_flow(self.flow_id)
        resp = self.post_answer_by_page_id(
            "half", answer_data={"answer": "ok"})

        self.assertResponseContextEqual(resp, "prev_visit_id", 1)

        fpvs = models.FlowPageVisit.objects.all()
        self.assertEqual(fpvs.count(), 1)

        fpv = fpvs[0]

        resp = self.post_answer_by_page_id(
            "half", answer_data={"answer": "1/2"})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(resp, "prev_visit_id", fpv.id)

    def test_get_prev_visit_id_not_number(self):
        self.start_flow(self.flow_id)
        resp = self.c.get(self.get_page_url_by_ordinal(1, visit_id="foo"))
        self.assertEqual(resp.status_code, 400)

    def test_get_prev_visit_id_not_exists(self):
        # no prev_answer_visits
        self.start_flow(self.flow_id)
        resp = self.c.get(self.get_page_url_by_ordinal(1, visit_id=100))
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(resp, "viewing_prior_version", False)

    def test_get_prev_visit_id_not_exists_with_prev_answer_visit(self):
        self.start_flow(self.flow_id)
        page_id = "half"
        page_data = models.FlowPageData.objects.get(page_id=page_id)
        factories.FlowPageVisitFactory(
            page_data=page_data, answer={"answer": "hi"})

        resp = self.c.get(self.get_page_url_by_page_id(page_id, visit_id=100))
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(resp, "viewing_prior_version", False)

    def switch_to_fake_commit_sha(
            self, commit_sha="my_fake_commit_sha_for_view_flow_page"):
        self.course.active_git_commit_sha = commit_sha
        self.course.save()

    def test_get_prev_visit_id_exists(self):
        self.switch_to_fake_commit_sha()

        self.start_flow(self.flow_id)
        page_id = "half"
        page_data = models.FlowPageData.objects.get(page_id=page_id)

        visit_time = now() - timedelta(days=1)

        visit0 = factories.FlowPageVisitFactory(
            page_data=page_data, answer=None, visit_time=visit_time)

        visit_time = visit_time + timedelta(hours=1)

        visit1 = factories.FlowPageVisitFactory(
            page_data=page_data, answer={"answer": "hi"}, visit_time=visit_time)

        visit_time = visit_time + timedelta(hours=1)

        visit2 = factories.FlowPageVisitFactory(
            page_data=page_data, answer={"answer": "hello"}, visit_time=visit_time)

        with mock.patch("course.flow.messages.add_message") as mock_add_msg:
            # viewing current visit
            resp = self.c.get(
                self.get_page_url_by_page_id(page_id, visit_id=visit2.id))
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "viewing_prior_version", False)
            self.assertEqual(mock_add_msg.call_count, 0, mock_add_msg.call_args)
            mock_add_msg.reset_mock()

            # viewing non-answer visit
            resp = self.c.get(
                self.get_page_url_by_page_id(page_id, visit_id=visit0.id))
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "viewing_prior_version", False)
            self.assertEqual(mock_add_msg.call_count, 0, mock_add_msg.call_args)
            mock_add_msg.reset_mock()

            # viewing previous visit
            resp = self.c.get(
                self.get_page_url_by_page_id(page_id, visit_id=visit1.id))
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "viewing_prior_version", True)
            self.assertEqual(mock_add_msg.call_count, 1)
            expected_warn_message_partial = "Viewing prior submission dated"
            self.assertIn(
                expected_warn_message_partial, mock_add_msg.call_args[0][2])

    def test_see_session_time_not_in_progress(self):
        completion_time = now() - timedelta(days=1)
        start_time = completion_time - timedelta(hours=1)
        self.student_participation.time_factor = 1.11
        self.student_participation.save()

        fs = factories.FlowSessionFactory(
            course=self.course,
            participation=self.student_participation,
            start_time=start_time,
            completion_time=completion_time, in_progress=False)

        resp = self.c.get(self.get_page_url_by_ordinal(0, flow_session_id=fs.id))
        self.assertResponseContextEqual(resp, "session_minutes", None)
        self.assertResponseContextEqual(resp, "time_factor", 1)

        self.switch_to_fake_commit_sha()
        resp = self.c.get(self.get_page_url_by_ordinal(0, flow_session_id=fs.id))
        self.assertResponseContextEqual(resp, "session_minutes", 60)
        self.assertResponseContextEqual(resp, "time_factor", 1.11)

    def test_see_session_time_in_progress(self):
        self.switch_to_fake_commit_sha()

        start_time = now() - timedelta(minutes=62)

        fs = factories.FlowSessionFactory(
            course=self.course,
            participation=self.student_participation,
            start_time=start_time,
            in_progress=True)

        resp = self.c.get(self.get_page_url_by_ordinal(0, flow_session_id=fs.id))
        self.assertTrue(resp.context["session_minutes"] > 61)
        self.assertResponseContextEqual(resp, "time_factor", 1)

    def test_warning_for_anonymous_flow_session(self):
        # switch to a fake flow which allow anonymous to start a flow
        self.switch_to_fake_commit_sha()
        self.c.logout()
        self.start_flow(self.flow_id)

        with mock.patch("course.flow.messages.add_message") as mock_add_msg:
            resp = self.c.get(self.get_page_url_by_ordinal(1))
            expected_warn_msg = (
                "Changes to this session are being prevented "
                "because this session yields a permanent grade, but "
                "you have not completed your enrollment process in "
                "this course.")
            self.assertIn(expected_warn_msg, mock_add_msg.call_args[0])
            self.assertResponseContextIsNotNone(resp, "session_minutes")
            self.assertResponseContextEqual(resp, "time_factor", 1)

    def test_viewing_optional_page(self):
        self.switch_to_fake_commit_sha()
        self.start_flow(self.flow_id)

        resp = self.c.get(self.get_page_url_by_page_id("half"))
        self.assertResponseHasNoContext(resp, "is_optional_page")

        resp = self.c.get(self.get_page_url_by_page_id("half2"))
        self.assertResponseContextEqual(resp, "is_optional_page", True)


@unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
class GetPressedButtonTest(unittest.TestCase):
    def test_success(self):
        buttons = ["save", "save_and_next", "save_and_finish", "submit"]
        for button in buttons:
            with self.subTest(button=button):
                form = StyledForm(data={button: ""})
                self.assertEqual(flow.get_pressed_button(form), button)

    def test_failure(self):
        form = StyledForm(data={"unknown": ""})
        from django.core.exceptions import SuspiciousOperation
        with self.assertRaises(SuspiciousOperation) as cm:
            flow.get_pressed_button(form)

        expected_error_msg = "could not find which button was pressed"
        self.assertIn(expected_error_msg, str(cm.exception))


class PostFlowPageTest(HackRepoMixin, SingleCourseQuizPageTestMixin, TestCase):
    # test flow.post_flow_page for not covered part by other tests

    initial_commit_sha = "my_fake_commit_sha_for_view_flow_page"
    page_id = "half"

    @classmethod
    def setUpTestData(cls):  # noqa
        super(PostFlowPageTest, cls).setUpTestData()

        # We only concern one page, so it can be put here to speed up
        cls.start_flow(cls.flow_id)

        # Because they change between test, we need to refer to them
        # to do refresh_from_db when setUp.
        cls.flow_session = models.FlowSession.objects.first()
        cls.page_data = models.FlowPageData.objects.get(page_id=cls.page_id)

    def setUp(self):
        super(PostFlowPageTest, self).setUp()
        self.flow_session.refresh_from_db()
        self.page_data.refresh_from_db()
        self.fpctx = mock.MagicMock()

        rf = RequestFactory()
        self.request = rf.get(self.get_course_page_url())
        self.request.user = self.student_participation.user
        middleware = SessionMiddleware()
        middleware.process_request(self.request)
        self.request.session.save()

        self.fpctx.course = self.course
        self.fpctx.page_data = self.page_data
        self.fpctx.page.answer_data.return_value = {"answer": "hello"}
        self.fpctx.page_ordinal = self.page_data.page_ordinal

        from course.page.base import AnswerFeedback
        self.fpctx.page.grade.return_value = AnswerFeedback(correctness=1)

        fake_create_flow_page_visit = mock.patch(
            "course.flow.create_flow_page_visit")
        self.mock_create_flow_page_visit = fake_create_flow_page_visit.start()
        self.addCleanup(fake_create_flow_page_visit.stop)

        fake_get_prev_answer_visits_qset = mock.patch(
            "course.flow.get_prev_answer_visits_qset")
        self.mock_get_prev_answer_visits_qset = (
            fake_get_prev_answer_visits_qset.start())
        self.addCleanup(fake_get_prev_answer_visits_qset.stop)

        fake_get_pressed_button = mock.patch(
            "course.flow.get_pressed_button")
        self.mock_get_pressed_button = fake_get_pressed_button.start()
        self.addCleanup(fake_get_pressed_button.stop)

        fake_add_message = mock.patch("course.flow.messages.add_message")
        self.mock_add_message = fake_add_message.start()
        self.addCleanup(fake_add_message.stop)

        fake_will_receive_feedback = mock.patch(
            "course.flow.will_receive_feedback")
        self.mock_will_receive_feedback = fake_will_receive_feedback.start()
        self.addCleanup(fake_will_receive_feedback.stop)

    def test_no_submit_answer_fperm(self):
        flow.post_flow_page(
            self.flow_session, self.fpctx, self.request,
            permissions=frozenset(), generates_grade=True)

        self.assertEqual(
            self.mock_create_flow_page_visit.call_count, 1)
        self.assertEqual(self.mock_add_message.call_count, 2)
        msgs = ["Answer submission not allowed.",
                "Failed to submit answer."]

        used = []
        for calls in self.mock_add_message.call_args_list:
            args, _ = calls
            for msg in msgs:
                if msg in args:
                    used.append(msg)

        for msg in msgs:
            if msg not in used:
                self.fail("%s is unexpectedly not used in adding message")

    def test_impersonated(self):
        setattr(self.request, "relate_impersonate_original_user",
                self.instructor_participation.user)
        self.mock_get_pressed_button.return_value = "save"
        flow.post_flow_page(
            self.flow_session, self.fpctx, self.request,
            permissions=frozenset([fperm.submit_answer, fperm.change_answer]),
            generates_grade=True)

        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertIn("Answer saved.",
                      self.mock_add_message.call_args[0])

        self.assertEqual(
            self.mock_create_flow_page_visit.call_count, 0)

        latest_answer_visit = models.FlowPageVisit.objects.last()
        self.assertEqual(latest_answer_visit.impersonated_by,
                         self.instructor_participation.user)

    def test_save_and_next(self):
        self.mock_get_pressed_button.return_value = "save_and_next"
        self.mock_will_receive_feedback.return_value = False
        resp = flow.post_flow_page(
            self.flow_session, self.fpctx, self.request,
            permissions=frozenset([fperm.submit_answer, fperm.change_answer]),
            generates_grade=True)

        self.assertIsInstance(resp, http.HttpResponse)

        next_page_ordinal = self.page_data.page_ordinal + 1

        self.assertRedirects(
            resp, self.get_page_url_by_ordinal(next_page_ordinal),
            fetch_redirect_response=False)

        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertIn("Answer saved.",
                      self.mock_add_message.call_args[0])

        self.assertEqual(
            self.mock_create_flow_page_visit.call_count, 0)

        latest_answer_visit = models.FlowPageVisit.objects.last()
        self.assertIsNone(latest_answer_visit.impersonated_by)

    def test_save_and_finish(self):
        self.mock_get_pressed_button.return_value = "save_and_finish"
        self.mock_will_receive_feedback.return_value = False
        resp = flow.post_flow_page(
            self.flow_session, self.fpctx, self.request,
            permissions=frozenset([fperm.submit_answer, fperm.change_answer]),
            generates_grade=True)

        self.assertRedirects(
            resp, self.get_finish_flow_session_view_url(),
            fetch_redirect_response=False)

        self.assertIsInstance(resp, http.HttpResponse)
        self.assertEqual(resp.status_code, 302)

        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertIn("Answer saved.",
                      self.mock_add_message.call_args[0])

        self.assertEqual(
            self.mock_create_flow_page_visit.call_count, 0)


class SendEmailAboutFlowPageTest(HackRepoMixin,
                                 SingleCourseQuizPageTestMixin, TestCase):
    # test flow.send_email_about_flow_page
    initial_commit_sha = "my_fake_commit_sha_for_view_flow_page"
    page_id = "half"

    @classmethod
    def setUpTestData(cls):  # noqa
        super(SendEmailAboutFlowPageTest, cls).setUpTestData()

        # We only conern one page, so it can be put here to speed up
        cls.start_flow(cls.flow_id)

        # Because they change between test, we need to refer to them
        # to do refresh_from_db when setUp.
        cls.flow_session = models.FlowSession.objects.first()
        cls.page_data = models.FlowPageData.objects.get(page_id=cls.page_id)

    def setUp(self):
        super(SendEmailAboutFlowPageTest, self).setUp()

        fake_get_session_access_rule = mock.patch(
            "course.flow.get_session_access_rule")
        self.mock_get_session_access_rule = fake_get_session_access_rule.start()
        self.addCleanup(fake_get_session_access_rule.stop)

        fake_adjust_flow_session_page_data = mock.patch(
            "course.flow.adjust_flow_session_page_data")
        self.mock_adjust_flow_session_page_data = (
            fake_adjust_flow_session_page_data.start())
        self.mock_adjust_flow_session_page_data.return_value = None
        self.addCleanup(fake_adjust_flow_session_page_data.stop)

        fake_get_login_exam_ticket = mock.patch("course.flow.get_login_exam_ticket")
        self.mock_get_login_exam_ticket = fake_get_login_exam_ticket.start()
        self.addCleanup(fake_get_login_exam_ticket.stop)

        fake_get_modified_permissions_for_page = mock.patch(
            "course.page.base.PageBase.get_modified_permissions_for_page")
        self.mock_get_modified_permissions_for_page = (
            fake_get_modified_permissions_for_page.start()
        )
        self.mock_get_modified_permissions_for_page.return_value = [
            fperm.view, fperm.send_email_about_flow_page]
        self.addCleanup(fake_get_modified_permissions_for_page.stop)

        fake_get_and_check_flow_session = mock.patch(
            "course.flow.get_and_check_flow_session")
        self.mock_get_and_check_flow_session = (
            fake_get_and_check_flow_session.start())
        self.mock_get_and_check_flow_session.return_value = self.flow_session
        self.addCleanup(fake_get_and_check_flow_session.stop)

        fake_add_message = mock.patch("course.flow.messages.add_message")
        self.mock_add_message = fake_add_message.start()
        self.addCleanup(fake_add_message.stop)

        fake_will_use_masked_profile_for_email = mock.patch(
            "course.utils.will_use_masked_profile_for_email")
        self.mock_will_use_masked_profile_for_email = (
            fake_will_use_masked_profile_for_email.start())
        self.mock_will_use_masked_profile_for_email.return_value = False
        self.addCleanup(fake_will_use_masked_profile_for_email.stop)

    def get_send_email_about_flow_page_url(
            self, page_ordinal, course_identifier=None,
            flow_session_id=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        flow_session_id = (flow_session_id
                           or self.get_default_flow_session_id(course_identifier))
        return reverse(
            "relate-flow_page_interaction_email",
            kwargs={"course_identifier": course_identifier,
                    "flow_session_id": flow_session_id,
                    "page_ordinal": page_ordinal})

    def test_404(self):
        with mock.patch("course.content.get_flow_page_desc") as mock_get_page_desc:
            from django.core.exceptions import ObjectDoesNotExist
            mock_get_page_desc.side_effect = ObjectDoesNotExist
            resp = self.c.get(
                self.get_send_email_about_flow_page_url(page_ordinal=1))
            self.assertEqual(resp.status_code, 404)

            self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 1)
            self.assertEqual(self.mock_get_login_exam_ticket.call_count, 0)

    def test_no_permission_404(self):
        self.mock_get_modified_permissions_for_page.return_value = [fperm.view]

        resp = self.c.get(
            self.get_send_email_about_flow_page_url(page_ordinal=1))
        self.assertEqual(resp.status_code, 404)

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 1)
        self.assertEqual(self.mock_get_login_exam_ticket.call_count, 1)
        self.assertEqual(self.mock_get_session_access_rule.call_count, 1)
        self.assertEqual(self.mock_get_modified_permissions_for_page.call_count, 1)

    def test_may_send_email_about_flow_page_called(self):
        with mock.patch(
                "course.flow.may_send_email_about_flow_page") as mock_check:
            mock_check.return_value = False

            permissions = mock.MagicMock()
            self.mock_get_modified_permissions_for_page.return_value = permissions

            resp = self.c.get(
                self.get_send_email_about_flow_page_url(page_ordinal=1))
            self.assertEqual(resp.status_code, 404)
            self.assertEqual(mock_check.call_count, 1)
            self.assertIn(permissions, mock_check.call_args[0])

            mock_check.reset_mock()

            mock_check.return_value = True

            resp = self.c.get(
                self.get_send_email_about_flow_page_url(page_ordinal=1))
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(mock_check.call_count, 1)
            self.assertIn(permissions, mock_check.call_args[0])

    def test_get(self):
        resp = self.c.get(
            self.get_send_email_about_flow_page_url(page_ordinal=1))
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(self.mock_adjust_flow_session_page_data.call_count, 1)
        self.assertEqual(self.mock_get_login_exam_ticket.call_count, 1)
        self.assertEqual(self.mock_get_session_access_rule.call_count, 1)
        self.assertEqual(self.mock_get_modified_permissions_for_page.call_count, 1)

    def test_post(self):
        resp = self.c.post(
            self.get_send_email_about_flow_page_url(page_ordinal=1),
            data={"message": "foo bar" * 10}
        )
        self.assertRedirects(resp, self.get_page_url_by_ordinal(1),
                             fetch_redirect_response=False)

        self.assertEqual(self.mock_add_message.call_count, 1)
        expected_msg = ("Email sent, and notice that you will "
                        "also receive a copy of the email.")
        self.assertIn(expected_msg, self.mock_add_message.call_args[0])

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            mail.outbox[0].recipients(),
            [self.ta_participation.user.email,
             self.student_participation.user.email])
        self.assertEqual(
            mail.outbox[0].reply_to, [self.student_participation.user.email])
        self.assertEqual(
            mail.outbox[0].bcc, [self.student_participation.user.email])

    def test_post_too_few_words(self):
        resp = self.c.post(
            self.get_send_email_about_flow_page_url(page_ordinal=1),
            data={"message": "foo bar"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFormErrorLoose(
            resp, "At least 20 characters are required for submission.")
        self.assertEqual(len(mail.outbox), 0)

    def test_no_tas(self):
        self.ta_participation.status = constants.participation_status.dropped
        self.ta_participation.save()

        resp = self.c.post(
            self.get_send_email_about_flow_page_url(page_ordinal=1),
            data={"message": "foo bar" * 10}
        )
        self.assertRedirects(resp, self.get_page_url_by_ordinal(1),
                             fetch_redirect_response=False)

        self.assertEqual(self.mock_add_message.call_count, 1)
        expected_msg = ("Email sent, and notice that you will "
                        "also receive a copy of the email.")
        self.assertIn(expected_msg, self.mock_add_message.call_args[0])

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            mail.outbox[0].recipients(),
            [self.instructor_participation.user.email,
             self.student_participation.user.email])
        self.assertEqual(
            mail.outbox[0].reply_to, [self.student_participation.user.email])
        self.assertEqual(
            mail.outbox[0].bcc, [self.student_participation.user.email])

        self.assertIn(
            self.student_participation.user.get_email_appellation(),
            mail.outbox[0].body)
        self.assertNotIn(
            self.student_participation.user.get_masked_profile(),
            mail.outbox[0].body)
        self.assertNotIn(
            "Dear user",
            mail.outbox[0].body)

    def test_mask_student_profile(self):
        self.mock_will_use_masked_profile_for_email.return_value = True

        resp = self.c.post(
            self.get_send_email_about_flow_page_url(page_ordinal=1),
            data={"message": "foo bar" * 10}
        )
        self.assertRedirects(resp, self.get_page_url_by_ordinal(1),
                             fetch_redirect_response=False)

        self.assertEqual(self.mock_add_message.call_count, 1)
        expected_msg = ("Email sent, and notice that you will "
                        "also receive a copy of the email.")
        self.assertIn(expected_msg, self.mock_add_message.call_args[0])

        self.assertEqual(len(mail.outbox), 1)

        self.assertNotIn(
            self.student_participation.user.get_email_appellation(),
            mail.outbox[0].body)
        self.assertIn(
            self.student_participation.user.get_masked_profile(),
            mail.outbox[0].body)


class UpdatePageBookmarkStateTest(SingleCourseQuizPageTestMixin, TestCase):
    # test flow.update_page_bookmark_state

    def setUp(self):
        super(UpdatePageBookmarkStateTest, self).setUp()
        self.start_flow(self.flow_id)
        self.flow_session = models.FlowSession.objects.last()

    def get_update_page_bookmark_state_url(
            self, page_ordinal, course_identifier=None, flow_session_id=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        flow_session_id = (flow_session_id
                           or self.get_default_flow_session_id(course_identifier))
        return reverse(
            "relate-update_page_bookmark_state",
            kwargs={"course_identifier": course_identifier,
                    "flow_session_id": flow_session_id,
                    "page_ordinal": page_ordinal})

    def test_not_post(self):
        resp = self.c.get(self.get_update_page_bookmark_state_url(1))
        self.assertEqual(resp.status_code, 400)
        fpd = models.FlowPageData.objects.get(
            flow_session=self.flow_session, page_ordinal=1)
        self.assertEqual(fpd.bookmarked, False)

    def test_invalid_flow_session_id(self):
        resp = self.c.post(
            self.get_update_page_bookmark_state_url(1, flow_session_id=100),
            data={"bookmark_state": "1"})
        self.assertEqual(resp.status_code, 404)
        fpd = models.FlowPageData.objects.get(
            flow_session=self.flow_session, page_ordinal=1)
        self.assertEqual(fpd.bookmarked, False)

    def test_success(self):
        resp = self.c.post(
            self.get_update_page_bookmark_state_url(1),
            data={"bookmark_state": "1"})
        self.assertEqual(resp.status_code, 200)
        fpd = models.FlowPageData.objects.get(
            flow_session=self.flow_session, page_ordinal=1)
        self.assertEqual(fpd.bookmarked, True)

    def test_post_invalid_bookmark_state(self):
        resp = self.c.post(
            self.get_update_page_bookmark_state_url(1),
            data={"bookmark_state": "a"})
        self.assertEqual(resp.status_code, 400)
        fpd = models.FlowPageData.objects.get(
            flow_session=self.flow_session, page_ordinal=1)
        self.assertEqual(fpd.bookmarked, False)

    def test_not_you_session(self):
        with self.temporarily_switch_to_user(self.ta_participation.user):
            resp = self.c.post(
                self.get_update_page_bookmark_state_url(1),
                data={"bookmark_state": "1"})
            self.assertEqual(resp.status_code, 403)
            fpd = models.FlowPageData.objects.get(
                flow_session=self.flow_session, page_ordinal=1)
            self.assertEqual(fpd.bookmarked, False)


class UpdateExpirationModeTest(SingleCourseQuizPageTestMixin, TestCase):
    # test flow.update_expiration_mode

    def setUp(self):
        super(UpdateExpirationModeTest, self).setUp()
        self.start_flow(self.flow_id)
        self.flow_session = models.FlowSession.objects.last()

        fake_get_login_exam_ticket = mock.patch("course.flow.get_login_exam_ticket")
        self.mock_get_login_exam_ticket = fake_get_login_exam_ticket.start()
        self.addCleanup(fake_get_login_exam_ticket.stop)

        fake_is_expiration_mode_allowed = mock.patch(
            "course.flow.is_expiration_mode_allowed")
        self.mock_is_expiration_mode_allowed = (
            fake_is_expiration_mode_allowed.start())
        self.mock_is_expiration_mode_allowed.return_value = True
        self.addCleanup(fake_is_expiration_mode_allowed.stop)

    def get_relate_update_expiration_mode_url(
            self, course_identifier=None, flow_session_id=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        flow_session_id = (flow_session_id
                           or self.get_default_flow_session_id(course_identifier))
        return reverse(
            "relate-update_expiration_mode",
            kwargs={"course_identifier": course_identifier,
                    "flow_session_id": flow_session_id})

    def test_not_post(self):
        resp = self.c.get(self.get_relate_update_expiration_mode_url())
        self.assertEqual(resp.status_code, 400)
        fs = models.FlowSession.objects.last()
        self.assertEqual(fs.expiration_mode,
                         constants.flow_session_expiration_mode.end)

    def test_invalid_flow_session_id(self):
        resp = self.c.post(
            self.get_relate_update_expiration_mode_url(flow_session_id=100),
            data={"expiration_mode":
                      constants.flow_session_expiration_mode.roll_over})
        self.assertEqual(resp.status_code, 404)
        fs = models.FlowSession.objects.last()
        self.assertEqual(fs.expiration_mode,
                         constants.flow_session_expiration_mode.end)

    def test_session_not_in_progress(self):
        self.flow_session.in_progress = False
        self.flow_session.save()
        resp = self.c.post(
            self.get_relate_update_expiration_mode_url(),
            data={"expiration_mode":
                      constants.flow_session_expiration_mode.roll_over})
        self.assertEqual(resp.status_code, 403)
        fs = models.FlowSession.objects.last()
        self.assertEqual(fs.expiration_mode,
                         constants.flow_session_expiration_mode.end)

    def test_success(self):
        resp = self.c.post(
            self.get_relate_update_expiration_mode_url(),
            data={"expiration_mode":
                      constants.flow_session_expiration_mode.roll_over})
        self.assertEqual(resp.status_code, 200)
        fs = models.FlowSession.objects.last()
        self.assertEqual(fs.expiration_mode,
                         constants.flow_session_expiration_mode.roll_over)

    def test_not_is_expiration_mode_allowed(self):
        self.mock_is_expiration_mode_allowed.return_value = False
        resp = self.c.post(
            self.get_relate_update_expiration_mode_url(),
            data={"expiration_mode":
                      constants.flow_session_expiration_mode.roll_over})
        self.assertEqual(resp.status_code, 403)
        fs = models.FlowSession.objects.last()
        self.assertEqual(fs.expiration_mode,
                         constants.flow_session_expiration_mode.end)

    def test_post_invalid_bookmark_state(self):
        resp = self.c.post(
            self.get_relate_update_expiration_mode_url(),
            data={"expiration_mode": "unknown"})
        self.assertEqual(resp.status_code, 400)
        fs = models.FlowSession.objects.last()
        self.assertEqual(fs.expiration_mode,
                         constants.flow_session_expiration_mode.end)

    def test_not_you_session(self):
        with self.temporarily_switch_to_user(self.ta_participation.user):
            resp = self.c.post(
                self.get_relate_update_expiration_mode_url(),
                data={"expiration_mode":
                          constants.flow_session_expiration_mode.roll_over})
            self.assertEqual(resp.status_code, 403)
            fs = models.FlowSession.objects.last()
            self.assertEqual(fs.expiration_mode,
                             constants.flow_session_expiration_mode.end)


class RegradeFlowsViewTest(SingleCourseQuizPageTestMixin, TestCase):
    # test flow.regrade_flows_view

    def setUp(self):
        super(RegradeFlowsViewTest, self).setUp()
        self.c.force_login(self.instructor_participation.user)

        fake_regrade_task = mock.patch(
                "course.tasks.regrade_flow_sessions.delay")
        self.mock_regrade_task = fake_regrade_task.start()
        self.addCleanup(fake_regrade_task.stop)

        fake_redirect = mock.patch("course.flow.redirect")
        self.mock_redirect = fake_redirect.start()
        self.addCleanup(fake_redirect.stop)

    def get_regrade_flows_view_url(self, course_identfier=None):
        course_identfier = course_identfier or self.get_default_course_identifier()
        return reverse("relate-regrade_flows_view", args=(course_identfier,))

    def test_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(self.get_regrade_flows_view_url())
            self.assertEqual(resp.status_code, 403)

            self.assertEqual(self.mock_regrade_task.call_count, 0)
            self.assertEqual(self.mock_redirect.call_count, 0)

            resp = self.c.post(
                self.get_regrade_flows_view_url(),
                data={
                    "regraded_session_in_progress": "yes",
                    "flow_id": QUIZ_FLOW_ID,
                    "access_rules_tag": "",
                }
            )
            self.assertEqual(resp.status_code, 403)

            self.assertEqual(self.mock_regrade_task.call_count, 0)
            self.assertEqual(self.mock_redirect.call_count, 0)

    def test_form_error(self):
        with mock.patch(
                "course.flow.RegradeFlowForm.is_valid") as mock_form_is_valid:
            mock_form_is_valid.return_value = False
            resp = self.c.post(
                self.get_regrade_flows_view_url(),
                data={
                    "regraded_session_in_progress": "yes",
                    "flow_id": QUIZ_FLOW_ID,
                    "access_rules_tag": "",
                }
            )
            self.assertEqual(resp.status_code, 200)

            self.assertEqual(self.mock_regrade_task.call_count, 0)
            self.assertEqual(self.mock_redirect.call_count, 0)

    @unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_success(self):
        # get success
        resp = self.c.get(self.get_regrade_flows_view_url())
        self.assertEqual(resp.status_code, 200)

        # post success
        access_rules_tag = "some_tag"
        flow_id = self.flow_id
        inprog_value_map = {
            "any": None,
            "yes": True,
            "no": False,
        }
        for regraded_session_in_progress, inprog_value in (
                six.iteritems(inprog_value_map)):
            with self.subTest(
                    regraded_session_in_progress=regraded_session_in_progress):
                self.mock_regrade_task.return_value = mock.MagicMock()
                self.mock_redirect.return_value = http.HttpResponse()
                resp = self.c.post(
                    self.get_regrade_flows_view_url(),
                    data={
                        "regraded_session_in_progress":
                            regraded_session_in_progress,
                        "flow_id": flow_id,
                        "access_rules_tag": access_rules_tag,
                    }
                )
                self.assertFormErrorLoose(resp, None)
                self.assertEqual(self.mock_regrade_task.call_count, 1)
                self.mock_regrade_task.assert_called_once_with(
                    self.course.id,
                    flow_id,
                    access_rules_tag,
                    inprog_value,
                )
                self.mock_regrade_task.reset_mock()
                self.assertEqual(self.mock_redirect.call_count, 1)
                self.assertIn(
                    "relate-monitor_task", self.mock_redirect.call_args[0])
                self.mock_redirect.reset_mock()


class ViewUnsubmitFlowPageTest(SingleCourseQuizPageTestMixin, TestCase):
    # test flow.view_unsubmit_flow_page

    page_id = "half"

    @classmethod
    def setUpTestData(cls):  # noqa
        super(ViewUnsubmitFlowPageTest, cls).setUpTestData()
        with cls.temporarily_switch_to_user(cls.student_participation.user):
            cls.start_flow(cls.flow_id)
            cls.submit_page_answer_by_page_id_and_test(page_id=cls.page_id)

    def setUp(self):
        super(ViewUnsubmitFlowPageTest, self).setUp()
        self.c.force_login(self.instructor_participation.user)

        fake_unsubmit_page = mock.patch(
            "course.flow.unsubmit_page")
        self.mock_unsubmit_page = fake_unsubmit_page.start()
        self.addCleanup(fake_unsubmit_page.stop)

        fake_add_message = mock.patch("course.flow.messages.add_message")
        self.mock_add_message = fake_add_message.start()
        self.addCleanup(fake_add_message.stop)

        fake_adjust_flow_session_page_data = mock.patch(
            "course.flow.adjust_flow_session_page_data")
        self.mock_adjust_flow_session_page_data = (
            fake_adjust_flow_session_page_data.start())
        self.mock_adjust_flow_session_page_data.return_value = None
        self.addCleanup(fake_adjust_flow_session_page_data.stop)

    def get_view_unsubmit_flow_page_url(
            self, page_ordinal, course_identifier=None, flow_session_id=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        flow_session_id = (flow_session_id
                           or self.get_default_flow_session_id(course_identifier))
        return reverse(
            "relate-unsubmit_flow_page",
            kwargs={"course_identifier": course_identifier,
                    "flow_session_id": flow_session_id,
                    "page_ordinal": page_ordinal})

    def get_view_unsubmit_flow_page_url_by_page_id(
            self, page_id, course_identifier=None, flow_session_id=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        flow_session_id = (flow_session_id
                           or self.get_default_flow_session_id(course_identifier))
        page_ordinal = self.get_page_ordinal_via_page_id(page_id)
        return self.get_view_unsubmit_flow_page_url(
            page_ordinal, course_identifier, flow_session_id)

    def test_anonymous(self):
        with self.temporarily_switch_to_user(None):
            resp = self.c.get(
                self.get_view_unsubmit_flow_page_url_by_page_id(self.page_id))
            self.assertEqual(resp.status_code, 403)

            resp = self.c.post(
                self.get_view_unsubmit_flow_page_url_by_page_id(self.page_id),
                data={"submit": ""})

            self.assertEqual(resp.status_code, 403)
            self.assertEqual(self.mock_unsubmit_page.call_count, 0)

    def test_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(
                self.get_view_unsubmit_flow_page_url_by_page_id(self.page_id))
            self.assertEqual(resp.status_code, 403)

            resp = self.c.post(
                self.get_view_unsubmit_flow_page_url_by_page_id(self.page_id),
                data={"submit": ""})

            self.assertEqual(resp.status_code, 403)
            self.assertEqual(self.mock_unsubmit_page.call_count, 0)

    def test_session_does_not_exist(self):
        resp = self.c.get(
            self.get_view_unsubmit_flow_page_url_by_page_id(
                self.page_id, flow_session_id=100))
        self.assertEqual(resp.status_code, 404)

        resp = self.c.post(
            self.get_view_unsubmit_flow_page_url_by_page_id(
                self.page_id, flow_session_id=100),
            data={"submit": ""})

        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.mock_unsubmit_page.call_count, 0)

    def test_success(self):
        # get_success
        resp = self.c.get(
            self.get_view_unsubmit_flow_page_url_by_page_id(self.page_id))
        self.assertEqual(resp.status_code, 200)

        # post_success
        resp = self.c.post(
            self.get_view_unsubmit_flow_page_url_by_page_id(self.page_id),
            data={"submit": ""})

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.mock_unsubmit_page.call_count, 1)
        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertIn(
            "Flow page changes reallowed. ",
            self.mock_add_message.call_args[0]
        )

    def test_postdata_without_submit(self):
        resp = self.c.post(
            self.get_view_unsubmit_flow_page_url_by_page_id(self.page_id),
            data={})

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.mock_unsubmit_page.call_count, 0)

        self.assertEqual(self.mock_add_message.call_count, 0)

    def test_post_form_not_valid(self):
        with mock.patch(
                "course.flow.UnsubmitFlowPageForm.is_valid") as mock_form_valid:
            mock_form_valid.return_value = False
            resp = self.c.post(
                self.get_view_unsubmit_flow_page_url_by_page_id(self.page_id),
                data={"submit": ""})

            self.assertEqual(resp.status_code, 200)
            self.assertEqual(self.mock_unsubmit_page.call_count, 0)

    def test_unsubmit_page_has_no_answer_visit(self):
        # this page has not been answered yet
        page_id = "ice_cream_toppings"
        expected_error_msg = "No prior answers found that could be un-submitted."

        resp = self.c.get(
            self.get_view_unsubmit_flow_page_url_by_page_id(page_id))

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.mock_unsubmit_page.call_count, 0)

        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertIn(expected_error_msg, self.mock_add_message.call_args[0])
        self.mock_add_message.reset_mock()

        resp = self.c.post(
            self.get_view_unsubmit_flow_page_url_by_page_id(page_id),
            data={"submit": ""})

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.mock_unsubmit_page.call_count, 0)

        self.assertEqual(self.mock_add_message.call_count, 1)
        self.assertIn(expected_error_msg, self.mock_add_message.call_args[0])

# vim: foldmethod=marker
