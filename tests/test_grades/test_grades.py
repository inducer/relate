# -*- coding: utf-8 -*-

from __future__ import division

__copyright__ = "Copyright (C) 2018 Dong Zhuang, Zesheng Wang, Andreas Kloeckner"

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

import io
import datetime
from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import now, timedelta
import unittest

from relate.utils import local_now

from course import models, grades, constants
from course.constants import (
    grade_aggregation_strategy as g_stragety,
    grade_state_change_types as g_state,
    participation_permission as pperm)
from course.flow import reopen_session
from course.grades import (
    get_single_grade_changes_and_state_machine as get_gc_and_machine)

from tests.utils import mock, may_run_expensive_tests, SKIP_EXPENSIVE_TESTS_REASON
from tests.base_test_mixins import (
    SingleCoursePageTestMixin, SingleCourseQuizPageTestMixin,
    HackRepoMixin, MockAddMessageMixing)
from tests import factories
from tests.constants import QUIZ_FLOW_ID


def get_session_grading_rule_use_last_activity_as_cmplt_time_side_effect(
        session, flow_desc, now_datetime):
    # The testing flow "quiz-test" didn't set the attribute
    from course.utils import get_session_grading_rule
    actual_grading_rule = get_session_grading_rule(session, flow_desc, now_datetime)
    actual_grading_rule.use_last_activity_as_completion_time = True
    return actual_grading_rule


class GradesTestMixin(SingleCoursePageTestMixin, MockAddMessageMixing):
    time = now() - timedelta(days=10)

    @classmethod
    def setUpTestData(cls):  # noqa
        super(GradesTestMixin, cls).setUpTestData()
        cls.gopp = factories.GradingOpportunityFactory(
            course=cls.course, aggregation_strategy=g_stragety.use_latest)

    def setUp(self):
        super(GradesTestMixin, self).setUp()
        self.gopp.refresh_from_db()

    def use_default_setup(self):  # noqa
        self.session1 = factories.FlowSessionFactory.create(
            participation=self.student_participation, completion_time=self.time)
        self.time_increment()
        self.gc_main_1 = factories.GradeChangeFactory.create(**(self.gc(points=5)))
        self.gc_session1 = factories.GradeChangeFactory.create(**(self.gc(points=0,
                                                       flow_session=self.session1)))

        self.session2 = factories.FlowSessionFactory.create(
            participation=self.student_participation, completion_time=self.time)
        self.gc_main_2 = factories.GradeChangeFactory.create(**(self.gc(points=7)))
        self.gc_session2 = factories.GradeChangeFactory.create(**(self.gc(points=6,
                                                       flow_session=self.session2)))
        assert models.GradingOpportunity.objects.count() == 1
        assert models.GradeChange.objects.count() == 4
        assert models.FlowSession.objects.count() == 2

    def time_increment(self, minute_delta=10):
        self.time += timedelta(minutes=minute_delta)

    @classmethod
    def gc(cls, opportunity=None, state=None, attempt_id=None, points=None,
           max_points=None, comment=None, due_time=None,
           grade_time=None, flow_session=None, null_attempt_id=False, **kwargs):

        if attempt_id is None:
            if flow_session is None:
                if not null_attempt_id:
                    attempt_id = "main"
            else:
                from course.flow import get_flow_session_attempt_id
                attempt_id = get_flow_session_attempt_id(flow_session)
        gc_kwargs = {
            "opportunity": opportunity or cls.gopp,
            "participation": cls.student_participation,
            "state": state or g_state.graded,
            "attempt_id": attempt_id,
            "points": points,
            "max_points": max_points or 100,
            "comment": comment,
            "due_time": due_time,
            "grade_time": grade_time or cls.time,
            "flow_session": flow_session,
        }
        cls.time += timedelta(minutes=10)
        gc_kwargs.update(kwargs)
        return gc_kwargs

    def get_gc_machine(self, gopp=None, participation=None):
        if not gopp:
            gopp = self.gopp
        if not participation:
            participation = self.student_participation
        _, machine = get_gc_and_machine(gopp, participation)
        return machine

    def get_gc_stringify_machine_readable_state(self):
        machine = self.get_gc_machine()
        return machine.stringify_machine_readable_state()

    def get_gc_stringify_state(self):
        machine = self.get_gc_machine()
        return machine.stringify_state()

    def update_gopp_strategy(self, strategy=None):
        if not strategy:
            return
        else:
            self.gopp.aggregation_strategy = strategy
            self.gopp.save()
            self.gopp.refresh_from_db()

    def assertGradeChangeStateEqual(self, expected_state_string=None):  # noqa
        # targeting stringify_state
        state_string = self.get_gc_stringify_state()

        from django.utils.encoding import force_text
        self.assertEqual(force_text(state_string), expected_state_string)

    def assertGradeChangeMachineReadableStateEqual(self, expected_state_string=None):  # noqa
        # targeting stringify_machine_readable_state
        state_string = self.get_gc_stringify_machine_readable_state()
        from decimal import Decimal, InvalidOperation
        try:
            percentage = Decimal(state_string, )
        except InvalidOperation:
            percentage = None

        try:
            expected_percentage = Decimal(expected_state_string)
        except InvalidOperation:
            expected_percentage = None

        not_equal_msg = (
                "%s does not have equal value with '%s'"
                % (state_string, str(expected_percentage))
        )

        if percentage is not None and expected_percentage is not None:
            self.assertTrue(
                abs(percentage - expected_percentage) < 1e-4, msg=not_equal_msg)
        else:
            if type(percentage) != type(expected_percentage):
                self.fail(not_equal_msg)

        if percentage is None and expected_percentage is None:
            self.assertEqual(state_string, expected_state_string)

    def append_gc(self, gc):
        return factories.GradeChangeFactory.create(**gc)

    def update_gc(self, gc_object, update_time=True, **kwargs):
        # This is alter GradeChange objects via db.

        gc_dict = gc_object.__dict__
        gc_dict.update(**kwargs)
        if update_time:
            gc_dict["grade_time"] = now()
        gc_object.save()
        gc_object.refresh_from_db()


