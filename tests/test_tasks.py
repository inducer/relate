from __future__ import division

__copyright__ = "Copyright (C) 2017 Zesheng Wang"

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

from django.utils.timezone import now, timedelta
from django.test import TestCase, override_settings

from course import models
from course.tasks import (
    expire_in_progress_sessions,
    finish_in_progress_sessions,
    regrade_flow_sessions,
    recalculate_ended_sessions,
    purge_page_view_data,
)

from tests.base_test_mixins import SingleCourseTestMixin, TwoCoursePageTestMixin
from tests.test_flow.test_purge_page_view_data import (
    PURGE_VIEW_TWO_COURSE_SETUP_LIST)
from tests import factories
from tests.utils import mock

from pkg_resources import parse_version
import celery

is_celery_4_or_higher = parse_version(celery.__version__) >= parse_version("4.0.0")


def get_session_grading_rule_1_day_due_side_effect(
        session, flow_desc, now_datetime):
    from course.utils import get_session_grading_rule
    actual_grading_rule = get_session_grading_rule(session, flow_desc, now_datetime)
    actual_grading_rule.due = now() + timedelta(days=1)
    return actual_grading_rule


class FactoryTest(SingleCourseTestMixin, TestCase):
    def test_create_participations(self):
        exist_participation_count = models.Participation.objects.count()
        factories.ParticipationFactory.create_batch(4)
        self.assertEqual(
            models.Participation.objects.count(),
            exist_participation_count+4)

    def test_create_gopp(self):
        gopp = factories.GradingOpportunityFactory()
        self.assertEqual(
            gopp.flow_id, models.GradingOpportunity.objects.first().flow_id)

    def test_create_flow_sessions(self):
        exist_flowsession_count = models.FlowSession.objects.count()
        participations = factories.ParticipationFactory.create_batch(10)
        for p in participations:
            factories.FlowSessionFactory.create(participation=p)
        self.assertEqual(models.FlowSession.objects.count(),
                         exist_flowsession_count+10)


class TaskTestMixin(object):
    """
    This test is actually testing without celery dependency.
    """
    @classmethod
    def setUpClass(cls):  # noqa
        super(TaskTestMixin, cls).setUpClass()
        cls.update_state_patcher = mock.patch(
            "celery.app.task.Task.update_state", side_effect=mock.MagicMock)
        cls.update_state_patcher.start()

    def setUp(self):
        super(TaskTestMixin, self).setUp()

        # Emulates the behavior of AsyncResult
        if is_celery_4_or_higher:
            override_settings_kwargs = {"task_always_eager": True}
        else:
            override_settings_kwargs = {"CELERY_TASK_ALWAYS_EAGER": True}
        celery_fake_overriding = (
            override_settings(**override_settings_kwargs))
        celery_fake_overriding.enable()
        self.addCleanup(celery_fake_overriding.disable)

    @classmethod
    def tearDownClass(cls):  # noqa
        super(TaskTestMixin, cls).tearDownClass()
        cls.update_state_patcher.stop()


class GradesTasksTestSetUpMixin(object):
    def create_flow_sessions(self, course,
                             n_participations_per_course=5,
                             n_in_progress_sessions_per_participation=1,
                             n_ended_sessions_per_participation=3):
        """
        Create multiple flow_sessions with a single gopp
        :param course::class:`Course`
        :param n_participations_per_course: number of participation created for
        each course
        :param n_in_progress_sessions_per_participation: number of in_progress
        sessions created for each participation
        :param n_ended_sessions_per_participation: number of ended sessions
        created for each participation
        """

        self.gopp = factories.GradingOpportunityFactory(course=course)
        participations = factories.ParticipationFactory.create_batch(
            n_participations_per_course)

        for i, p in enumerate(participations):
            factories.FlowSessionFactory.create_batch(
                size=n_in_progress_sessions_per_participation,
                participation=p)
            factories.FlowSessionFactory.create_batch(
                size=n_ended_sessions_per_participation,
                participation=p,
                in_progress=True)

        all_sessions = models.FlowSession.objects.all()
        self.all_sessions_count = all_sessions.count()
        self.in_progress_sessions = list(all_sessions.filter(in_progress=True))
        self.ended_sessions = list(all_sessions.filter(in_progress=False))
        self.in_progress_sessions_count = len(self.in_progress_sessions)
        self.ended_sessions_count = len(self.ended_sessions)


