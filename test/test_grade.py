from __future__ import division

__copyright__ = "Copyright (C) 2014 Andreas Kloeckner"

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

import shutil
from django.test import TestCase, Client
from django.urls import resolve, reverse
from accounts.models import User
from course.models import FlowSession, Course, GradingOpportunity #, Participation



class GradeTest(TestCase):
    # @classmethod
    # def setUpClass(cls):
    #     super(GradeTest, cls).setUpClass()
    #     cls.modify_settings(EMAIL_BACKEND=
    #                     'django.core.mail.backends.console.EmailBackend')

    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase
        # Admin account
        cls.admin = User.objects.create_superuser(
                username="testadmin",
                password="test",
                email="test@example.com",
                first_name="Test",
                last_name="Admin")
        cls.admin.save()

        # User account
        # cls.user1 = User.objects.create_user(
        #         username="tester1",
        #         password="test",
        #         email="tester1@example.com",
        #         first_name="Test1",
        #         last_name="Tester")
        # cls.user1.save()
        #
        # cls.user2 = User.objects.create_user(
        #         username="tester2",
        #         password="test",
        #         email="tester2@example.com",
        #         first_name="Test2",
        #         last_name="Tester")
        # cls.user2.save()

        # Create the course here and check later to
        # avoid exceptions raised here
        cls.c = Client()
        cls.c.login(
            username="testadmin",
            password="test")
        cls.c.post("/new-course/", dict(
            identifier="test-course",
            name="Test Course",
            number="CS123",
            time_period="Fall 2016",
            hidden=False,
            listed=True,
            accepts_enrollment=True,
            git_source="git://github.com/inducer/relate-sample",
            course_file="course.yml",
            events_file="events.yml",
            enrollment_approval_required=False,
            enrollment_required_email_suffix=None,
            from_email="inform@tiker.net",
            notify_email="inform@tiker.net"))

        cls.course = Course.objects.all()[0]
        # Some classwise sharing data
        cls.datas = {"course_identifier": cls.course.identifier,
                                                "flow_id": "quiz-test"}
        cls.datas["flow_session_id"] = []

        # Make sure admin is logged in after all this
        # cls.do_quiz(cls.user1)
        # cls.do_quiz(cls.user2)
        cls.do_quiz(cls.admin)

    @classmethod
    def tearDownClass(cls):
        # Remove created folder
        shutil.rmtree('../' + cls.datas["course_identifier"])
        super(GradeTest, cls).tearDownClass()

    # Use specified user to take a quiz
    @classmethod
    def do_quiz(cls, user):
        # Login user first
        cls.c.logout()
        cls.c.login(
                    username=user.username,
                    password="test")

        # Enroll if not admin
        # Little hacky for not using enrollment view
        # if not user.is_superuser:
        #     participation = Participation()
        #     participation.user = user
        #     participation.course = Course.objects.filter(identifier=
        #                                                     "test-course")[0]
        #     participation.status = "active"
        #     participation.save()

        params = cls.datas.copy()
        del params["flow_session_id"]
        resp = cls.c.post(reverse("relate-view_start_flow", kwargs=params))

        # Yep, no regax!
        _, _, kwargs = resolve(resp.url)
        # Store flow_session_id
        cls.datas["flow_session_id"].append(kwargs["flow_session_id"])

        # Let it raise error
        # Use pop() will not
        del kwargs["ordinal"]
        resp = cls.c.post(reverse("relate-finish_flow_session_view",
                                kwargs=kwargs), {'submit': ['']})

    # Seperate the test here
    def test_grading_opportunity(self):
        # Should only have one grading opportunity object
        self.assertEqual(len(GradingOpportunity.objects.all()), 1)

    def test_view_my_grade(self):
        resp = self.c.get(reverse("relate-view_participant_grades",
                                            args=[self.datas["course_identifier"]]))
        self.assertEqual(resp.status_code, 200)

    def test_view_participant_grades(self):
        params = {"course_identifier": self.datas["course_identifier"],
                                                "participation_id": self.admin.id}
        resp = self.c.get(reverse("relate-view_participant_grades",
                                                    kwargs=params))
        self.assertEqual(resp.status_code, 200)

    def test_view_participant_list(self):
        resp = self.c.get(reverse("relate-view_participant_list",
                                            args=[self.datas["course_identifier"]]))
        self.assertEqual(resp.status_code, 200)

    def test_view_grading_opportunity_list(self):
        resp = self.c.get(reverse("relate-view_grading_opportunity_list",
                                            args=[self.datas["course_identifier"]]))
        self.assertEqual(resp.status_code, 200)

    def test_view_gradebook(self):
        resp = self.c.get(reverse("relate-view_gradebook",
                                            args=[self.datas["course_identifier"]]))
        self.assertEqual(resp.status_code, 200)

    def test_view_export_gradebook_csv(self):
        resp = self.c.get(reverse("relate-export_gradebook_csv",
                                            args=[self.datas["course_identifier"]]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Disposition"],
                            'attachment; filename="grades-test-course.csv"')

    def test_view_grades_by_opportunity(self):
        # Check attributes
        opportunity = GradingOpportunity.objects.all()[0]
        self.assertEqual(self.course, opportunity.course)
        self.assertEqual(self.datas["flow_id"], opportunity.flow_id)

        # Check page
        params = {"course_identifier": self.datas["course_identifier"],
                    "opp_id": opportunity.id}
        resp = self.c.get(reverse("relate-view_grades_by_opportunity",
                                            kwargs=params))
        self.assertEqual(resp.status_code, 200)

    def test_view_participant_grade_by_opportunity(self):
        # Check attributes
        opportunity = GradingOpportunity.objects.all()[0]
        self.assertEqual(self.course, opportunity.course)
        self.assertEqual(self.datas["flow_id"], opportunity.flow_id)

        # Check page
        params = {"course_identifier": self.datas["course_identifier"],
                    "opportunity_id": opportunity.id,
                    "participation_id": self.admin.id}
        resp = self.c.get(reverse("relate-view_single_grade",
                                            kwargs=params))
        self.assertEqual(resp.status_code, 200)

    def test_view_reopen_session(self):
        # Check attributes
        opportunity = GradingOpportunity.objects.all()[0]
        self.assertEqual(self.course, opportunity.course)
        self.assertEqual(self.datas["flow_id"], opportunity.flow_id)

        # Check flow, should have only one
        self.assertEqual(len(FlowSession.objects.all()), 1)

        # Finished flow session
        flow_session = FlowSession.objects.all()[0]
        self.assertEqual(flow_session.in_progress, False)

        # Check reopen session form
        params = {"course_identifier": self.datas["course_identifier"],
                    "opportunity_id": opportunity.id,
                    "flow_session_id": self.datas["flow_session_id"][0]}
        resp = self.c.get(reverse("relate-view_reopen_session",
                                                    kwargs=params))
        self.assertEqual(resp.status_code, 200)

        # Reopen session
        datas = {'set_access_rules_tag': ['<<<NONE>>>'], 'comment': ['test-reopen'],
                                'unsubmit_pages': ['on'], 'reopen': ['Reopen']}
        resp = self.c.post(reverse("relate-view_reopen_session",
                                                    kwargs=params), datas)

        # Should still have one
        self.assertEqual(len(FlowSession.objects.all()), 1)
        flow_session = FlowSession.objects.all()[0]
        self.assertEqual(flow_session.in_progress, True)

    # Only test if import form is working for now
    # Maybe try export then import?
    def test_view_import_grades(self):
        resp = self.c.get(reverse("relate-import_grades",
                                            args=[self.datas["course_identifier"]]))
        self.assertEqual(resp.status_code, 200)

    # Seems just show the answer
    def test_view_grade_flow_page(self):
        params = {"course_identifier": self.datas["course_identifier"],
                    "flow_session_id": self.datas["flow_session_id"][0]}
        for i in xrange(18):
            params["page_ordinal"] = str(i)
            resp = self.c.get(reverse("relate-grade_flow_page",
                                                kwargs=params))
            self.assertEqual(resp.status_code, 200)

    # flow_session_id and flow_id
    # Consistency plz :(
    # Should be flow_session_id?
    def test_view_grader_statistics(self):
        params = {"course_identifier": self.datas["course_identifier"],
                    "flow_id": self.datas["flow_session_id"][0]}
        resp = self.c.get(reverse("relate-show_grader_statistics",
                                            kwargs=params))
        self.assertEqual(resp.status_code, 200)

    def test_view_download_submissions(self):
        params = {"course_identifier": self.datas["course_identifier"],
                    "flow_id": self.datas["flow_id"]}

        # Check download form first
        resp = self.c.get(reverse("relate-download_all_submissions",
                                            kwargs=params))
        self.assertEqual(resp.status_code, 200)

        # Check download here, only test intro page
        # Maybe we should include an "all" option in the future?
        datas = {'restrict_to_rules_tag': ['<<<ALL>>>'], 'which_attempt': ['last'],
                'extra_file': [''], 'download': ['Download'],
                'page_id': ['intro/welcome'], 'non_in_progress_only': ['on']}
        resp = self.c.post(reverse("relate-download_all_submissions",
                                            kwargs=params), datas)
        self.assertEqual(resp.status_code, 200)
        prefix, zip_file = resp["Content-Disposition"].split('=')
        self.assertEqual(prefix, "attachment; filename")
        zip_file_name = zip_file.replace('"', '').split('_')
        self.assertEqual(zip_file_name[0], "submissions")
        self.assertEqual(zip_file_name[1], self.datas["course_identifier"])
        self.assertEqual(zip_file_name[2], self.datas["flow_id"])
        self.assertEqual(zip_file_name[3], "intro")
        self.assertEqual(zip_file_name[4], "welcome")
        self.assertTrue(zip_file_name[5].endswith(".zip"))

    def test_view_edit_grading_opportunity(self):
        # Check attributes
        opportunity = GradingOpportunity.objects.all()[0]
        self.assertEqual(self.course, opportunity.course)
        self.assertEqual(self.datas["flow_id"], opportunity.flow_id)

        params = {"course_identifier": self.datas["course_identifier"],
                    "opportunity_id": opportunity.id}
        # Check page
        resp = self.c.get(reverse("relate-edit_grading_opportunity",
                                            kwargs=params))
        self.assertEqual(resp.status_code, 200)
        # Try making a change
        self.assertEqual(opportunity.page_scores_in_participant_gradebook, False)
        datas = {'page_scores_in_participant_gradebook': ['on'],
                 'name': ['Flow: RELATE Test Quiz'],
                 'hide_superseded_grade_history_before': [''],
                 'submit': ['Update'],
                 'shown_in_participant_grade_book': ['on'],
                 'aggregation_strategy': ['use_latest'],
                 'shown_in_grade_book': ['on'],
                 'result_shown_in_participant_grade_book': ['on']}
        resp = self.c.post(reverse("relate-edit_grading_opportunity",
                                                    kwargs=params), datas)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse("relate-edit_grading_opportunity",
                                                            kwargs=params))

        # Check objects and attributes
        # Should still be one
        self.assertEqual(len(GradingOpportunity.objects.all()), 1)
        opportunity = GradingOpportunity.objects.all()[0]
        self.assertEqual(self.course, opportunity.course)
        self.assertEqual(self.datas["flow_id"], opportunity.flow_id)
        # Check changes
        self.assertEqual(opportunity.page_scores_in_participant_gradebook, True)

# @TODO remain tests
# http://localhost:8000/course/course-test/flow-analytics/quiz-test/
# http://localhost:8000/course/course-test/regrade-flows/
# http://localhost:8000/course/course-test/grant-exception/
# http://localhost:8000/course/course-test/batch-issue-exam-tickets/
