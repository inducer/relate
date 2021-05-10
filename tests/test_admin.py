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

from django.test import TestCase, RequestFactory
from django.contrib.admin import site
from django.utils.timezone import now
import pytest

from course import models, admin, constants

from tests.base_test_mixins import AdminTestMixin
from tests import factories
from tests.constants import QUIZ_FLOW_ID


class CourseAdminTestMixin(AdminTestMixin):
    @classmethod
    def get_admin_course_change_list_view_url(cls, model_name):
        return super().get_admin_change_list_view_url(
            app_name="course", model_name=model_name.lower())

    @classmethod
    def get_admin_course_add_view_url(cls, model_name):
        return super().get_admin_add_view_url(
            app_name="course", model_name=model_name.lower())

    @classmethod
    def get_admin_course_change_view_url(cls, model_name, args=None):
        return super().get_admin_change_view_url(
            app_name="course", model_name=model_name.lower(), args=args)

    def setUp(self):
        super().setUp()
        self.superuser.refresh_from_db()
        self.rf = RequestFactory()

    def navigate_admin_view_by_model(
            self, model_class, with_add_view=True, with_change_view=True):
        for user in [self.superuser, self.instructor1, self.instructor2]:
            with self.temporarily_switch_to_user(user):
                resp = self.client.get(self.get_admin_course_change_list_view_url(
                    model_class.__name__))
                self.assertEqual(resp.status_code, 200)

                if with_add_view:
                    resp = self.client.get(
                        self.get_admin_course_add_view_url(model_class.__name__))
                    self.assertIn(resp.status_code, [200, 403])  # 403 for not implemented  # noqa

                if with_change_view:
                    resp = self.client.get(
                        self.get_admin_course_change_view_url(
                            model_class.__name__, args=[1]))
                    self.assertIn(resp.status_code, [200, 302])  # 302 for no objects  # noqa

    def list_filter_result(self, model_class, model_admin_class,
                           expected_counts_dict):
        modeladmin = model_admin_class(model_class, site)

        for user in [self.superuser, self.instructor1, self.instructor2]:
            with self.subTest(user=user):
                request = self.rf.get(
                    self.get_admin_course_change_list_view_url(
                        model_class.__name__), {})
                request.user = user
                changelist = self.get_changelist(request, model_class, modeladmin)

                filterspec_list = self.get_filterspec_list(request, changelist)
                queryset = changelist.get_queryset(request)

                if request.user == self.superuser:
                    self.assertIn(
                        ('All', self.course1.identifier, self.course2.identifier),
                        filterspec_list)
                    self.assertEqual(queryset.count(), expected_counts_dict["all"])
                elif request.user == self.instructor1:
                    self.assertNotIn(
                        ('All', self.course1.identifier, self.course2.identifier),
                        filterspec_list)
                    self.assertNotIn(
                        ('All', self.course2.identifier), filterspec_list)
                    self.assertNotIn(
                        (self.course2.identifier, ), filterspec_list)
                    self.assertEqual(queryset.count(),
                                     expected_counts_dict["course1"])
                else:
                    assert request.user == self.instructor2
                    self.assertNotIn(
                        ('All', self.course1.identifier, self.course2.identifier),
                        filterspec_list)
                    self.assertNotIn(
                        ('All', self.course1.identifier), filterspec_list)
                    self.assertNotIn(
                        (self.course1.identifier, ), filterspec_list)
                    self.assertEqual(queryset.count(),
                                     expected_counts_dict["course2"])


