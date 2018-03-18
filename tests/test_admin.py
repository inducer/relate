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

import six
from unittest import skipIf

from django.test import TestCase, RequestFactory
from django.contrib.admin import site

from course import models, admin

from tests.base_test_mixins import AdminTestMixin
from tests import factories
from tests.contants import QUIZ_FLOW_ID


class CourseAdminTest(AdminTestMixin, TestCase):

    @classmethod
    def setUpTestData(cls):  # noqa
        super(CourseAdminTest, cls).setUpTestData()  # noqa

        cls.course1_session = factories.FlowSessionFactory.create(
            participation=cls.course1_student_participation2,
            flow_id="001-linalg-recap")
        course1_flow_page_data = factories.FlowPageDataFactory.create(
            flow_session=cls.course1_session
        )
        cls.coures1_visit = (
            factories.FlowPageVisitFactory.create(page_data=course1_flow_page_data))
        cls.course1_session_count = 1
        cls.course1_visits_count = 1
        cls.course1_event = (factories.EventFactory.create(
            course=cls.course1, kind="course1_kind"))
        cls.course1_event_count = 1

        cls.course2_sessions = factories.FlowSessionFactory.create_batch(
            size=3, participation=cls.course2_student_participation)
        cls.course2_session_count = 3
        for session in cls.course2_sessions:
            course2_flow_page_data = factories.FlowPageDataFactory.create(
                flow_session=session
            )
            factories.FlowPageVisitFactory.create(page_data=course2_flow_page_data)
        cls.course2_visits = models.FlowPageVisit.objects.filter(
            flow_session__course=cls.course2)
        cls.course2_visits_count = cls.course2_visits.count()

        cls.course2_events = factories.EventFactory.create_batch(
            size=5, course=cls.course2, kind="course2_kind")
        cls.course2_event_count = len(cls.course2_events)

    @classmethod
    def get_admin_change_list_view_url(cls, model_name):
        return super(CourseAdminTest, cls).get_admin_change_list_view_url(
            app_name="course", model_name=model_name.lower())

    @classmethod
    def get_admin_change_view_url(cls, model_name, args=None):
        return super(CourseAdminTest, cls).get_admin_change_view_url(
            app_name="course", model_name=model_name.lower(), args=args)

    def setUp(self):
        super(CourseAdminTest, self).setUp()
        self.superuser.refresh_from_db()
        self.rf = RequestFactory()

    def list_filter_result(self, model_class, model_admin_class,
                           expected_counts_dict):
        modeladmin = model_admin_class(model_class, site)

        for user in [self.superuser, self.instructor1, self.instructor2]:
            with self.subTest(user=user):
                request = self.rf.get(
                    self.get_admin_change_list_view_url(model_class.__name__), {})
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

    @skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_flowsession_filter_result(self):
        self.list_filter_result(
            models.FlowSession, admin.FlowSessionAdmin,
            expected_counts_dict={
                "all": (self.course1_session_count + self.course2_session_count),
                "course1": self.course1_session_count,
                "course2": self.course2_session_count
            })

    @skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_event_filter_result(self):
        self.list_filter_result(
            models.Event, admin.EventAdmin,
            expected_counts_dict={
                "all": (self.course1_event_count + self.course2_event_count),
                "course1": self.course1_event_count,
                "course2": self.course2_event_count
            })

    @skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_participation_filter_result(self):
        self.list_filter_result(
            models.Participation, admin.ParticipationAdmin,
            expected_counts_dict={
                "all": models.Participation.objects.count(),
                "course1":
                    models.Participation.objects.filter(course=self.course1).count(),
                "course2":
                    models.Participation.objects.filter(course=self.course2).count(),
            })

    @skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_flowpagevisit_filter_result(self):
        self.list_filter_result(
            models.FlowPageVisit, admin.FlowPageVisitAdmin,
            expected_counts_dict={
                "all": self.course1_visits_count + self.course2_visits_count,
                "course1": self.course1_visits_count,
                "course2": self.course2_visits_count
            })

    @skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_flowpagevisit_flow_id_filter_result(self):
        modeladmin = admin.FlowPageVisitAdmin(models.FlowPageVisit, site)

        for user in [self.superuser, self.instructor1, self.instructor2]:
            with self.subTest(user=user):
                request = self.rf.get(
                    self.get_admin_change_list_view_url("FlowPageVisit"), {})
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
                        (QUIZ_FLOW_ID, ), filterspec_list)
                else:
                    assert request.user == self.instructor2
                    self.assertNotIn(
                        ('All', "001-linalg-recap", QUIZ_FLOW_ID),
                        filterspec_list)
                    self.assertNotIn(
                        ('All', "001-linalg-recap"), filterspec_list)
                    self.assertNotIn(
                        ("001-linalg-recap", ), filterspec_list)

    def test_flowpagevisit_get_queryset_by_flow_id_filter(self):
        modeladmin = admin.FlowPageVisitAdmin(models.FlowPageVisit, site)

        request = self.rf.get(
            self.get_admin_change_list_view_url("FlowPageVisit"),
            {"flow_id": "001-linalg-recap"})
        request.user = self.instructor1
        changelist = self.get_changelist(
            request, models.FlowPageVisit, modeladmin)

        queryset = changelist.get_queryset(request)
        self.assertEqual(queryset.count(), self.course1_visits_count)

# vim: foldmethod=marker
