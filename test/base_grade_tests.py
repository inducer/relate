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

import cStringIO
import csv
from django.test import Client
from django.urls import resolve, reverse
from accounts.models import User
from course.models import FlowSession, Course, GradingOpportunity, \
                            Participation, FlowRuleException, ParticipationRole, \
                            GradeChange


# This serve as a base test cases for other grade tests to subclass
# Nice little tricks :)
class BaseGradeTest(object):

    @classmethod
    def setUpTestData(cls):  # noqa
        # Set up data for the whole TestCase
        # Admin account
        cls.admin = User.objects.create_superuser(
                username="testadmin",
                password="test",
                email="testadmin@example.com",
                first_name="Test",
                last_name="Admin")
        cls.admin.save()

        # Student account
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
            participation.course = Course.objects.filter(
                                    identifier=cls.datas["course_identifier"])[0]
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
        self.assertEqual(len(GradingOpportunity.objects.all()), 1)
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
        self.assertEqual(len(GradingOpportunity.objects.all()), 1)
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
        self.assertEqual(len(GradingOpportunity.objects.all()), 1)
        opportunity = GradingOpportunity.objects.all()[0]
        self.assertEqual(self.course, opportunity.course)
        self.assertEqual(self.datas["flow_id"], opportunity.flow_id)

        all_session = FlowSession.objects.all()
        # Check flow numbers
        self.assertEqual(len(all_session),
                                len(self.datas["flow_session_id"]))

        # Check each flow session
        for session in all_session:
            self.check_reopen_session(session.id, opportunity.id)

        # Check flow numbers again
        self.assertEqual(len(FlowSession.objects.all()),
                                len(self.datas["flow_session_id"]))

    def test_view_import_grades_without_header(self):
        csv_datas = [("testadmin", 99, "Almost!"),
                ("tester1", 50, "I hate this course :(")]
        self.check_import_grade(csv_datas)

    def test_view_import_grades_with_header(self):
        csv_datas = [("username", "grade", "feedback"),
                ("testadmin", 99, "Almost!"),
                ("tester1", 50, "I hate this course :(")]
        self.check_import_grade(csv_datas, True)

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
        self.assertEqual(len(GradingOpportunity.objects.all()), 1)
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
        all_session = FlowSession.objects.all()
        # Check number of flow sessions and ids
        self.assertEqual(len(all_session),
                                    len(self.datas["flow_session_id"]))
        for session in all_session:
            # Perform all checking before moving to stage three
            params = self.check_stage_one_and_two(session.participation)
            self.assertTrue(session.id in self.datas["flow_session_id"])
            self.check_grant_new_exception(params)

        # Should have two flow sessions now
        self.assertEqual(len(FlowSession.objects.all()), 2 * self.datas["accounts"])

    def test_view_grant_exception_exist_session(self):
        # Store numbers to reuse
        session_nums = len(self.datas["flow_session_id"])

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

    # Helper method for creating in memory csv files to test import grades
    def creat_grading_csv(self, datas):
        csvfile = cStringIO.StringIO()
        csvwriter = csv.writer(csvfile)
        for data in datas:
            # (username, grades, feedback)
            csvwriter.writerow([data[0], data[1], data[2]])
        # Reset back to the start of file to avoid invalid form error
        # Otherwise it will consider the file as empty
        csvfile.seek(0)
        return csvfile

    # Helper method for testing import grades
    def check_import_grade(self, csv_datas, headers=False):
        # Check import form works well
        resp = self.c.get(reverse("relate-import_grades",
                                            args=[self.datas["course_identifier"]]))
        self.assertEqual(resp.status_code, 200)

        # Check number of GradeChange
        self.assertEqual(len(GradeChange.objects.all()), self.datas["accounts"])

        # Check attributes
        self.assertEqual(len(GradingOpportunity.objects.all()), 1)
        opportunity = GradingOpportunity.objects.all()[0]
        self.assertEqual(self.course, opportunity.course)
        self.assertEqual(self.datas["flow_id"], opportunity.flow_id)

        # Prepare datas
        # Prepare csv
        csv_file = self.creat_grading_csv(csv_datas)
        # Prepare form datas
        datas = {'points_column': ['2'], 'attr_column': ['1'],
                'feedback_column': ['3'],
                'grading_opportunity': [str(opportunity.id)],
                'format': ['csv' + ('head' if headers else '')],
                'attempt_id': ['main'], 'max_points': ['100'],
                'import': ['Import'], 'attr_type': ['email_or_id'],
                'file': csv_file}

        # Check importing
        resp = self.c.post(reverse("relate-import_grades",
                                    args=[self.datas["course_identifier"]]), datas)
        self.assertEqual(resp.status_code, 200)

        # Check number of GradeChange
        num_diff = len(csv_datas) - 1 if headers else len(csv_datas)
        self.assertEqual(len(GradeChange.objects.all()),
                                            self.datas["accounts"] + num_diff)

    # Helper method for testing grant exceptions for new session
    def check_grant_new_exception(self, params):
        # Grant a new one
        datas = {'access_rules_tag_for_new_session': ['<<<NONE>>>'],
                    'create_session': ['Create session']}
        resp = self.c.post(reverse("relate-grant_exception_stage_2",
                                                kwargs=params), datas)
        self.assertEqual(resp.status_code, 200)

    # Helper method for testing grant exceptions for existing one
    def check_grant_exist_exception(self, session_id, parameters):
        params = parameters.copy()
        flow_session = FlowSession.objects.filter(id=session_id)[0]
        self.assertTrue(flow_session.id in self.datas["flow_session_id"])

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

    # Helper method for testing reopen session
    def check_reopen_session(self, session_id, opportunity_id):
        flow_session = FlowSession.objects.filter(id=session_id)[0]
        self.assertEqual(flow_session.in_progress, False)

        # Check reopen session form
        params = {"course_identifier": self.datas["course_identifier"],
                    "opportunity_id": opportunity_id,
                    "flow_session_id": session_id}
        resp = self.c.get(reverse("relate-view_reopen_session",
                                                    kwargs=params))
        self.assertEqual(resp.status_code, 200)

        # Reopen session
        datas = {'set_access_rules_tag': ['<<<NONE>>>'], 'comment': ['test-reopen'],
                                'unsubmit_pages': ['on'], 'reopen': ['Reopen']}
        resp = self.c.post(reverse("relate-view_reopen_session",
                                                    kwargs=params), datas)

        flow_session = FlowSession.objects.filter(id=session_id)[0]
        self.assertEqual(flow_session.in_progress, True)

    # Helper method for testing grant exception view
    def check_stage_one_and_two(self, participation):
        # Check stage one page
        resp = self.c.get(reverse("relate-grant_exception",
                                        args=[self.datas["course_identifier"]]))
        self.assertEqual(resp.status_code, 200)

        # Move to stage two
        # Shoud be only one participation record
        self.assertEqual(len(Participation.objects.all()), self.datas["accounts"])

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
