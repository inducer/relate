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


from random import shuffle
from django.utils.timezone import now, timedelta
from django.core import mail
from django.test import TestCase, override_settings

from course.models import ParticipationPermission
from course.constants import participation_permission as pperm

from tests.base_test_mixins import SingleCourseQuizPageTestMixin
from tests import factories
from tests.utils import mock


class SingleCourseQuizPageGradeInterfaceTestMixin(SingleCourseQuizPageTestMixin):

    page_id = "anyup"

    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCourseQuizPageGradeInterfaceTestMixin, cls).setUpTestData()
        cls.c.force_login(cls.student_participation.user)
        cls.start_flow(cls.flow_id)
        cls.this_flow_session_id = cls.default_flow_params["flow_session_id"]
        cls.submit_page_answer_by_page_id_and_test(cls.page_id)


class SingleCourseQuizPageGradeInterfaceTest(
        SingleCourseQuizPageGradeInterfaceTestMixin, TestCase):

    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCourseQuizPageGradeInterfaceTest, cls).setUpTestData()

        with cls.temporarily_switch_to_user(cls.student_participation.user):
            # a failure submission
            cls.submit_page_answer_by_page_id_and_test(
                cls.page_id, answer_data={"uploaded_file": []})
            # a success full
            cls.submit_page_answer_by_page_id_and_test(
                cls.page_id,
                do_grading=False)

        cls.end_flow()

    def setUp(self):
        super(SingleCourseQuizPageGradeInterfaceTest, self).setUp()
        self.c.force_login(self.student_participation.user)

    def test_post_grades(self):
        self.submit_page_human_grading_by_page_id_and_test(self.page_id)

        grade_data = {
            "grade_points": "4",
            "released": []
        }
        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data=grade_data, expected_grades=None)

        grade_data = {
            "grade_points": "4",
            "released": "on"
        }
        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data=grade_data, expected_grades=4)

    def test_post_grades_huge_points_failure(self):
        grade_data = {
            "grade_percent": "2000",
            "released": 'on'
        }

        resp = self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data=grade_data, expected_grades=None)

        # value exceeded allowed
        self.assertResponseContextContains(
            resp, "grading_form_html",
            "Ensure this value is less than or equal to")

    def test_post_grades_forbidden(self):
        # with self.student_participation.user logged in
        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, expected_grades=None,
            force_login_instructor=False, expected_post_grading_status_code=403)

    def test_feedback_and_notify(self):
        grade_data_extra_kwargs = {
            "feedback_text": 'test feedback'
        }

        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data_extra_kwargs=grade_data_extra_kwargs)
        self.assertEqual(len(mail.outbox), 0)

        grade_data_extra_kwargs["notify"] = "on"
        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data_extra_kwargs=grade_data_extra_kwargs)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].reply_to, [])

        # Instructor also get the feedback email
        self.assertIn(self.course.notify_email, mail.outbox[0].recipients())

        # make sure the name (appellation) is in the email body, not the masked one
        self.assertIn(
            self.student_participation.user.get_email_appellation(),
            mail.outbox[0].body)
        self.assertNotIn(
            self.student_participation.user.get_masked_profile(),
            mail.outbox[0].body)
        self.assertNotIn(
            "Dear user",
            mail.outbox[0].body)

    def test_feedback_and_notify_instructor_pperm_masked_profile(self):

        # add view_participant_masked_profile pperm to instructor
        pp = ParticipationPermission(
            participation=self.instructor_participation,
            permission=pperm.view_participant_masked_profile
        )
        pp.save()
        self.instructor_participation.individual_permissions.set([pp])

        grade_data_extra_kwargs = {
            "feedback_text": 'test feedback',
            "notify": "on"}
        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data_extra_kwargs=grade_data_extra_kwargs)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].reply_to, [])

        # Instructor also get the feedback email
        self.assertIn(self.course.notify_email, mail.outbox[0].recipients())

        # make sure the name (appellation) not in the email body, not the masked one
        self.assertNotIn(
            self.student_participation.user.get_email_appellation(),
            mail.outbox[0].body)
        self.assertNotIn(
            self.student_participation.user.get_masked_profile(),
            mail.outbox[0].body)
        self.assertIn("Dear user", mail.outbox[0].body)

    @override_settings(
        EMAIL_CONNECTIONS={
            "grader_feedback": {
                'backend': 'tests.resource.MyFakeEmailBackend',
            },
        },
        GRADER_FEEDBACK_EMAIL_FROM="my_feedback_from_email@example.com"
    )
    def test_feedback_notify_with_grader_feedback_connection(self):
        grade_data_extra_kwargs = {
            "feedback_text": 'test feedback',
            "notify": "on"
        }

        from django.core.mail import get_connection
        connection = get_connection(
            backend='django.core.mail.backends.locmem.EmailBackend')

        with mock.patch("django.core.mail.get_connection") as mock_get_connection:
            mock_get_connection.return_value = connection
            self.submit_page_human_grading_by_page_id_and_test(
                self.page_id, grade_data_extra_kwargs=grade_data_extra_kwargs)
            self.assertEqual(len(mail.outbox), 1)
            self.assertEqual(mail.outbox[0].from_email,
                             "my_feedback_from_email@example.com")
            self.assertEqual(
                mock_get_connection.call_args[1]["backend"],
                "tests.resource.MyFakeEmailBackend"
            )

        # make sure the name (appellation) is in the email body, not the masked one
        self.assertIn(
            self.student_participation.user.get_email_appellation(),
            mail.outbox[0].body)
        self.assertNotIn(
            self.student_participation.user.get_masked_profile(),
            mail.outbox[0].body)
        self.assertNotIn(
            "Dear user",
            mail.outbox[0].body)

    def test_feedback_email_may_reply(self):
        grade_data_extra_kwargs = {
            "feedback_text": 'test feedback',
            "may_reply": "on",
            "notify": "on"
        }

        with self.temporarily_switch_to_user(self.ta_participation.user):
            self.submit_page_human_grading_by_page_id_and_test(
                self.page_id, grade_data_extra_kwargs=grade_data_extra_kwargs,
                force_login_instructor=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].reply_to,
                         [self.ta_participation.user.email])

        # Instructor also get the feedback email
        self.assertIn(self.course.notify_email, mail.outbox[0].recipients())

        # make sure the name (appellation) is in the email body, not the masked one
        self.assertIn(
            self.student_participation.user.get_email_appellation(),
            mail.outbox[0].body)
        self.assertNotIn(
            self.student_participation.user.get_masked_profile(),
            mail.outbox[0].body)
        self.assertNotIn(
            "Dear user",
            mail.outbox[0].body)

    def test_notes_and_notify(self):
        grade_data_extra_kwargs = {
            "notes": 'test notes'
        }

        with self.temporarily_switch_to_user(self.ta_participation.user):
            self.submit_page_human_grading_by_page_id_and_test(
                self.page_id, grade_data_extra_kwargs=grade_data_extra_kwargs,
                force_login_instructor=False)
            self.assertEqual(len(mail.outbox), 0)

            grade_data_extra_kwargs["notify_instructor"] = "on"
            self.submit_page_human_grading_by_page_id_and_test(
                self.page_id, grade_data_extra_kwargs=grade_data_extra_kwargs,
                force_login_instructor=False)
            self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.course.notify_email, mail.outbox[0].recipients())

        # make sure the name (appellation) is in the email body, not the masked one
        self.assertIn(
            self.student_participation.user.get_email_appellation(),
            mail.outbox[0].body)
        self.assertNotIn(
            self.student_participation.user.get_masked_profile(),
            mail.outbox[0].body)

    def test_notes_and_notify_ta_pperm_masked_profile(self):

        # add view_participant_masked_profile pperm to ta
        pp = ParticipationPermission(
            participation=self.ta_participation,
            permission=pperm.view_participant_masked_profile
        )
        pp.save()
        self.ta_participation.individual_permissions.set([pp])

        grade_data_extra_kwargs = {
            "notes": 'test notes',
            "notify_instructor": "on"}

        with self.temporarily_switch_to_user(self.ta_participation.user):
            self.submit_page_human_grading_by_page_id_and_test(
                self.page_id, grade_data_extra_kwargs=grade_data_extra_kwargs,
                force_login_instructor=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.course.notify_email, mail.outbox[0].recipients())

        # make sure the name (appellation) not in the email body,
        # the masked one is used instead
        self.assertNotIn(
            self.student_participation.user.get_email_appellation(),
            mail.outbox[0].body)
        self.assertIn(
            self.student_participation.user.get_masked_profile(),
            mail.outbox[0].body)

    @override_settings(
        EMAIL_CONNECTIONS={
            "grader_feedback": {
                'backend': 'tests.resource.MyFakeEmailBackend',
            },
        },
        GRADER_FEEDBACK_EMAIL_FROM="my_feedback_from_email@example.com"
    )
    def test_notes_and_notify_with_grader_feedback_connection(self):
        grade_data_extra_kwargs = {
            "notes": 'test notes',
            "notify_instructor": "on"
        }

        from django.core.mail import get_connection
        connection = get_connection(
            backend='django.core.mail.backends.locmem.EmailBackend')

        with mock.patch("django.core.mail.get_connection") as mock_get_connection:
            mock_get_connection.return_value = connection
            with self.temporarily_switch_to_user(self.ta_participation.user):
                self.submit_page_human_grading_by_page_id_and_test(
                    self.page_id, grade_data_extra_kwargs=grade_data_extra_kwargs,
                    force_login_instructor=False)

            self.assertEqual(len(mail.outbox), 1)

        self.assertIn(self.course.notify_email, mail.outbox[0].recipients())
        self.assertEqual(mail.outbox[0].from_email,
                         "my_feedback_from_email@example.com")
        self.assertEqual(
            mock_get_connection.call_args[1]["backend"],
            "tests.resource.MyFakeEmailBackend"
        )

        # make sure the name (appellation) is in the email body, not the masked one
        self.assertIn(
            self.student_participation.user.get_email_appellation(),
            mail.outbox[0].body)
        self.assertNotIn(
            self.student_participation.user.get_masked_profile(),
            mail.outbox[0].body)

    # {{{ test grading.get_prev_grades_dropdown_content
    def test_grade_history_failure_no_perm(self):
        resp = self.c.get(
            self.get_page_grade_history_url_by_ordinal(
                page_ordinal=1), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 403)

    def test_grade_history_failure_not_ajax(self):
        resp = self.c.get(
            self.get_page_grade_history_url_by_ordinal(
                page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    def test_submit_history_failure_not_get(self):
        resp = self.c.post(
            self.get_page_grade_history_url_by_ordinal(
                page_ordinal=1), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 403)

    def test_grade_history_failure_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.c.get(
                self.get_page_grade_history_url_by_ordinal(
                    page_ordinal=1), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 403)

    def test_grades_history_after_graded(self):
        self.submit_page_human_grading_by_page_id_and_test(self.page_id)

        ordinal = self.get_page_ordinal_via_page_id(self.page_id)
        self.assertGradeHistoryItemsCount(page_ordinal=ordinal, expected_count=3)

        grade_data = {
            "grade_points": "4",
            "released": []
        }
        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data=grade_data, expected_grades=None)
        self.assertGradeHistoryItemsCount(page_ordinal=ordinal, expected_count=4)

        grade_data = {
            "grade_points": "4",
            "released": "on"
        }
        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data=grade_data, expected_grades=4)
        self.assertGradeHistoryItemsCount(page_ordinal=ordinal,
                                          expected_count=5)

    # }}}

    # {{{ test grade_flow_page (for cases not covered by other tests)

    # {{{ prev_grade
    def test_viewing_prev_grade_id_not_exist(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(
                self.get_page_grading_url_by_page_id(self.page_id)
                + "?grade_id=1000")
            self.assertEqual(resp.status_code, 404)

    def test_viewing_prev_grade_id_not_int(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(
                self.get_page_grading_url_by_page_id(self.page_id)
                + "?grade_id=my_id")
            self.assertEqual(resp.status_code, 400)

    def test_viewing_prev_grade(self):
        grade_data = {
            "grade_points": "4",
            "released": "on"
        }
        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data=grade_data, expected_grades=4)
        with self.temporarily_switch_to_user(
                self.instructor_participation.user), mock.patch(
                "course.grading.get_feedback_for_grade") as mock_get_feedback:

            resp = self.c.get(
                self.get_page_grading_url_by_page_id(self.page_id)
                + "?grade_id=1")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(mock_get_feedback.call_count, 1)

    def test_viewing_prev_grade_may_not_post_grade(self):
        grade_data = {
            "grade_points": "4",
            "released": "on"
        }
        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data=grade_data, expected_grades=4)

        ordinal = self.get_page_ordinal_via_page_id(self.page_id)
        self.assertGradeHistoryItemsCount(page_ordinal=ordinal, expected_count=3)

        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.post(
                self.get_page_grading_url_by_page_id(self.page_id) + "?grade_id=1",
                data=grade_data
            )
            self.assertEqual(resp.status_code, 200)
        self.assertGradeHistoryItemsCount(page_ordinal=ordinal, expected_count=3)

    # }}}

    def test_flow_session_course_not_matching(self):
        another_course = factories.CourseFactory(identifier="another-course")
        some_user = factories.UserFactory()
        his_participation = factories.ParticipationFactory(
            course=another_course, user=some_user)
        his_flow_session = factories.FlowSessionFactory(
            course=another_course, participation=his_participation)

        url = self.get_page_grading_url_by_ordinal(
            page_ordinal=1, course_identifier=self.course.identifier,
            flow_session_id=his_flow_session.pk)

        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(url)
            self.assertEqual(resp.status_code, 400)

    def test_flow_session_has_no_participation(self):
        null_participation_flow_session = factories.FlowSessionFactory(
            course=self.course, participation=None, user=None)

        url = self.get_page_grading_url_by_ordinal(
            page_ordinal=1,
            flow_session_id=null_participation_flow_session.pk,
        )

        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(url)
            self.assertEqual(resp.status_code, 400)

    def test_page_desc_none(self):
        with mock.patch(
                "course.content.get_flow_page_desc") as mock_get_flow_page_desc:
            from django.core.exceptions import ObjectDoesNotExist
            mock_get_flow_page_desc.side_effect = ObjectDoesNotExist

            with self.temporarily_switch_to_user(self.instructor_participation.user):
                resp = self.c.get(
                    self.get_page_grading_url_by_page_id(self.page_id))
                self.assertEqual(resp.status_code, 404)

    def test_invalid_page_data(self):
        with mock.patch(
                "course.page.upload.FileUploadQuestion.make_form"
        ) as mock_make_form, mock.patch(
            "course.grading.messages.add_message"
        ) as mock_add_msg:
            from course.grading import InvalidPageData
            error_msg = "your file is broken."
            mock_make_form.side_effect = InvalidPageData(error_msg)

            expected_error_msg = (
                    "The page data stored in the database was found "
                    "to be invalid for the page as given in the "
                    "course content. Likely the course content was "
                    "changed in an incompatible way (say, by adding "
                    "an option to a choice question) without changing "
                    "the question ID. The precise error encountered "
                    "was the following: %s" % error_msg)

            with self.temporarily_switch_to_user(
                    self.instructor_participation.user):
                resp = self.c.get(
                    self.get_page_grading_url_by_page_id(self.page_id))
                self.assertEqual(resp.status_code, 200)
                self.assertIn(expected_error_msg, mock_add_msg.call_args[0])

    def test_no_perm_to_post_grade(self):
        some_user = factories.UserFactory()
        his_participation = factories.ParticipationFactory(
            user=some_user, course=self.course)
        from course.models import ParticipationPermission
        pp = ParticipationPermission(
            participation=his_participation,
            permission=pperm.view_gradebook
        )
        pp.save()
        his_participation.individual_permissions.set([pp])
        with self.temporarily_switch_to_user(some_user):
            resp = self.c.get(
                self.get_page_grading_url_by_page_id(self.page_id))
            self.assertEqual(resp.status_code, 200)

            grade_data = {
                "grade_points": "4",
                "released": "on"
            }
            resp = self.post_grade_by_page_id(
                self.page_id, grade_data, force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

    def test_flow_session_grading_opportunity_is_none(self):
        grade_data = {
            "grade_points": "4",
            "released": "on"
        }

        def get_session_grading_rule_side_effect(session, flow_desc, now_datetime):
            from course.utils import (
                get_session_grading_rule, FlowSessionGradingRule)
            true_g_rule = get_session_grading_rule(
                session, flow_desc, now_datetime)

            fake_grading_rule = FlowSessionGradingRule(
                # make grade_identifier None
                grade_identifier=None,
                grade_aggregation_strategy=true_g_rule.grade_aggregation_strategy,
                due=true_g_rule.due,
                generates_grade=true_g_rule.generates_grade,
                description=true_g_rule.description,
                credit_percent=true_g_rule.credit_percent,
                use_last_activity_as_completion_time=(
                    true_g_rule.use_last_activity_as_completion_time),
                bonus_points=true_g_rule.bonus_points,
                max_points=true_g_rule.max_points,
                max_points_enforced_cap=true_g_rule.max_points_enforced_cap)
            return fake_grading_rule

        with mock.patch(
                "course.grading.get_session_grading_rule"
        ) as mock_get_grading_rule:
            mock_get_grading_rule.side_effect = get_session_grading_rule_side_effect

            with self.temporarily_switch_to_user(
                    self.instructor_participation.user):
                # get success
                resp = self.c.get(
                    self.get_page_grading_url_by_page_id(self.page_id))
                self.assertEqual(resp.status_code, 200)
                self.assertResponseContextIsNone(
                    resp, "grading_opportunity")

                # post success
                resp = self.post_grade_by_page_id(
                    self.page_id, grade_data)
                self.assertEqual(resp.status_code, 200)

                self.assertResponseContextIsNone(
                    resp, "grading_opportunity")


class GraderSetUpMixin(object):
    @classmethod
    def create_flow_page_visit_grade(cls, course=None,
                                     n_participations_per_course=1,
                                     n_sessions_per_participation=1,
                                     n_non_null_answer_visits_per_session=3):
        if course is None:
            course = factories.CourseFactory(identifier=course.identifier)
        participations = factories.ParticipationFactory.create_batch(
            size=n_participations_per_course, course=course)

        grader1 = factories.UserFactory()
        grader2 = factories.UserFactory()

        graders = [grader1, grader2]

        visit_time = now() - timedelta(days=1)
        for participation in participations:
            flow_sessions = factories.FlowSessionFactory.create_batch(
                size=n_sessions_per_participation, participation=participation)
            for flow_session in flow_sessions:
                non_null_anaswer_fpds = factories.FlowPageDataFactory.create_batch(
                    size=n_non_null_answer_visits_per_session,
                    flow_session=flow_session
                )
                for fpd in non_null_anaswer_fpds:
                    visit_time = visit_time + timedelta(seconds=10)
                    factories.FlowPageVisitFactory.create(
                        visit_time=visit_time,
                        page_data=fpd,
                        answer={"answer": "abcd"})

                    shuffle(graders)

                    grade_time = visit_time + timedelta(seconds=10)
                    factories.FlowPageVisitGradeFactory.create(
                        grader=graders[0],
                        grade_time=grade_time)

        n_non_null_answer_fpv = (
                n_participations_per_course
                * n_sessions_per_participation
                * n_non_null_answer_visits_per_session)

        #print(n_non_null_answer_fpv)
        return n_non_null_answer_fpv


class ShowGraderStatisticsTest(
        SingleCourseQuizPageTestMixin, GraderSetUpMixin, TestCase):
    # test grading.show_grader_statistics

    @classmethod
    def setUpTestData(cls):  # noqa
        super(ShowGraderStatisticsTest, cls).setUpTestData()
        cls.create_flow_page_visit_grade(cls.course)

    def get_show_grader_statistics_url(self, flow_id, course_identifier=None):
        course_identifier = (
                course_identifier or self.get_default_course_identifier())
        from tests.base_test_mixins import reverse
        params = {"course_identifier": course_identifier,
                    "flow_id": flow_id}
        return reverse("relate-show_grader_statistics", kwargs=params)

    def test_no_permission(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(self.get_show_grader_statistics_url(self.flow_id))
            self.assertEqual(resp.status_code, 403)

    def test_success(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(self.get_show_grader_statistics_url(self.flow_id))
            self.assertEqual(resp.status_code, 200)


# vim: fdm=marker