class ViewParticipantGradesTest(GradesTestMixin, TestCase):
    # test grades.view_participant_grades
    def test_pctx_no_participation(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_my_grades_view()
            self.assertEqual(resp.status_code, 403)

    def test_view_others_grades_no_perm(self):
        other_participation = factories.ParticipationFactory(course=self.course)
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_view_participant_grades(other_participation.pk)
            self.assertEqual(resp.status_code, 403)

    def test_view_others_grades_no_pctx(self):
        other_participation = factories.ParticipationFactory(course=self.course)
        with self.temporarily_switch_to_user(None):
            resp = self.get_view_participant_grades(other_participation.pk)
            self.assertEqual(resp.status_code, 403)

    def test_view_my_participation_grades(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_view_participant_grades(self.student_participation.pk)
            self.assertEqual(resp.status_code, 200)

    def test_view_my_grades(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_my_grades_view()
            self.assertEqual(resp.status_code, 200)

    def test_ta_view_student_grades(self):
        with self.temporarily_switch_to_user(self.ta_participation.user):
            resp = self.get_view_participant_grades(self.student_participation.pk)
            self.assertEqual(resp.status_code, 200)

    def test_view(self):

        # {{{ gopps. Notice: there is another gopp created in setUp
        # shown for all (gopp with no gchanges)

        # shown for all
        shown_gopp = factories.GradingOpportunityFactory(
            course=self.course, identifier="1shown", name="SHOWN")

        # hidden for all view
        hidden_gopp_all = factories.GradingOpportunityFactory(
            course=self.course, identifier="2hidden_all", name="HIDDEN_ALL",
            shown_in_grade_book=False)

        # hidden if is_privileged_view is True
        hidden_gopp = factories.GradingOpportunityFactory(
            course=self.course, identifier="3hidden", name="HIDDEN",
            shown_in_participant_grade_book=False)

        # result hidden
        shown_gopp_result_hidden = factories.GradingOpportunityFactory(
            course=self.course, identifier="4shown_result_hidden",
            name="SHOWN_RESULT_HIDDEN",
            result_shown_in_participant_grade_book=False)

        # }}}

        # {{{ gchanges
        # this will be consumed
        gchange_shown1 = factories.GradeChangeFactory(
            **self.gc(
                opportunity=shown_gopp,
                attempt_id="main", points=0, max_points=10))

        # this won't be consumed
        gchange_hidden_all = factories.GradeChangeFactory(
            **self.gc(
                opportunity=hidden_gopp_all, attempt_id="hidden_all",
                points=1, max_points=5))

        # this will be consumed
        gchange_result_hidden = factories.GradeChangeFactory(
            **self.gc(
                opportunity=shown_gopp_result_hidden,
                attempt_id="shown_result_hidden", points=15, max_points=15))

        # this will be consumed only when is_privileged_view is True
        gchange_hidden = factories.GradeChangeFactory(
            **self.gc(
                opportunity=hidden_gopp, attempt_id="hidden", points=2,
                max_points=5))

        # this will be consumed
        gchange_shown2 = factories.GradeChangeFactory(
            **self.gc(
                opportunity=shown_gopp,
                attempt_id="main", points=10, max_points=10))

        # this will be consumed
        gchange_shown3 = factories.GradeChangeFactory(
            **self.gc(
                opportunity=shown_gopp,
                attempt_id="main", points=6, max_points=10))
        # }}}

        user = self.student_participation.user
        with self.temporarily_switch_to_user(user):
            with self.subTest(user=user):
                with mock.patch(
                        "course.models.GradeStateMachine.consume") as mock_consume:
                    resp = self.get_my_grades_view()
                    self.assertEqual(resp.status_code, 200)

                    # testing call of GradeStateMachine consume
                    expected_called = [
                        [gchange_shown1, gchange_shown2, gchange_shown3],
                        [gchange_result_hidden]]

                    # no expected to be consumed
                    not_expected_called = [
                        [gchange_hidden_all], [gchange_hidden]]

                    actually_called = []
                    for call in mock_consume.call_args_list:
                        arg, _ = call
                        for not_expected in not_expected_called:
                            self.assertNotIn(not_expected, arg)
                        if len(arg[0]):
                            actually_called.append(arg[0])
                    self.assertListEqual(actually_called, expected_called)

                # non mock call
                resp = self.get_my_grades_view()
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(
                    len(resp.context["grading_opportunities"]), 3)
                self.assertEqual(len(resp.context["grade_table"]), 3)
                self.assertFalse(resp.context["is_privileged_view"])
                self.assertContains(resp, "60.0%", count=1)  # for shown_gopp
                self.assertNotContains(resp, "40.0%")  # for hidden_gopp
                self.assertContains(resp, "(not released)", count=2)  # for hidden_gopp  # noqa

        user = self.ta_participation.user
        with self.temporarily_switch_to_user(user):
            with self.subTest(user=user):
                with mock.patch(
                        "course.models.GradeStateMachine.consume") as mock_consume:
                    resp = self.get_view_participant_grades(
                        self.student_participation.pk)
                    self.assertEqual(resp.status_code, 200)

                    # testing call of GradeStateMachine consume
                    expected_called = [
                        [gchange_shown1, gchange_shown2, gchange_shown3],
                        [gchange_hidden],
                        [gchange_result_hidden]]

                    # no expected to be consumed
                    not_expected_called = [
                        [gchange_hidden_all]]

                    actually_called = []
                    for call in mock_consume.call_args_list:
                        arg, _ = call
                        for not_expected in not_expected_called:
                            self.assertNotIn(not_expected, arg)
                        if len(arg[0]):
                            actually_called.append(arg[0])

                    self.assertListEqual(actually_called, expected_called)

                # non mock call
                resp = self.get_view_participant_grades(
                    self.student_participation.pk)
                self.assertEqual(
                    len(resp.context["grading_opportunities"]), 4)
                self.assertEqual(len(resp.context["grade_table"]), 4)
                self.assertTrue(resp.context["is_privileged_view"])

                self.assertContains(resp, "60.0%", count=1)  # for shown_gopp
                self.assertContains(resp, "40.0%", count=1)  # for hidden_gopp


@unittest.skipUnless(may_run_expensive_tests(), SKIP_EXPENSIVE_TESTS_REASON)
class GetGradeTableTest(GradesTestMixin, TestCase):
    # test grades.get_grade_table

    @classmethod
    def setUpTestData(cls):  # noqa
        super(GetGradeTableTest, cls).setUpTestData()
        # 2 more participations
        (cls.ptpt1, cls.ptpt2) = factories.ParticipationFactory.create_batch(
            size=2, course=cls.course)

        # this make sure it filtered by participation status active
        factories.ParticipationFactory(
            course=cls.course, status=constants.participation_status.dropped)

        # another course and a gopp, this make sure it filtered by course
        another_course = factories.CourseFactory(identifier="another-course")
        factories.GradingOpportunityFactory(course=another_course)

    def run_test(self):
        super(GetGradeTableTest, self).setUp()

        # {{{ gopps. Notice: there is another gopp created in setUp
        # shown for all (gopp with no gchanges)

        # shown for all
        shown_gopp = factories.GradingOpportunityFactory(
            course=self.course, identifier="1shown", name="SHOWN")

        # hidden for all view
        hidden_gopp_all = factories.GradingOpportunityFactory(
            course=self.course, identifier="2hidden_all", name="HIDDEN_ALL",
            shown_in_grade_book=False)

        # hidden if is_privileged_view is True
        hidden_gopp = factories.GradingOpportunityFactory(
            course=self.course, identifier="3hidden", name="HIDDEN",
            shown_in_participant_grade_book=False)

        # }}}

        # {{{ gchanges for stu
        stu_shown_gopp_gchanges = [
            self.gc(
                participation=self.student_participation,
                opportunity=shown_gopp,
                attempt_id="main", points=0, max_points=10),
            self.gc(
                participation=self.student_participation,
                opportunity=shown_gopp,
                attempt_id="main", points=2, max_points=10),
            self.gc(
                participation=self.student_participation,
                opportunity=shown_gopp,
                attempt_id="main", points=5, max_points=10),
            self.gc(
                participation=self.student_participation,
                opportunity=shown_gopp,
                attempt_id="main", points=4, max_points=10),
        ]  # expecting 40%

        stu_hidden_gopp_gchanges = [
            self.gc(
                participation=self.student_participation,
                opportunity=hidden_gopp,
                attempt_id="hidden", points=5, max_points=10),
            self.gc(
                participation=self.student_participation,
                opportunity=hidden_gopp,
                attempt_id="hidden", points=4, max_points=10),
            self.gc(
                participation=self.student_participation,
                opportunity=hidden_gopp,
                attempt_id="hidden", points=3, max_points=10),
            self.gc(
                participation=self.student_participation,
                opportunity=hidden_gopp,
                attempt_id="hidden", points=2, max_points=10),
        ]  # expecting 20%

        stu_hidden_all_gopp_gchanges = [
            self.gc(
                participation=self.student_participation,
                opportunity=hidden_gopp_all,
                attempt_id="hidden_all", points=5, max_points=10),
            self.gc(
                participation=self.student_participation,
                opportunity=hidden_gopp_all,
                attempt_id="hidden_all", points=4, max_points=10),
            self.gc(
                participation=self.student_participation,
                opportunity=hidden_gopp_all,
                attempt_id="hidden_all", points=3, max_points=10),
            self.gc(
                participation=self.student_participation,
                opportunity=hidden_gopp_all,
                attempt_id="hidden_all", points=2, max_points=10),
        ]  # no result expected

        # }}}

        # {{{ gchanges for ptpt1
        ptpt1shown_gopp_gchanges = [
            self.gc(
                participation=self.ptpt1,
                opportunity=shown_gopp,
                attempt_id="main", points=1, max_points=10),
            self.gc(
                participation=self.ptpt1,
                opportunity=shown_gopp,
                attempt_id="main", points=3, max_points=10),
            self.gc(
                participation=self.ptpt1,
                opportunity=shown_gopp,
                attempt_id="main", points=6, max_points=10),
            self.gc(
                participation=self.ptpt1,
                opportunity=shown_gopp,
                attempt_id="main", points=9, max_points=10),
        ]  # expecting 90%

        ptpt1_hidden_gopp_gchanges = [
            self.gc(
                participation=self.ptpt1,
                opportunity=hidden_gopp,
                attempt_id="hidden", points=10, max_points=10),
            self.gc(
                participation=self.ptpt1,
                opportunity=hidden_gopp,
                attempt_id="hidden", points=9, max_points=10),
            self.gc(
                participation=self.ptpt1,
                opportunity=hidden_gopp,
                attempt_id="hidden", points=8, max_points=10),
            self.gc(
                participation=self.ptpt1,
                opportunity=hidden_gopp,
                attempt_id="hidden", points=7, max_points=10),
        ]  # expecting 70%

        ptpt1_hidden_all_gopp_gchanges = [
            self.gc(
                participation=self.ptpt1,
                opportunity=hidden_gopp_all,
                attempt_id="hidden_all", points=3, max_points=10),
            self.gc(
                participation=self.ptpt1,
                opportunity=hidden_gopp_all,
                attempt_id="hidden_all", points=2, max_points=10),
            self.gc(
                participation=self.ptpt1,
                opportunity=hidden_gopp_all,
                attempt_id="hidden_all", points=1, max_points=10),
            self.gc(
                participation=self.ptpt1,
                opportunity=hidden_gopp_all,
                attempt_id="hidden_all", points=1.5, max_points=10),
        ]  # no result expected

        # {{{ gchanges for ptpt2
        ptpt2_shown_gopp_gchanges = [
            self.gc(
                participation=self.ptpt2,
                opportunity=shown_gopp,
                attempt_id="main", points=10, max_points=10),
            self.gc(
                participation=self.ptpt2,
                opportunity=shown_gopp,
                attempt_id="main", points=1, max_points=10),
            self.gc(
                participation=self.ptpt2,
                opportunity=shown_gopp,
                attempt_id="main", points=2, max_points=10),
            self.gc(
                participation=self.ptpt2,
                opportunity=shown_gopp,
                attempt_id="main", points=3.5, max_points=10),
        ]  # expecting 35%

        ptpt2_hidden_gopp_gchanges = [
            self.gc(
                participation=self.ptpt2,
                opportunity=hidden_gopp,
                attempt_id="hidden", points=2, max_points=10),
            self.gc(
                participation=self.ptpt2,
                opportunity=hidden_gopp,
                attempt_id="hidden", points=4, max_points=10),
            self.gc(
                participation=self.ptpt2,
                opportunity=hidden_gopp,
                attempt_id="hidden", points=3, max_points=10),
            self.gc(
                participation=self.ptpt2,
                opportunity=hidden_gopp,
                attempt_id="hidden", points=6.5, max_points=10),
        ]  # expecting 65%

        ptpt2_hidden_all_gopp_gchanges = [
            self.gc(
                participation=self.ptpt2,
                opportunity=hidden_gopp_all,
                attempt_id="hidden_all", points=5, max_points=10),
            self.gc(
                participation=self.ptpt2,
                opportunity=hidden_gopp_all,
                attempt_id="hidden_all", points=4, max_points=10),
            self.gc(
                participation=self.ptpt2,
                opportunity=hidden_gopp_all,
                attempt_id="hidden_all", points=3, max_points=10),
            self.gc(
                participation=self.ptpt2,
                opportunity=hidden_gopp_all,
                attempt_id="hidden_all", points=6, max_points=10),
        ]  # no result expected
        # }}}

        gchange_kwargs_lists = [
            stu_hidden_all_gopp_gchanges,
            stu_hidden_gopp_gchanges,
            stu_shown_gopp_gchanges,

            ptpt1_hidden_all_gopp_gchanges,
            ptpt1_hidden_gopp_gchanges,
            ptpt1shown_gopp_gchanges,

            ptpt2_hidden_all_gopp_gchanges,
            ptpt2_hidden_gopp_gchanges,
            ptpt2_shown_gopp_gchanges]

        from random import shuffle

        while True:
            gchange_kwargs_lists = [l for l in gchange_kwargs_lists if len(l)]
            if not gchange_kwargs_lists:
                break

            shuffle(gchange_kwargs_lists)
            kwarg_list = gchange_kwargs_lists[0]
            gchange_kwargs = kwarg_list.pop(0)
            factories.GradeChangeFactory(**gchange_kwargs)

        participations, grading_opps, grade_table = (
            grades.get_grade_table(self.course))

        self.assertEqual(
            participations, [
                self.instructor_participation,
                self.ta_participation,
                self.student_participation,
                self.ptpt1,
                self.ptpt2])

        # hidden_gopp_all not shown
        # ordered by identifier
        self.assertListEqual(grading_opps, [shown_gopp, hidden_gopp, self.gopp])

        self.assertEqual(len(grade_table), 5)
        for i in range(5):
            self.assertEqual(len(grade_table[i]), 3)

        self.assertEqual(grade_table[2][0].grade_state_machine.percentage(), 40)
        self.assertEqual(grade_table[2][1].grade_state_machine.percentage(), 20)
        self.assertEqual(grade_table[2][2].grade_state_machine.percentage(), None)

        self.assertEqual(grade_table[3][0].grade_state_machine.percentage(), 90)
        self.assertEqual(grade_table[3][1].grade_state_machine.percentage(), 70)
        self.assertEqual(grade_table[3][2].grade_state_machine.percentage(), None)

        self.assertEqual(grade_table[4][0].grade_state_machine.percentage(), 35)
        self.assertEqual(grade_table[4][1].grade_state_machine.percentage(), 65)
        self.assertEqual(grade_table[4][2].grade_state_machine.percentage(), None)

    def test(self):
        for i in range(10):
            self.run_test()
            factories.UserFactory.reset_sequence(0)
            self.setUp()


fake_access_rules_tag = "fake_tag"
fake_task_id = "abcdef123"


class MockAsyncRes(object):
    def __init__(self):
        self.id = fake_task_id


class ViewGradesByOpportunityTest(GradesTestMixin, TestCase):
    # test grades.view_grades_by_opportunity

    def setUp(self):
        super(ViewGradesByOpportunityTest, self).setUp()

        # create 2 flow sessions, one with access_rules_tag
        factories.FlowSessionFactory(
            participation=self.student_participation,
            flow_id=QUIZ_FLOW_ID, in_progress=False, page_count=15)

        factories.FlowSessionFactory(
            participation=self.student_participation,
            access_rules_tag=fake_access_rules_tag, page_count=15)

        fake_expire_in_progress_sessions = mock.patch(
            "course.tasks.expire_in_progress_sessions.delay",
            return_value=MockAsyncRes())
        self.mock_expire_in_progress_sessions = (
            fake_expire_in_progress_sessions.start())
        self.addCleanup(fake_expire_in_progress_sessions.stop)

        fake_finish_in_progress_sessions = mock.patch(
            "course.tasks.finish_in_progress_sessions.delay",
            return_value=MockAsyncRes())
        self.mock_finish_in_progress_sessions = (
            fake_finish_in_progress_sessions.start())
        self.addCleanup(fake_finish_in_progress_sessions.stop)

        fake_regrade_flow_sessions = mock.patch(
            "course.tasks.regrade_flow_sessions.delay",
            return_value=MockAsyncRes())
        self.mock_regrade_flow_sessions = fake_regrade_flow_sessions.start()
        self.addCleanup(fake_regrade_flow_sessions.stop)

        fake_recalculate_ended_sessions = mock.patch(
            "course.tasks.recalculate_ended_sessions.delay",
            return_value=MockAsyncRes())
        self.mock_recalculate_ended_sessions = (
            fake_recalculate_ended_sessions.start())
        self.addCleanup(fake_recalculate_ended_sessions.stop)

    gopp_id = "la_quiz"

    def test_no_permission(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_gradebook_by_opp_view(
                self.gopp_id, force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)
            resp = self.post_gradebook_by_opp_view(
                self.gopp_id, {}, force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_gradebook_by_opp_view(
                self.gopp_id, force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)
            resp = self.post_gradebook_by_opp_view(
                self.gopp_id, {}, force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

    def test_gopp_does_not_exist(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(self.get_gradebook_url_by_opp_id("2"))
            self.assertEqual(resp.status_code, 404)

    def test_gopp_course_not_match(self):
        another_course = factories.CourseFactory(identifier="another-course")
        another_course_gopp = factories.GradingOpportunityFactory(
            course=another_course, identifier=self.gopp_id)

        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(self.get_gradebook_url_by_opp_id(
                another_course_gopp.id))
            self.assertEqual(resp.status_code, 400)

    def test_batch_op_no_permission(self):
        with self.temporarily_switch_to_user(self.ta_participation.user):
            for op in ["expire", "end", "regrade", "recalculate"]:
                with self.subTest(user=self.ta_participation.user, op=op):
                    resp = self.post_gradebook_by_opp_view(
                        self.gopp_id,
                        post_data={"rule_tag": grades.RULE_TAG_NONE_STRING,
                                   "past_due_only": True,
                                   op: ""},
                        force_login_instructor=False)

                    # because post is neglected for user without those pperms
                    self.assertEqual(resp.status_code, 200)
                    self.assertEqual(
                        self.mock_expire_in_progress_sessions.call_count, 0)
                    self.assertEqual(
                        self.mock_finish_in_progress_sessions.call_count, 0)
                    self.assertEqual(
                        self.mock_regrade_flow_sessions.call_count, 0)
                    self.assertEqual(
                        self.mock_recalculate_ended_sessions.call_count, 0)

    def test_batch_op_no_permission2(self):
        # with partitial permission
        permission_ops = [
            (pperm.batch_end_flow_session, "end"),
            (pperm.batch_impose_flow_session_deadline, "expire"),
            (pperm.batch_regrade_flow_session, "regrade"),
            (pperm.batch_recalculate_flow_session_grade, "recalculate")]

        from itertools import combinations
        comb = list(combinations(permission_ops, 2))
        comb += [reversed(c) for c in comb]

        with self.temporarily_switch_to_user(self.ta_participation.user):
            for po in comb:
                allowed, not_allowed = po
                pp = models.ParticipationPermission(
                    participation=self.ta_participation,
                    permission=allowed[0])
                pp.save()
                op = not_allowed[1]

                with self.subTest(user=self.ta_participation.user, op=op):
                    resp = self.post_gradebook_by_opp_view(
                        self.gopp_id,
                        post_data={"rule_tag": grades.RULE_TAG_NONE_STRING,
                                   "past_due_only": True,
                                   op: ""},
                        force_login_instructor=False)

                self.assertEqual(resp.status_code, 403)

                # revoke permission
                pp.delete()

        self.assertEqual(
            self.mock_expire_in_progress_sessions.call_count, 0)
        self.assertEqual(
            self.mock_finish_in_progress_sessions.call_count, 0)
        self.assertEqual(
            self.mock_regrade_flow_sessions.call_count, 0)
        self.assertEqual(
            self.mock_recalculate_ended_sessions.call_count, 0)

    def test_batch_op(self):
        for op in ["expire", "end", "regrade", "recalculate"]:
            for rule_tag in [fake_access_rules_tag, grades.RULE_TAG_NONE_STRING]:
                with self.subTest(user=self.instructor_participation.user, op=op):
                    resp = self.post_gradebook_by_opp_view(
                        self.gopp_id,
                        post_data={"rule_tag": rule_tag,
                                   "past_due_only": True,
                                   op: ""})

                    self.assertRedirects(
                        resp, reverse(
                            "relate-monitor_task",
                            kwargs={"task_id": fake_task_id}),
                        fetch_redirect_response=False)

        self.assertEqual(
            self.mock_expire_in_progress_sessions.call_count, 2)
        self.assertEqual(
            self.mock_finish_in_progress_sessions.call_count, 2)
        self.assertEqual(
            self.mock_regrade_flow_sessions.call_count, 2)
        self.assertEqual(
            self.mock_recalculate_ended_sessions.call_count, 2)

    def test_invalid_batch_op(self):
        resp = self.post_gradebook_by_opp_view(
            self.gopp_id,
            post_data={"rule_tag": grades.RULE_TAG_NONE_STRING,
                       "past_due_only": True,
                       "invalid_op": ""})

        # because post is neglected for user without those pperms
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            self.mock_expire_in_progress_sessions.call_count, 0)
        self.assertEqual(
            self.mock_finish_in_progress_sessions.call_count, 0)
        self.assertEqual(
            self.mock_regrade_flow_sessions.call_count, 0)
        self.assertEqual(
            self.mock_recalculate_ended_sessions.call_count, 0)

    def test_post_form_invalid(self):
        with mock.patch(
                "course.grades.ModifySessionsForm.is_valid") as mock_form_valid:
            mock_form_valid.return_value = False
            resp = self.post_gradebook_by_opp_view(
                self.gopp_id,
                post_data={"rule_tag": grades.RULE_TAG_NONE_STRING,
                           "past_due_only": True,
                           "end": ""})

        # just ignore
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self.mock_expire_in_progress_sessions.call_count, 0)
        self.assertEqual(
            self.mock_finish_in_progress_sessions.call_count, 0)
        self.assertEqual(
            self.mock_regrade_flow_sessions.call_count, 0)
        self.assertEqual(
            self.mock_recalculate_ended_sessions.call_count, 0)

    def test_get_flow_status(self):
        factories.FlowSessionFactory(participation=self.student_participation,
                                     in_progress=True, page_count=13)

        # There're 3 participations, student has 2 finished session,
        # 1 in-progress session

        not_started = '<span class="label label-danger">not started</span>'
        finished = '<span class="label label-success">finished</span>'
        unfinished = '<span class="label label-warning">unfinished</span>'

        resp = self.get_gradebook_by_opp_view(self.gopp_id)
        self.assertEqual(resp.status_code, 200)
        # The instructor and ta didn't start the session
        self.assertContains(resp, not_started, count=2, html=True)

        self.assertContains(resp, finished, count=2, html=True)
        self.assertContains(resp, unfinished, count=1, html=True)

        resp = self.get_gradebook_by_opp_view(self.gopp_id, view_page_grades=True)
        self.assertEqual(resp.status_code, 200)

        # The student_participation has 2 session in setUp
        self.assertContains(resp, finished, count=2, html=True)
        self.assertContains(resp, unfinished, count=1, html=True)

        # no "not started" when view_page_grades
        self.assertContains(resp, not_started, count=0, html=True)

        # remove all flow sessions
        for fs in models.FlowSession.objects.all():
            fs.delete()

        resp = self.get_gradebook_by_opp_view(self.gopp_id)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, not_started, count=3, html=True)
        self.assertContains(resp, finished, count=0, html=True)
        self.assertContains(resp, unfinished, count=0, html=True)

        resp = self.get_gradebook_by_opp_view(self.gopp_id, view_page_grades=True)
        self.assertEqual(resp.status_code, 200)

        # no "not started" when view_page_grades
        self.assertContains(resp, not_started, count=0, html=True)
        self.assertContains(resp, finished, count=0, html=True)
        self.assertContains(resp, unfinished, count=0, html=True)

    def test_get_with_multiple_flow_sessions(self):
        factories.FlowSessionFactory(
            participation=self.student_participation,
            flow_id=QUIZ_FLOW_ID,
            in_progress=True)
        resp = self.get_gradebook_by_opp_view(self.gopp_id)
        self.assertEqual(resp.status_code, 200)

    def test_get_with_multiple_flow_sessions_view_page_grade(self):
        factories.FlowSessionFactory(
            participation=self.student_participation,
            flow_id=QUIZ_FLOW_ID,
            in_progress=True,
            page_count=12
        )

        resp = self.get_gradebook_by_opp_view(self.gopp_id, view_page_grades=True)
        self.assertEqual(resp.status_code, 200)

    def test_non_session_gopp(self):
        gopp = factories.GradingOpportunityFactory(
            course=self.course, identifier="another_gopp", flow_id=None)

        factories.GradeChangeFactory(**self.gc(opportunity=gopp))

        resp = self.get_gradebook_by_opp_view(gopp.identifier, view_page_grades=True)
        self.assertEqual(resp.status_code, 200)

        resp = self.get_gradebook_by_opp_view(gopp.identifier)
        self.assertEqual(resp.status_code, 200)


class GradesChangeStateMachineTest(GradesTestMixin, TestCase):

    def test_no_gradechange(self):
        # when no grade change object exists
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_view_single_grade(self.student_participation, self.gopp)

        self.assertResponseContextEqual(resp, "avg_grade_percentage", None)
        self.assertResponseContextEqual(resp, "avg_grade_population", 0)

    def test_default_setup(self):
        self.use_default_setup()
        self.assertGradeChangeMachineReadableStateEqual(6)
        self.assertGradeChangeStateEqual("6.0% (/3)")

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_view_single_grade(self.student_participation, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", 6)
        self.assertResponseContextEqual(resp, "avg_grade_population", 1)

    def test_change_aggregate_strategy_average(self):
        self.use_default_setup()
        self.update_gopp_strategy(g_stragety.avg_grade)
        self.assertGradeChangeMachineReadableStateEqual(4.333)
        self.assertGradeChangeStateEqual("4.3% (/3)")

    def test_change_aggregate_strategy_earliest(self):
        self.use_default_setup()
        self.update_gopp_strategy(g_stragety.use_earliest)
        self.assertGradeChangeMachineReadableStateEqual(0)
        self.assertGradeChangeStateEqual("0.0% (/3)")

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_view_single_grade(self.student_participation, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", 0)
        self.assertResponseContextEqual(resp, "avg_grade_population", 1)

    def test_change_aggregate_strategy_max(self):
        self.use_default_setup()
        self.update_gopp_strategy(g_stragety.max_grade)
        self.assertGradeChangeMachineReadableStateEqual(7)
        self.assertGradeChangeStateEqual("7.0% (/3)")

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_view_single_grade(self.student_participation, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", 7)
        self.assertResponseContextEqual(resp, "avg_grade_population", 1)

    def test_change_aggregate_strategy_max_none(self):
        # when no grade change has percentage
        self.update_gopp_strategy(g_stragety.max_grade)
        self.assertGradeChangeMachineReadableStateEqual("NONE")
        self.assertGradeChangeStateEqual("- ∅ -")

        factories.GradeChangeFactory.create(**(self.gc(points=None)))
        self.assertGradeChangeMachineReadableStateEqual("NONE")
        self.assertGradeChangeStateEqual("- ∅ -")

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_view_single_grade(self.student_participation, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", None)
        self.assertResponseContextEqual(resp, "avg_grade_population", 0)

    def test_change_aggregate_strategy_min(self):
        self.use_default_setup()
        self.update_gopp_strategy(g_stragety.min_grade)
        self.assertGradeChangeMachineReadableStateEqual(0)
        self.assertGradeChangeStateEqual("0.0% (/3)")

    def test_change_aggregate_strategy_min_none(self):
        # when no grade change has percentage
        self.update_gopp_strategy(g_stragety.min_grade)
        self.assertGradeChangeMachineReadableStateEqual("NONE")
        self.assertGradeChangeStateEqual("- ∅ -")

        factories.GradeChangeFactory.create(**(self.gc(points=None)))
        self.assertGradeChangeMachineReadableStateEqual("NONE")
        self.assertGradeChangeStateEqual("- ∅ -")

    def test_change_aggregate_strategy_invalid(self):
        self.use_default_setup()
        self.update_gopp_strategy("invalid_strategy")
        with self.assertRaises(ValueError):
            self.get_gc_stringify_machine_readable_state()

    def test_average_grade_value(self):
        # Other tests for course.grades.average_grade
        self.use_default_setup()
        self.assertGradeChangeMachineReadableStateEqual(6)
        self.assertGradeChangeStateEqual("6.0% (/3)")

        # make sure participations with pperm.included_in_grade_statistics
        # are not included
        factories.GradeChangeFactory.create(**(self.gc(
            participation=self.instructor_participation, points=2)))
        factories.GradeChangeFactory.create(**(self.gc(
            participation=self.ta_participation, points=3)))

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_view_single_grade(self.student_participation, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", 6)
        self.assertResponseContextEqual(resp, "avg_grade_population", 1)

        temp_ptcp = factories.ParticipationFactory.create(
            course=self.course)

        factories.GradeChangeFactory.create(
            **(self.gc(participation=temp_ptcp, points=3)))
        with self.temporarily_switch_to_user(temp_ptcp.user):
            resp = self.get_view_single_grade(temp_ptcp, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", 4.5)
        self.assertResponseContextEqual(resp, "avg_grade_population", 2)

    def test_append_gc(self):
        self.use_default_setup()
        self.append_gc(self.gc(points=8, flow_session=self.session2))
        self.assertGradeChangeMachineReadableStateEqual(8)
        self.assertGradeChangeStateEqual("8.0% (/3)")

        self.append_gc(self.gc(points=0, flow_session=self.session2))
        self.assertGradeChangeMachineReadableStateEqual(0)
        self.assertGradeChangeStateEqual("0.0% (/3)")

    def test_update_latest_gc_of_latest_finished_session(self):
        self.use_default_setup()
        self.assertGradeChangeMachineReadableStateEqual(6)

        self.update_gc(self.gc_session2, points=10)
        self.assertGradeChangeMachineReadableStateEqual(10)
        self.assertGradeChangeStateEqual("10.0% (/3)")

    def test_update_ealiest_gc_of_ealier_finished_session(self):
        self.use_default_setup()
        self.assertGradeChangeMachineReadableStateEqual(6)

        self.update_gc(self.gc_main_2, update_time=False, points=15)
        self.assertGradeChangeMachineReadableStateEqual(6)
        self.assertGradeChangeStateEqual("6.0% (/3)")

    def test_gc_without_attempt_id(self):
        # TODO: Is it a bug? percentage of GradeChanges without attempt_id are
        # put at the begining of the valid_percentages list.

        # Uncomment the following to see the failure
        # self.use_default_setup()
        # self.assertGradeChangeMachineReadableStateEqual(6)
        # print(self.gc_main_1.grade_time)
        #
        # self.time_increment()

        # create a gc without attempt_id
        gc = factories.GradeChangeFactory.create(  # noqa
            **(self.gc(points=8.5, null_attempt_id=True)))  # noqa
        # print(gc.grade_time)

        machine = self.get_gc_machine()
        self.assertGradeChangeMachineReadableStateEqual(8.5)
        self.assertEqual(machine.valid_percentages, [8.5])

    def test_gc_unavailable(self):
        factories.GradeChangeFactory.create(**(self.gc(points=9.1)))
        factories.GradeChangeFactory.create(
            **(self.gc(points=0, state=g_state.unavailable)))
        machine = self.get_gc_machine()
        self.assertGradeChangeMachineReadableStateEqual("OTHER_STATE")
        self.assertEqual(machine.valid_percentages, [])
        self.assertGradeChangeStateEqual("(other state)")

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_view_single_grade(self.student_participation, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", None)
        self.assertResponseContextEqual(resp, "avg_grade_population", 0)

        # failure when unavailable gc follows another grade change
        factories.GradeChangeFactory.create(**(self.gc(points=5)))

        with self.assertRaises(ValueError) as e:
            self.get_gc_stringify_machine_readable_state()
            self.assertIn("cannot accept grade once opportunity has been "
                            "marked 'unavailable'", e.exception)

    def test_gc_exempt(self):
        factories.GradeChangeFactory.create(**(self.gc(points=6)))
        factories.GradeChangeFactory.create(
            **(self.gc(points=0, state=g_state.exempt)))
        machine = self.get_gc_machine()
        self.assertGradeChangeMachineReadableStateEqual("EXEMPT")
        self.assertEqual(machine.valid_percentages, [])
        self.assertGradeChangeStateEqual("(exempt)")

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_view_single_grade(self.student_participation, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", None)
        self.assertResponseContextEqual(resp, "avg_grade_population", 0)

        # failure when exempt gc follows another grade change
        factories.GradeChangeFactory.create(**(self.gc(points=5)))

        with self.assertRaises(ValueError) as e:
            self.get_gc_stringify_machine_readable_state()
            self.assertIn("cannot accept grade once opportunity has been "
                            "marked 'exempt'", e.exception)

    def test_gc_do_over(self):
        factories.GradeChangeFactory.create(**(self.gc(points=6)))

        # This creates a GradeChange object with no attempt_id
        factories.GradeChangeFactory.create(
            **(self.gc(points=0, state=g_state.do_over,
                       null_attempt_id=True)))
        machine = self.get_gc_machine()
        self.assertGradeChangeMachineReadableStateEqual("NONE")
        self.assertEqual(machine.valid_percentages, [])
        self.assertGradeChangeStateEqual("- ∅ -")

        # This make sure new grade change objects following do_over gc is
        # consumed without problem
        factories.GradeChangeFactory.create(**(self.gc(points=5)))
        self.assertGradeChangeMachineReadableStateEqual("5")
        machine = self.get_gc_machine()
        self.assertEqual(machine.valid_percentages, [5])
        self.assertGradeChangeStateEqual("5.0%")

    def test_gc_do_over_average_grade_value(self):
        self.use_default_setup()
        factories.GradeChangeFactory.create(
            **(self.gc(points=None, state=g_state.do_over,
                       flow_session=self.session2)))

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_view_single_grade(self.student_participation, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", None)
        self.assertResponseContextEqual(resp, "avg_grade_population", 0)

    def test_gc_report_sent(self):
        factories.GradeChangeFactory.create(**(self.gc(points=6)))
        gc2 = factories.GradeChangeFactory.create(
            **(self.gc(points=0, state=g_state.report_sent)))
        machine = self.get_gc_machine()
        self.assertGradeChangeMachineReadableStateEqual("6")
        self.assertGradeChangeStateEqual("6.0%")
        self.assertEqual(machine.last_report_time, gc2.grade_time)

    def test_gc_extension(self):
        factories.GradeChangeFactory.create(**(self.gc(points=6)))
        gc2 = factories.GradeChangeFactory.create(
            **(self.gc(points=0, state=g_state.extension,
                       due_time=self.time + timedelta(days=1))))
        machine = self.get_gc_machine()
        self.assertGradeChangeMachineReadableStateEqual("6")
        self.assertGradeChangeStateEqual("6.0%")
        self.assertEqual(machine.due_time, gc2.due_time)

    def test_gc_grading_started(self):
        factories.GradeChangeFactory.create(**(self.gc(points=6)))
        factories.GradeChangeFactory.create(
            **(self.gc(points=0, state=g_state.grading_started)))
        self.assertGradeChangeMachineReadableStateEqual("6")
        self.assertGradeChangeStateEqual("6.0%")

    def test_gc_retrieved(self):
        factories.GradeChangeFactory.create(**(self.gc(points=6)))
        factories.GradeChangeFactory.create(
            **(self.gc(points=0, state=g_state.retrieved)))
        self.assertGradeChangeMachineReadableStateEqual("6")
        self.assertGradeChangeStateEqual("6.0%")

    def test_gc_non_exist_state(self):
        factories.GradeChangeFactory.create(**(self.gc(points=6)))
        factories.GradeChangeFactory.create(
            **(self.gc(points=0, state="some_state")))

        with self.assertRaises(RuntimeError):
            self.get_gc_stringify_machine_readable_state()

    def test_gc_non_point(self):
        factories.GradeChangeFactory.create(**(self.gc(points=None)))
        self.assertGradeChangeMachineReadableStateEqual("NONE")
        self.assertGradeChangeStateEqual("- ∅ -")

    # }}}


class ViewParticipantGradesTest2(GradesTestMixin, TestCase):
    def setUp(self):
        super(ViewParticipantGradesTest2, self).setUp()
        self.use_default_setup()
        self.gopp_hidden_in_gradebook = factories.GradingOpportunityFactory(
            course=self.course, aggregation_strategy=g_stragety.use_latest,
            flow_id=None, shown_in_grade_book=False,
            identifier="hidden_in_instructor_grade_book")

        self.gopp_hidden_in_gradebook = factories.GradingOpportunityFactory(
            course=self.course, aggregation_strategy=g_stragety.use_latest,
            flow_id=None, shown_in_grade_book=False,
            identifier="only_hidden_in_grade_book")

        self.gopp_hidden_in_participation_gradebook = (
            factories.GradingOpportunityFactory(
                course=self.course,
                shown_in_participant_grade_book=False,
                aggregation_strategy=g_stragety.use_latest,
                flow_id=None, identifier="all_hidden_in_ptcp_gradebook"))

        self.gopp_result_hidden_in_participation_gradebook = (
            factories.GradingOpportunityFactory(
                course=self.course, result_shown_in_participant_grade_book=False,
                aggregation_strategy=g_stragety.use_latest,
                flow_id=None, identifier="result_hidden_in_ptcp_gradebook"))

        self.gc_gopp_result_hidden = factories.GradeChangeFactory(
            **self.gc(points=66.67,
                      opportunity=self.gopp_result_hidden_in_participation_gradebook,
                      state=g_state.graded))

    def test_view_my_grade(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_view_my_grades()
            self.assertEqual(resp.status_code, 200)
            grade_table = self.get_response_context_value_by_name(
                resp, "grade_table")
            self.assertEqual((len(grade_table)), 2)
            self.assertEqual([g_info.opportunity.identifier
                              for g_info in grade_table],
                             [factories.DEFAULT_GRADE_IDENTIFIER,
                              "result_hidden_in_ptcp_gradebook"])

            # the grade is hidden
            self.assertNotContains(resp, 66.67)

            grade_participation = self.get_response_context_value_by_name(
                resp, "grade_participation")
            self.assertEqual(grade_participation.pk, self.student_participation.pk)

            # shown
            self.assertContains(resp, factories.DEFAULT_GRADE_IDENTIFIER)
            self.assertContains(resp, "result_hidden_in_ptcp_gradebook")

            # hidden
            self.assertNotContains(resp, "hidden_in_instructor_grade_book")
            self.assertNotContains(resp, "all_hidden_in_ptcp_gradebook")

    def test_view_participant_grades(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.get_view_participant_grades(self.student_participation.id)
            self.assertEqual(resp.status_code, 200)
            grade_table = self.get_response_context_value_by_name(
                resp, "grade_table")
            self.assertEqual((len(grade_table)), 3)
            self.assertEqual([g_info.opportunity.identifier
                              for g_info in grade_table],
                             ['all_hidden_in_ptcp_gradebook',
                              factories.DEFAULT_GRADE_IDENTIFIER,
                              "result_hidden_in_ptcp_gradebook"])

            # the grade hidden to participation is show to instructor
            # self.assertContains(resp, "66.67%(not released)")

            grade_participation = self.get_response_context_value_by_name(
                resp, "grade_participation")
            self.assertEqual(grade_participation.pk, self.student_participation.pk)

            # shown
            self.assertContains(resp, factories.DEFAULT_GRADE_IDENTIFIER)
            self.assertContains(resp, "result_hidden_in_ptcp_gradebook")
            self.assertContains(resp, "all_hidden_in_ptcp_gradebook")

            # hidden
            self.assertNotContains(resp, "hidden_in_instructor_grade_book")

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_view_participant_grades(
                participation_id=self.instructor_participation.id)
            self.assertEqual(resp.status_code, 403)


class ViewReopenSessionTest(GradesTestMixin, TestCase):
    # grades.view_reopen_session (currently for cases not covered by other tests)

    gopp_id = "la_quiz"

    def setUp(self):
        super(ViewReopenSessionTest, self).setUp()
        self.fs1 = factories.FlowSessionFactory(
            participation=self.student_participation, in_progress=False)

        self.fs2 = factories.FlowSessionFactory(
            participation=self.student_participation, in_progress=True)

    def test_flow_desc_not_exist(self):
        with mock.patch("course.content.get_flow_desc") as mock_get_flow_desc:
            from django.core.exceptions import ObjectDoesNotExist
            mock_get_flow_desc.side_effect = ObjectDoesNotExist
            resp = self.get_reopen_session_view(
                self.gopp_id, flow_session_id=self.fs1.pk)
            self.assertEqual(resp.status_code, 404)

    def test_already_in_progress(self):
        # not unsubmit, because we don't have previoius grade visit (which will
        # result in error)
        data = {'set_access_rules_tag': ['<<<NONE>>>'],
                'comment': ['test reopen'],
                'reopen': ''}

        resp = self.post_reopen_session_view(
            self.gopp_id, flow_session_id=self.fs2.pk, data=data)
        self.assertEqual(resp.status_code, 200)

        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(
            "Cannot reopen a session that's already in progress.")
        self.assertTrue(self.fs2.in_progress)

    def test_reopen_success(self):
        resp = self.get_reopen_session_view(
            self.gopp_id, flow_session_id=self.fs1.pk)
        self.assertEqual(resp.status_code, 200)

        # not unsubmit, because we don't have previoius grade visit (which will
        # result in error)
        data = {'set_access_rules_tag': ['<<<NONE>>>'],
                'comment': ['test reopen'],
                'reopen': ''}

        resp = self.post_reopen_session_view(
            self.gopp_id, flow_session_id=self.fs1.pk, data=data)
        self.assertEqual(resp.status_code, 302)

        self.fs1.refresh_from_db()
        self.assertTrue(self.fs1.in_progress)

    def test_set_access_rule_tag(self):
        hacked_flow_desc = (
            self.get_hacked_flow_desc_with_access_rule_tags(["blahblah"]))

        with mock.patch("course.content.get_flow_desc") as mock_get_flow_desc:
            mock_get_flow_desc.return_value = hacked_flow_desc

            # not unsubmit, because we don't have previoius grade visit (which will
            # result in error)
            data = {'set_access_rules_tag': ['blahblah'],
                    'comment': ['test reopen'],
                    'reopen': ''}

            resp = self.post_reopen_session_view(
                self.gopp_id, flow_session_id=self.fs1.pk, data=data)
            self.assertEqual(resp.status_code, 302)

        self.fs1.refresh_from_db()
        self.assertTrue(self.fs1.in_progress)
        self.assertEqual(self.fs1.access_rules_tag, 'blahblah')


class ViewSingleGradeTest(GradesTestMixin, TestCase):
    # grades.view_single_grade (currently for cases not covered by other tests)

    def setUp(self):
        super(ViewSingleGradeTest, self).setUp()

        fake_regrade_session = mock.patch("course.flow.regrade_session")
        self.mock_regrade_session = fake_regrade_session.start()
        self.addCleanup(fake_regrade_session.stop)

        fake_recalculate_session_grade = mock.patch(
            "course.flow.recalculate_session_grade")
        self.mock_recalculate_session_grade = fake_recalculate_session_grade.start()
        self.addCleanup(fake_recalculate_session_grade.stop)

        fake_expire_flow_session_standalone = mock.patch(
            "course.flow.expire_flow_session_standalone")
        self.mock_expire_flow_session_standalone = (
            fake_expire_flow_session_standalone.start())
        self.addCleanup(fake_expire_flow_session_standalone.stop)

        fake_finish_flow_session_standalone = mock.patch(
            "course.flow.finish_flow_session_standalone")
        self.mock_finish_flow_session_standalone = (
            fake_finish_flow_session_standalone.start())
        self.addCleanup(fake_finish_flow_session_standalone.stop)

    def test_participation_course_not_match(self):
        another_course_participation = factories.ParticipationFactory(
            course=factories.CourseFactory(identifier="another-course"))
        resp = self.get_view_single_grade(another_course_participation, self.gopp)
        self.assertEqual(resp.status_code, 400)

    def test_gopp_course_not_match(self):
        another_course_gopp = factories.GradingOpportunityFactory(
            course=factories.CourseFactory(identifier="another-course"),
            identifier=QUIZ_FLOW_ID)
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(self.get_single_grade_url(
                self.student_participation.pk, another_course_gopp.pk))
            self.assertEqual(resp.status_code, 400)

    def test_view_other_single_grade_no_pperm(self):
        another_participation = factories.ParticipationFactory(
            course=self.course)
        with self.temporarily_switch_to_user(another_participation.user):
            resp = self.get_view_single_grade(
                self.student_participation, self.gopp, force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

            resp = self.post_view_single_grade(
                self.student_participation, self.gopp, data={},
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

    def test_view_success(self):
        resp = self.get_view_single_grade(
            self.student_participation, self.gopp)
        self.assertEqual(resp.status_code, 200)

    def test_view_not_shown_in_grade_book(self):
        hidden_gopp = factories.GradingOpportunityFactory(
            course=self.course, identifier="hidden",
            shown_in_grade_book=False)

        resp = self.get_view_single_grade(
            self.student_participation, hidden_gopp)
        self.assertEqual(resp.status_code, 200)
        self.assertAddMessageCalledWith(
            "This grade is not shown in the grade book.")

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_view_single_grade(
                self.student_participation, hidden_gopp,
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

    def test_view_not_shown_in_participant_grade_book(self):
        hidden_gopp = factories.GradingOpportunityFactory(
            course=self.course, identifier="hidden",
            shown_in_participant_grade_book=False)

        resp = self.get_view_single_grade(
            self.student_participation, hidden_gopp)
        self.assertEqual(resp.status_code, 200)
        self.assertAddMessageCalledWith(
            "This grade is not shown in the student grade book.")

        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_view_single_grade(
                self.student_participation, hidden_gopp,
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

    def test_post_no_pperm(self):
        another_participation = factories.ParticipationFactory(
            course=self.course)

        # only view_gradebook pperm
        pp = models.ParticipationPermission(
            participation=another_participation,
            permission=pperm.view_gradebook)
        pp.save()

        fs = factories.FlowSessionFactory(
            participation=self.student_participation, flow_id=self.flow_id)

        for op in ["imposedl", "end", "regrade", "recalculate"]:
            with self.subTest(op=op):
                resp = self.post_view_single_grade(
                    self.student_participation, self.gopp,
                    data={"%s_%d" % (op, fs.pk): ''},
                    force_login_instructor=False)
                self.assertEqual(resp.status_code, 403)

    def test_post_no_action_match(self):
        resp = self.post_view_single_grade(
            self.student_participation, self.gopp,
            data={"blablabal": ''})
        self.assertEqual(resp.status_code, 400)

    def test_post(self):
        fs = factories.FlowSessionFactory(
            participation=self.student_participation, flow_id=self.flow_id)

        tup = (
            ("imposedl", self.mock_expire_flow_session_standalone,
             "Session deadline imposed."),
            ("end", self.mock_finish_flow_session_standalone, "Session ended."),
            ("regrade", self.mock_regrade_session, "Session regraded."),
            ("recalculate", self.mock_recalculate_session_grade,
             "Session grade recalculated."))

        for op, mock_func, msg in tup:
            with self.subTest(op=op):
                resp = self.post_view_single_grade(
                    self.student_participation, self.gopp,
                    data={"%s_%d" % (op, fs.pk): ''})
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(mock_func.call_count, 1)
                self.assertAddMessageCalledWith(msg, reset=True)
                mock_func.reset_mock()

    def test_post_invalid_session_op(self):
        fs = factories.FlowSessionFactory(
            participation=self.student_participation, flow_id=self.flow_id)

        resp = self.post_view_single_grade(
            self.student_participation, self.gopp,
            data={"blablabal_%d" % fs.pk: ''})
        self.assertEqual(resp.status_code, 400)

    def test_post_keyboard_interrupt(self):
        fs = factories.FlowSessionFactory(
            participation=self.student_participation, flow_id=self.flow_id)

        tup = (
            ("imposedl", self.mock_expire_flow_session_standalone,
             "Session deadline imposed."),
            ("end", self.mock_finish_flow_session_standalone, "Session ended."),
            ("regrade", self.mock_regrade_session, "Session regraded."),
            ("recalculate", self.mock_recalculate_session_grade,
             "Session grade recalculated."))

        err = "foo"
        self.mock_regrade_session.side_effect = KeyboardInterrupt(err)
        self.mock_recalculate_session_grade.side_effect = KeyboardInterrupt(err)
        self.mock_expire_flow_session_standalone.side_effect = KeyboardInterrupt(err)
        self.mock_finish_flow_session_standalone.side_effect = KeyboardInterrupt(err)

        for op, mock_func, msg in tup:
            with self.subTest(op=op):
                resp = self.post_view_single_grade(
                    self.student_participation, self.gopp,
                    data={"%s_%d" % (op, fs.pk): ''})
                self.assertEqual(resp.status_code, 200)
                self.assertAddMessageNotCalledWith(msg, reset=False)
                self.assertAddMessageCalledWith(
                    "Error: KeyboardInterrupt %s" % err, reset=True)

                mock_func.reset_mock()

    def test_view_gopp_flow_desc_not_exist(self):
        with mock.patch("course.content.get_flow_desc") as mock_get_flow_desc:
            from django.core.exceptions import ObjectDoesNotExist
            mock_get_flow_desc.side_effect = ObjectDoesNotExist()
            resp = self.get_view_single_grade(
                self.student_participation, self.gopp)
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextIsNone(
                resp, "flow_sessions_and_session_properties")

    def test_view_gopp_no_flow_id(self):
        gopp = factories.GradingOpportunityFactory(
            course=self.course,
            identifier="no_flow_id",
            flow_id=None)
        factories.GradeChangeFactory(
            **self.gc(
                opportunity=gopp))
        resp = self.get_view_single_grade(
            self.student_participation, gopp)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextIsNone(
            resp, "flow_sessions_and_session_properties")

    def test_filter_out_pre_public_grade_changes(self):
        gopp = factories.GradingOpportunityFactory(
            course=self.course,
            identifier="no_flow_id",
            flow_id=None)
        # 5 gchanges

        factories.GradeChangeFactory(**self.gc(
            opportunity=gopp))
        factories.GradeChangeFactory(**self.gc(
            opportunity=gopp))
        factories.GradeChangeFactory(**self.gc(
            opportunity=gopp))
        fourth_gc = factories.GradeChangeFactory(**self.gc(
            opportunity=gopp))
        factories.GradeChangeFactory(**self.gc(
            opportunity=gopp))

        resp = self.get_view_single_grade(
            self.student_participation, gopp)
        self.assertEqual(resp.status_code, 200)
        resp_gchanges = resp.context["grade_changes"]
        self.assertEqual(len(resp_gchanges), 5)

        # update_gopp
        gopp.hide_superseded_grade_history_before = (
            fourth_gc.grade_time - timedelta(minutes=1))
        gopp.save()

        # view by instructor
        resp = self.get_view_single_grade(
            self.student_participation, gopp)
        self.assertEqual(resp.status_code, 200)
        resp_gchanges = resp.context["grade_changes"]
        self.assertEqual(len(resp_gchanges), 5)

        # view by student
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_view_single_grade(
                self.student_participation, gopp, force_login_instructor=False)
            self.assertEqual(resp.status_code, 200)
            resp_gchanges = resp.context["grade_changes"]
            self.assertEqual(len(resp_gchanges), 2)


class EditGradingOpportunityTest(GradesTestMixin, TestCase):
    # test grades.edit_grading_opportunity

    def get_edit_grading_opportunity_url(self, opp_id, course_identifier=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        kwargs = {"course_identifier": course_identifier,
                  "opportunity_id": opp_id}
        return reverse("relate-edit_grading_opportunity", kwargs=kwargs)

    def get_edit_grading_opportunity_view(self, opp_id, course_identifier=None,
                                          force_login_instructor=True):
        course_identifier = course_identifier or self.get_default_course_identifier()
        if not force_login_instructor:
            user = self.get_logged_in_user()
        else:
            user = self.instructor_participation.user

        with self.temporarily_switch_to_user(user):
            return self.c.get(
                self.get_edit_grading_opportunity_url(opp_id, course_identifier))

    def post_edit_grading_opportunity_view(self, opp_id, data,
                                           course_identifier=None,
                                           force_login_instructor=True):
        course_identifier = course_identifier or self.get_default_course_identifier()
        if not force_login_instructor:
            user = self.get_logged_in_user()
        else:
            user = self.instructor_participation.user

        with self.temporarily_switch_to_user(user):
            return self.c.post(
                self.get_edit_grading_opportunity_url(opp_id, course_identifier),
                data)

    def edit_grading_opportunity_post_data(
            self, name, identifier, page_scores_in_participant_gradebook=False,
            hide_superseded_grade_history_before=None,
            op="sumbit", shown_in_participant_grade_book=True,
            aggregation_strategy=constants.grade_aggregation_strategy.use_latest,
            shown_in_grade_book=True, result_shown_in_participant_grade_book=True,
            **kwargs):

        data = {"name": name,
                "identifier": identifier,
                op: '',
                "aggregation_strategy": aggregation_strategy}

        if page_scores_in_participant_gradebook:
            data["page_scores_in_participant_gradebook"] = ''

        if hide_superseded_grade_history_before:
            if isinstance(hide_superseded_grade_history_before, datetime.datetime):
                date_time_picker_time_format = "%Y-%m-%d %H:%M"
                hide_superseded_grade_history_before = (
                    hide_superseded_grade_history_before.strftime(
                        date_time_picker_time_format))
            data["hide_superseded_grade_history_before"] = (
                hide_superseded_grade_history_before)
        if shown_in_participant_grade_book:
            data["shown_in_participant_grade_book"] = ''
        if shown_in_grade_book:
            data["shown_in_grade_book"] = ''
        if result_shown_in_participant_grade_book:
            data["result_shown_in_participant_grade_book"] = ''

        data.update(kwargs)
        return data

    def test_get_add_new(self):
        resp = self.get_edit_grading_opportunity_view(-1)
        self.assertEqual(resp.status_code, 200)

    def test_post_get_add_new(self):
        name = "my Gopp"
        identifier = "my_gopp"
        data = self.edit_grading_opportunity_post_data(
            name=name, identifier=identifier)
        resp = self.post_edit_grading_opportunity_view(-1, data=data)
        gopps = models.GradingOpportunity.objects.all()
        self.assertEqual(gopps.count(), 2)
        my_gopp = gopps.last()
        self.assertEqual(my_gopp.name, name)
        self.assertEqual(my_gopp.identifier, identifier)
        self.assertRedirects(
            resp, self.get_edit_grading_opportunity_url(my_gopp.pk),
            fetch_redirect_response=False)

    def test_course_not_match(self):
        another_course = factories.CourseFactory(identifier="another-course")
        another_course_gopp = factories.GradingOpportunityFactory(
            course=another_course)
        gopps = models.GradingOpportunity.objects.all()
        self.assertEqual(gopps.count(), 2)

        resp = self.get_edit_grading_opportunity_view(
            another_course_gopp.id, course_identifier=self.course.identifier)
        self.assertEqual(resp.status_code, 400)

    def test_view_edit_grading_opportunity(self):
        my_gopp = factories.GradingOpportunityFactory(
            course=self.course, identifier="another_gopp")

        data = self.edit_grading_opportunity_post_data(
            name=my_gopp.name, identifier=my_gopp.identifier,
            shown_in_grade_book=False)

        resp = self.post_edit_grading_opportunity_view(my_gopp.id, data=data)

        self.assertRedirects(
            resp, self.get_edit_grading_opportunity_url(my_gopp.pk),
            fetch_redirect_response=False)

        my_gopp.refresh_from_db()
        self.assertEqual(my_gopp.shown_in_grade_book, False)

    def test_view_edit_grading_opportunity_form_invalid(self):
        my_gopp = factories.GradingOpportunityFactory(
            course=self.course, identifier="another_gopp")

        data = self.edit_grading_opportunity_post_data(
            name=my_gopp.name, identifier=my_gopp.identifier,
            shown_in_grade_book=False)
        with mock.patch(
                "course.grades.EditGradingOpportunityForm.is_valid"
        ) as mock_form_is_valid:
            mock_form_is_valid.return_value = False

            resp = self.post_edit_grading_opportunity_view(my_gopp.id, data=data)
            self.assertEqual(resp.status_code, 200)

        my_gopp.refresh_from_db()
        self.assertEqual(my_gopp.shown_in_grade_book, True)


class DownloadAllSubmissionsTest(SingleCourseQuizPageTestMixin,
                                 HackRepoMixin, TestCase):
    # test grades.download_all_submissions (for cases not covered by other tests)

    page_id = "half"
    my_access_rule_tag = "my_access_rule_tag"

    @classmethod
    def setUpTestData(cls):  # noqa
        super(DownloadAllSubmissionsTest, cls).setUpTestData()

        # with this faked commit_sha, we may do multiple submissions
        cls.course.active_git_commit_sha = (
            "my_fake_commit_sha_for_download_submissions")
        cls.course.save()
        with cls.temporarily_switch_to_user(cls.student_participation.user):
            cls.start_flow(cls.flow_id)
            cls.submit_page_answer_by_page_id_and_test(
                cls.page_id, answer_data={"answer": 0.25})
            cls.end_flow()

            fs = models.FlowSession.objects.first()
            fs.access_rules_tag = cls.my_access_rule_tag
            fs.save()

            cls.start_flow(cls.flow_id)
            cls.submit_page_answer_by_page_id_and_test("proof")
            cls.submit_page_answer_by_page_id_and_test(cls.page_id)
            cls.end_flow()

        # create an in_progress flow, with the same page submitted
        another_particpation = factories.ParticipationFactory(
            course=cls.course)
        with cls.temporarily_switch_to_user(another_particpation.user):
            cls.start_flow(cls.flow_id)
            cls.submit_page_answer_by_page_id_and_test(cls.page_id)

            # create a flow with no answers
            cls.start_flow(cls.flow_id)
            cls.end_flow()

    @property
    def group_page_id(self):
        _, group_id = self.get_page_ordinal_via_page_id(
            self.page_id, with_group_id=True)
        return "%s/%s" % (group_id, self.page_id)

    def get_zip_file_buf_from_response(self, resp):
        return io.BytesIO(resp.content)

    def assertDownloadedFileZippedExtensionCount(self, resp, extensions, counts):  # noqa

        assert isinstance(extensions, list)
        assert isinstance(counts, list)
        assert len(extensions) == len(counts)
        prefix, zip_file = resp["Content-Disposition"].split('=')
        self.assertEqual(prefix, "attachment; filename")
        self.assertEqual(resp.get('Content-Type'), "application/zip")
        buf = io.BytesIO(resp.content)
        import zipfile
        with zipfile.ZipFile(buf, 'r') as zf:
            self.assertIsNone(zf.testzip())

            for f in zf.filelist:
                self.assertTrue(f.file_size > 0)

            for i, ext in enumerate(extensions):
                self.assertEqual(
                    len([f for f in zf.filelist if
                         f.filename.endswith(ext)]), counts[i])

    def test_no_rules_tag(self):
        hacked_flow_desc = self.get_hacked_flow_desc(del_rules=True)
        with mock.patch("course.content.get_flow_desc") as mock_get_flow_desc:
            mock_get_flow_desc.return_value = hacked_flow_desc

            with self.temporarily_switch_to_user(self.instructor_participation.user):
                resp = self.post_download_all_submissions_by_group_page_id(
                    group_page_id=self.group_page_id, flow_id=self.flow_id)
                self.assertEqual(resp.status_code, 200)
                self.assertDownloadedFileZippedExtensionCount(
                    resp, [".txt"], [1])

    def test_download_first_attempt(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.post_download_all_submissions_by_group_page_id(
                group_page_id=self.group_page_id, flow_id=self.flow_id,
                which_attempt="first")

            self.assertEqual(resp.status_code, 200)
            self.assertDownloadedFileZippedExtensionCount(
                resp, [".txt"], [1])

    def test_download_all_attempts(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.post_download_all_submissions_by_group_page_id(
                group_page_id=self.group_page_id, flow_id=self.flow_id,
                which_attempt="all")

            self.assertEqual(resp.status_code, 200)
            self.assertDownloadedFileZippedExtensionCount(
                resp, [".txt"], [2])

    def test_download_include_feedback(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.post_download_all_submissions_by_group_page_id(
                group_page_id=self.group_page_id, flow_id=self.flow_id,
                include_feedback=True)

            self.assertEqual(resp.status_code, 200)
            self.assertDownloadedFileZippedExtensionCount(
                resp, [".txt"], [2])

    def test_download_include_feedback_no_feedback(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            another_group_page_id = (
                self.group_page_id.replace(self.page_id, "proof"))
            resp = self.post_download_all_submissions_by_group_page_id(
                group_page_id=another_group_page_id, flow_id=self.flow_id,
                include_feedback=True)

            self.assertEqual(resp.status_code, 200)
            self.assertDownloadedFileZippedExtensionCount(
                resp, [".pdf"], [1])

    def test_download_include_extra_file(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            import os
            with open(
                    os.path.join(os.path.dirname(__file__),
                                 '../resource',
                                 'test_file.pdf'), 'rb') as extra_file:
                resp = self.post_download_all_submissions_by_group_page_id(
                    group_page_id=self.group_page_id, flow_id=self.flow_id,
                    extra_file=extra_file)

            self.assertEqual(resp.status_code, 200)
            self.assertDownloadedFileZippedExtensionCount(
                resp, [".txt", ".pdf"], [1, 1])

    def test_download_in_progress(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.post_download_all_submissions_by_group_page_id(
                group_page_id=self.group_page_id, flow_id=self.flow_id,
                non_in_progress_only=False)

            self.assertEqual(resp.status_code, 200)
            self.assertDownloadedFileZippedExtensionCount(
                resp, [".txt"], [2])

    def test_download_other_access_rule_tags(self):
        hacked_flow_desc = (
            self.get_hacked_flow_desc_with_access_rule_tags(
                [self.my_access_rule_tag, "blahblah"]))

        with mock.patch("course.content.get_flow_desc") as mock_get_flow_desc:
            mock_get_flow_desc.return_value = hacked_flow_desc

            with self.temporarily_switch_to_user(self.instructor_participation.user):
                resp = self.post_download_all_submissions_by_group_page_id(
                    group_page_id=self.group_page_id, flow_id=self.flow_id,
                    restrict_to_rules_tag=self.my_access_rule_tag)

                self.assertEqual(resp.status_code, 200)

                self.assertDownloadedFileZippedExtensionCount(
                    resp, [".txt"], [1])


class PointsEqualTest(unittest.TestCase):
    # grades.points_equal
    def test(self):
        from decimal import Decimal
        self.assertTrue(grades.points_equal(None, None))
        self.assertFalse(grades.points_equal(Decimal(1.11), None))
        self.assertFalse(grades.points_equal(None, Decimal(1.11)))
        self.assertTrue(grades.points_equal(Decimal(1.11), Decimal(1.11)))
        self.assertFalse(grades.points_equal(Decimal(1.11), Decimal(1.12)))


@unittest.SkipTest
class FixingTest(GradesTestMixin, TestCase):
    # currently skipped

    def reopen_session1(self):
        existing_gc_count = models.GradeChange.objects.count()
        reopen_session(now_datetime=local_now(), session=self.session1,
                       generate_grade_change=True,
                       suppress_log=True)
        self.assertEqual(models.GradeChange.objects.count(), existing_gc_count+1)
        self.session1.refresh_from_db()

    def reopen_session2(self):
        existing_gc_count = models.GradeChange.objects.count()
        reopen_session(now_datetime=local_now(), session=self.session2,
                       generate_grade_change=True,
                       suppress_log=True)
        self.assertEqual(models.GradeChange.objects.count(), existing_gc_count+1)
        self.session2.refresh_from_db()

    def test_append_gc_with_session_after_reopen_session2(self):
        self.use_default_setup()
        self.reopen_session2()

        # append a grade change for session2
        # grade_time need to be specified, because the faked gc
        # is using fake time, while reopen a session will create
        # an actual gc using the actual time.

        latest_gc = models.GradeChange.objects.all().order_by("-grade_time")[0]

        self.append_gc(self.gc(points=12, flow_session=self.session2,
                               grade_time=now(),
                               effective_time=latest_gc.effective_time))
        self.assertGradeChangeMachineReadableStateEqual(12)
        self.assertGradeChangeStateEqual("12.00% (/3)")

    def test_append_nonsession_gc_after_reopen_session2(self):
        self.use_default_setup()
        self.reopen_session2()

        # Append a grade change without session
        # grade_time need to be specified, because the faked gc
        # is using fake time, while reopen a session will create
        # an actual gc using the actual time.
        self.append_gc(self.gc(points=11, grade_time=now()))
        self.assertGradeChangeMachineReadableStateEqual(11)
        self.assertGradeChangeStateEqual("11.00% (/3)")

    def test_new_gchange_created_when_finish_flow_use_last_has_activity(self):
        # With use_last_activity_as_completion_time = True, if a flow session HAS
        # last_activity, the expected effective_time of the new gchange should be
        # the last_activity() of the related flow_session.
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            self.start_flow(QUIZ_FLOW_ID)

            # create a flow page visit, then there should be last_activity() for
            # the session.
            self.post_answer_by_ordinal(1, {"answer": ['0.5']})
            self.assertEqual(
                models.FlowPageVisit.objects.filter(answer__isnull=False).count(),
                1)
            last_answered_visit = (
                models.FlowPageVisit.objects.filter(answer__isnull=False).first())
            last_answered_visit.visit_time = now() - timedelta(hours=1)
            last_answered_visit.save()
            self.assertEqual(models.GradeChange.objects.count(), 0)

            with mock.patch("course.flow.get_session_grading_rule") as \
                    mock_get_grading_rule:
                mock_get_grading_rule.side_effect = (
                    get_session_grading_rule_use_last_activity_as_cmplt_time_side_effect)  # noqa
                resp = self.end_flow()
                self.assertEqual(resp.status_code, 200)

            self.assertEqual(models.GradeChange.objects.count(), 1)
            latest_gchange = models.GradeChange.objects.last()
            latest_flow_session = models.FlowSession.objects.last()
            self.assertIsNotNone(latest_flow_session.last_activity())
            self.assertEqual(latest_flow_session.completion_time,
                             latest_flow_session.last_activity())
            self.assertEqual(latest_gchange.effective_time,
                             latest_flow_session.last_activity())

    # {{{ Fixed issue #263 and #417

    def test_update_latest_gc_of_ealier_finished_session(self):
        self.use_default_setup()
        self.assertGradeChangeMachineReadableStateEqual(6)

        # Issue #263 and #417
        # gc_session1 is the GradeChange object of session 1, update it's
        # value won't change the consumed state.
        self.update_gc(self.gc_session1, points=10)
        self.assertGradeChangeMachineReadableStateEqual(6)
        self.assertGradeChangeStateEqual("6.00% (/3)")

    def test_special_case(self):
        # https://github.com/inducer/relate/pull/423#discussion_r162121467
        gc2015 = factories.GradeChangeFactory.create(**(self.gc(points=5)))

        session1 = factories.FlowSessionFactory.create(
            participation=self.student_participation,
            start_time=self.time-timedelta(days=17),
            completion_time=self.time-timedelta(days=14))

        self.time_increment()

        gc2016 = factories.GradeChangeFactory.create(
            **(self.gc(points=0, flow_session=session1, grade_time=self.time)))

        gc2017 = factories.GradeChangeFactory.create(**(self.gc(points=7)))

        session2 = factories.FlowSessionFactory.create(
            participation=self.student_participation,
            start_time=self.time-timedelta(days=17),
            completion_time=self.time-timedelta(days=15))

        self.time_increment()

        gc2018 = factories.GradeChangeFactory.create(
            **(self.gc(points=6, flow_session=session2)))

        assert models.GradingOpportunity.objects.count() == 1
        assert models.GradeChange.objects.count() == 4
        assert models.FlowSession.objects.count() == 2

        self.assertTrue(session2.completion_time < session1.completion_time)
        self.assertTrue(
            gc2015.grade_time < gc2016.grade_time < gc2017.grade_time
            < gc2018.grade_time)

        self.assertGradeChangeMachineReadableStateEqual(gc2017.percentage())

    # {{{ When two grade changes have the same grade_time
    # The expected behavior is GradeChange object with the larger pk
    # dominate. Fixed with #263 and #417

    def test_gcs_have_same_grade_time1(self):
        gc1 = factories.GradeChangeFactory.create(**(self.gc(points=0)))
        session = factories.FlowSessionFactory.create(
            participation=self.student_participation,
            completion_time=gc1.grade_time-timedelta(days=1))
        factories.GradeChangeFactory.create(
            **(self.gc(points=5, flow_session=session,
                       grade_time=gc1.grade_time)))
        self.assertGradeChangeMachineReadableStateEqual(5)
        self.assertGradeChangeStateEqual("5.0% (/2)")

    def test_gc_have_same_grade_time2(self):
        session = factories.FlowSessionFactory.create(
            participation=self.student_participation,
            start_time=self.time-timedelta(days=1),
            completion_time=self.time)
        self.time_increment()
        gc1 = factories.GradeChangeFactory.create(
            **(self.gc(points=5, flow_session=session)))
        factories.GradeChangeFactory.create(
            **(self.gc(points=0, grade_time=gc1.grade_time)))
        self.assertGradeChangeMachineReadableStateEqual(0)
        self.assertGradeChangeStateEqual("0.00% (/2)")
    # }}}

    # {{{ Fix #430

    def test_reopen_session2(self):
        self.use_default_setup()

        # original state
        self.assertGradeChangeMachineReadableStateEqual("6")

        n_gc = models.GradeChange.objects.count()
        self.reopen_session2()

        # A new GradeChange object is created, with state "do_over"
        expected_n_gc = models.GradeChange.objects.count()
        self.assertEqual(expected_n_gc, n_gc + 1)
        self.assertEqual(
            models.GradeChange.objects.order_by("grade_time").last().state,
            g_state.do_over)

        self.assertGradeChangeMachineReadableStateEqual("NONE")
        self.assertGradeChangeStateEqual("- ∅ - (/3)")

    def test_reopen_session_without_existing_gc(self):
        # This is rare, because a completed_session should had created
        # a GradeChange object.
        session_temp = factories.FlowSessionFactory.create(
            participation=self.student_participation, completion_time=self.time)

        existing_gc_count = models.GradeChange.objects.count()
        reopen_session(now_datetime=local_now(), session=session_temp,
                       generate_grade_change=True,
                       suppress_log=True)
        self.assertEqual(models.GradeChange.objects.count(), existing_gc_count)

    def test_reopen_session1(self):
        self.use_default_setup()
        self.assertGradeChangeMachineReadableStateEqual("6")

        n_gc = models.GradeChange.objects.count()
        self.reopen_session1()

        # A new GradeChange object is created, with state "do_over"
        expected_n_gc = models.GradeChange.objects.count()
        self.assertEqual(expected_n_gc, n_gc + 1)
        self.assertEqual(
            models.GradeChange.objects.order_by("grade_time").last().state,
            g_state.do_over)

        # session 1 is not the latest session
        self.assertGradeChangeMachineReadableStateEqual("6")
        self.assertGradeChangeStateEqual("6.00% (/3)")

    def _get_admin_flow_session_delete_url(self, args):
        return reverse("admin:course_flowsession_delete", args=args)

    def _delete_flow_session_admin(self, flow_session):
        exist_flow_session_count = models.FlowSession.objects.count()
        flow_session_delete_url = self._get_admin_flow_session_delete_url(
            args=(flow_session.id,))
        delete_dict = {'post': 'yes'}
        with self.temporarily_switch_to_user(self.superuser):
            resp = self.c.get(flow_session_delete_url)
            self.assertEqual(resp.status_code, 200)
            resp = self.c.post(flow_session_delete_url, data=delete_dict)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(exist_flow_session_count,
                         models.FlowSession.objects.count() + 1)

    def test_delete_flow_session_admin_new_exempt_gradechange_created(self):
        self.use_default_setup()
        exist_grade_change_count = models.GradeChange.objects.count()

        # session1 has related grade changes, so a new grade change with 'exempt' is
        # created
        self._delete_flow_session_admin(self.session1)

        self.assertEqual(exist_grade_change_count + 1,
                         models.GradeChange.objects.count())

        last_gchange = (
            models.GradeChange.objects
            .order_by("-grade_time").first())
        self.assertIsNone(last_gchange.flow_session)
        self.assertEqual(last_gchange.state, g_state.exempt)

    def test_delete_flow_session_admin_no_new_gradechange_created(self):
        session_temp = factories.FlowSessionFactory.create(
            participation=self.student_participation, completion_time=self.time)

        exist_grade_change_count = models.GradeChange.objects.count()
        last_gchange_of_session_temp = (
            models.GradeChange.objects
            .filter(flow_session=session_temp)
            .order_by("-grade_time")[:1])
        self.assertEqual(last_gchange_of_session_temp.count(), 0)

        # session_temp has no related grade changes, so no new grade change
        # is created after deleted
        self._delete_flow_session_admin(session_temp)

        self.assertEqual(exist_grade_change_count,
                         models.GradeChange.objects.count())

    # }}}

    def test_backward_compatibility_merging_466(self):
        # this make sure after merging https://github.com/inducer/relate/pull/466
        # gchanges are consumed without issue
        self.use_default_setup()
        self.gc_session2.effective_time = None
        self.gc_session2.save()
        self.gc_session2.refresh_from_db()

        # We are not using reopen_session(), because that will create new
        # gchange, which only happen after #466 was merged.
        self.session2.in_progress = True
        self.session2.save()
        self.session2.refresh_from_db()

        machine = self.get_gc_machine()

        # session2's gchange is excluded
        self.assertGradeChangeMachineReadableStateEqual(7)
        self.assertEqual(machine.valid_percentages, [0, 7])
        self.assertGradeChangeStateEqual("7.00% (/2)")

    # {{{ test new gchange created when finishing flow

    def test_new_gchange_created_when_finish_flow_use_last_no_activity(self):
        # With use_last_activity_as_completion_time = True, if a flow session has
        # no last_activity, the expected effective_time of the new gchange should
        # be the completion time of the related flow_session.
        with self.temporarily_switch_to_user(self.student_participation.user):
            self.start_flow(QUIZ_FLOW_ID)
            self.assertEqual(models.GradeChange.objects.count(), 0)

            with mock.patch("course.flow.get_session_grading_rule") as \
                    mock_get_grading_rule:
                mock_get_grading_rule.side_effect = (
                    get_session_grading_rule_use_last_activity_as_cmplt_time_side_effect)  # noqa
                resp = self.end_flow()
                self.assertEqual(resp.status_code, 200)

            self.assertEqual(models.GradeChange.objects.count(), 1)
            latest_gchange = models.GradeChange.objects.last()
            latest_flow_session = models.FlowSession.objects.last()
            self.assertIsNone(latest_flow_session.last_activity())
            self.assertEqual(latest_gchange.effective_time,
                             latest_flow_session.completion_time)

    def test_new_gchange_created_when_finish_flow_not_use_last_no_activity(self):
        # With use_last_activity_as_completion_time = False, if a flow session has
        # no last_activity, the expected effective_time of the new gchange should
        # be the completion time of the related flow_session.
        with self.temporarily_switch_to_user(self.student_participation.user):
            self.start_flow(QUIZ_FLOW_ID)
            self.assertEqual(models.GradeChange.objects.count(), 0)

            resp = self.end_flow()
            self.assertEqual(resp.status_code, 200)

            self.assertEqual(models.GradeChange.objects.count(), 1)
            latest_gchange = models.GradeChange.objects.last()
            latest_flow_session = models.FlowSession.objects.last()
            self.assertIsNone(latest_flow_session.last_activity())
            self.assertEqual(latest_gchange.effective_time,
                             latest_flow_session.completion_time)

    def test_new_gchange_created_when_finish_flow_not_use_last_has_activity(self):
        # With use_last_activity_as_completion_time = False, even if a flow session
        # HAS last_activity, the expected effective_time of the new gchange should
        # be the completion_time of the related flow_session.
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            self.start_flow(QUIZ_FLOW_ID)

            # create a flow page visit, then there should be last_activity() for
            # the session.
            self.post_answer_by_ordinal(1, {"answer": ['0.5']})
            self.assertEqual(
                models.FlowPageVisit.objects.filter(answer__isnull=False).count(),
                1)
            last_answered_visit = (
                models.FlowPageVisit.objects.filter(answer__isnull=False).first())
            last_answered_visit.visit_time = now() - timedelta(hours=1)
            last_answered_visit.save()
            self.assertEqual(models.GradeChange.objects.count(), 0)

            resp = self.end_flow()
            self.assertEqual(resp.status_code, 200)

            self.assertEqual(models.GradeChange.objects.count(), 1)
            latest_gchange = models.GradeChange.objects.last()
            latest_flow_session = models.FlowSession.objects.last()
            self.assertIsNotNone(latest_flow_session.last_activity())
            self.assertNotEqual(latest_flow_session.completion_time,
                             latest_flow_session.last_activity())
            self.assertEqual(latest_gchange.effective_time,
                             latest_flow_session.completion_time)

    # }}}

# vim: fdm=marker
