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
from django.test import TestCase, override_settings, mock
from .base_test_mixins import (
    SingleCourseTestMixin)
from course import models
from . import factories


from course.tasks import (  # noqa
    expire_in_progress_sessions,
    finish_in_progress_sessions,
    regrade_flow_sessions,
    recalculate_ended_sessions)


def check_celery_version():
    from pkg_resources import parse_version
    import celery
    celery_version_upbound = "4.0.0"
    if parse_version(celery.__version__) >= parse_version(celery_version_upbound):
        raise RuntimeError(
            "This test is not expected to work for "
            "celery version >= %s" % celery_version_upbound)


check_celery_version()


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


class GradesTasksTest(SingleCourseTestMixin, TestCase):
    @classmethod
    def setUpClass(cls):  # noqa
        super(GradesTasksTest, cls).setUpClass()
        cls.update_state_patcher = mock.patch(
            "celery.app.task.Task.update_state", side_effect=mock.MagicMock)
        cls.update_state_patcher.start()

    @classmethod
    def tearDownClass(cls):  # noqa
        super(GradesTasksTest, cls).tearDownClass()
        cls.update_state_patcher.stop()

    def setUp(self):
        super(GradesTasksTest, self).setUp()
        self.gopp = factories.GradingOpportunityFactory()
        participations = factories.ParticipationFactory.create_batch(5)

        for i, p in enumerate(participations):
            factories.FlowSessionFactory.create(participation=p)
            if i < 3:
                factories.FlowSessionFactory.create(participation=p,
                                                    in_progress=True)

        all_sessions = models.FlowSession.objects.all()
        self.all_sessions_count = all_sessions.count()
        self.in_progress_sessions = list(all_sessions.filter(in_progress=True))
        self.ended_sessions = list(all_sessions.filter(in_progress=False))
        self.in_progress_sessions_count = len(self.in_progress_sessions)
        self.ended_sessions_count = len(self.ended_sessions)

        assert self.in_progress_sessions_count == 3
        assert self.ended_sessions_count == 5

    # {{{ test expire_in_progress_sessions
    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
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

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
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

        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=True).count(),
            0)

        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=False).count(),
            self.all_sessions_count)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
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

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_expire_in_progress_sessions_all(self):
        expire_in_progress_sessions(
            self.gopp.course.id, self.gopp.flow_id,
            rule_tag=None, now_datetime=now(),
            past_due_only=False)
        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=True).count(),
            0)

        self.assertEqual(
            models.FlowSession.objects.filter(in_progress=False).count(),
            self.all_sessions_count)

    # }}}

# vim: foldmethod=marker