class GradesTasksTest(SingleCourseTestMixin, GradesTasksTestSetUpMixin,
                      TaskTestMixin, TestCase):

    def setUp(self):
        super(GradesTasksTest, self).setUp()
        self.create_flow_sessions(self.course)

        # reset the user_name format sequence
        self.addCleanup(factories.UserFactory.reset_sequence)

    # {{{ test expire_in_progress_sessions
    def test_expire_in_progress_sessions_past_due_only_due_none(self):
        # grading_rule.due is None
        expire_in_progress_sessions(
            self.gopp.course.id, self.gopp.flow_id,
            rule_tag=None, now_datetime=now(),
            past_due_only=True)

        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=True).count(),
            self.in_progress_sessions_count)

        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=False).count(),
            self.ended_sessions_count)

    def test_expire_in_progress_sessions_past_due_only_dued(self):
        # now_datetime > grading_rule.due
        with mock.patch("course.flow.get_session_grading_rule") as \
                mock_get_grading_rule:
            mock_get_grading_rule.side_effect = (
                get_session_grading_rule_1_day_due_side_effect)
            expire_in_progress_sessions(
                self.gopp.course.id, self.gopp.flow_id,
                rule_tag=None, now_datetime=now()+timedelta(days=3),
                past_due_only=True)

        # no in_progress sessions
        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=True).count(),
            0)

        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=False).count(),
            self.all_sessions_count)

    def test_expire_in_progress_sessions_past_due_only_not_dued(self):
        # now_datetime <= grading_rule.due
        with mock.patch("course.flow.get_session_grading_rule") as \
                mock_get_grading_rule:
            mock_get_grading_rule.side_effect = (
                get_session_grading_rule_1_day_due_side_effect)

            expire_in_progress_sessions(
                self.gopp.course.id, self.gopp.flow_id,
                rule_tag=None, now_datetime=now(),
                past_due_only=True)

        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=True).count(),
            self.in_progress_sessions_count)

        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=False).count(),
            self.ended_sessions_count)

    def test_expire_in_progress_sessions_all(self):
        expire_in_progress_sessions(
            self.gopp.course.id, self.gopp.flow_id,
            rule_tag=None, now_datetime=now(),
            past_due_only=False)

        # no in_progress sessions
        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=True).count(),
            0)

        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=False).count(),
            self.all_sessions_count)

    # }}}

    # {{{ test finish_in_progress_sessions

    def test_finish_in_progress_sessions_past_due_only_due_none(self):
        # grading_rule.due is None
        finish_in_progress_sessions(
            self.gopp.course_id, self.gopp.flow_id,
            rule_tag=None, now_datetime=now(),
            past_due_only=True
        )
        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=True).count(),
            self.in_progress_sessions_count)

        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=False).count(),
            self.ended_sessions_count)

        self.assertEqual(
            models.FlowPageVisitGrade.objects.count(), 0
        )

    def test_finish_in_progress_sessions_past_due_only_dued(self):
        # now_datetime > grading_rule.due
        with mock.patch("course.flow.get_session_grading_rule") as \
                mock_get_grading_rule:
            mock_get_grading_rule.side_effect = (
                get_session_grading_rule_1_day_due_side_effect)
            finish_in_progress_sessions(
                self.gopp.course_id, self.gopp.flow_id,
                rule_tag=None, now_datetime=now()+timedelta(days=3),
                past_due_only=True
            )

        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=True).count(),
            0)

        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=False).count(),
            self.all_sessions_count)

        self.assertEqual(
            models.FlowPageVisitGrade.objects.filter(
                visit__flow_session__in=self.ended_sessions).count(),
            0
        )

        for ended_session in self.in_progress_sessions:
            self.assertTrue(
                models.FlowPageVisitGrade.objects.filter(
                    visit__flow_session=ended_session).count() > 0
            )

    def test_finish_in_progress_sessions_past_due_only_not_dued(self):
        # now_datetime < grading_rule.due
        with mock.patch("course.flow.get_session_grading_rule") as \
                mock_get_grading_rule:
            mock_get_grading_rule.side_effect = (
                get_session_grading_rule_1_day_due_side_effect)
            finish_in_progress_sessions(
                self.gopp.course_id, self.gopp.flow_id,
                rule_tag=None, now_datetime=now(),
                past_due_only=True
            )

        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=True).count(),
            self.in_progress_sessions_count)

        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=False).count(),
            self.ended_sessions_count)

        self.assertEqual(
            models.FlowPageVisitGrade.objects.count(), 0
        )

    def test_finish_in_progress_sessions_all(self):
        finish_in_progress_sessions(
            self.gopp.course_id, self.gopp.flow_id,
            rule_tag=None, now_datetime=now(),
            past_due_only=False
        )
        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=True).count(),
            0)

        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=False).count(),
            self.all_sessions_count)

        self.assertEqual(
            models.FlowPageVisitGrade.objects.filter(
                visit__flow_session__in=self.ended_sessions).count(),
            0
        )

        # each ended sessions in this operation got page grades
        for session in self.in_progress_sessions:
            self.assertTrue(
                models.FlowPageVisitGrade.objects.filter(
                    visit__flow_session=session).count() > 0
            )

        # each previously ended sessions didn't got page grades
        for session in self.ended_sessions:
            self.assertTrue(
                models.FlowPageVisitGrade.objects.filter(
                    visit__flow_session=session).count() == 0
            )

    # }}}

    # {{{ test recalculate_ended_sessions
    def test_recalculate_ended_sessions(self):
        recalculate_ended_sessions(self.gopp.course_id,
                                   self.gopp.flow_id,
                                   rule_tag=None)

        # because we didn't create grades, this operation will create them first
        first_round_visit_grade_count = models.FlowPageVisitGrade.objects.count()
        self.assertTrue(first_round_visit_grade_count > 0)

        # second round
        recalculate_ended_sessions(self.gopp.course_id,
                                   self.gopp.flow_id,
                                   rule_tag=None)
        # count of page regrade won't increase
        self.assertEqual(
            models.FlowPageVisitGrade.objects.count(), first_round_visit_grade_count
        )

    # }}}

    # {{{ test regrade_flow_sessions
    def test_recalculate_ended_sessions_not_in_progress_only(self):
        regrade_flow_sessions(self.gopp.course_id,
                              self.gopp.flow_id,
                              access_rules_tag=None,
                              inprog_value=False
                              )

        # each previously ended session got page regrades
        for session in self.ended_sessions:
            self.assertTrue(
                models.FlowPageVisitGrade.objects.filter(
                    visit__flow_session=session).count() > 0
            )

        first_round_visit_grade_count = models.FlowPageVisitGrade.objects.count()
        regrade_flow_sessions(self.gopp.course_id,
                              self.gopp.flow_id,
                              access_rules_tag=None,
                              inprog_value=False
                              )

        # number of visit grades increased
        self.assertTrue(models.FlowPageVisitGrade.objects.count()
                        > first_round_visit_grade_count)

    def test_recalculate_ended_sessions_in_progress_only(self):
        regrade_flow_sessions(self.gopp.course_id,
                              self.gopp.flow_id,
                              access_rules_tag=None,
                              inprog_value=True
                              )

        # ended session should not have page regrades
        self.assertTrue(
            models.FlowPageVisitGrade.objects.filter(
                visit__flow_session__in=self.ended_sessions).count() == 0
        )

        # in-progress session got no page regrades, because we didn't
        # submit a page
        self.assertTrue(
            models.FlowPageVisitGrade.objects.filter(
                visit__flow_session__in=self.in_progress_sessions).count() == 0
        )

    def test_recalculate_ended_sessions_all(self):
        # inprog_value=None means "any" page will be regraded disregard whether
        # the session is in-progress
        regrade_flow_sessions(self.gopp.course_id,
                              self.gopp.flow_id,
                              access_rules_tag=None,
                              inprog_value=None
                              )

        # each ended session got not page regrades
        self.assertTrue(
            models.FlowPageVisitGrade.objects.filter(
                visit__flow_session__in=self.ended_sessions).count() > 0
        )

        # each in-progress session also got no page regrades
        self.assertTrue(
            models.FlowPageVisitGrade.objects.filter(
                visit__flow_session__in=self.in_progress_sessions).count() == 0
        )
    # }}}