@pytest.mark.slow
class CourseAdminGenericTest(CourseAdminTestMixin, TestCase):

    def test_course(self):
        # todo: make assertion
        self.navigate_admin_view_by_model(models.Course)

    def test_event_filter_result(self):
        factories.EventFactory.create(
            course=self.course1, kind="course1_kind")
        course1_event_count = 1

        course2_events = factories.EventFactory.create_batch(
            size=5, course=self.course2, kind="course2_kind")
        course2_event_count = len(course2_events)

        self.navigate_admin_view_by_model(models.Event)
        self.list_filter_result(
            models.Event, admin.EventAdmin,
            expected_counts_dict={
                "all": (course1_event_count + course2_event_count),
                "course1": course1_event_count,
                "course2": course2_event_count
            })

    def test_participation_filter_result(self):
        self.navigate_admin_view_by_model(models.Participation)
        self.list_filter_result(
            models.Participation, admin.ParticipationAdmin,
            expected_counts_dict={
                "all": models.Participation.objects.count(),
                "course1":
                    models.Participation.objects.filter(course=self.course1).count(),
                "course2":
                    models.Participation.objects.filter(course=self.course2).count(),
            })

    def test_participation_tag(self):
        self.navigate_admin_view_by_model(
            models.ParticipationTag)

    def test_participation_role(self):
        self.navigate_admin_view_by_model(
            models.ParticipationRole)

    def test_flow_rule_exception(self):
        factories.FlowRuleExceptionFactory(
            participation=self.course2_student_participation)
        self.navigate_admin_view_by_model(models.FlowRuleException)

    def test_instant_message(self):
        factories.InstantMessageFactory(
            participation=self.course1_student_participation)
        self.navigate_admin_view_by_model(models.InstantMessage)

    def test_instant_flow_request(self):
        self.navigate_admin_view_by_model(models.InstantFlowRequest)

    def test_exam(self):
        factories.ExamFactory(course=self.course1)
        self.navigate_admin_view_by_model(models.Exam)


class CourseAdminSessionRelatedMixin(CourseAdminTestMixin):
    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()

        course1_session = factories.FlowSessionFactory.create(
            participation=cls.course1_student_participation2,
            flow_id="001-linalg-recap")
        course1_flow_page_data = factories.FlowPageDataFactory.create(
            flow_session=course1_session)
        factories.FlowPageVisitFactory.create(page_data=course1_flow_page_data)

        course2_sessions = factories.FlowSessionFactory.create_batch(
            size=3, participation=cls.course2_student_participation)
        cls.course2_session4 = factories.FlowSessionFactory(
            course=cls.course2, participation=None, user=None)

        for session in course2_sessions:
            course2_flow_page_data = factories.FlowPageDataFactory.create(
                flow_session=session,
            )
            factories.FlowPageVisitFactory.create(
                page_data=course2_flow_page_data, answer={"answer": "hi"})

        # a flow session without page_ordinal
        course2_non_ordinal_flow_page_data = factories.FlowPageDataFactory(
            flow_session=cls.course2_session4, page_ordinal=None)
        factories.FlowPageVisitFactory(page_data=course2_non_ordinal_flow_page_data)

        course1_sessions = models.FlowSession.objects.filter(
            course=cls.course1)
        cls.course1_session_count = course1_sessions.count()
        course1_visits = models.FlowPageVisit.objects.filter(
            flow_session__course=cls.course1)
        cls.course1_visits_count = course1_visits.count()
        cls.course1_visits_has_answer_count = course1_visits.filter(
            answer__isnull=False).count()

        cls.course2_sessions = models.FlowSession.objects.filter(course=cls.course2)
        cls.course2_session_count = cls.course2_sessions.count()
        course2_visits = models.FlowPageVisit.objects.filter(
            flow_session__course=cls.course2)
        cls.course2_visits_count = course2_visits.count()
        cls.course2_visits_has_answer_count = course2_visits.filter(
            answer__isnull=False).count()


