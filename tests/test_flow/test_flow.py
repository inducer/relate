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

import unittest
from django.test import TestCase
from django.utils.timezone import now, timedelta

from relate.utils import dict_to_struct

from course.content import get_repo_blob
from course import models, flow
from course import constants
from course.constants import grade_aggregation_strategy as g_strategy
from course.utils import FlowSessionStartRule, FlowSessionGradingRule

from tests.base_test_mixins import (
    CoursesTestMixinBase, SingleCourseQuizPageTestMixin, SingleCourseTestMixin)
from tests.constants import QUIZ_FLOW_ID
from tests.utils import mock
from tests import factories

YAML_PATH = os.path.join(os.path.dirname(__file__), 'resource')


class Blob(object):
    def __init__(self, yaml_file_name):
        with open(os.path.join(YAML_PATH, yaml_file_name), "rb") as f:
            data = f.read()
        self.data = data


# This is need to for correctly getting other blob
current_commit_sha = b"4124e0c23e369d6709a670398167cb9c2fe52d35"

COMMIT_SHA_MAP = {
    "flows/%s.yml" % QUIZ_FLOW_ID: [
        {"my_fake_commit_sha_1": {"path": "fake-quiz-test1.yml"}},
        {"my_fake_commit_sha_2": {"path": "fake-quiz-test2.yml"}},

        {"my_fake_commit_sha_for_grades1": {
            "path": "fake-quiz-test-for-grade1.yml",
            "page_ids": ["half", "krylov", "quarter"]}},
        {"my_fake_commit_sha_for_grades2": {
            "path": "fake-quiz-test-for-grade2.yml",
            "page_ids": ["krylov", "quarter"]}},

        {"my_fake_commit_sha_for_gradesinfo": {
            "path": "fake-quiz-test-for-gradeinfo.yml",
            "page_ids": ["half", "krylov", "matrix_props", "age_group",
                         "anyup", "proof", "neumann"]
        }},

        {"my_fake_commit_sha_for_grade_flow_session": {
            "path": "fake-quiz-test-for-grade_flow_session.yml",
            "page_ids": ["anyup"]}},
        {"my_fake_commit_sha_for_grade_flow_session2": {
            "path": "fake-quiz-test-for-grade_flow_session2.yml",
            "page_ids": ["anyup"]}}
    ],

    "flow/%s.yml" % "001-linalg-recap":
        [{"my_fake_commit_sha_3": {"path": "fake-001-linalg-recap.yml"}}]
}


def get_repo_side_effect(repo, full_name, commit_sha, allow_tree=True):
    commit_sha_path_maps = COMMIT_SHA_MAP.get(full_name)
    if commit_sha_path_maps:
        assert isinstance(commit_sha_path_maps, list)
        for cs_map in commit_sha_path_maps:
            if commit_sha.decode() in cs_map:
                path = cs_map[commit_sha.decode()]["path"]
                return Blob(path)

    return get_repo_blob(repo, full_name, current_commit_sha, allow_tree=allow_tree)


def flow_page_data_save_side_effect(self, *args, **kwargs):
    if self.page_id == "half1":
        raise RuntimeError("this error should not have been raised!")


class BatchFakeGetRepoBlobMixin(object):
    def setUp(self):
        super(BatchFakeGetRepoBlobMixin, self).setUp()
        batch_fake_get_repo_blob = mock.patch(
            "course.content.get_repo_blob")
        self.batch_mock_get_repo_blob = batch_fake_get_repo_blob.start()
        self.batch_mock_get_repo_blob.side_effect = get_repo_side_effect
        self.addCleanup(batch_fake_get_repo_blob.stop)

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


class AdjustFlowSessionPageDataTest(
        BatchFakeGetRepoBlobMixin, SingleCourseQuizPageTestMixin, TestCase):
    # test flow.adjust_flow_session_page_data

    def setUp(self):
        super(AdjustFlowSessionPageDataTest, self).setUp()
        self.c.force_login(self.student_participation.user)

    def test_remove_rename_and_revive(self):
        self.course.active_git_commit_sha = "my_fake_commit_sha_1"
        self.course.save()

        self.start_flow(flow_id=self.flow_id)

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
        self.course.active_git_commit_sha = "my_fake_commit_sha_1"
        self.course.save()

        self.start_flow(flow_id=self.flow_id)

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

    def tearDown(self):
        for fs in models.FlowSession.objects.all():
            fs.delete()

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