class PurgePageViewDataTaskTestSetUpMixin(object):
    def create_flow_page_visit(self, course,
                               n_participations_per_course=5,
                               n_sessions_per_participation=1,
                               n_null_answer_visits_per_session=5,
                               n_non_null_answer_visits_per_session=3):
        """
        :param course::class:`Course`
        :param n_participations_per_course: number of participation created for
        each course
        :param n_sessions_per_participation: number of session created for
        each participation
        :param n_null_answer_visits_per_session: number of flowpagevisit, which does
        not have an answer, created for each session
        :param n_non_null_answer_visits_per_session: number of flowpagevisit, which
        has an answer, created for each session
        :return::class:`Tuple`: number of all flow_page_visits, number of null
        answer flow_page_visits, and number of non-null answer flow_page_visits.
        """
        my_course = factories.CourseFactory(identifier=course.identifier)
        participations = factories.ParticipationFactory.create_batch(
            size=n_participations_per_course, course=my_course)
        for participation in participations:
            flow_sessions = factories.FlowSessionFactory.create_batch(
                size=n_sessions_per_participation, participation=participation)
            for flow_session in flow_sessions:
                null_anaswer_fpds = factories.FlowPageDataFactory.create_batch(
                    size=n_null_answer_visits_per_session, flow_session=flow_session
                )
                for fpd in null_anaswer_fpds:
                    factories.FlowPageVisitFactory.create(page_data=fpd)
                non_null_anaswer_fpds = factories.FlowPageDataFactory.create_batch(
                    size=n_non_null_answer_visits_per_session,
                    flow_session=flow_session
                )
                for fpd in non_null_anaswer_fpds:
                    factories.FlowPageVisitFactory.create(
                        page_data=fpd,
                        answer={"answer": "abcd"})

        n_null_answer_fpv = (
                n_participations_per_course
                * n_sessions_per_participation
                * n_null_answer_visits_per_session)

        n_non_null_answer_fpv = (
                n_participations_per_course
                * n_sessions_per_participation
                * n_non_null_answer_visits_per_session)

        n_all_fpv = n_null_answer_fpv + n_non_null_answer_fpv

        return n_all_fpv, n_null_answer_fpv, n_non_null_answer_fpv