@pytest.mark.slow
class CourseAdminSessionRelatedTest(CourseAdminSessionRelatedMixin, TestCase):
    def test_flowsession_filter_result(self):
        self.navigate_admin_view_by_model(models.FlowSession)
        self.list_filter_result(
            models.FlowSession, admin.FlowSessionAdmin,
            expected_counts_dict={
                "all": (self.course1_session_count + self.course2_session_count),
                "course1": self.course1_session_count,
                "course2": self.course2_session_count
            })

    def test_grading_opportunity(self):
        self.navigate_admin_view_by_model(models.GradingOpportunity)

    def test_flowpagevisit_filter_result(self):
        self.navigate_admin_view_by_model(models.FlowPageVisit)
        self.list_filter_result(
            models.FlowPageVisit, admin.FlowPageVisitAdmin,
            expected_counts_dict={
                "all": self.course1_visits_count + self.course2_visits_count,
                "course1": self.course1_visits_count,
                "course2": self.course2_visits_count
            })

    def test_flowpagevisit_flow_id_filter_result(self):
        modeladmin = admin.FlowPageVisitAdmin(models.FlowPageVisit, site)

        for user in [self.superuser, self.instructor1, self.instructor2]:
            with self.subTest(user=user):
                request = self.rf.get(
                    self.get_admin_course_change_list_view_url("FlowPageVisit"), {})
                request.user = user
                changelist = self.get_changelist(
                    request, models.FlowPageVisit, modeladmin)

                filterspec_list = self.get_filterspec_list(request, changelist)

                if request.user == self.superuser:
                    self.assertIn(
                        ('All', "001-linalg-recap", QUIZ_FLOW_ID),
                        filterspec_list)
                elif request.user == self.instructor1:
                    self.assertNotIn(
                        ('All', "001-linalg-recap", QUIZ_FLOW_ID),
                        filterspec_list)
                    self.assertNotIn(
                        ('All', QUIZ_FLOW_ID), filterspec_list)
                    self.assertNotIn(
                        (QUIZ_FLOW_ID,), filterspec_list)
                else:
                    assert request.user == self.instructor2
                    self.assertNotIn(
                        ('All', "001-linalg-recap", QUIZ_FLOW_ID),
                        filterspec_list)
                    self.assertNotIn(
                        ('All', "001-linalg-recap"), filterspec_list)
                    self.assertNotIn(
                        ("001-linalg-recap",), filterspec_list)

    def test_flowpagevisit_get_queryset_by_flow_id_filter(self):
        modeladmin = admin.FlowPageVisitAdmin(models.FlowPageVisit, site)

        request = self.rf.get(
            self.get_admin_course_change_list_view_url("FlowPageVisit"),
            {"flow_id": "001-linalg-recap"})
        request.user = self.instructor1
        changelist = self.get_changelist(
            request, models.FlowPageVisit, modeladmin)

        queryset = changelist.get_queryset(request)
        self.assertEqual(queryset.count(), self.course1_visits_count)

    def test_flowpagevisit_get_queryset_by_has_answer_list_filter(self):
        modeladmin = admin.FlowPageVisitAdmin(models.FlowPageVisit, site)

        request = self.rf.get(
            self.get_admin_course_change_list_view_url("FlowPageVisit"),
            {"has_answer": "y"})
        request.user = self.instructor1
        changelist = self.get_changelist(
            request, models.FlowPageVisit, modeladmin)

        queryset = changelist.get_queryset(request)
        self.assertEqual(queryset.count(), self.course1_visits_has_answer_count)

        request.user = self.instructor2
        changelist = self.get_changelist(
            request, models.FlowPageVisit, modeladmin)
        queryset = changelist.get_queryset(request)
        self.assertEqual(queryset.count(), self.course2_visits_has_answer_count)


