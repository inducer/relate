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

from django.test import Client
from django.urls import resolve, reverse
from accounts.models import User
from course.models import FlowSession, Course, GradingOpportunity, \
                            Participation, FlowRuleException, ParticipationRole


# Nice little tricks :)
class BaseGradeTest(object):

    @classmethod
    def setUpTestData(cls):  # noqa
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
        cls.student = User.objects.create_user(
                username="tester1",
                password="test",
                email="tester1@example.com",
                first_name="Student",
                last_name="Tester")
        cls.student.save()

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

        # Make sure admin is logged in after all this in all sub classes
        # Student takes quiz anyway
        cls.do_quiz(cls.student, "student")

    # Use specified user to take a quiz
    @classmethod
    def do_quiz(cls, user, assign_role=None):
        # Login user first
        cls.c.logout()
        cls.c.login(
                    username=user.username,
                    password="test")

        # Enroll if not admin
        # Little hacky for not using enrollment view
        if assign_role:
            participation = Participation()
            participation.user = user
            participation.course = Course.objects.filter(identifier=
                                                cls.datas["course_identifier"])[0]
            participation.status = "active"
            participation.save()
            
            if assign_role == "student":
                role = ParticipationRole.objects.filter(id=3)[0]
            elif assign_role == "ta":
                role = ParticipationRole.objects.filter(id=2)[0]
            participation.roles.add(role)


        params = cls.datas.copy()
        del params["flow_session_id"]
        resp = cls.c.post(reverse("relate-view_start_flow", kwargs=params))

        # Yep, no regax!
        _, _, kwargs = resolve(resp.url)
        # Store flow_session_id
        cls.datas["flow_session_id"].append(int(kwargs["flow_session_id"]))

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
        for i in range(18):
            params["page_ordinal"] = str(i)
            resp = self.c.get(reverse("relate-grade_flow_page",
                                                kwargs=params))
            self.assertEqual(resp.status_code, 200)

    def test_view_grader_statistics(self):
        params = {"course_identifier": self.datas["course_identifier"],
                    "flow_id": self.datas["flow_id"]}
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

    def test_view_flow_list_analytics(self):
        resp = self.c.get(reverse("relate-flow_list",
                                            args=[self.datas["course_identifier"]]))
        self.assertEqual(resp.status_code, 200)

    def test_view_flow_analytics(self):
        params = {"course_identifier": self.datas["course_identifier"],
                    "flow_id": self.datas["flow_id"]}
        resp = self.c.get(reverse("relate-flow_analytics",
                                            kwargs=params))
        self.assertEqual(resp.status_code, 200)

    # Only check page for now
    def test_view_regrade_flow(self):
        resp = self.c.get(reverse("relate-regrade_flows_view",
                                            args=[self.datas["course_identifier"]]))
        self.assertEqual(resp.status_code, 200)

    def test_view_grant_exception_new_session(self):
        # Perform all checking before moving to stage three
        params = self.check_stage_one_and_two()

        # Should have only one flow session now
        self.assertEqual(len(FlowSession.objects.all()), 1)
        self.assertEqual(FlowSession.objects.all()[0].id,
                                self.datas["flow_session_id"][0])

        # Grant a new one
        datas = {'access_rules_tag_for_new_session': ['<<<NONE>>>'],
                    'create_session': ['Create session']}
        resp = self.c.post(reverse("relate-grant_exception_stage_2",
                                                kwargs=params), datas)
        self.assertEqual(resp.status_code, 200)

        # Should have two flow sessions now
        self.assertEqual(len(FlowSession.objects.all()), 2)

    def test_view_grant_exception_exist_session(self):
        # Perform all checking before moving to stage three
        params = self.check_stage_one_and_two()

        # Should have only one flow session now
        self.assertEqual(len(FlowSession.objects.all()), 1)
        flow_session = FlowSession.objects.all()[0]
        self.assertEqual(flow_session.id,
                                self.datas["flow_session_id"][0])

        # Grant an existing one
        datas = {'session': [str(flow_session.id)], 'next': ['Next \xbb']}
        resp = self.c.post(reverse("relate-grant_exception_stage_2",
                                                kwargs=params), datas)
        self.assertEqual(resp.status_code, 302)

        # Prepare parameters
        params["session_id"] = datas["session"][0]
        # Check redirect
        self.assertEqual(resp.url, reverse("relate-grant_exception_stage_3",
                                                                kwargs=params))

        # Check stage three page
        resp = self.c.get(reverse("relate-grant_exception_stage_3",
                                                                kwargs=params))
        self.assertEqual(resp.status_code, 200)

        # Should have no exception rule now
        self.assertEqual(len(FlowRuleException.objects.all()), 0)

        # Create a new exception rule
        datas = {'comment': ['test-rule'], 'save': ['Save'], 'view': ['on'],
                'see_answer_after_submission': ['on'],
                'create_grading_exception': ['on'],
                'create_access_exception': ['on'],
                'access_expires': [''], 'due': [''],
                'bonus_points': ['0.0'], 'max_points': [''],
                'credit_percent': ['100.0'], 'max_points_enforced_cap': [''],
                'generates_grade': ['on'], 'see_correctness': ['on']}
        resp = self.c.post(reverse("relate-grant_exception_stage_3",
                                                kwargs=params), datas)
        self.assertEqual(resp.status_code, 302)

        # Check redirect
        self.assertEqual(resp.url, reverse("relate-grant_exception",
                                        args=[self.datas["course_identifier"]]))

        # Should have two exception rules now
        # One for access and one for grading
        self.assertEqual(len(FlowRuleException.objects.all()), 2)

    # Helper method for testing grant exception view
    def check_stage_one_and_two(self):
        # Check stage one page
        resp = self.c.get(reverse("relate-grant_exception",
                                        args=[self.datas["course_identifier"]]))
        self.assertEqual(resp.status_code, 200)

        # Move to stage two
        # Shoud be only one participation record
        self.assertEqual(len(Participation.objects.all()), 1)
        participation = Participation.objects.all()[0]

        datas = {"next": ["Next \xbb"], "participation": [str(participation.id)],
                "flow_id": [self.datas["flow_id"]]}
        resp = self.c.post(reverse("relate-grant_exception",
                                    args=[self.datas["course_identifier"]]), datas)
        self.assertEqual(resp.status_code, 302)

        # Prepare parameters
        params = datas.copy()
        params["participation_id"] = params["participation"][0]
        params["course_identifier"] = self.datas["course_identifier"]
        params["flow_id"] = params["flow_id"][0]
        del params["next"]
        del params["participation"]
        # Check redirect
        self.assertEqual(resp.url, reverse("relate-grant_exception_stage_2",
                                                                kwargs=params))

        # Check stage two page
        resp = self.c.get(reverse("relate-grant_exception_stage_2",
                                                                kwargs=params))
        self.assertEqual(resp.status_code, 200)

        # Return params to reuse
        return params
