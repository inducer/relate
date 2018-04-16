from __future__ import division

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

import six
import csv
import os
from six import StringIO
from django.conf import settings  # noqa
from django.test import TestCase
from django.test.utils import override_settings  # noqa
from django.utils.timezone import now
from unittest import skipIf

from course import models

from course.constants import (
    grade_state_change_types as g_state)

from tests.base_test_mixins import SingleCoursePageTestMixin
from tests import factories as fctr  # noqa
from tests.factories import GradeChangeFactory as gc_factory  # noqa
from tests.utils import mock


class ExportGradebook(SingleCoursePageTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):  # noqa
        super(ExportGradebook, cls).setUpTestData()
        cls.gopp = fctr.GradingOpportunityFactory(course=cls.course)
        cls.student_participation.user.institutional_id = "1234"
        cls.student_participation.user.save()

        cls.session1 = fctr.FlowSessionFactory.create(
            participation=cls.instructor_participation)
        cls.ta_session = fctr.FlowSessionFactory.create(
            participation=cls.ta_participation)
        cls.instructor_gc = gc_factory.create(
            **(cls.gc(participation=cls.instructor_participation, points=90)))
        cls.student_gc = gc_factory.create(
            **(cls.gc(participation=cls.student_participation, points=86.66666)))

        assert models.GradingOpportunity.objects.count() == 1
        assert models.GradeChange.objects.count() == 2

    @classmethod
    def gc(cls, participation=None, state=None, attempt_id=None, points=None,
           max_points=None, comment=None, due_time=None,
           grade_time=None, flow_session=None, **kwargs):
        gc_kwargs = {
            "opportunity": cls.gopp,
            "participation": participation or cls.student_participation,
            "state": state or g_state.graded,
            "attempt_id": attempt_id,
            "points": points,
            "max_points": max_points or 100,
            "comment": comment,
            "due_time": due_time,
            "grade_time": grade_time or now(),
            "flow_session": flow_session,
        }
        gc_kwargs.update(kwargs)
        return gc_kwargs

    def setUp(self):
        super(ExportGradebook, self).setUp()
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

    def get_export_gradebook_csv(self, force_login_instructor=None):
        if force_login_instructor:
            user = self.instructor_participation.user
        else:
            user = self.get_logged_in_user()
        with self.temporarily_switch_to_user(user):
            return self.c.get(self.get_export_gradebook_csv_url())

    def test(self):
        pass