@pytest.mark.slow
class ParticipationAdminTest(CourseAdminTestMixin, TestCase):
    def test_approve_enrollment(self):
        active = factories.ParticipationFactory(
            course=self.course1,
            status=constants.participation_status.active)
        (requested1, requested2) = factories.ParticipationFactory.create_batch(
            size=2,
            course=self.course1,
            status=constants.participation_status.requested)

        from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
        action_data = {
            ACTION_CHECKBOX_NAME: [active.pk, requested1.pk],
            'action': "approve_enrollment",
            'index': 0,
        }
        with self.temporarily_switch_to_user(self.instructor1):
            resp = self.client.post(
                self.get_admin_course_change_list_view_url(
                    models.Participation.__name__), action_data)
            self.assertEqual(resp.status_code, 302)

        active.refresh_from_db()
        self.assertEqual(active.status, constants.participation_status.active)
        requested1.refresh_from_db()
        self.assertEqual(requested1.status, constants.participation_status.active)
        requested2.refresh_from_db()
        self.assertEqual(requested2.status, constants.participation_status.requested)

    def test_deny_enrollment(self):
        active = factories.ParticipationFactory(
            course=self.course1,
            status=constants.participation_status.active)
        (requested1, requested2) = factories.ParticipationFactory.create_batch(
            size=2,
            course=self.course1,
            status=constants.participation_status.requested)

        from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
        action_data = {
            ACTION_CHECKBOX_NAME: [active.pk, requested1.pk, requested2.pk],
            'action': "deny_enrollment",
            'index': 0,
        }
        with self.temporarily_switch_to_user(self.instructor1):
            resp = self.client.post(
                self.get_admin_course_change_list_view_url(
                    models.Participation.__name__), action_data)
            self.assertEqual(resp.status_code, 302)

        active.refresh_from_db()
        self.assertEqual(active.status, constants.participation_status.active)
        requested1.refresh_from_db()
        self.assertEqual(requested1.status, constants.participation_status.denied)
        requested2.refresh_from_db()
        self.assertEqual(requested2.status, constants.participation_status.denied)