class AssemblePageGradesTest(BatchFakeGetRepoBlobMixin,
                             SingleCourseQuizPageTestMixin, TestCase):
    # This is actually test course.flow.assemble_page_grades

    @classmethod
    def setUpTestData(cls):  # noqa
        super(AssemblePageGradesTest, cls).setUpTestData()
        cls.course.active_git_commit_sha = "my_fake_commit_sha_for_grades1"
        cls.course.save()
        cls.student = cls.student_participation.user

    def setUp(self):
        super(AssemblePageGradesTest, self).setUp()
        self.c.force_login(self.student)

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
        self.start_flow(self.flow_id)

        page_ids = self.get_current_page_ids()
        for page_id in page_ids:
            self.submit_page_answer_by_page_id_and_test(page_id)

        self.end_flow()

        self.assertSessionScoreEqual(7)

        self.assertListEqual(list(self.get_grades_of_opps()), ["100.0%"])
        self.assertListEqual(
            self.get_page_grades_of_opp("la_quiz")[self.student.username],
            [None, 100, 100, 100])

    def test_view_gradebook_two_submissions(self):
        self.start_flow(self.flow_id)
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

        self.assertListEqual(list(self.get_grades_of_opps()), ['28.6% (/2)'])
        self.assertListEqual(
            self.get_page_grades_of_opp("la_quiz")[self.student.username],
            [None, 0, 100, 100])

    def test_view_gradebook_with_question_deleted(self):
        self.start_flow(self.flow_id)
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

        self.assertListEqual(list(self.get_grades_of_opps()), ['28.6%'])
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

        self.assertListEqual(list(self.get_grades_of_opps()), ['100.0% (/2)'])
        self.assertListEqual(
            self.get_page_grades_of_opp("la_quiz")[self.student.username],
            [None, 100, 100, None])

    def test_view_gradebook_with_question_deleted_page_data_adjusted(self):
        self.start_flow(self.flow_id)
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

        self.assertListEqual(list(self.get_grades_of_opps()), ['28.6%'])
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

        self.assertListEqual(list(self.get_grades_of_opps()), ['100.0% (/2)'])
        self.assertListEqual(
            self.get_page_grades_of_opp("la_quiz")[self.student.username],
            [None, 100, 100])

    def test_view_gradebook_with_question_when_session_reopened(self):
        self.start_flow(self.flow_id)
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

        self.assertListEqual(list(self.get_grades_of_opps()), ['28.6%'])
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
        self.assertListEqual(list(self.get_grades_of_opps()), ['100.0% (/2)'])
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


