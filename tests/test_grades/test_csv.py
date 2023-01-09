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

import csv
import sys
import os
from io import StringIO
from django.test import TestCase
import unittest

from course import models, grades, constants
from course.constants import (
    grade_state_change_types as g_state)

from tests.base_test_mixins import CoursesTestMixinBase

from tests.test_grades.test_grades import GradesTestMixin

from tests import factories
from tests.factories import GradeChangeFactory as gc_factory  # noqa
from tests.utils import mock
from tests.constants import CSV_PATH


class ExportGradebook(GradesTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()
        cls.gopp = factories.GradingOpportunityFactory(course=cls.course)
        cls.student_participation.user.institutional_id = "1234"
        cls.student_participation.user.save()

        cls.session1 = factories.FlowSessionFactory.create(
            participation=cls.instructor_participation)
        cls.ta_session = factories.FlowSessionFactory.create(
            participation=cls.ta_participation)
        cls.instructor_gc = gc_factory.create(
            **(cls.gc(participation=cls.instructor_participation, points=90)))
        cls.student_gc = gc_factory.create(
            **(cls.gc(participation=cls.student_participation, points=86.66666)))

        assert models.GradingOpportunity.objects.count() == 1
        assert models.GradeChange.objects.count() == 2

    def setUp(self):
        super().setUp()
        self.gopp.refresh_from_db()
        self.ta_session.refresh_from_db()
        self.instructor_gc.refresh_from_db()
        self.student_gc.refresh_from_db()

    def assertResponseCsvResultEqual(self, resp, expected_result):  # noqa
        file_contents = StringIO(resp.content.decode())
        spamreader = csv.reader(file_contents)
        result = []
        for row in spamreader:
            result.append(row)
        self.assertEqual(result, expected_result)

    def assertResponseHasCsv(self, resp):  # noqa
        self.assertEqual(resp["Content-Disposition"],
                         'attachment; filename="grades-%s.csv"'
                         % self.course.identifier)

    def get_export_gradebook_csv_url(self):
        return self.get_course_view_url("relate-export_gradebook_csv")

    def get_export_gradebook_csv(self, force_login_instructor=True):
        if force_login_instructor:
            user = self.instructor_participation.user
        else:
            user = self.get_logged_in_user()
        with self.temporarily_switch_to_user(user):
            return self.client.get(self.get_export_gradebook_csv_url())

    def test_view_export_gradebook_csv(self):
        resp = self.get_export_gradebook_csv()
        self.assertEqual(resp.status_code, 200)
        self.assertResponseHasCsv(resp)


class FindParticipantFromIdTest(CoursesTestMixinBase, TestCase):
    # test grades.find_participant_from_id
    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()
        cls.course = factories.CourseFactory()
        cls.student_participation = factories.ParticipationFactory(
            course=cls.course)

    def test_found_iexact(self):
        self.assertEqual(grades.find_participant_from_id(
            self.course, self.student_participation.user.email.upper()),
            self.student_participation)

    def test_not_found_across_course(self):
        # This ensure course is filtered
        another_participation = factories.ParticipationFactory(
            course=factories.CourseFactory(identifier="another-course"))

        with self.assertRaises(grades.ParticipantNotFound):
            grades.find_participant_from_id(
                self.course,
                another_participation.user.email)

    def test_skip_not_active(self):
        dropped_participation = factories.ParticipationFactory(
            course=self.course, status=constants.participation_status.dropped)

        with self.assertRaises(grades.ParticipantNotFound) as cm:
            grades.find_participant_from_id(self.course,
                                            dropped_participation.user.email)
        expected_error_msg = (
                "no participant found for '%s'" % dropped_participation.user.email)
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_found_by_id(self):
        email = self.student_participation.user.email
        at_index = email.index("@")
        uid = email[:at_index].upper()
        self.assertEqual(grades.find_participant_from_id(
            self.course, uid),
            self.student_participation)

    def test_not_found(self):
        with self.assertRaises(grades.ParticipantNotFound) as cm:
            grades.find_participant_from_id(self.course, "blahblah@blah.com")
        expected_error_msg = "no participant found for 'blahblah@blah.com'"
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_not_found_email_not_match_exactly(self):
        idstr = self.student_participation.user.email.replace(".com", "")
        with self.assertRaises(grades.ParticipantNotFound) as cm:
            grades.find_participant_from_id(self.course, idstr)
        expected_error_msg = "no participant found for '%s'" % idstr
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_found_multiple(self):
        email = self.student_participation.user.email
        at_index = email.index("@")
        uid = email[:at_index]

        # create another participation with the same uid
        factories.ParticipationFactory(
            course=self.course, user=factories.UserFactory(
                email="%s@somewhere.com" % uid.upper()))

        with self.assertRaises(grades.ParticipantNotFound) as cm:
            grades.find_participant_from_id(self.course, uid)

        expected_error_msg = "more than one participant found for '%s'" % uid
        self.assertIn(expected_error_msg, str(cm.exception))


class FindParticipantFromUserAttrTest(CoursesTestMixinBase, TestCase):
    # test grades.find_participant_from_user_attr

    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()
        cls.course = factories.CourseFactory()
        cls.student_participation = factories.ParticipationFactory(
            course=cls.course)

    def test_found_strip_inst_id(self):
        self.assertEqual(grades.find_participant_from_user_attr(
            self.course, "institutional_id",
            "  %s  " % self.student_participation.user.institutional_id),
            self.student_participation)

    def test_found_iexact_by_inst_id(self):
        if (self.student_participation.user.institutional_id
                == self.student_participation.user.institutional_id.upper()):
            raise unittest.SkipTest(
                "The created user should have lower cased character to "
                "make the test meaningful.")

        self.assertEqual(grades.find_participant_from_user_attr(
            self.course, "institutional_id",
            self.student_participation.user.institutional_id.upper()),
            self.student_participation)

    def test_found_strip_username(self):
        self.assertEqual(grades.find_participant_from_user_attr(
            self.course, "username",
            "  %s " % self.student_participation.user.username),
            self.student_participation)

    def test_found_exact_by_username(self):
        self.assertEqual(grades.find_participant_from_user_attr(
            self.course, "username",
            self.student_participation.user.username),
            self.student_participation)

    def test_not_found_by_username_case_sensitive(self):
        if (self.student_participation.user.institutional_id
                == self.student_participation.user.institutional_id.upper()):
            raise unittest.SkipTest(
                "The created user should have lower cased character to "
                "make the test meaningful.")
        upper_user_name = self.student_participation.user.username.upper()
        with self.assertRaises(grades.ParticipantNotFound) as cm:
            grades.find_participant_from_user_attr(
                self.course, "username", upper_user_name)

        expected_error_msg = (
                "no participant found with username '%s'" % upper_user_name)
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_not_found_across_course(self):
        # This ensure course is filtered
        another_participation = factories.ParticipationFactory(
            course=factories.CourseFactory(identifier="another-course"))

        with self.assertRaises(grades.ParticipantNotFound) as cm:
            grades.find_participant_from_user_attr(
                self.course, "username", another_participation.user.username)

            expected_error_msg = (
                    "no participant found with username '%s'"
                    % another_participation.user.username)
            self.assertIn(expected_error_msg, str(cm.exception))

    def test_skip_not_active(self):
        dropped_participation = factories.ParticipationFactory(
            course=self.course, status=constants.participation_status.dropped)

        with self.assertRaises(grades.ParticipantNotFound) as cm:
            grades.find_participant_from_user_attr(
                self.course, "username", dropped_participation.user.username)

        expected_error_msg = (
                "no participant found with username '%s'"
                % dropped_participation.user.username)
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_multiple_found(self):
        exist_inst_id = self.student_participation.user.institutional_id
        another_student_participation = factories.ParticipationFactory(
            course=self.course,
            user=factories.UserFactory(institutional_id=exist_inst_id.upper()))

        with self.assertRaises(grades.ParticipantNotFound) as cm:
            grades.find_participant_from_user_attr(
                self.course, "institutional_id",
                another_student_participation.user.institutional_id)

        expected_error_msg = (
                "more than one participant found with Institutional ID '%s'"
                % another_student_participation.user.institutional_id)
        self.assertIn(expected_error_msg, str(cm.exception))


class ImportGradesTest(GradesTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()
        cls.gopp = factories.GradingOpportunityFactory(course=cls.course)
        cls.student_participation.user.institutional_id = "1234"
        cls.student_participation.user.save()
        assert models.GradeChange.objects.count() == 0

    def get_import_grades_url(self):
        return self.get_course_view_url("relate-import_grades")

    def get_import_grades(self, force_login_instructor=None):
        if force_login_instructor:
            user = self.instructor_participation.user
        else:
            user = self.get_logged_in_user()
        with self.temporarily_switch_to_user(user):
            return self.client.get(self.get_import_grades_url())

    def post_import_grades(self, csv_file=None, post_data=None,
                           force_login_instructor=True, post_type='import',
                           **kwargs):
        assert post_type in ['import', 'preview']
        if post_data is None:
            post_data = {
                'grading_opportunity': str(self.gopp.id),
                'attempt_id': 'main',
                'file': csv_file,
                'format': 'csvhead',  # or csv,
                'attr_type': 'email_or_id',  # or inst_id
                'attr_column': 1,
                'points_column': 5,
                'feedback_column': 6,
                'max_points': 100,
            }

        post_data.update(kwargs)

        post_data[post_type] = "on"

        if force_login_instructor:
            user = self.instructor_participation.user
        else:
            user = self.get_logged_in_user()
        with self.temporarily_switch_to_user(user):
            return self.client.post(self.get_import_grades_url(), data=post_data)

    def test_preview_success(self):
        with open(
                os.path.join(CSV_PATH, 'test_import_csv.csv'), 'rb') as csv_file:
            resp = self.post_import_grades(csv_file, post_type="preview")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(models.GradeChange.objects.count(), 0)
            self.assertContains(resp, "This is the feedback for test_student")
            self.assertNotContains(resp, "This is the not imported feedback")

    def test_preview_not_importing_feedback(self):
        with open(
                os.path.join(CSV_PATH, 'test_import_csv.csv'), 'rb') as csv_file:
            resp = self.post_import_grades(csv_file, post_type="preview",
                                           feedback_column="")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(models.GradeChange.objects.count(), 0)
            self.assertNotContains(resp, "This is the feedback for test_student")
            self.assertNotContains(resp, "This is the not imported feedback")

    def test_import_success(self):
        with open(
                os.path.join(CSV_PATH, 'test_import_csv.csv'), 'rb') as csv_file:
            resp = self.post_import_grades(csv_file)
            self.assertEqual(resp.status_code, 200)
            gchanges = models.GradeChange.objects.all()
            self.assertEqual(gchanges.count(), 1)
            gchange, = gchanges
            self.assertEqual(float(gchange.points), float(86.66))

    def test_import_success_by_username(self):
        with open(
                os.path.join(CSV_PATH, 'test_import_csv.csv'), 'rb') as csv_file:
            resp = self.post_import_grades(csv_file, attr_type="username")
            self.assertEqual(resp.status_code, 200)
            gchanges = models.GradeChange.objects.all()
            self.assertEqual(gchanges.count(), 1)
            gchange, = gchanges
            self.assertEqual(float(gchange.points), float(86.66))

    def test_import_success_by_inst_id(self):
        with open(
                os.path.join(CSV_PATH, 'test_import_csv.csv'), 'rb') as csv_file:
            resp = self.post_import_grades(
                csv_file,
                attr_type="institutional_id",
                attr_column=2)
            self.assertEqual(resp.status_code, 200)
            gchanges = models.GradeChange.objects.all()
            self.assertEqual(gchanges.count(), 1)
            gchange, = gchanges
            self.assertEqual(float(gchange.points), float(86.66))

    def test_import_success_not_importing_feedback(self):
        with open(
                os.path.join(CSV_PATH, 'test_import_csv.csv'), 'rb') as csv_file:
            resp = self.post_import_grades(csv_file, feedback_column="")
            self.assertEqual(resp.status_code, 200)
            gchanges = models.GradeChange.objects.all()
            self.assertEqual(gchanges.count(), 1)
            gchange, = gchanges
            self.assertEqual(float(gchange.points), float(86.66))

    def test_import_success_none_points(self):
        with open(
                os.path.join(CSV_PATH, 'test_import_csv_none_points.csv'),
                'rb') as csv_file:
            resp = self.post_import_grades(csv_file)
            self.assertEqual(resp.status_code, 200)
            gchanges = models.GradeChange.objects.all()
            self.assertEqual(gchanges.count(), 1)
            gchange, = gchanges
            self.assertEqual(gchange.points, None)

    def test_preview_success_no_header(self):
        with open(
                os.path.join(CSV_PATH, 'test_import_csv_no_header.csv'),
                'rb') as csv_file:
            resp = self.post_import_grades(csv_file, format="csv",
                                           post_type='preview')
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(models.GradeChange.objects.count(), 0)
            self.assertNotContains(resp, "This is the not imported feedback")

    def test_import_success_no_header(self):
        with open(
                os.path.join(CSV_PATH, 'test_import_csv_no_header.csv'),
                'rb') as csv_file:
            resp = self.post_import_grades(csv_file, format="csv")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(models.GradeChange.objects.count(), 1)

    def test_import_file_error(self):
        if sys.version_info >= (3, 11):
            expected_file_error_msg = (
                "Error: new-line character seen in unquoted field"
                # FIXME This message is incomplete.
                # This is incomplete.
                )
        else:
            expected_file_error_msg = (
                "Error: line contains NUL. Are you sure the file is a "
                "CSV file other than a Microsoft Excel file?")

        with open(
                os.path.join(CSV_PATH, 'test_import_excel_failed.xlsx'),
                'rb') as csv_file:
            resp = self.post_import_grades(csv_file, format="csv")
            self.assertEqual(resp.status_code, 200)
            if sys.version_info < (3, 11):
                self.assertFormError(resp.context["form"], "file",
                                     expected_file_error_msg)
            self.assertEqual(models.GradeChange.objects.count(), 0)

    def test_import_csv_reader_next_error(self):
        error_msg = "This is a faked error"
        expected_file_error_msg = (
            "Error: TypeError: %s" % error_msg)

        with open(
                os.path.join(CSV_PATH, 'test_import_csv.csv'), 'rb') as csv_file:
            with mock.patch("csv.reader") as mock_csv_reader:
                def sf():
                    raise TypeError(error_msg)

                mock_csv_reader.return_value.__next__.side_effect = sf
                resp = self.post_import_grades(csv_file, format="csv")
                self.assertEqual(resp.status_code, 200)
                self.assertFormError(
                        resp.context["form"], "file", expected_file_error_msg)
                self.assertEqual(models.GradeChange.objects.count(), 0)

    def test_import_csv_unicode_error(self):
        error_msg = ("Columns to be imported contain non-ASCII "
                     "characters. Please save your CSV file as utf-8 "
                     "encoded and import again.")
        expected_file_error_msg = (
            "Error: %s" % error_msg)

        with open(
                os.path.join(CSV_PATH, 'test_import_csv.csv'), 'rb') as csv_file:
            with mock.patch(
                    "course.utils.get_col_contents_or_empty") as mock_get_col:
                def sf(row, index):
                    raise UnicodeDecodeError(
                        "something", b'something', 0, 1, "dont know")

                mock_get_col.side_effect = sf
                resp = self.post_import_grades(csv_file, format="csv")
                self.assertEqual(resp.status_code, 200)
                self.assertFormError(
                        resp.context["form"], "file", expected_file_error_msg)
                self.assertEqual(models.GradeChange.objects.count(), 0)

    def test_import_csv_other_error(self):
        error_msg = ("Some other unkown error")
        expected_file_error_msg = (
            "Error: TypeError: %s" % error_msg)

        with open(
                os.path.join(CSV_PATH, 'test_import_csv.csv'), 'rb') as csv_file:
            with mock.patch(
                    "course.utils.get_col_contents_or_empty") as mock_get_col:
                def sf(row, index):
                    raise TypeError(error_msg)

                mock_get_col.side_effect = sf
                resp = self.post_import_grades(csv_file, format="csv")
                self.assertEqual(resp.status_code, 200)
                self.assertFormError(
                        resp.context["form"], "file", expected_file_error_msg)
                self.assertEqual(models.GradeChange.objects.count(), 0)

    def test_used_preserved_attempt_id(self):
        attempt_id = "flow-session-blabla"
        error_msg = '"%s" as a prefix is not allowed' % "flow-session-"

        with open(
                os.path.join(CSV_PATH, 'test_import_csv.csv'), 'rb') as csv_file:
            resp = self.post_import_grades(csv_file, format="csv",
                                           attempt_id=attempt_id)
            self.assertEqual(resp.status_code, 200)
            self.assertFormError(resp.context["form"], "attempt_id", error_msg)
            self.assertEqual(models.GradeChange.objects.count(), 0)

    def test_has_last_grades_points_updated(self):
        factories.GradeChangeFactory(
            **self.gc(opportunity=self.gopp, points=86.66))
        factories.GradeChangeFactory(
            **self.gc(opportunity=self.gopp, points=88))
        gchanges = models.GradeChange.objects.all()
        self.assertEqual(gchanges.count(), 2)

        with open(
                os.path.join(CSV_PATH, 'test_import_csv.csv'), 'rb') as csv_file:
            resp = self.post_import_grades(csv_file, feedback_column="")
            self.assertContains(
                resp,
                "test_student in test-course as student: points updated")

            self.assertEqual(resp.status_code, 200)
            gchanges = models.GradeChange.objects.all()
            self.assertEqual(gchanges.count(), 3)
            gchange = gchanges.last()
            self.assertEqual(float(gchange.points), float(86.66))

    def test_has_last_grades_max_points_updated(self):
        factories.GradeChangeFactory(
            **self.gc(opportunity=self.gopp, points=86.66, max_points=90))
        gchanges = models.GradeChange.objects.all()
        self.assertEqual(gchanges.count(), 1)

        with open(
                os.path.join(CSV_PATH, 'test_import_csv.csv'), 'rb') as csv_file:
            resp = self.post_import_grades(csv_file, feedback_column="")
            self.assertContains(
                resp,
                "test_student in test-course as student: max_points updated")

            self.assertEqual(resp.status_code, 200)
            gchanges = models.GradeChange.objects.all()
            self.assertEqual(gchanges.count(), 2)
            gchange = gchanges.last()
            self.assertEqual(float(gchange.points), float(86.66))

    def test_has_last_grades_multiple_attrs_updated(self):
        factories.GradeChangeFactory(
            **self.gc(opportunity=self.gopp, points=85,
                      max_points=90, comment="first grades"))
        gchanges = models.GradeChange.objects.all()
        self.assertEqual(gchanges.count(), 1)

        with open(
                os.path.join(CSV_PATH, 'test_import_csv.csv'), 'rb') as csv_file:
            resp = self.post_import_grades(csv_file)
            self.assertContains(
                resp,
                "test_student in test-course as student: points, max_points, "
                "comment updated")

            self.assertEqual(resp.status_code, 200)
            gchanges = models.GradeChange.objects.all()
            self.assertEqual(gchanges.count(), 2)
            gchange = gchanges.last()
            self.assertEqual(float(gchange.points), float(86.66))

    def test_has_last_grades_state_not_graded(self):
        factories.GradeChangeFactory(
            **self.gc(opportunity=self.gopp, points=None,
                      max_points=100, comment="not grades",
                      state=g_state.grading_started))
        gchanges = models.GradeChange.objects.all()
        self.assertEqual(gchanges.count(), 1)

        with open(
                os.path.join(CSV_PATH, 'test_import_csv.csv'), 'rb') as csv_file:
            resp = self.post_import_grades(csv_file)

            self.assertEqual(resp.status_code, 200)
            gchanges = models.GradeChange.objects.all()
            self.assertEqual(gchanges.count(), 2)
            gchange = gchanges.last()
            self.assertEqual(float(gchange.points), float(86.66))

    def test_re_import_same(self):
        with open(
                os.path.join(CSV_PATH, 'test_import_csv.csv'), 'rb') as csv_file:
            self.post_import_grades(csv_file)
            gchanges = models.GradeChange.objects.all()
            self.assertEqual(gchanges.count(), 1)

        # re-import
        with open(
                os.path.join(CSV_PATH, 'test_import_csv.csv'), 'rb') as csv_file:
            self.post_import_grades(csv_file)
            gchanges = models.GradeChange.objects.all()
            self.assertEqual(gchanges.count(), 1)

    def test_unexpected_error_for_csv_to_grade_changes(self):
        with mock.patch(
                "course.grades.csv_to_grade_changes") as mock_csv_to_grade_changes:
            mock_csv_to_grade_changes.side_effect = RuntimeError("my import error")
            with open(
                    os.path.join(CSV_PATH, 'test_import_csv.csv'), 'rb') as csv_file:
                self.post_import_grades(csv_file)
                gchanges = models.GradeChange.objects.all()
                self.assertEqual(gchanges.count(), 0)

        self.assertAddMessageCalledWith("Error: RuntimeError my import error")