@pytest.mark.slow
class ParticipationFormTest(CourseAdminTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.test_user = factories.UserFactory()

    def test_clean_success(self):
        data = {
            "user": self.test_user.pk,
            "course": self.course2.pk,
            "status": constants.participation_status.active,
            "enroll_time": now(),
            "time_factor": 1
        }
        form = admin.ParticipationForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_clean_tag_course_matched(self):
        course1_tag = factories.ParticipationTagFactory(course=self.course1)

        data = {
            "user": self.test_user.pk,
            "course": self.course1.pk,
            "status": constants.participation_status.active,
            "enroll_time": now(),
            "time_factor": 1,
            "tags": [course1_tag]
        }
        form = admin.ParticipationForm(data=data)
        self.assertTrue(form.is_valid())

    def test_clean_tag_course_not_match(self):
        course1_tag = factories.ParticipationTagFactory(course=self.course1)

        data = {
            "user": self.test_user.pk,
            "course": self.course2.pk,
            "status": constants.participation_status.active,
            "enroll_time": now(),
            "time_factor": 1,
            "tags": [course1_tag]
        }
        form = admin.ParticipationForm(data=data)
        self.assertFalse(form.is_valid())
        expected_error_msg = "Tags must belong to same course as participation."
        self.assertIn(expected_error_msg, str(form.errors))

    def test_clean_roles_course_matched(self):
        course1_role = factories.ParticipationRoleFactory(course=self.course1)

        data = {
            "user": self.test_user.pk,
            "course": self.course1.pk,
            "status": constants.participation_status.active,
            "enroll_time": now(),
            "time_factor": 1,
            "roles": [course1_role]
        }
        form = admin.ParticipationForm(data=data)
        self.assertTrue(form.is_valid())

    def test_clean_roles_course_not_match(self):
        course1_role = factories.ParticipationRoleFactory(course=self.course1)

        data = {
            "user": self.test_user.pk,
            "course": self.course2.pk,
            "status": constants.participation_status.active,
            "enroll_time": now(),
            "time_factor": 1,
            "roles": [course1_role]
        }
        form = admin.ParticipationForm(data=data)
        self.assertFalse(form.is_valid())
        expected_error_msg = "Role must belong to same course as participation."
        self.assertIn(expected_error_msg, str(form.errors))


@pytest.mark.slow
class ParticipationPreapprovalAdminTest(CourseAdminTestMixin, TestCase):
    def test_participation_preapproval(self):
        factories.ParticipationPreapprovalFactory(course=self.course1)
        self.navigate_admin_view_by_model(models.ParticipationPreapproval)

    def test_save_model(self):
        add_dict = {'institutional_id': '1234',
                    'course': self.course1.pk}
        with self.temporarily_switch_to_user(self.instructor1):
            self.client.post(
                self.get_admin_course_add_view_url(
                    models.ParticipationPreapproval.__name__), add_dict)
        all_objs = models.ParticipationPreapproval.objects
        self.assertEqual(all_objs.count(), 1)
        self.assertEqual(
            all_objs.last().creator, self.course1_instructor_participation.user)


@pytest.mark.slow
class GradeChangeAdminTest(CourseAdminSessionRelatedMixin, TestCase):
    def test_grade_change(self):
        gopp = factories.GradingOpportunityFactory(course=self.course2)

        factories.GradeChangeFactory(
            opportunity=gopp, participation=self.course2_student_participation,
            flow_session=self.course2_sessions[0], points=5)

        # a gchange without percentage
        factories.GradeChangeFactory(
            opportunity=gopp, participation=self.course2_student_participation,
            flow_session=None)

        self.navigate_admin_view_by_model(models.GradeChange)

    def test_save_model(self):
        gopp = factories.GradingOpportunityFactory(course=self.course2)
        add_dict = {
            "opportunity": gopp.pk,
            'participation': self.course2_student_participation.pk,
            'state': constants.grade_state_change_types.graded,
            'attempt_id': "main",
            'max_points': 100,
        }
        with self.temporarily_switch_to_user(self.instructor2):
            self.client.post(
                self.get_admin_course_add_view_url(
                    models.GradeChange.__name__), add_dict)
        all_objs = models.GradeChange.objects
        self.assertEqual(all_objs.count(), 1)
        self.assertEqual(
            all_objs.last().creator, self.course2_instructor_participation.user)


@pytest.mark.slow
class ExamTicketAdminTest(CourseAdminTestMixin, TestCase):
    def setUp(self):
        self.exam = factories.ExamFactory(course=self.course1)

    def test_navigate(self):
        factories.ExamTicketFactory(
            exam=self.exam,
            participation=self.course1_student_participation)
        self.navigate_admin_view_by_model(models.ExamTicket)

    def test_save_model(self):
        add_dict = {
            "exam": self.exam.pk,
            'participation': self.course1_student_participation.pk,
            'state': constants.exam_ticket_states.valid,
            'code': "abcde",
            'creation_time_0': "2019-3-31",
            'creation_time_1': "10:54:39",
        }
        with self.temporarily_switch_to_user(self.instructor1):
            resp = self.client.post(
                self.get_admin_course_add_view_url(
                    models.ExamTicket.__name__), add_dict)
            self.assertEqual(resp.status_code, 302)
        all_objs = models.ExamTicket.objects
        self.assertEqual(all_objs.count(), 1)
        self.assertEqual(
            all_objs.last().creator, self.course1_instructor_participation.user)

    def test_revoke_exam_tickets(self):
        ticket1 = factories.ExamTicketFactory(
            exam=self.exam,
            participation=self.course1_student_participation)
        ticket2 = factories.ExamTicketFactory(
            exam=self.exam,
            participation=self.course1_ta_participation)

        from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
        action_data = {
            ACTION_CHECKBOX_NAME: [ticket1.pk],
            'action': "revoke_exam_tickets",
            'index': 0,
        }
        with self.temporarily_switch_to_user(self.instructor1):
            resp = self.client.post(
                self.get_admin_course_change_list_view_url(
                    models.ExamTicket.__name__), action_data)
            self.assertEqual(resp.status_code, 302)

        ticket1.refresh_from_db()
        self.assertEqual(ticket1.state, constants.exam_ticket_states.revoked)
        ticket2.refresh_from_db()
        self.assertEqual(ticket2.state, constants.exam_ticket_states.valid)

# vim: foldmethod=marker
