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

from django.test import TestCase
from django.utils.timezone import now, timedelta

from course import models
from course.constants import (
    grade_aggregation_strategy as g_stragety,
    grade_state_change_types as g_state)
from course.grades import (
    get_single_grade_changes_and_state_machine as get_gc_and_machine)

from tests.utils import mock  # noqa
from tests.base_test_mixins import SingleCourseTestMixin
from tests import factories as fctr
from tests.factories import GradeChangeFactory as GCFactory


class GradesChangeStateMachineTest(SingleCourseTestMixin, TestCase):

    def setUp(self):
        super(GradesChangeStateMachineTest, self).setUp()
        self.time = now() - timedelta(days=1)
        self.gopp = fctr.GradingOpportunityFactory(
            course=self.course, aggregation_strategy=g_stragety.use_latest)
        self.ptcp = self.student_participation

    def use_default_setup(self):  # noqa
        self.session1 = fctr.FlowSessionFactory.create(
            participation=self.ptcp, completion_time=self.time)
        self.time_increment()
        self.gc1 = GCFactory.create(**(self.gc(points=5)))
        self.gc2 = GCFactory.create(**(self.gc(points=0,
                                               flow_session=self.session1)))

        self.session2 = fctr.FlowSessionFactory.create(
            participation=self.ptcp, completion_time=self.time)
        self.gc3 = GCFactory.create(**(self.gc(points=7)))
        self.gc4 = GCFactory.create(**(self.gc(points=6,
                                               flow_session=self.session2)))
        assert models.GradingOpportunity.objects.count() == 1
        assert models.GradeChange.objects.count() == 4
        assert models.FlowSession.objects.count() == 2

    def time_increment(self, minute_delta=10):
        self.time += timedelta(minutes=minute_delta)

    def gc(self, state=None, attempt_id=None, points=None,
           max_points=None, comment=None, due_time=None,
           grade_time=None, flow_session=None, **kwargs):

        if attempt_id is None:
            if flow_session is None:
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

    def get_gc_machine_state(self):
        _, machine = get_gc_and_machine(self.gopp, self.ptcp)
        return machine.stringify_machine_readable_state()

    def update_gopp_strategy(self, strategy=None):
        if not strategy:
            return
        else:
            self.gopp.aggregation_strategy = strategy
            self.gopp.save()
            self.gopp.refresh_from_db()

    def assertGradeChangeStateEqual(self, expected_state_string=None):  # noqa
        state_string = self.get_gc_machine_state()
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

    def reopen_session2(self):
        existing_gc_count = models.GradeChange.objects.count()
        self.session2.in_progress = True
        self.session2.completion_time = None
        self.session2.save()
        self.assertEqual(models.GradeChange.objects.count(), existing_gc_count+1)
        self.session2.refresh_from_db()

    def update_gc(self, gc_object, update_time=True, **kwargs):
        gc_dict = gc_object.__dict__
        gc_dict.update(**kwargs)
        if update_time:
            gc_dict["grade_time"] = now()
        gc_object.save()
        gc_object.refresh_from_db()

    def test_original(self):
        self.use_default_setup()
        self.assertGradeChangeStateEqual(6)

    def test_change_aggregate_strategy_average(self):
        self.use_default_setup()
        self.update_gopp_strategy(g_stragety.avg_grade)
        self.assertGradeChangeStateEqual(4.333)

    def test_change_aggregate_strategy_earliest(self):
        self.use_default_setup()
        self.update_gopp_strategy(g_stragety.use_earliest)
        self.assertGradeChangeStateEqual(0)

    def test_change_aggregate_strategy_max(self):
        self.use_default_setup()
        self.update_gopp_strategy(g_stragety.max_grade)
        self.assertGradeChangeStateEqual(7)

    def test_change_aggregate_strategy_min(self):
        self.use_default_setup()
        self.update_gopp_strategy(g_stragety.min_grade)
        self.assertGradeChangeStateEqual(0)

    def test_change_aggregate_strategy_invalid(self):
        self.use_default_setup()
        self.update_gopp_strategy("invalid_strategy")
        with self.assertRaises(ValueError):
            self.get_gc_machine_state()

    def test_append_gc(self):
        self.use_default_setup()
        self.append_gc(self.gc(points=8, flow_session=self.session2))
        self.assertGradeChangeStateEqual(8)
        self.append_gc(self.gc(points=0, flow_session=self.session2))
        self.assertGradeChangeStateEqual(0)

    def test_update_latest_gc_of_latest_finished_session(self):
        self.use_default_setup()
        self.update_gc(self.gc4, points=10)
        self.assertGradeChangeStateEqual(10)

    def test_update_ealiest_gc_of_ealier_finished_session(self):
        """
        This is rare, because this can only occur when update the
        GradeChange in admin or by pure db operation
        """
        self.use_default_setup()
        self.update_gc(self.gc3, update_time=False, points=15)
        self.assertGradeChangeStateEqual(6)

    def test_gc_consume_failure1(self):
        GCFactory.create(**(self.gc(points=5, state=g_state.unavailable)))
        GCFactory.create(**(self.gc(points=6)))
        with self.assertRaises(ValueError):
            get_gc_and_machine(self.gopp, self.ptcp)

    def test_gc_consume_failure2(self):
        GCFactory.create(**(self.gc(points=5, state=g_state.exempt)))
        GCFactory.create(**(self.gc(points=6)))
        with self.assertRaises(ValueError):
            get_gc_and_machine(self.gopp, self.ptcp)

    def test_gc_without_attempt_id(self):
        gc = GCFactory.create(**(self.gc(points=6)))
        gc.attempt_id = None
        gc.save()
        _, machine = get_gc_and_machine(self.gopp, self.ptcp)
        self.assertGradeChangeStateEqual(6)
        self.assertEqual(machine.valid_percentages, [6])

    def test_gc_last_unavailable(self):
        GCFactory.create(**(self.gc(points=6)))
        GCFactory.create(**(self.gc(points=0, state=g_state.unavailable)))
        _, machine = get_gc_and_machine(self.gopp, self.ptcp)
        self.assertGradeChangeStateEqual("OTHER_STATE")
        self.assertEqual(machine.valid_percentages, [])

    def test_gc_last_exempt(self):
        GCFactory.create(**(self.gc(points=6)))
        GCFactory.create(**(self.gc(points=0, state=g_state.exempt)))
        _, machine = get_gc_and_machine(self.gopp, self.ptcp)
        self.assertGradeChangeStateEqual("EXEMPT")
        self.assertEqual(machine.valid_percentages, [])

    def test_gc_last_do_over(self):
        GCFactory.create(**(self.gc(points=6)))
        GCFactory.create(**(self.gc(points=0, state=g_state.do_over)))
        _, machine = get_gc_and_machine(self.gopp, self.ptcp)
        self.assertGradeChangeStateEqual("NONE")
        self.assertEqual(machine.valid_percentages, [])

    def test_gc_last_report_sent(self):
        GCFactory.create(**(self.gc(points=6)))
        gc2 = GCFactory.create(**(self.gc(points=0, state=g_state.report_sent)))
        _, machine = get_gc_and_machine(self.gopp, self.ptcp)
        self.assertGradeChangeStateEqual("6")
        self.assertEqual(machine.last_report_time, gc2.grade_time)

    def test_gc_last_extension(self):
        GCFactory.create(**(self.gc(points=6)))
        gc2 = GCFactory.create(**(self.gc(points=0, state=g_state.extension,
                                          due_time=self.time+timedelta(days=1))))
        _, machine = get_gc_and_machine(self.gopp, self.ptcp)
        self.assertGradeChangeStateEqual("6")
        self.assertEqual(machine.due_time, gc2.due_time)

    def test_gc_last_grading_started(self):
        GCFactory.create(**(self.gc(points=6)))
        GCFactory.create(**(self.gc(points=0, state=g_state.grading_started)))
        _, machine = get_gc_and_machine(self.gopp, self.ptcp)
        self.assertGradeChangeStateEqual("6")

    def test_gc_last_retrieved(self):
        GCFactory.create(**(self.gc(points=6)))
        GCFactory.create(**(self.gc(points=0, state=g_state.retrieved)))
        _, machine = get_gc_and_machine(self.gopp, self.ptcp)
        self.assertGradeChangeStateEqual("6")

    def test_gc_last_non_exist_state(self):
        GCFactory.create(**(self.gc(points=6)))
        GCFactory.create(**(self.gc(points=0, state="some_state")))
        with self.assertRaises(RuntimeError):
            get_gc_and_machine(self.gopp, self.ptcp)

    def test_gc_last_non_point(self):
        GCFactory.create(**(self.gc(points=None)))
        self.assertGradeChangeStateEqual("NONE")

    # {{{ Fixing Issue # 263 and #417

    def test_update_latest_gc_of_ealier_finished_session(self):
        self.use_default_setup()

        # Issue # 263 and #417
        self.update_gc(self.gc2, points=10)
        self.assertGradeChangeStateEqual(6)

    def test_append_nonsession_gc_after_reopen_session2(self):
        self.use_default_setup()
        self.reopen_session2()

        # Append a grade change without session
        # grade_time need to be specified, because the faked gc
        # is using fake time, while reopen a session will create
        # an actual gc using the actual time.
        self.append_gc(self.gc(points=11, grade_time=now()))
        self.assertGradeChangeStateEqual(11)

    def test_append_gc_with_session_after_reopen_session2(self):
        self.use_default_setup()
        self.reopen_session2()

        # append a grade change for session2
        # grade_time need to be specified, because the faked gc
        # is using fake time, while reopen a session will create
        # an actual gc using the actual time.
        self.append_gc(self.gc(points=12, flow_session=self.session2,
                               grade_time=now()))
        self.assertGradeChangeStateEqual(12)

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

        self.assertGradeChangeStateEqual(gc2017.percentage())

    # }}}

    # {{{ GradeChange object with the larger pk dominate the final result.
    def test_gcs_have_same_grade_time1(self):
        gc1 = GCFactory.create(**(self.gc(points=0)))
        session = fctr.FlowSessionFactory.create(
            participation=self.ptcp,
            completion_time=gc1.grade_time-timedelta(days=1))
        GCFactory.create(**(self.gc(points=5, flow_session=session,
                                    grade_time=gc1.grade_time)))
        self.assertGradeChangeStateEqual(5)

    def test_gc_have_same_grade_time2(self):
        session = fctr.FlowSessionFactory.create(
            participation=self.ptcp,
            start_time=self.time-timedelta(days=1),
            completion_time=self.time)
        self.time_increment()
        gc1 = GCFactory.create(**(self.gc(points=5, flow_session=session)))
        GCFactory.create(**(self.gc(points=0, grade_time=gc1.grade_time)))
        self.assertGradeChangeStateEqual(0)

    # }}}

    # {{{ Fixing #430, session_reopened is introduced as a gradechange state

    def test_reopen_session2(self):
        self.use_default_setup()

        # Issue #430
        n_gc = models.GradeChange.objects.count()
        self.reopen_session2()
        self.assertGradeChangeStateEqual("OTHER_STATE")

        # New GradeChange object is created, with state "session_reopened"
        expected_n_gc = models.GradeChange.objects.count()

        self.assertEqual(expected_n_gc, n_gc + 1)

        # This need to add a gracde change state session_reopened
        self.assertEqual(models.GradeChange.objects.last().state,
                         g_state.session_reopened)

        # Test saving an reopened session won't created new GradeChange object
        self.session2.start_time = now()
        self.session2.save()
        self.session2.refresh_from_db()
        self.assertEqual(expected_n_gc, n_gc + 1)
        self.assertEqual(models.GradeChange.objects.last().state,
                         g_state.session_reopened)

    def test_gc_last_session_reopened(self):
        GCFactory.create(**(self.gc(points=6)))
        GCFactory.create(**(self.gc(points=0, state=g_state.session_reopened)))
        _, machine = get_gc_and_machine(self.gopp, self.ptcp)
        self.assertGradeChangeStateEqual("OTHER_STATE")
        self.assertEqual(machine.valid_percentages, [])

    # }}}