class PurgePageViewDataTaskTest(TwoCoursePageTestMixin,
                                PurgePageViewDataTaskTestSetUpMixin, TaskTestMixin,
                                TestCase):
    """ test purge_page_view_data
    """

    courses_setup_list = PURGE_VIEW_TWO_COURSE_SETUP_LIST

    def setUp(self):
        super(PurgePageViewDataTaskTest, self).setUp()

        # {{{ create flow page visits
        # all 40, null answer 25, answerd 15
        result1 = self.create_flow_page_visit(self.course1)

        (self.course1_n_all_fpv, self.course1_n_null_answer_fpv,
         self.course1_n_non_null_answer_fpv) = result1

        # all 30, null answer 24, answerd 6
        result2 = self.create_flow_page_visit(
            self.course2,
            n_participations_per_course=3, n_sessions_per_participation=2,
            n_null_answer_visits_per_session=4,
            n_non_null_answer_visits_per_session=1)

        (self.course2_n_all_fpv, self.course2_n_null_answer_fpv,
         self.course2_n_non_null_answer_fpv) = result2

    # }}}

        # reset the user_name format sequence
        self.addCleanup(factories.UserFactory.reset_sequence)

    def test_purge_page_view_data(self):
        purge_page_view_data(self.course1.pk)

        # Expected counts of course 1
        self.assertEqual(
            models.FlowPageVisit.objects.filter(
                flow_session__course=self.course1).count(),
            self.course1_n_non_null_answer_fpv
        )
        self.assertEqual(
            models.FlowPageVisit.objects.filter(
                flow_session__course=self.course1,
                answer__isnull=True,
            ).count(),
            0
        )

        # Counts for course 2 are not affected
        self.assertEqual(
            models.FlowPageVisit.objects.filter(
                flow_session__course=self.course2).count(),
            self.course2_n_all_fpv
        )
        self.assertEqual(
            models.FlowPageVisit.objects.filter(
                flow_session__course=self.course2,
                answer__isnull=True,
            ).count(),
            self.course2_n_null_answer_fpv
        )
    # }}}


