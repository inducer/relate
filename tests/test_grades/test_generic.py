from __future__ import division

__copyright__ = "Copyright (C) 2017 Zesheng Wang, Andreas Kloeckner, Zhuang Dong"

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

import six
from django.urls import reverse, NoReverseMatch
from django.test import TestCase
from unittest import skipIf

from course.models import (
    Participation, GradingOpportunity, FlowSession,
    FlowRuleException
)

from tests.base_test_mixins import SingleCoursePageTestMixin


class GradeGenericTestMixin(SingleCoursePageTestMixin):
    # This serve as a base test cases for other grade tests to subclass
    # Nice little tricks :)
    @classmethod
    def setUpTestData(cls):  # noqa
        super(GradeGenericTestMixin, cls).setUpTestData()
        cls.flow_session_ids = []
        cls.do_quiz(cls.student_participation)

    @classmethod
    def tearDownClass(cls):
        super(GradeGenericTestMixin, cls).tearDownClass()

    # Use specified user to take a quiz
    @classmethod
    def do_quiz(cls, participation):
        # Login user first
        cls.c.force_login(participation.user)
        cls.start_flow(cls.flow_id)
        cls.end_flow()
        cls.flow_session_ids.append(
            int(cls.default_flow_params["flow_session_id"]))

    # Seperate the test here
    def test_grading_opportunity(self):
        # Should only have one grading opportunity object
        self.assertEqual(GradingOpportunity.objects.all().count(), 1)

    def test_view_my_grade(self):
        resp = self.c.get(reverse("relate-view_participant_grades",
                                  args=[self.course.identifier]))
        self.assertEqual(resp.status_code, 200)

    def test_view_participant_grades(self):
        params = {"course_identifier": self.course.identifier,
                  "participation_id": self.instructor_participation.user.id}
        resp = self.c.get(reverse("relate-view_participant_grades",
                                                    kwargs=params))
        self.assertEqual(resp.status_code, 200)

    def test_view_participant_list(self):
        resp = self.c.get(reverse("relate-view_participant_list",
                                  args=[self.course.identifier]))
        self.assertEqual(resp.status_code, 200)

    def test_view_grading_opportunity_list(self):
        resp = self.c.get(reverse("relate-view_grading_opportunity_list",
                                  args=[self.course.identifier]))
        self.assertEqual(resp.status_code, 200)

    def test_view_gradebook(self):
        resp = self.c.get(reverse("relate-view_gradebook",
                                  args=[self.course.identifier]))
        self.assertEqual(resp.status_code, 200)

    # todo: move to test_csv
    def test_view_export_gradebook_csv(self):
        resp = self.c.get(reverse("relate-export_gradebook_csv",
                                  args=[self.course.identifier]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Disposition"],
                         'attachment; filename="grades-test-course.csv"')

    def test_view_grades_by_opportunity(self):
        # Check attributes
        self.assertEqual(GradingOpportunity.objects.all().count(), 1)
        opportunity = GradingOpportunity.objects.first()
        self.assertEqual(self.course, opportunity.course)
        self.assertEqual(self.flow_id, opportunity.flow_id)

        # Check page
        params = {"course_identifier": self.course.identifier,
                  "opp_id": opportunity.id}
        resp = self.c.get(reverse("relate-view_grades_by_opportunity",
                                  kwargs=params))
        self.assertEqual(resp.status_code, 200)

    def test_view_participant_grade_by_opportunity(self):
        # Check attributes
        self.assertEqual(GradingOpportunity.objects.all().count(), 1)
        opportunity = GradingOpportunity.objects.first()
        self.assertEqual(self.course, opportunity.course)
        self.assertEqual(self.flow_id, opportunity.flow_id)

        # Check page
        params = {"course_identifier": self.course.identifier,
                  "opportunity_id": opportunity.id,
                  "participation_id": self.student_participation.id}
        resp = self.c.get(reverse("relate-view_single_grade", kwargs=params))
        self.assertEqual(resp.status_code, 200)

    def test_view_reopen_session(self):
        # Check attributes
        self.assertEqual(len(GradingOpportunity.objects.all()), 1)
        opportunity = GradingOpportunity.objects.all()[0]
        self.assertEqual(self.course, opportunity.course)
        self.assertEqual(self.flow_id, opportunity.flow_id)

        all_session = FlowSession.objects.all()
        # Check flow numbers
        self.assertEqual(len(all_session), len(self.flow_session_ids))

        # Check each flow session
        for session in all_session:
            self.check_reopen_session(session.id, opportunity.id)

        # Check flow numbers again
        self.assertEqual(FlowSession.objects.all().count(),
                         len(self.flow_session_ids))

    # Just show the grading interfaces of the unanswered pages
    # the answered pages are tested in tests.teat_pages.test_generic
    def test_view_grade_flow_page(self):
        params = {"course_identifier": self.course.identifier,
                  "flow_session_id": self.flow_session_ids[0]}

        page_count = FlowSession.objects.get(id=self.flow_session_ids[0]).page_count
        for i in range(page_count):
            resp = self.c.get(
                self.get_page_grading_url_by_ordinal(page_ordinal=i, **params))
            self.assertEqual(resp.status_code, 200)

        # test PageOrdinalOutOfRange
        resp = self.c.get(
            self.get_page_grading_url_by_ordinal(page_ordinal=page_count+1,
                                                 **params))
        self.assertEqual(resp.status_code, 404)

    def test_view_grader_statistics(self):
        params = {"course_identifier": self.course.identifier,
                    "flow_id": self.flow_id}
        resp = self.c.get(reverse("relate-show_grader_statistics",
                                            kwargs=params))
        self.assertEqual(resp.status_code, 200)

    def test_view_flow_list_analytics(self):
        resp = self.c.get(reverse("relate-flow_list",
                                            args=[self.course.identifier]))
        self.assertEqual(resp.status_code, 200)

    def test_view_flow_analytics(self):
        params = {"course_identifier": self.course.identifier,
                    "flow_id": self.flow_id}
        resp = self.c.get(reverse("relate-flow_analytics",
                                            kwargs=params))
        self.assertEqual(resp.status_code, 200)

    def test_view_grant_exception_new_session(self):
        all_session = FlowSession.objects.all()
        # Check number of flow sessions and ids
        self.assertEqual(all_session.count(), len(self.flow_session_ids))
        for session in all_session:
            # Perform all checking before moving to stage three
            params = self.check_stage_one_and_two(session.participation)
            self.assertTrue(session.id in self.flow_session_ids)
            self.check_grant_new_exception(params)

        self.assertEqual(FlowSession.objects.all().count(),
                         2 * self.n_quiz_takers)

    def test_view_grant_exception_exist_session(self):
        # Store numbers to reuse
        session_nums = len(self.flow_session_ids)

        all_session = FlowSession.objects.all()
        # Check session numbers
        self.assertEqual(len(all_session), session_nums)

        # Check for each existing session
        for session in all_session:
            # Perform all checking before moving to stage three
            params = self.check_stage_one_and_two(session.participation)
            self.check_grant_exist_exception(session.id, params)

        # Should have two exception rules now
        # One for access and one for grading
        self.assertEqual(len(FlowRuleException.objects.all()), 2 * session_nums)

    # Helper method for testing grant exceptions for new session
    def check_grant_new_exception(self, params):
        # Grant a new one
        data = {'access_rules_tag_for_new_session': ['<<<NONE>>>'],
                    'create_session': ['Create session']}
        resp = self.c.post(reverse("relate-grant_exception_stage_2",
                                                kwargs=params), data)
        self.assertEqual(resp.status_code, 200)

    # Helper method for testing grant exceptions for existing one
    def check_grant_exist_exception(self, session_id, parameters):
        params = parameters.copy()
        flow_session = FlowSession.objects.filter(id=session_id)[0]
        self.assertTrue(flow_session.id in self.flow_session_ids)

        # Grant an existing one
        data = {'session': [str(flow_session.id)], 'next': ['Next \xbb']}
        resp = self.c.post(reverse("relate-grant_exception_stage_2",
                                                kwargs=params), data)
        self.assertEqual(resp.status_code, 302)

        # Prepare parameters
        params["session_id"] = data["session"][0]
        # Check redirect
        self.assertEqual(resp.url, reverse("relate-grant_exception_stage_3",
                                                                kwargs=params))

        # Check stage three page
        resp = self.c.get(reverse("relate-grant_exception_stage_3",
                                                                kwargs=params))
        self.assertEqual(resp.status_code, 200)

        # Create a new exception rule
        data = {'comment': ['test-rule'], 'save': ['Save'], 'view': ['on'],
                'see_answer_after_submission': ['on'],
                'create_grading_exception': ['on'],
                'create_access_exception': ['on'],
                'access_expires': [''], 'due': [''],
                'bonus_points': ['0.0'], 'max_points': [''],
                'credit_percent': ['100.0'], 'max_points_enforced_cap': [''],
                'generates_grade': ['on'], 'see_correctness': ['on']}
        resp = self.c.post(reverse("relate-grant_exception_stage_3",
                                                kwargs=params), data)
        self.assertEqual(resp.status_code, 302)

        # Check redirect
        self.assertEqual(resp.url, reverse("relate-grant_exception",
                                        args=[self.course.identifier]))

    # Helper method for testing reopen session
    def check_reopen_session(self, session_id, opportunity_id):
        flow_session = FlowSession.objects.filter(id=session_id)[0]
        self.assertEqual(flow_session.in_progress, False)

        # Check reopen session form
        params = {"course_identifier": self.course.identifier,
                    "opportunity_id": opportunity_id,
                    "flow_session_id": session_id}
        resp = self.c.get(reverse("relate-view_reopen_session",
                                                    kwargs=params))
        self.assertEqual(resp.status_code, 200)

        # Reopen session
        data = {'set_access_rules_tag': ['<<<NONE>>>'],
                'comment': ['test-reopen'],
                'unsubmit_pages': ['on'],
                'reopen': ['Reopen']}
        resp = self.c.post(
            reverse("relate-view_reopen_session", kwargs=params), data)

        flow_session = FlowSession.objects.filter(id=session_id)[0]
        self.assertEqual(flow_session.in_progress, True)

    # Helper method for testing grant exception view
    def check_stage_one_and_two(self, participation):
        # Check stage one page
        resp = self.c.get(
            reverse("relate-grant_exception", args=[self.course.identifier]))
        self.assertEqual(resp.status_code, 200)

        # Move to stage two
        self.assertEqual(Participation.objects.all().count(), self.n_participations)

        data = {"next": ["Next \xbb"],
                "participation": [str(participation.id)],
                "flow_id": [self.flow_id]}
        resp = self.c.post(reverse("relate-grant_exception",
                                   args=[self.course.identifier]), data)
        self.assertEqual(resp.status_code, 302)

        # Prepare parameters
        params = data.copy()
        params["participation_id"] = params["participation"][0]
        params["course_identifier"] = self.course.identifier
        params["flow_id"] = params["flow_id"][0]
        del params["next"]
        del params["participation"]
        # Check redirect
        self.assertEqual(resp.url,
                         reverse(
                             "relate-grant_exception_stage_2", kwargs=params))

        # Check stage two page
        resp = self.c.get(
            reverse("relate-grant_exception_stage_2", kwargs=params))
        self.assertEqual(resp.status_code, 200)

        # Return params to reuse
        return params


class GradeTwoQuizTakerTest(GradeGenericTestMixin, TestCase):

    force_login_student_for_each_test = False

    @classmethod
    def setUpTestData(cls): # noqa
        super(GradeTwoQuizTakerTest, cls).setUpTestData()
        cls.do_quiz(cls.instructor_participation)
        cls.n_quiz_takers = 2
        cls.n_participations = 3

        # Make sure the instructor is logged in after all quizes finished
        cls.c.force_login(cls.instructor_participation.user)


class GradeThreeQuizTakerTest(GradeGenericTestMixin, TestCase):

    force_login_student_for_each_test = False

    @classmethod
    def setUpTestData(cls): # noqa
        super(GradeThreeQuizTakerTest, cls).setUpTestData()
        cls.do_quiz(cls.ta_participation)
        cls.do_quiz(cls.instructor_participation)
        cls.n_quiz_takers = 3
        cls.n_participations = 3

        cls.c.force_login(cls.instructor_participation.user)


@skipIf(six.PY2, "PY2 doesn't support subTest")
class GradePermissionsTests(SingleCoursePageTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):  # noqa
        super(GradePermissionsTests, cls).setUpTestData()
        cls.start_flow(flow_id=cls.flow_id)
        cls.end_flow()

    def view_grades_permission(self, user, status_codes):
        try:
            participation = Participation.objects.get(user=user)
        except Participation.DoesNotExist:
            participation = self.student_participation

        urlname_views = ([
            ("relate-view_gradebook",
             {"course_identifier": self.course.identifier}),
            ("relate-view_grades_by_opportunity",
             {"course_identifier": self.course.identifier, "opp_id": 1}),
            ("relate-view_grading_opportunity_list",
             {"course_identifier": self.course.identifier}),
            ("relate-view_participant_grades",
             {"course_identifier": self.course.identifier,
              "participation_id": participation.pk}),
            ("relate-view_participant_list",
             {"course_identifier": self.course.identifier}),
            ("relate-view_reopen_session",
             {"course_identifier": self.course.identifier, "flow_session_id": 1,
              "opportunity_id": 1}),
            ("relate-view_single_grade",
             {"course_identifier": self.course.identifier,
              "participation_id": participation.pk, "opportunity_id": 1}),
            ("relate-export_gradebook_csv",
             {"course_identifier": self.course.identifier}),
            ("relate-import_grades",
             {"course_identifier": self.course.identifier}),
            ("relate-download_all_submissions",
             {"course_identifier": self.course.identifier,
              "flow_id": self.flow_id}),
            ("relate-edit_grading_opportunity",
             {"course_identifier": self.course.identifier, "opportunity_id": 1})]
        )
        with self.temporarily_switch_to_user(user):
            for (urlname, kwargs) in urlname_views:
                try:
                    url = reverse(urlname, kwargs=kwargs)
                except NoReverseMatch:
                    self.fail(
                        "Reversal of url named '%s' failed with "
                        "NoReverseMatch" % urlname)
                with self.subTest(user=user, urlname=urlname, method="GET"):
                    resp = self.c.get(url)
                    self.assertEqual(
                        resp.status_code,
                        status_codes.get(
                            urlname + "_get",
                            status_codes.get(
                                urlname,
                                status_codes.get("default_status_code")
                            )))

                with self.subTest(user=user, urlname=urlname, method="POST"):
                    postdata = {}
                    resp = self.c.post(url, data=postdata)
                    self.assertEqual(
                        resp.status_code,
                        status_codes.get(
                            urlname + "_post",
                            status_codes.get(
                                urlname,
                                status_codes.get("default_status_code")
                            )))

    def test_view_grades_instructor(self):
        status_codes = {"default_status_code": 200,

                        # no action_defined
                        "relate-view_single_grade_post": 400,
                        "relate-view_grades_by_opportunity_post": 400}
        self.view_grades_permission(self.instructor_participation.user,
                                    status_codes)

    @skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_view_grades_ta(self):
        status_codes = {"default_status_code": 200,
                        "relate-edit_grading_opportunity": 403,
                        "relate-import_grades": 403,
                        "relate-export_gradebook_csv": 403,

                        # no action_defined
                        "relate-view_single_grade_post": 400,
                        "relate-view_grades_by_opportunity": 200}
        self.view_grades_permission(self.ta_participation.user,
                                    status_codes)

    def test_view_grades_student(self):
        status_codes = {"default_status_code": 403,
                        "relate-view_participant_grades": 200,

                        # no action_defined
                        "relate-view_single_grade_post": 400,
                        "relate-view_single_grade": 200}
        self.view_grades_permission(self.student_participation.user,
                                    status_codes)

    def test_view_grades_anonymous(self):
        status_codes = {"default_status_code": 403}
        self.view_grades_permission(None, status_codes)
