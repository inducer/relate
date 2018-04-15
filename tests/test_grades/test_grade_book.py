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

from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import now, timedelta

from relate.utils import local_now

from course import models
from course.constants import (
    grade_aggregation_strategy as g_stragety,
    grade_state_change_types as g_state)
from course.flow import reopen_session
from course.grades import (
    get_single_grade_changes_and_state_machine as get_gc_and_machine)

from tests.utils import mock  # noqa
from tests.base_test_mixins import SingleCoursePageTestMixin
from tests import factories as fctr
from tests.factories import GradeChangeFactory as GCFactory
from tests.constants import QUIZ_FLOW_ID


def get_session_grading_rule_use_last_activity_as_cmplt_time_side_effect(
        session, flow_desc, now_datetime):
    # The testing flow "quiz-test" didn't set the attribute
    from course.utils import get_session_grading_rule
    actual_grading_rule = get_session_grading_rule(session, flow_desc, now_datetime)
    actual_grading_rule.use_last_activity_as_completion_time = True
    return actual_grading_rule


class GradeBookTestMixin(SingleCoursePageTestMixin):

    def setUp(self):
        super(GradeBookTestMixin, self).setUp()
        self.time = now() - timedelta(days=1)
        self.gopp = fctr.GradingOpportunityFactory(
            course=self.course, aggregation_strategy=g_stragety.use_latest)
        self.ptcp = self.student_participation

    def get_single_grade_view_url(self, participation, gopp,
                                  course_identifier=None):
        course_identifier = (
            course_identifier or self.get_default_course_identifier())
        return reverse(
            "relate-view_single_grade",
            kwargs={
                "course_identifier": course_identifier,
                "participation_id": participation.pk,
                "opportunity_id": gopp.id})

    def get_single_grade(self, participation, gopp, course_identifier=None):
        course_identifier = (
            course_identifier or self.get_default_course_identifier())
        return self.c.get(
            self.get_single_grade_view_url(participation, gopp, course_identifier))

    def use_default_setup(self):  # noqa
        self.session1 = fctr.FlowSessionFactory.create(
            participation=self.ptcp, completion_time=self.time)
        self.time_increment()
        self.gc_main_1 = GCFactory.create(**(self.gc(points=5)))
        self.gc_session1 = GCFactory.create(**(self.gc(points=0,
                                                       flow_session=self.session1)))

        self.session2 = fctr.FlowSessionFactory.create(
            participation=self.ptcp, completion_time=self.time)
        self.gc_main_2 = GCFactory.create(**(self.gc(points=7)))
        self.gc_session2 = GCFactory.create(**(self.gc(points=6,
                                                       flow_session=self.session2)))
        assert models.GradingOpportunity.objects.count() == 1
        assert models.GradeChange.objects.count() == 4
        assert models.FlowSession.objects.count() == 2

    def time_increment(self, minute_delta=10):
        self.time += timedelta(minutes=minute_delta)

    def gc(self, state=None, attempt_id=None, points=None,
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
            "opportunity": self.gopp,
            "participation": self.ptcp,
            "state": state or g_state.graded,
            "attempt_id": attempt_id,
            "points": points,
            "max_points": max_points or 100,
            "comment": comment,
            "due_time": due_time,
            "grade_time": grade_time or self.time,
            "flow_session": flow_session,
        }
        self.time += timedelta(minutes=10)
        gc_kwargs.update(kwargs)
        return gc_kwargs

    def get_gc_machine(self, gopp=None, participation=None):
        if not gopp:
            gopp = self.gopp
        if not participation:
            participation = self.ptcp
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
        return GCFactory.create(**gc)

    def update_gc(self, gc_object, update_time=True, **kwargs):
        # This is alter GradeChange objects via db.

        gc_dict = gc_object.__dict__
        gc_dict.update(**kwargs)
        if update_time:
            gc_dict["grade_time"] = now()
        gc_object.save()
        gc_object.refresh_from_db()

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