class ImportGradesTest(SingleCoursePageTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):  # noqa
        super(ImportGradesTest, cls).setUpTestData()
        cls.gopp = fctr.GradingOpportunityFactory(course=cls.course)
        cls.student_participation.user.institutional_id = "1234"
        cls.student_participation.user.save()
        assert models.GradeChange.objects.count() == 0

    def setUp(self):
        super(ImportGradesTest, self).setUp()

    def get_import_grades_url(self):
        return self.get_course_view_url("relate-import_grades")

    def get_import_grades(self, force_login_instructor=None):
        if force_login_instructor:
            user = self.instructor_participation.user
        else:
            user = self.get_logged_in_user()
        with self.temporarily_switch_to_user(user):
            return self.c.get(self.get_import_grades_url())

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
            return self.c.post(self.get_import_grades_url(), data=post_data)

    def test_preview_success(self):
        with open(
                os.path.join(os.path.dirname(__file__),
                             '../fixtures', 'csv', 'test_import_csv.csv'),
                'rb') as csv_file:
            resp = self.post_import_grades(csv_file, post_type="preview")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(models.GradeChange.objects.count(), 0)
            self.assertContains(resp, "This is the feedback for test_student")
            self.assertNotContains(resp, "This is the not imported feedback")

    def test_import_success(self):
        with open(
                os.path.join(os.path.dirname(__file__),
                             '../fixtures', 'csv', 'test_import_csv.csv'),
                'rb') as csv_file:
            resp = self.post_import_grades(csv_file)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(models.GradeChange.objects.count(), 1)

    def test_preview_success_no_header(self):
        with open(
                os.path.join(
                    os.path.dirname(__file__),
                    '../fixtures', 'csv', 'test_import_csv_no_header.csv'),
                'rb') as csv_file:
            resp = self.post_import_grades(csv_file, format="csv",
                                           post_type='preview')
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(models.GradeChange.objects.count(), 0)
            self.assertNotContains(resp, "This is the not imported feedback")

    def test_import_success_no_header(self):
        with open(
                os.path.join(
                    os.path.dirname(__file__),
                    '../fixtures', 'csv', 'test_import_csv_no_header.csv'),
                'rb') as csv_file:
            resp = self.post_import_grades(csv_file, format="csv")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(models.GradeChange.objects.count(), 1)

    def test_import_file_error(self):
        expected_file_error_msg = (
            "Error: line contains NULL byte. Are you sure the file is a "
            "CSV file other than a Microsoft Excel file?")

        with open(
                os.path.join(os.path.dirname(__file__),
                             '../fixtures', 'csv',
                             'test_import_excel_failed.xlsx'), 'rb') as csv_file:
            resp = self.post_import_grades(csv_file, format="csv")
            self.assertEqual(resp.status_code, 200)
            self.assertFormError(resp, "form", "file", expected_file_error_msg)
            self.assertEqual(models.GradeChange.objects.count(), 0)

    @skipIf(six.PY2, "csv for py2 seems won't raise expected error when "
                     "import an excel file.")
    def test_import_csv_reader_next_error(self):
        error_msg = "This is a faked error"
        expected_file_error_msg = (
            "Error: TypeError: %s" % error_msg)

        with open(
                os.path.join(os.path.dirname(__file__),
                             '../fixtures', 'csv', 'test_import_csv.csv'),
                'rb') as csv_file:
            with mock.patch("csv.reader") as mock_csv_reader:
                def sf():
                    raise TypeError(error_msg)

                mock_csv_reader.return_value.__next__.side_effect = sf
                resp = self.post_import_grades(csv_file, format="csv")
                self.assertEqual(resp.status_code, 200)
                self.assertFormError(resp, "form", "file", expected_file_error_msg)
                self.assertEqual(models.GradeChange.objects.count(), 0)

    def test_import_csv_unicode_error(self):
        error_msg = ("Columns to be imported contain non-ASCII "
                     "characters. Please save your CSV file as utf-8 "
                     "encoded and import again.")
        expected_file_error_msg = (
            "Error: %s" % error_msg)

        with open(
                os.path.join(os.path.dirname(__file__),
                             '../fixtures', 'csv', 'test_import_csv.csv'),
                'rb') as csv_file:
            with mock.patch(
                    "course.utils.get_col_contents_or_empty") as mock_get_col:
                def sf(row, index):
                    raise UnicodeDecodeError(
                        "something", b'something', 0, 1, "dont know")

                mock_get_col.side_effect = sf
                resp = self.post_import_grades(csv_file, format="csv")
                self.assertEqual(resp.status_code, 200)
                self.assertFormError(resp, "form", "file", expected_file_error_msg)
                self.assertEqual(models.GradeChange.objects.count(), 0)

    def test_import_csv_other_error(self):
        error_msg = ("Some other unkown error")
        expected_file_error_msg = (
            "Error: TypeError: %s" % error_msg)

        with open(
                os.path.join(os.path.dirname(__file__),
                             '../fixtures',
                             'csv', 'test_import_csv.csv'), 'rb') as csv_file:
            with mock.patch(
                    "course.utils.get_col_contents_or_empty") as mock_get_col:
                def sf(row, index):
                    raise TypeError(error_msg)

                mock_get_col.side_effect = sf
                resp = self.post_import_grades(csv_file, format="csv")
                self.assertEqual(resp.status_code, 200)
                self.assertFormError(resp, "form", "file", expected_file_error_msg)
                self.assertEqual(models.GradeChange.objects.count(), 0)

    def test_used_preserved_attempt_id(self):
        attempt_id = "flow-session-blabla"
        error_msg = '"%s" as a prefix is not allowed' % "flow-session-"

        with open(
                os.path.join(os.path.dirname(__file__),
                             '../fixtures',
                             'csv', 'test_import_csv.csv'), 'rb') as csv_file:
            resp = self.post_import_grades(csv_file, format="csv",
                                           attempt_id=attempt_id)
            self.assertEqual(resp.status_code, 200)
            self.assertFormError(resp, "form", "attempt_id", error_msg)
            self.assertEqual(models.GradeChange.objects.count(), 0)