class FinishFlowSessionViewTest(BatchFakeGetRepoBlobMixin,
                                SingleCourseQuizPageTestMixin, TestCase):

    # test flow.finish_flow_session

    @classmethod
    def setUpTestData(cls):  # noqa
        super(FinishFlowSessionViewTest, cls).setUpTestData()
        cls.course.active_git_commit_sha = "my_fake_commit_sha_for_gradesinfo"
        cls.course.save()
        cls.student = cls.student_participation.user

    def setUp(self):
        super(FinishFlowSessionViewTest, self).setUp()
        self.c.force_login(self.student)

    def test_submit_all_correct(self):
        # with human graded questions not graded

        self.start_flow(self.flow_id)

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

        self.start_flow(self.flow_id)

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
        self.start_flow(self.flow_id)

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

    def get_hacked_session_grading_rule(self, **kwargs):
        from course.utils import FlowSessionGradingRule
        defaults = {
            "grade_identifier": "la_quiz",
            "grade_aggregation_strategy": g_strategy.use_latest,
            "due": None,
            "generates_grade": True,
            "description": None,
            "credit_percent": 100,
            "use_last_activity_as_completion_time": False,
            "bonus_points": 0,
            "max_points": None,
            "max_points_enforced_cap": None,
        }
        defaults.update(kwargs)
        return FlowSessionGradingRule(**defaults)

    def test_submit_with_bonus(self):  # noqa
        with mock.patch(
                "course.flow.get_session_grading_rule") as mock_get_grule:
            mock_get_grule.return_value = \
                self.get_hacked_session_grading_rule(bonus_points=2)

            self.start_flow(self.flow_id)

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

            self.start_flow(self.flow_id)

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

            self.start_flow(self.flow_id)

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

            self.start_flow(self.flow_id)

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

            self.start_flow(self.flow_id)

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
                           BatchFakeGetRepoBlobMixin, TestCase):
    # test flow.grade_flow_session

    def setUp(self):
        super(GradeFlowSessionTest, self).setUp()
        self.course.active_git_commit_sha = (
            "my_fake_commit_sha_for_grade_flow_session")
        self.course.save()
        self.c.force_login(self.student_participation.user)
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

    def get_hacked_session_grading_rule(self, **kwargs):
        from course.utils import FlowSessionGradingRule
        defaults = {
            "grade_identifier": "la_quiz",
            "grade_aggregation_strategy": g_strategy.use_latest,
            "due": None,
            "generates_grade": True,
            "description": None,
            "credit_percent": 100,
            "use_last_activity_as_completion_time": False,
            "bonus_points": 0,
            "max_points": None,
            "max_points_enforced_cap": None,
        }
        defaults.update(kwargs)
        return FlowSessionGradingRule(**defaults)

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

    def get_hacked_session_grading_rule(self, **kwargs):
        from course.utils import FlowSessionGradingRule
        defaults = {
            "grade_identifier": "la_quiz",
            "grade_aggregation_strategy": g_strategy.use_latest,
            "due": None,
            "generates_grade": True,
            "description": None,
            "credit_percent": 100,
            "use_last_activity_as_completion_time": False,
            "bonus_points": 0,
            "max_points": None,
            "max_points_enforced_cap": None,
        }
        defaults.update(kwargs)
        return FlowSessionGradingRule(**defaults)

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
            self.mock_finish_flow_session_standalone.call_args[1]["respect_preview"])  # noqa

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
            self.mock_finish_flow_session_standalone.call_args[1]["respect_preview"])  # noqa


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
        flow_permissions = [constants.flow_permission.lock_down_as_exam_session,
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

    def get_hacked_session_grading_rule(self, **kwargs):
        from course.utils import FlowSessionGradingRule
        defaults = {
            "grade_identifier": "la_quiz",
            "grade_aggregation_strategy": g_strategy.use_latest,
            "due": None,
            "generates_grade": True,
            "description": None,
            "credit_percent": 100,
            "use_last_activity_as_completion_time": False,
            "bonus_points": 0,
            "max_points": None,
            "max_points_enforced_cap": None,
        }
        defaults.update(kwargs)
        return FlowSessionGradingRule(**defaults)

    def get_hacked_session_access_rule(self, **kwargs):
        from course.utils import FlowSessionAccessRule
        defaults = {
            "permissions": [],
        }
        defaults.update(kwargs)
        return FlowSessionAccessRule(**defaults)

    def get_hacked_session_start_rule(self, **kwargs):
        from course.utils import FlowSessionStartRule
        defaults = {
            "tag_session": None,
            "may_start_new_session": True,
            "may_list_existing_sessions": True,
            "default_expiration_mode": None,
        }
        defaults.update(kwargs)
        return FlowSessionStartRule(**defaults)

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
            permissions=[constants.flow_permission.cannot_see_flow_result]
        )

        access_rule_for_session2 = self.get_hacked_session_access_rule(
            permissions=[
                constants.flow_permission.view,
                constants.flow_permission.submit_answer,
                constants.flow_permission.end_session,
                constants.flow_permission.see_answer_after_submission]
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

    def get_hacked_session_access_rule(self, **kwargs):
        from course.utils import FlowSessionAccessRule
        defaults = {
            "permissions": [],
        }
        defaults.update(kwargs)
        return FlowSessionAccessRule(**defaults)

    def get_hacked_session_start_rule(self, **kwargs):
        from course.utils import FlowSessionStartRule
        defaults = {
            "tag_session": None,
            "may_start_new_session": True,
            "may_list_existing_sessions": True,
            "default_expiration_mode": None,
        }
        defaults.update(kwargs)
        return FlowSessionStartRule(**defaults)

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


# vim: foldmethod=marker