class GradesChangeStateMachineTest(GradeBookTestMixin, TestCase):

    def test_no_gradechange(self):
        # when no grade change object exists
        with self.temporarily_switch_to_user(self.ptcp.user):
            resp = self.get_single_grade(self.ptcp, self.gopp)

        self.assertResponseContextEqual(resp, "avg_grade_percentage", None)
        self.assertResponseContextEqual(resp, "avg_grade_population", 0)

    def test_default_setup(self):
        self.use_default_setup()
        self.assertGradeChangeMachineReadableStateEqual(6)
        self.assertGradeChangeStateEqual("6.00% (/3)")

        with self.temporarily_switch_to_user(self.ptcp.user):
            resp = self.get_single_grade(self.ptcp, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", 6)
        self.assertResponseContextEqual(resp, "avg_grade_population", 1)

    def test_change_aggregate_strategy_average(self):
        self.use_default_setup()
        self.update_gopp_strategy(g_stragety.avg_grade)
        self.assertGradeChangeMachineReadableStateEqual(4.333)
        self.assertGradeChangeStateEqual("4.33% (/3)")

    def test_change_aggregate_strategy_earliest(self):
        self.use_default_setup()
        self.update_gopp_strategy(g_stragety.use_earliest)
        self.assertGradeChangeMachineReadableStateEqual(0)
        self.assertGradeChangeStateEqual("0.00% (/3)")

        with self.temporarily_switch_to_user(self.ptcp.user):
            resp = self.get_single_grade(self.ptcp, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", 0)
        self.assertResponseContextEqual(resp, "avg_grade_population", 1)

    def test_change_aggregate_strategy_max(self):
        self.use_default_setup()
        self.update_gopp_strategy(g_stragety.max_grade)
        self.assertGradeChangeMachineReadableStateEqual(7)
        self.assertGradeChangeStateEqual("7.00% (/3)")

        with self.temporarily_switch_to_user(self.ptcp.user):
            resp = self.get_single_grade(self.ptcp, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", 7)
        self.assertResponseContextEqual(resp, "avg_grade_population", 1)

    def test_change_aggregate_strategy_max_none(self):
        # when no grade change has percentage
        self.update_gopp_strategy(g_stragety.max_grade)
        self.assertGradeChangeMachineReadableStateEqual("NONE")
        self.assertGradeChangeStateEqual("- ∅ -")

        GCFactory.create(**(self.gc(points=None)))
        self.assertGradeChangeMachineReadableStateEqual("NONE")
        self.assertGradeChangeStateEqual("- ∅ -")

        with self.temporarily_switch_to_user(self.ptcp.user):
            resp = self.get_single_grade(self.ptcp, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", None)
        self.assertResponseContextEqual(resp, "avg_grade_population", 0)

    def test_change_aggregate_strategy_min(self):
        self.use_default_setup()
        self.update_gopp_strategy(g_stragety.min_grade)
        self.assertGradeChangeMachineReadableStateEqual(0)
        self.assertGradeChangeStateEqual("0.00% (/3)")

    def test_change_aggregate_strategy_min_none(self):
        # when no grade change has percentage
        self.update_gopp_strategy(g_stragety.min_grade)
        self.assertGradeChangeMachineReadableStateEqual("NONE")
        self.assertGradeChangeStateEqual("- ∅ -")

        GCFactory.create(**(self.gc(points=None)))
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
        self.assertGradeChangeStateEqual("6.00% (/3)")

        # make sure participations with pperm.included_in_grade_statistics
        # are not included
        GCFactory.create(**(self.gc(
            participation=self.instructor_participation, points=2)))
        GCFactory.create(**(self.gc(
            participation=self.ta_participation, points=3)))

        with self.temporarily_switch_to_user(self.ptcp.user):
            resp = self.get_single_grade(self.ptcp, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", 6)
        self.assertResponseContextEqual(resp, "avg_grade_population", 1)

        temp_ptcp = fctr.ParticipationFactory.create(
            course=self.course)

        GCFactory.create(**(self.gc(participation=temp_ptcp, points=3)))
        with self.temporarily_switch_to_user(temp_ptcp.user):
            resp = self.get_single_grade(temp_ptcp, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", 4.5)
        self.assertResponseContextEqual(resp, "avg_grade_population", 2)

    def test_append_gc(self):
        self.use_default_setup()
        self.append_gc(self.gc(points=8, flow_session=self.session2))
        self.assertGradeChangeMachineReadableStateEqual(8)
        self.assertGradeChangeStateEqual("8.00% (/3)")

        self.append_gc(self.gc(points=0, flow_session=self.session2))
        self.assertGradeChangeMachineReadableStateEqual(0)
        self.assertGradeChangeStateEqual("0.00% (/3)")

    def test_update_latest_gc_of_latest_finished_session(self):
        self.use_default_setup()
        self.assertGradeChangeMachineReadableStateEqual(6)

        self.update_gc(self.gc_session2, points=10)
        self.assertGradeChangeMachineReadableStateEqual(10)
        self.assertGradeChangeStateEqual("10.00% (/3)")

    def test_update_ealiest_gc_of_ealier_finished_session(self):
        self.use_default_setup()
        self.assertGradeChangeMachineReadableStateEqual(6)

        self.update_gc(self.gc_main_2, update_time=False, points=15)
        self.assertGradeChangeMachineReadableStateEqual(6)
        self.assertGradeChangeStateEqual("6.00% (/3)")

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
        gc = GCFactory.create(**(self.gc(points=8.5, null_attempt_id=True)))  # noqa
        # print(gc.grade_time)

        machine = self.get_gc_machine()
        self.assertGradeChangeMachineReadableStateEqual(8.5)
        self.assertEqual(machine.valid_percentages, [8.5])

    def test_gc_unavailable(self):
        GCFactory.create(**(self.gc(points=9.1)))
        GCFactory.create(**(self.gc(points=0, state=g_state.unavailable)))
        machine = self.get_gc_machine()
        self.assertGradeChangeMachineReadableStateEqual("OTHER_STATE")
        self.assertEqual(machine.valid_percentages, [])
        self.assertGradeChangeStateEqual("(other state)")

        with self.temporarily_switch_to_user(self.ptcp.user):
            resp = self.get_single_grade(self.ptcp, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", None)
        self.assertResponseContextEqual(resp, "avg_grade_population", 0)

        # failure when unavailable gc follows another grade change
        GCFactory.create(**(self.gc(points=5)))

        with self.assertRaises(ValueError) as e:
            self.get_gc_stringify_machine_readable_state()
            self.assertIn("cannot accept grade once opportunity has been "
                            "marked 'unavailable'", e.exception)

    def test_gc_exempt(self):
        GCFactory.create(**(self.gc(points=6)))
        GCFactory.create(**(self.gc(points=0, state=g_state.exempt)))
        machine = self.get_gc_machine()
        self.assertGradeChangeMachineReadableStateEqual("EXEMPT")
        self.assertEqual(machine.valid_percentages, [])
        self.assertGradeChangeStateEqual("(exempt)")

        with self.temporarily_switch_to_user(self.ptcp.user):
            resp = self.get_single_grade(self.ptcp, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", None)
        self.assertResponseContextEqual(resp, "avg_grade_population", 0)

        # failure when exempt gc follows another grade change
        GCFactory.create(**(self.gc(points=5)))

        with self.assertRaises(ValueError) as e:
            self.get_gc_stringify_machine_readable_state()
            self.assertIn("cannot accept grade once opportunity has been "
                            "marked 'exempt'", e.exception)

    def test_gc_do_over(self):
        GCFactory.create(**(self.gc(points=6)))

        # This creates a GradeChange object with no attempt_id
        GCFactory.create(**(self.gc(points=0, state=g_state.do_over,
                                    null_attempt_id=True)))
        machine = self.get_gc_machine()
        self.assertGradeChangeMachineReadableStateEqual("NONE")
        self.assertEqual(machine.valid_percentages, [])
        self.assertGradeChangeStateEqual("- ∅ -")

        # This make sure new grade change objects following do_over gc is
        # consumed without problem
        GCFactory.create(**(self.gc(points=5)))
        self.assertGradeChangeMachineReadableStateEqual("5")
        machine = self.get_gc_machine()
        self.assertEqual(machine.valid_percentages, [5])
        self.assertGradeChangeStateEqual("5.00%")

    def test_gc_do_over_average_grade_value(self):
        self.use_default_setup()
        GCFactory.create(**(self.gc(points=None, state=g_state.do_over,
                                    flow_session=self.session2)))

        with self.temporarily_switch_to_user(self.ptcp.user):
            resp = self.get_single_grade(self.ptcp, self.gopp)
        self.assertResponseContextEqual(resp, "avg_grade_percentage", None)
        self.assertResponseContextEqual(resp, "avg_grade_population", 0)

    def test_gc_report_sent(self):
        GCFactory.create(**(self.gc(points=6)))
        gc2 = GCFactory.create(**(self.gc(points=0, state=g_state.report_sent)))
        machine = self.get_gc_machine()
        self.assertGradeChangeMachineReadableStateEqual("6")
        self.assertGradeChangeStateEqual("6.00%")
        self.assertEqual(machine.last_report_time, gc2.grade_time)

    def test_gc_extension(self):
        GCFactory.create(**(self.gc(points=6)))
        gc2 = GCFactory.create(**(self.gc(points=0, state=g_state.extension,
                                          due_time=self.time+timedelta(days=1))))
        machine = self.get_gc_machine()
        self.assertGradeChangeMachineReadableStateEqual("6")
        self.assertGradeChangeStateEqual("6.00%")
        self.assertEqual(machine.due_time, gc2.due_time)

    def test_gc_grading_started(self):
        GCFactory.create(**(self.gc(points=6)))
        GCFactory.create(**(self.gc(points=0, state=g_state.grading_started)))
        self.assertGradeChangeMachineReadableStateEqual("6")
        self.assertGradeChangeStateEqual("6.00%")

    def test_gc_retrieved(self):
        GCFactory.create(**(self.gc(points=6)))
        GCFactory.create(**(self.gc(points=0, state=g_state.retrieved)))
        self.assertGradeChangeMachineReadableStateEqual("6")
        self.assertGradeChangeStateEqual("6.00%")

    def test_gc_non_exist_state(self):
        GCFactory.create(**(self.gc(points=6)))
        GCFactory.create(**(self.gc(points=0, state="some_state")))

        with self.assertRaises(RuntimeError):
            self.get_gc_stringify_machine_readable_state()

    def test_gc_non_point(self):
        GCFactory.create(**(self.gc(points=None)))
        self.assertGradeChangeMachineReadableStateEqual("NONE")
        self.assertGradeChangeStateEqual("- ∅ -")

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

    def test_special_case(self):
        # https://github.com/inducer/relate/pull/423#discussion_r162121467
        gc2015 = GCFactory.create(**(self.gc(points=5)))

        session1 = fctr.FlowSessionFactory.create(
            participation=self.ptcp,
            start_time=self.time-timedelta(days=17),
            completion_time=self.time-timedelta(days=14))

        self.time_increment()

        gc2016 = GCFactory.create(
            **(self.gc(points=0, flow_session=session1, grade_time=self.time)))

        gc2017 = GCFactory.create(**(self.gc(points=7)))

        session2 = fctr.FlowSessionFactory.create(
            participation=self.ptcp,
            start_time=self.time-timedelta(days=17),
            completion_time=self.time-timedelta(days=15))

        self.time_increment()

        gc2018 = GCFactory.create(**(self.gc(points=6, flow_session=session2)))

        assert models.GradingOpportunity.objects.count() == 1
        assert models.GradeChange.objects.count() == 4
        assert models.FlowSession.objects.count() == 2

        self.assertTrue(session2.completion_time < session1.completion_time)
        self.assertTrue(
            gc2015.grade_time < gc2016.grade_time < gc2017.grade_time
            < gc2018.grade_time)

        self.assertGradeChangeMachineReadableStateEqual(gc2017.percentage())

    # }}}

    # {{{ When two grade changes have the same grade_time
    # The expected behavior is GradeChange object with the larger pk
    # dominate. Fixed with #263 and #417

    def test_gcs_have_same_grade_time1(self):
        gc1 = GCFactory.create(**(self.gc(points=0)))
        session = fctr.FlowSessionFactory.create(
            participation=self.ptcp,
            completion_time=gc1.grade_time-timedelta(days=1))
        GCFactory.create(**(self.gc(points=5, flow_session=session,
                                    grade_time=gc1.grade_time)))
        self.assertGradeChangeMachineReadableStateEqual(5)
        self.assertGradeChangeStateEqual("5.00% (/2)")

    def test_gc_have_same_grade_time2(self):
        session = fctr.FlowSessionFactory.create(
            participation=self.ptcp,
            start_time=self.time-timedelta(days=1),
            completion_time=self.time)
        self.time_increment()
        gc1 = GCFactory.create(**(self.gc(points=5, flow_session=session)))
        GCFactory.create(**(self.gc(points=0, grade_time=gc1.grade_time)))
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
        session_temp = fctr.FlowSessionFactory.create(
            participation=self.ptcp, completion_time=self.time)

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
        session_temp = fctr.FlowSessionFactory.create(
            participation=self.ptcp, completion_time=self.time)

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

    # {{{ test new gchange created when finishing flow

    def test_new_gchange_created_when_finish_flow_use_last_no_activity(self):
        # With use_last_activity_as_completion_time = True, if a flow session has
        # no last_activity, the expected effective_time of the new gchange should
        # be the completion time of the related flow_session.
        with self.temporarily_switch_to_user(self.ptcp):
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

    def test_new_gchange_created_when_finish_flow_use_last_has_activity(self):
        # With use_last_activity_as_completion_time = True, if a flow session HAS
        # last_activity, the expected effective_time of the new gchange should be
        # the last_activity() of the related flow_session.
        with self.temporarily_switch_to_user(self.instructor_participation):
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

    def test_new_gchange_created_when_finish_flow_not_use_last_no_activity(self):
        # With use_last_activity_as_completion_time = False, if a flow session has
        # no last_activity, the expected effective_time of the new gchange should
        # be the completion time of the related flow_session.
        with self.temporarily_switch_to_user(self.ptcp):
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
        with self.temporarily_switch_to_user(self.instructor_participation):
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


class ViewParticipantGradesTest(GradeBookTestMixin, TestCase):
    def setUp(self):
        super(ViewParticipantGradesTest, self).setUp()
        self.use_default_setup()
        self.gopp_hidden_in_gradebook = fctr.GradingOpportunityFactory(
            course=self.course, aggregation_strategy=g_stragety.use_latest,
            flow_id=None, shown_in_grade_book=False,
            identifier="hidden_in_instructor_grade_book")

        self.gopp_hidden_in_gradebook = fctr.GradingOpportunityFactory(
            course=self.course, aggregation_strategy=g_stragety.use_latest,
            flow_id=None, shown_in_grade_book=False,
            identifier="only_hidden_in_grade_book")

        self.gopp_hidden_in_participation_gradebook = (
            fctr.GradingOpportunityFactory(
                course=self.course,
                shown_in_participant_grade_book=False,
                aggregation_strategy=g_stragety.use_latest,
                flow_id=None, identifier="all_hidden_in_ptcp_gradebook"))

        self.gopp_result_hidden_in_participation_gradebook = (
            fctr.GradingOpportunityFactory(
                course=self.course, result_shown_in_participant_grade_book=False,
                aggregation_strategy=g_stragety.use_latest,
                flow_id=None, identifier="result_hidden_in_ptcp_gradebook"))

        self.gc_gopp_result_hidden = GCFactory(
            **self.gc(points=66.67,
                      opportunity=self.gopp_result_hidden_in_participation_gradebook,
                      state=g_state.graded))

    def test_view_my_grade(self):
        with self.temporarily_switch_to_user(self.ptcp):
            resp = self.get_view_my_grades()
            self.assertEqual(resp.status_code, 200)
            grade_table = self.get_response_context_value_by_name(
                resp, "grade_table")
            self.assertEqual((len(grade_table)), 2)
            self.assertEqual([g_info.opportunity.identifier
                              for g_info in grade_table],
                             [fctr.DEFAULT_GRADE_IDENTIFIER,
                              "result_hidden_in_ptcp_gradebook"])

            # the grade is hidden
            self.assertNotContains(resp, 66.67)

            grade_participation = self.get_response_context_value_by_name(
                resp, "grade_participation")
            self.assertEqual(grade_participation.pk, self.ptcp.pk)

            # shown
            self.assertContains(resp, fctr.DEFAULT_GRADE_IDENTIFIER)
            self.assertContains(resp, "result_hidden_in_ptcp_gradebook")

            # hidden
            self.assertNotContains(resp, "hidden_in_instructor_grade_book")
            self.assertNotContains(resp, "all_hidden_in_ptcp_gradebook")

    def test_view_participant_grades(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.get_view_participant_grades(self.ptcp.id)
            self.assertEqual(resp.status_code, 200)
            grade_table = self.get_response_context_value_by_name(
                resp, "grade_table")
            self.assertEqual((len(grade_table)), 3)
            self.assertEqual([g_info.opportunity.identifier
                              for g_info in grade_table],
                             ['all_hidden_in_ptcp_gradebook',
                              fctr.DEFAULT_GRADE_IDENTIFIER,
                              "result_hidden_in_ptcp_gradebook"])

            # the grade hidden to participation is show to instructor
            self.assertContains(resp, "66.67%(not released)")

            grade_participation = self.get_response_context_value_by_name(
                resp, "grade_participation")
            self.assertEqual(grade_participation.pk, self.ptcp.pk)

            # shown
            self.assertContains(resp, fctr.DEFAULT_GRADE_IDENTIFIER)
            self.assertContains(resp, "result_hidden_in_ptcp_gradebook")
            self.assertContains(resp, "all_hidden_in_ptcp_gradebook")

            # hidden
            self.assertNotContains(resp, "hidden_in_instructor_grade_book")

        with self.temporarily_switch_to_user(self.ptcp.user):
            resp = self.get_view_participant_grades(
                participation_id=self.instructor_participation.id)
            self.assertEqual(resp.status_code, 403)


# vim: fdm=marker
