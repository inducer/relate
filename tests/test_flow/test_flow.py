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
import six  # noqa
import unittest
from django.test import TestCase
from django.utils.timezone import now, timedelta

from relate.utils import dict_to_struct

from course.content import get_repo_blob
from course import models
from course import flow  # noqa
from course import constants
from course.utils import FlowSessionStartRule

from tests.base_test_mixins import (
    CoursesTestMixinBase, SingleCourseQuizPageTestMixin)
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


def get_repo_side_effect(repo, full_name, commit_sha, allow_tree=True):
    if full_name == "flows/%s.yml" % QUIZ_FLOW_ID:
        if commit_sha == b"my_fake_commit_sha_1":
            return Blob("fake-quiz-test1.yml")
        if commit_sha == b"my_fake_commit_sha_2":
            return Blob("fake-quiz-test2.yml")
        if commit_sha == b"my_fake_commit_sha_for_grades1":
            return Blob("fake-quiz-test-for-grade1.yml")
        if commit_sha == b"my_fake_commit_sha_for_grades2":
            return Blob("fake-quiz-test-for-grade2.yml")

    if full_name == "flow/%s.yml" % "001-linalg-recap":
        if commit_sha == b"my_fake_commit_sha_3":
            return Blob("fake-001-linalg-recap.yml")

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
                 "grade_aggregation_strategy":
                     constants.grade_aggregation_strategy.use_earliest})})

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

    commit_sha_page_id_map = {
        "my_fake_commit_sha_for_grades1": ["half", "krylov", "quarter"],
        "my_fake_commit_sha_for_grades2": ["krylov", "quarter"]}

    @classmethod
    def setUpTestData(cls):  # noqa
        super(AssemblePageGradesTest, cls).setUpTestData()
        cls.course.active_git_commit_sha = "my_fake_commit_sha_for_grades1"
        cls.course.save()
        cls.student = cls.student_participation.user

    def setUp(self):
        super(AssemblePageGradesTest, self).setUp()
        self.c.force_login(self.student)

    def get_current_page_ids(self):
        return self.commit_sha_page_id_map[self.course.active_git_commit_sha]

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


def instantiate_flow_page_with_ctx_get_interaction_kind_side_effect(fctx, page_data):  # noqa
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

# vim: foldmethod=marker
