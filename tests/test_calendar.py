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

import pytz
import json
import datetime

from django.test import TestCase
from django.utils.timezone import now, timedelta
from django.core.exceptions import ValidationError

from relate.utils import as_local_time

from course.models import Event
from course import calendar

from tests.base_test_mixins import (
    SingleCourseTestMixin, MockAddMessageMixing, HackRepoMixin)
from tests.utils import mock
from tests import factories
from tests.constants import DATE_TIME_PICKER_TIME_FORMAT


class CreateRecurringEventsTest(SingleCourseTestMixin,
                                MockAddMessageMixing, TestCase):
    """test course.calendar.create_recurring_events"""
    default_event_kind = "lecture"

    def get_create_recurring_events_url(self, course_identifier=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        return self.get_course_view_url(
            "relate-create_recurring_events", course_identifier)

    def get_create_recurring_events_view(self, course_identifier=None,
                                         force_login_instructor=True):
        course_identifier = course_identifier or self.get_default_course_identifier()
        if not force_login_instructor:
            user = self.get_logged_in_user()
        else:
            user = self.instructor_participation.user

        with self.temporarily_switch_to_user(user):
            return self.c.get(
                self.get_create_recurring_events_url(course_identifier))

    def post_create_recurring_events_view(self, data, course_identifier=None,
                                          force_login_instructor=True):
        course_identifier = course_identifier or self.get_default_course_identifier()
        if not force_login_instructor:
            user = self.get_logged_in_user()
        else:
            user = self.instructor_participation.user

        with self.temporarily_switch_to_user(self.client, user):
            return self.c.post(
                self.get_create_recurring_events_url(course_identifier), data)

    def get_post_create_recur_evt_data(
            self, op="submit", starting_ordinal=None, **kwargs):
        data = {
            "kind": self.default_event_kind,
            "time": now().replace(tzinfo=None).strftime(
                DATE_TIME_PICKER_TIME_FORMAT),
            "interval": "weekly",
            "count": 5,
            op: "",
        }

        if starting_ordinal:
            data["starting_ordinal"] = starting_ordinal

        data.update(kwargs)
        return data

    def test_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_create_recurring_events_view(
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 302)

            resp = self.post_create_recurring_events_view(
                data={}, force_login_instructor=False)
            self.assertEqual(resp.status_code, 302)

    def test_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_create_recurring_events_view(
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

            resp = self.post_create_recurring_events_view(
                data={}, force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

    def test_get_success(self):
        resp = self.get_create_recurring_events_view()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 0)

    def test_post_form_not_valid(self):
        with mock.patch(
                "course.calendar.RecurringEventForm.is_valid"
        ) as mock_form_valid:
            mock_form_valid.return_value = False
            resp = self.post_create_recurring_events_view(
                data=self.get_post_create_recur_evt_data())
            self.assertEqual(resp.status_code, 200)

    def test_post_success_starting_ordinal_specified(self):
        resp = self.post_create_recurring_events_view(
            data=self.get_post_create_recur_evt_data(starting_ordinal=4))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 5)
        self.assertListEqual(
            list(Event.objects.values_list("ordinal", flat=True)),
            [4, 5, 6, 7, 8])

        t = None
        for evt in Event.objects.all():
            if t is None:
                t = evt.time
                continue
            else:
                self.assertTrue(
                        evt.time - t
                        >= (
                            datetime.timedelta(weeks=1)
                            - datetime.timedelta(hours=1)))
                self.assertTrue(
                        evt.time - t
                        <= (
                            datetime.timedelta(weeks=1)
                            + datetime.timedelta(hours=1)))
                t = evt.time

    def test_post_success_starting_ordinal_not_specified(self):
        resp = self.post_create_recurring_events_view(
            data=self.get_post_create_recur_evt_data())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 5)
        self.assertListEqual(
            list(Event.objects.values_list("ordinal", flat=True)),
            [1, 2, 3, 4, 5])

    def test_post_success_starting_ordinal_not_specified_skip_exist(self):
        factories.EventFactory(
            course=self.course, kind=self.default_event_kind, ordinal=4)
        resp = self.post_create_recurring_events_view(
            data=self.get_post_create_recur_evt_data())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 6)
        self.assertListEqual(
            list(Event.objects.values_list("ordinal", flat=True)),
            [4, 11, 12, 13, 14, 15])

    def test_post_event_already_exists_starting_ordinal_specified(self):
        factories.EventFactory(
            course=self.course, kind=self.default_event_kind, ordinal=7)
        resp = self.post_create_recurring_events_view(
            data=self.get_post_create_recur_evt_data(starting_ordinal=4))
        self.assertEqual(resp.status_code, 200)

        # not created
        self.assertEqual(Event.objects.count(), 1)

        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(
            "EventAlreadyExists: 'lecture 7' already exists. "
            "No events created.")

    def test_post_event_already_exists_starting_ordinal_not_specified(self):
        factories.EventFactory(
            course=self.course, kind=self.default_event_kind, ordinal=4)
        resp = self.post_create_recurring_events_view(
            data=self.get_post_create_recur_evt_data())
        self.assertEqual(resp.status_code, 200)

        # created and ordinal is not None
        self.assertEqual(
            Event.objects.filter(
                kind=self.default_event_kind, ordinal__isnull=False).count(), 6)

        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("Events created.")

    def test_event_save_unknown_error(self):
        error_msg = "my unknown error"
        with mock.patch("course.models.Event.save") as mock_event_save:
            mock_event_save.side_effect = RuntimeError(error_msg)
            resp = self.post_create_recurring_events_view(
                data=self.get_post_create_recur_evt_data(starting_ordinal=4))
            self.assertEqual(resp.status_code, 200)

        # not created
        self.assertEqual(Event.objects.count(), 0)
        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith(
            "RuntimeError: %s. No events created." % error_msg)

    def test_event_save_other_validation_error(self):
        error_msg = "my unknown validation error for end_time"
        with mock.patch("course.models.Event.save") as mock_event_save:
            # mock error raised by event.end_time
            mock_event_save.side_effect = (
                ValidationError({"end_time": error_msg}))
            resp = self.post_create_recurring_events_view(
                data=self.get_post_create_recur_evt_data(starting_ordinal=4))
            self.assertEqual(resp.status_code, 200)

        # form error was raised instead of add_message
        self.assertFormErrorLoose(resp, error_msg)
        self.assertAddMessageCallCount(0)

        # not created
        self.assertEqual(Event.objects.count(), 0)

    def test_duration_in_minutes(self):
        resp = self.post_create_recurring_events_view(
            data=self.get_post_create_recur_evt_data(
                starting_ordinal=4, duration_in_minutes=20))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 5)
        self.assertListEqual(
            list(Event.objects.values_list("ordinal", flat=True)),
            [4, 5, 6, 7, 8])

        t = None
        for evt in Event.objects.all():
            self.assertEqual(evt.end_time - evt.time, timedelta(minutes=20))
            if t is None:
                t = evt.time
                continue
            else:
                # One hour slack to avoid failure due to daylight savings.
                self.assertTrue(evt.time - t >= (
                    datetime.timedelta(weeks=1) - datetime.timedelta(hours=1)))
                self.assertTrue(evt.time - t <= (
                    datetime.timedelta(weeks=1) + datetime.timedelta(hours=1)))
                t = evt.time

    def test_interval_biweekly(self):
        resp = self.post_create_recurring_events_view(
            data=self.get_post_create_recur_evt_data(
                starting_ordinal=4, interval="biweekly"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 5)
        self.assertListEqual(
            list(Event.objects.values_list("ordinal", flat=True)),
            [4, 5, 6, 7, 8])

        t = None
        for evt in Event.objects.all():
            if t is None:
                t = evt.time
                continue
            else:
                # One hour slack to avoid failure due to daylight savings.
                self.assertTrue(evt.time - t >= (
                    datetime.timedelta(weeks=2) - datetime.timedelta(hours=1)))
                self.assertTrue(evt.time - t <= (
                    datetime.timedelta(weeks=2) + datetime.timedelta(hours=1)))
                t = evt.time


class RecurringEventFormTest(SingleCourseTestMixin, TestCase):
    """test course.calendar.RecurringEventForm"""
    def test_valid(self):
        form_data = {
            "kind": "some_kind",
            "time": now().replace(tzinfo=None).strftime(
                DATE_TIME_PICKER_TIME_FORMAT),
            "interval": "weekly",
            "count": 2
        }
        form = calendar.RecurringEventForm(
            self.course.identifier,
            data=form_data)
        self.assertTrue(form.is_valid())

    def test_negative_duration_in_minutes(self):
        form_data = {
            "kind": "some_kind",
            "time": now().replace(tzinfo=None).strftime(
                DATE_TIME_PICKER_TIME_FORMAT),
            "duration_in_minutes": -1,
            "interval": "weekly",
            "count": 5
        }
        form = calendar.RecurringEventForm(self.course.identifier, data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn(
            "Ensure this value is greater than or equal to 0.",
            form.errors["duration_in_minutes"])

    def test_negative_event_count(self):
        form_data = {
            "kind": "some_kind",
            "time": now().replace(tzinfo=None).strftime(
                DATE_TIME_PICKER_TIME_FORMAT),
            "interval": "weekly",
            "count": -1
        }
        form = calendar.RecurringEventForm(self.course.identifier, data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn(
            "Ensure this value is greater than or equal to 0.",
            form.errors["count"])

    def test_available_kind_choices(self):
        factories.EventFactory(
            course=self.course, kind="some_kind1", ordinal=None)
        factories.EventFactory(
            course=self.course, kind="some_kind2", ordinal=1)
        another_course = factories.CourseFactory(identifier="another-course")
        factories.EventFactory(
            course=another_course, kind="some_kind3", ordinal=1)
        factories.EventFactory(
            course=another_course, kind="some_kind4", ordinal=1)
        form = calendar.RecurringEventForm(self.course.identifier)
        self.assertIn(
            '<option value="some_kind1">some_kind1</option>', form.as_p())
        self.assertIn(
            '<option value="some_kind2">some_kind2</option>', form.as_p())

        self.assertNotIn(
            '<option value="some_kind3">some_kind3</option>', form.as_p())
        self.assertNotIn(
            '<option value="some_kind4">some_kind4</option>', form.as_p())


class RenumberEventsTest(SingleCourseTestMixin,
                         MockAddMessageMixing, TestCase):
    """test course.calendar.create_recurring_events"""
    default_event_kind = "lecture"

    def get_renumber_events_events_url(self, course_identifier=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        return self.get_course_view_url(
            "relate-renumber_events", course_identifier)

    def get_renumber_events_view(self, course_identifier=None,
                                 force_login_instructor=True):
        course_identifier = course_identifier or self.get_default_course_identifier()
        if not force_login_instructor:
            user = self.get_logged_in_user()
        else:
            user = self.instructor_participation.user

        with self.temporarily_switch_to_user(user):
            return self.c.get(
                self.get_renumber_events_events_url(course_identifier))

    def post_renumber_events_view(self, data, course_identifier=None,
                                  force_login_instructor=True):
        course_identifier = course_identifier or self.get_default_course_identifier()
        if not force_login_instructor:
            user = self.get_logged_in_user()
        else:
            user = self.instructor_participation.user

        with self.temporarily_switch_to_user(user):
            return self.c.post(
                self.get_renumber_events_events_url(course_identifier), data)

    def get_post_renumber_evt_data(
            self, starting_ordinal, kind=None, op="submit", **kwargs):

        data = {
            "kind": kind or self.default_event_kind,
            "starting_ordinal": starting_ordinal,
            "preserve_ordinal_order": False}

        data.update(kwargs)
        return data

    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()
        times = []
        now_time = now()
        for i in range(5):
            times.append(now_time)
            now_time += timedelta(weeks=1)
            factories.EventFactory(
                kind=cls.default_event_kind, ordinal=i * 2 + 1, time=now_time)

        cls.evt1, cls.evt2, cls.evt3, cls.evt4, cls.evt5 = Event.objects.all()

        for i in range(2):
            factories.EventFactory(
                kind="another_kind", ordinal=i * 3 + 1, time=now_time)
            now_time += timedelta(weeks=1)

        cls.evt_another_kind1, cls.evt_another_kind2 = (
            Event.objects.filter(kind="another_kind"))
        cls.evt_another_kind1_ordinal = cls.evt_another_kind1.ordinal
        cls.evt_another_kind2_ordinal = cls.evt_another_kind2.ordinal

    def setUp(self):
        super().setUp()
        self.evt1.refresh_from_db()
        self.evt2.refresh_from_db()
        self.evt3.refresh_from_db()
        self.evt4.refresh_from_db()
        self.evt5.refresh_from_db()

    def test_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_renumber_events_view(
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 302)

            resp = self.post_renumber_events_view(data={},
                                                  force_login_instructor=False)
            self.assertEqual(resp.status_code, 302)

    def test_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_renumber_events_view(
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

            resp = self.post_renumber_events_view(data={},
                                                  force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

    def test_get_success(self):
        resp = self.get_renumber_events_view()
        self.assertEqual(resp.status_code, 200)

    def test_post_form_not_valid(self):
        with mock.patch(
                "course.calendar.RenumberEventsForm.is_valid"
        ) as mock_form_valid:
            mock_form_valid.return_value = False

            resp = self.post_renumber_events_view(
                data=self.get_post_renumber_evt_data(starting_ordinal=3))
            self.assertEqual(resp.status_code, 200)

        all_default_evts = Event.objects.filter(kind=self.default_event_kind)
        self.assertEqual(all_default_evts.count(), 5)
        self.assertListEqual(
            list(all_default_evts.values_list("ordinal", flat=True)),
            [1, 3, 5, 7, 9])

        t = None
        for evt in all_default_evts:
            if t is None:
                t = evt.time
                continue
            else:
                self.assertEqual(evt.time - t, datetime.timedelta(weeks=1))
                t = evt.time

        # other events also not affected
        self.evt_another_kind1.refresh_from_db()
        self.evt_another_kind2.refresh_from_db()
        self.assertEqual(
            self.evt_another_kind1.ordinal, self.evt_another_kind1_ordinal)
        self.assertEqual(
            self.evt_another_kind2.ordinal, self.evt_another_kind2_ordinal)

    def test_post_success(self):
        resp = self.post_renumber_events_view(
            data=self.get_post_renumber_evt_data(starting_ordinal=3))
        self.assertEqual(resp.status_code, 200)
        all_pks = list(Event.objects.values_list("pk", flat=True))

        # originally 1, 3, 5, 7, 9, now 3, 4, 5, 6, 7

        all_default_evts = Event.objects.filter(kind=self.default_event_kind)
        self.assertEqual(all_default_evts.count(), 5)
        self.assertListEqual(
            list(all_default_evts.values_list("ordinal", flat=True)),
            [3, 4, 5, 6, 7])

        t = None
        for evt in all_default_evts:
            if t is None:
                t = evt.time
                continue
            else:
                self.assertEqual(evt.time - t, datetime.timedelta(weeks=1))
                t = evt.time

        # other events not affected
        self.evt_another_kind1.refresh_from_db()
        self.evt_another_kind2.refresh_from_db()
        self.assertEqual(
            self.evt_another_kind1.ordinal, self.evt_another_kind1_ordinal)
        self.assertEqual(
            self.evt_another_kind2.ordinal, self.evt_another_kind2_ordinal)

        # no new objects created
        self.assertListEqual(
            list(Event.objects.values_list("pk", flat=True)), all_pks)

        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("Events renumbered.")

    def test_renumber_non_existing_events(self):
        resp = self.post_renumber_events_view(
            data=self.get_post_renumber_evt_data(
                kind="foo_kind", starting_ordinal=3))
        self.assertEqual(resp.status_code, 200)
        expected_errors = ["Select a valid choice. foo_kind is "
                           "not one of the available choices."]
        self.assertFormError(resp, "form", "kind", expected_errors)

    def test_renumber_preserve_ordinal_order(self):

        # make evt1 the latest, evt5 the earliest
        time1, time5 = self.evt1.time, self.evt5.time
        self.evt1.time, self.evt5.time = time5, time1
        self.evt1.save()
        self.evt5.save()

        all_default_evts = Event.objects.filter(kind=self.default_event_kind)
        self.assertEqual(all_default_evts.count(), 5)
        self.assertListEqual(
            list(
                all_default_evts.order_by("time").values_list("ordinal", flat=True)),
            [9, 3, 5, 7, 1])

        resp = self.post_renumber_events_view(
            data=self.get_post_renumber_evt_data(
                starting_ordinal=3, preserve_ordinal_order=True))
        self.assertEqual(resp.status_code, 200)

        # originally (ordered by time) 9, 3, 5, 7, 1, now 7, 4, 5, 6, 3
        all_default_evts = Event.objects.filter(kind=self.default_event_kind)
        self.assertEqual(all_default_evts.count(), 5)
        self.assertListEqual(
            list(
                all_default_evts.order_by("time").values_list("ordinal", flat=True)),
            [7, 4, 5, 6, 3])

        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("Events renumbered.")

    def test_no_ordinal_event_not_renumbered(self):

        no_ordinal_event = factories.EventFactory(
            kind=self.default_event_kind, ordinal=None)

        resp = self.post_renumber_events_view(
            data=self.get_post_renumber_evt_data(
                starting_ordinal=3, preserve_ordinal_order=True))
        self.assertEqual(resp.status_code, 200)

        all_evts_with_ordinal = Event.objects.filter(
            kind=self.default_event_kind, ordinal__isnull=False)
        self.assertEqual(all_evts_with_ordinal.count(), 5)
        self.assertListEqual(
            list(all_evts_with_ordinal.values_list("ordinal", flat=True)),
            [3, 4, 5, 6, 7])

        no_ordinal_event.refresh_from_db()
        self.assertEqual(no_ordinal_event.kind, self.default_event_kind)
        self.assertIsNone(no_ordinal_event.ordinal)

        self.assertAddMessageCallCount(1)
        self.assertAddMessageCalledWith("Events renumbered.")


class ViewCalendarTest(SingleCourseTestMixin, HackRepoMixin, TestCase):
    """test course.calendar.view_calendar"""

    default_faked_now = datetime.datetime(2019, 1, 1, tzinfo=pytz.UTC)
    default_event_time = default_faked_now - timedelta(hours=12)
    default_event_kind = "lecture"

    def setUp(self):
        super().setUp()
        fake_get_now_or_fake_time = mock.patch(
            "course.views.get_now_or_fake_time")
        self.mock_get_now_or_fake_time = fake_get_now_or_fake_time.start()
        self.mock_get_now_or_fake_time.return_value = now()
        self.addCleanup(fake_get_now_or_fake_time.stop)

        self.addCleanup(factories.EventFactory.reset_sequence)

    def get_course_calendar_view(self, course_identifier=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        return self.c.get(self.get_course_calender_url(course_identifier))

    def switch_to_fake_commit_sha(self):
        self.course.active_git_commit_sha = "my_fake_commit_sha_for_events"
        self.course.events_file = "events.yml"
        self.course.save()

    def test_no_pperm(self):
        with mock.patch(
                "course.utils.CoursePageContext.has_permission"
        ) as mock_has_pperm:
            mock_has_pperm.return_value = False
            resp = self.get_course_calendar_view()
            self.assertEqual(resp.status_code, 403)

    def test_neither_events_nor_event_file(self):
        self.mock_get_now_or_fake_time.return_value = self.default_faked_now
        resp = self.get_course_calendar_view()
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(resp, "events_json", '[]')
        self.assertResponseContextEqual(resp, "event_info_list", [])
        self.assertResponseContextEqual(
            resp, "default_date", self.default_faked_now.date().isoformat())

    def test_no_event_file(self):
        evt1 = factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=self.default_event_time)
        evt2 = factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=self.default_event_time + timedelta(hours=1))

        resp = self.get_course_calendar_view()
        self.assertEqual(resp.status_code, 200)

        events_json = json.loads(resp.context["events_json"])
        self.assertEqual(len(events_json), 2)
        self.assertDictEqual(
            events_json[0],
            {'id': evt1.pk, 'start': self.default_event_time.isoformat(),
             'allDay': False,
             'title': 'lecture 0'})
        self.assertDictEqual(
            events_json[1],
            {'id': evt2.pk,
             'start': (self.default_event_time + timedelta(hours=1)).isoformat(),
             'allDay': False,
             'title': 'lecture 1'})

        self.assertResponseContextEqual(resp, "event_info_list", [])

    def test_hidden_event_not_shown(self):
        evt1 = factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=self.default_event_time)
        factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            shown_in_calendar=False,
            time=self.default_event_time + timedelta(hours=1))

        resp = self.get_course_calendar_view()
        self.assertEqual(resp.status_code, 200)

        events_json = json.loads(resp.context["events_json"])
        self.assertEqual(len(events_json), 1)
        self.assertDictEqual(
            events_json[0],
            {'id': evt1.pk, 'start': self.default_event_time.isoformat(),
             'allDay': False,
             'title': 'lecture 0'})
        self.assertResponseContextEqual(resp, "event_info_list", [])

    def test_event_has_end_time(self):
        evt = factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=self.default_event_time,
            end_time=self.default_event_time + timedelta(hours=1))
        resp = self.get_course_calendar_view()
        self.assertEqual(resp.status_code, 200)

        events_json = json.loads(resp.context["events_json"])
        self.assertEqual(len(events_json), 1)
        event_json = events_json[0]
        self.assertDictEqual(
            event_json,
            {'id': evt.pk, 'start': self.default_event_time.isoformat(),
             'allDay': False,
             'title': 'lecture 0',
             'end': (self.default_event_time + timedelta(hours=1)).isoformat(),
             })

        self.assertResponseContextEqual(resp, "event_info_list", [])

    def test_event_course_finished(self):
        self.mock_get_now_or_fake_time.return_value = self.default_faked_now
        self.course.end_date = (self.default_faked_now - timedelta(weeks=1)).date()
        self.course.save()

        resp = self.get_course_calendar_view()
        self.assertEqual(resp.status_code, 200)

        self.assertResponseContextEqual(resp, "events_json", '[]')
        self.assertResponseContextEqual(resp, "event_info_list", [])
        self.assertResponseContextEqual(
            resp, "default_date", self.course.end_date.isoformat())

    def test_event_course_not_finished(self):
        self.mock_get_now_or_fake_time.return_value = self.default_faked_now
        self.course.end_date = (self.default_faked_now + timedelta(weeks=1)).date()
        self.course.save()

        resp = self.get_course_calendar_view()
        self.assertEqual(resp.status_code, 200)

        self.assertResponseContextEqual(resp, "events_json", '[]')
        self.assertResponseContextEqual(resp, "event_info_list", [])
        self.assertResponseContextEqual(
            resp, "default_date", self.default_faked_now.date().isoformat())

    def test_events_file_no_events(self):
        # make sure it works
        self.switch_to_fake_commit_sha()

        resp = self.get_course_calendar_view()

        self.assertResponseContextEqual(resp, "events_json", '[]')
        self.assertResponseContextEqual(resp, "event_info_list", [])

    def test_events_file_with_events_test1(self):
        self.switch_to_fake_commit_sha()
        self.mock_get_now_or_fake_time.return_value = (
                self.default_event_time - timedelta(days=5))

        # lecture 1
        lecture1_start_time = self.default_event_time - timedelta(weeks=1)
        evt1 = factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=lecture1_start_time, ordinal=1)

        # lecture 2
        evt2 = factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=self.default_event_time, ordinal=2)

        resp = self.get_course_calendar_view()

        events_json = json.loads(resp.context["events_json"])
        self.assertEqual(len(events_json), 2)
        self.assertDictEqual(
            events_json[0],
            {'id': evt2.pk, 'start': self.default_event_time.isoformat(),
             'allDay': False,
             'title': 'Lecture 2'})

        self.assertDictEqual(
            events_json[1],
            {'id': evt1.pk,
             'color': "red",
             'start': lecture1_start_time.isoformat(),
             'allDay': False,
             'title': 'Alternative title for lecture 1',
             'url': '#event-%i' % evt1.pk
             })

        event_info_list = resp.context["event_info_list"]

        # lecture 2 doesn't create an EventInfo object
        self.assertEqual(len(event_info_list), 1)

        # check the attributes of EventInfo of lecture 1
        evt_info_dict = event_info_list[0].__dict__
        evt_description = evt_info_dict.pop("description")

        self.assertDictEqual(
            evt_info_dict,
            {"id": evt1.pk, "human_title": "Alternative title for lecture 1",
             "start_time": lecture1_start_time,
             "end_time": None})

        # make sure markup_to_html is called
        self.assertIn(
            'href="/course/test-course/flow/prequiz-linear-algebra/start/',
            evt_description)

    def test_events_file_with_events_test2(self):
        self.switch_to_fake_commit_sha()

        self.mock_get_now_or_fake_time.return_value = (
                self.default_event_time + timedelta(minutes=5))

        # lecture 2
        evt_lecture2 = factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=self.default_event_time, ordinal=2)

        # lecture 3
        lecture3_start_time = self.default_event_time + timedelta(weeks=1)
        evt_lecture3 = factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=lecture3_start_time, ordinal=3)

        # test event
        test_start_time = self.default_event_time + timedelta(minutes=1)
        evt_all_day = factories.EventFactory(
            kind="test", course=self.course, all_day=True,
            time=test_start_time,
            ordinal=None)

        resp = self.get_course_calendar_view()

        events_json = json.loads(resp.context["events_json"])
        self.assertEqual(len(events_json), 3)

        self.assertDictEqual(
            events_json[0],
            {'id': evt_lecture3.pk, 'start': (lecture3_start_time).isoformat(),
             'allDay': False,
             'title': 'Lecture 3'})

        self.assertDictEqual(
            events_json[1],
            {'id': evt_lecture2.pk, 'start': self.default_event_time.isoformat(),
             'allDay': False,
             'title': 'Lecture 2',
             'url': '#event-%i' % evt_lecture2.pk})

        self.assertDictEqual(
            events_json[2],
            {'id': evt_all_day.pk, 'start': test_start_time.isoformat(),
             'allDay': True,
             'title': 'test'})

        event_info_list = resp.context["event_info_list"]

        # only lecture 2 create an EventInfo object
        self.assertEqual(len(event_info_list), 1)

        # check the attributes of EventInfo of lecture 1
        evt_info_dict = event_info_list[0].__dict__
        evt_description = evt_info_dict.pop("description")

        self.assertDictEqual(
            evt_info_dict,
            {"id": evt_lecture2.pk, "human_title": "Lecture 2",
             "start_time": self.default_event_time,
             "end_time": None})

        self.assertIn(
            'Can you see this?',
            evt_description)

        # lecture 2's description exceeded show_description_until
        self.mock_get_now_or_fake_time.return_value = (
                lecture3_start_time + timedelta(minutes=5))

        # no EventInfo object
        resp = self.get_course_calendar_view()
        self.assertResponseContextEqual(resp, "event_info_list", [])

    def test_events_file_with_events_test3(self):
        self.switch_to_fake_commit_sha()

        exam_end_time = self.default_event_time + timedelta(hours=2)
        evt = factories.EventFactory(
            kind="exam", course=self.course,
            ordinal=None,
            time=self.default_event_time,
            end_time=exam_end_time)

        resp = self.get_course_calendar_view()

        events_json = json.loads(resp.context["events_json"])
        self.assertEqual(len(events_json), 1)

        self.assertDictEqual(
            events_json[0],
            {'id': evt.pk,
             'start': self.default_event_time.isoformat(),
             'allDay': False,
             'title': 'Exam',
             'color': 'red',
             'end': exam_end_time.isoformat()})

        self.assertResponseContextEqual(resp, "event_info_list", [])

    def test_all_day_event(self):
        self.switch_to_fake_commit_sha()

        # lecture 2, no end_time
        lecture2_start_time = datetime.datetime(2019, 1, 1, tzinfo=pytz.UTC)

        self.mock_get_now_or_fake_time.return_value = (
                lecture2_start_time + timedelta(minutes=5))

        lecture2_evt = factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            all_day=True,
            time=lecture2_start_time, ordinal=2)

        # lecture 3
        lecture3_start_time = lecture2_start_time + timedelta(weeks=1)
        factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=lecture3_start_time, ordinal=3)

        resp = self.get_course_calendar_view()

        events_json = json.loads(resp.context["events_json"])
        self.assertEqual(len(events_json), 2)

        self.assertDictEqual(
            events_json[1],
            {'id': lecture2_evt.pk, 'start': lecture2_start_time.isoformat(),
             'allDay': True,
             'title': 'Lecture 2',
             'url': '#event-%i' % lecture2_evt.pk})

        # now we add end_time of lecture 2 evt to a time which is not midnight
        lecture2_end_time = lecture2_start_time + timedelta(hours=18)
        lecture2_evt.end_time = lecture2_end_time
        lecture2_evt.save()

        resp = self.get_course_calendar_view()

        events_json = json.loads(resp.context["events_json"])
        self.assertEqual(len(events_json), 2)

        self.assertDictEqual(
            events_json[1],
            {'id': lecture2_evt.pk, 'start': lecture2_start_time.isoformat(),
             'allDay': True,
             'title': 'Lecture 2',
             'url': '#event-%i' % lecture2_evt.pk,
             'end': lecture2_end_time.isoformat()
             })

        # now we update end_time of lecture 2 evt to midnight
        while True:
            local_t = as_local_time(lecture2_end_time)
            end_midnight = datetime.time(tzinfo=local_t.tzinfo)
            if local_t.time() == end_midnight:
                lecture2_evt.end_time = lecture2_end_time
                lecture2_evt.save()
                break

            lecture2_end_time += timedelta(hours=1)

        resp = self.get_course_calendar_view()

        events_json = json.loads(resp.context["events_json"])
        self.assertEqual(len(events_json), 2)

        self.assertDictEqual(
            events_json[1],
            {'id': lecture2_evt.pk, 'start': lecture2_start_time.isoformat(),
             'allDay': True,
             'title': 'Lecture 2',
             'url': '#event-%i' % lecture2_evt.pk,
             'end': lecture2_end_time.isoformat()
             })

# vim: fdm=marker