class TasksTestsWithCeleryDependency(SingleCourseTestMixin, TestCase):
    """
    This test involves celery. However, Django's sqlite3 is an in-memory database,
    and Celery is started in a separate process, it is fundamentally impossible
    to have Celery and Django to share a test database. In this tests, we only
    test that the serialization is working. The results are checked in other tests
    with settings.CELERY_TASK_ALWAYS_EAGER=True.
    """

    flow_id = "quiz-test"

    def test_expire_in_progress_sessions(self):
        with mock.patch("course.tasks.Course.objects.get")\
                as mock_course_object_get:

            # This is to avoid errors
            mock_course_object_get.return_value = self.course

            expire_in_progress_sessions(
                self.course.pk, self.flow_id,
                rule_tag=None, now_datetime=now(),
                past_due_only=True
            )
            mock_course_object_get.assert_called_once_with(id=self.course.pk)

    def test_finish_in_progress_sessions(self):
        with mock.patch("course.tasks.Course.objects.get")\
                as mock_course_object_get:

            # This is to avoid errors
            mock_course_object_get.return_value = self.course

            finish_in_progress_sessions(
                self.course.pk, self.flow_id,
                rule_tag=None, now_datetime=now(),
                past_due_only=True
            )
            mock_course_object_get.assert_called_once_with(id=self.course.pk)

    def test_regrade_flow_sessions(self):
        with mock.patch("course.tasks.Course.objects.get")\
                as mock_course_object_get:

            # This is to avoid errors
            mock_course_object_get.return_value = self.course

            regrade_flow_sessions(
                self.course.pk, self.flow_id,
                access_rules_tag=None, inprog_value=None
            )
            mock_course_object_get.assert_called_once_with(id=self.course.pk)

    def test_recalculate_ended_sessions(self):
        with mock.patch("course.tasks.Course.objects.get")\
                as mock_course_object_get:

            # This is to avoid errors
            mock_course_object_get.return_value = self.course

            recalculate_ended_sessions(
                self.course.pk, self.flow_id, rule_tag=None
            )
            mock_course_object_get.assert_called_once_with(id=self.course.pk)

    def test_purge_page_view_data(self):
        with mock.patch("course.tasks.Course.objects.get") \
                as mock_course_object_get:

            # This is to avoid errors
            mock_course_object_get.return_value = self.course

            purge_page_view_data(self.course.pk)
            mock_course_object_get.assert_called_once_with(id=self.course.pk)

# vim: foldmethod=marker
