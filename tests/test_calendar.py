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
import pytz
import json
import datetime
import unittest

from django.test import TestCase, override_settings, RequestFactory
from django.urls import reverse
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


def get_prefixed_form_data(form_klass, form_data):
    prefixed_form_data = {}
    for k, v in form_data.items():
        prefixed_form_data[
            "%s-%s" % (form_klass.prefix, k)] = v
    return prefixed_form_data


def get_object_dict(obj):
    return dict((k, v) for (k, v) in six.iteritems(obj.__dict__)
                if not k.startswith("_"))


class CalendarTestMixin(SingleCourseTestMixin, HackRepoMixin):

    default_faked_now = datetime.datetime(2019, 1, 1, tzinfo=pytz.UTC)
    default_event_time = default_faked_now - timedelta(hours=12)
    default_event_kind = "lecture"

    def setUp(self):
        super(CalendarTestMixin, self).setUp()
        fake_get_now_or_fake_time = mock.patch(
            "course.calendar.get_now_or_fake_time")
        self.mock_get_now_or_fake_time = fake_get_now_or_fake_time.start()
        self.mock_get_now_or_fake_time.return_value = now()
        self.addCleanup(fake_get_now_or_fake_time.stop)
        self.addCleanup(factories.EventFactory.reset_sequence)

    @classmethod
    def get_course_calender_url(cls, is_edit_view=False, course_identifier=None):
        course_identifier = course_identifier or cls.get_default_course_identifier()
        kwargs = {"course_identifier": course_identifier}
        if is_edit_view:
            kwargs["mode"] = "edit"
        return reverse("relate-view_calendar", kwargs=kwargs)

    def get_course_calender_view(self, is_edit_view=False, course_identifier=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        return self.c.get(
            self.get_course_calender_url(is_edit_view, course_identifier))

    def switch_to_fake_commit_sha(self):
        self.course.active_git_commit_sha = "my_fake_commit_sha_for_events"
        self.course.events_file = "events.yml"
        self.course.save()

    def create_recurring_events(
            self, n=5, staring_ordinal=1,
            staring_time_offset_days=0,
            staring_time_offset_hours=0,
            staring_time_offset_minutes=0,
            end_time_minute_duration=None):

        exist_events_pks = list(Event.objects.all().values_list("pk", flat=True))
        now_time = self.default_faked_now + timedelta(
            days=staring_time_offset_days,
            hours=staring_time_offset_hours,
            minutes=staring_time_offset_minutes)
        for i in range(n):
            kwargs = {"kind": self.default_event_kind,
                      "ordinal": i + staring_ordinal,
                      "time": now_time}
            if end_time_minute_duration is not None:
                kwargs["end_time"] = (
                        now_time + timedelta(minutes=end_time_minute_duration))
            factories.EventFactory(**kwargs)
            now_time += timedelta(weeks=1)

        return list(Event.objects.exclude(pk__in=exist_events_pks))


class ModalStyledFormMixinTest(CalendarTestMixin, TestCase):
    """test course.calendar.ModalStyledFormMixin"""
    def test_render_ajax_modal_form_html_with_context(self):
        rf = RequestFactory()
        request = rf.get(self.get_course_page_url())
        request.user = self.instructor_participation.user

        form = calendar.CreateEventModalForm(self.course.identifier)

        with mock.patch("crispy_forms.utils.render_crispy_form"
                        ) as mock_render_crispy_form:
            form.render_ajax_modal_form_html(request, context={"foo": "bar"})
            self.assertEqual(mock_render_crispy_form.call_count, 1)
            self.assertEqual(mock_render_crispy_form.call_args[0][2]["foo"], "bar")
            self.assertTemplateUsed(form.ajax_modal_form_template)


class CreateRecurringEventsTest(CalendarTestMixin, MockAddMessageMixing, TestCase):
    """test course.calendar.create_recurring_events"""

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
                                          force_login_instructor=True,
                                          using_ajax=False):
        course_identifier = course_identifier or self.get_default_course_identifier()
        if not force_login_instructor:
            user = self.get_logged_in_user()
        else:
            user = self.instructor_participation.user

        kwargs = {}
        if using_ajax:
            kwargs["HTTP_X_REQUESTED_WITH"] = 'XMLHttpRequest'

        with self.temporarily_switch_to_user(user):
            return self.c.post(
                self.get_create_recurring_events_url(course_identifier), data,
                **kwargs)

    def get_post_create_recur_evt_data(
            self, op="submit", starting_ordinal=None, **kwargs):
        data = {
            "kind": self.default_event_kind,
            "time": now().replace(tzinfo=None).strftime(
                DATE_TIME_PICKER_TIME_FORMAT),
            "interval": "weekly",
            "count": 5,
            op: ''
        }

        if starting_ordinal:
            data["starting_ordinal"] = starting_ordinal

        data.update(kwargs)
        return get_prefixed_form_data(calendar.RecurringEventForm, data)

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
                self.assertEqual(evt.time - t, datetime.timedelta(weeks=1))
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

    def test_event_save_field_error(self):
        error_msg = "my unknown validation error for start_time"
        with mock.patch("course.models.Event.save") as mock_event_save:
            # mock error raised by event.end_time
            mock_event_save.side_effect = (
                ValidationError({"time": error_msg}))
            resp = self.post_create_recurring_events_view(
                data=self.get_post_create_recur_evt_data(starting_ordinal=4))
            self.assertEqual(resp.status_code, 200)

        # form error was raised instead of add_message
        self.assertFormErrorLoose(resp, error_msg)
        self.assertAddMessageCallCount(0)

        # not created
        self.assertEqual(Event.objects.count(), 0)

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
                self.assertEqual(evt.time - t, datetime.timedelta(weeks=1))
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
                self.assertEqual(evt.time - t, datetime.timedelta(weeks=2))
                t = evt.time

    # {{{ Ajax part

    def test_get_by_ajax_failure(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(self.get_create_recurring_events_url(),
                              HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(resp.status_code, 403)

    def test_post_form_not_valid_ajax(self):
        resp = self.post_create_recurring_events_view(
            data=self.get_post_create_recur_evt_data(time="invalid_time"),
            using_ajax=True
        )
        self.assertEqual(resp.status_code, 400)
        json_resp = json.loads(resp.content.decode())
        self.assertEqual(
            json_resp["errors"]["time"], ['Enter a valid date/time.'])

        # not created
        self.assertEqual(Event.objects.count(), 0)

    def test_event_save_field_error_ajax(self):
        error_msg = "my unknown validation error for start_time"
        with mock.patch("course.models.Event.save") as mock_event_save:
            # mock error raised by event.end_time
            mock_event_save.side_effect = (
                ValidationError({"time": error_msg}))
            resp = self.post_create_recurring_events_view(
                data=self.get_post_create_recur_evt_data(starting_ordinal=4),
                using_ajax=True)
            self.assertEqual(resp.status_code, 400)

        json_resp = json.loads(resp.content.decode())
        self.assertEqual(json_resp["errors"]["time"], [error_msg])

        # not created
        self.assertEqual(Event.objects.count(), 0)

    @unittest.skipIf(six.PY2, "Python 2 string repr has 'u' prefix")
    def test_event_save_other_validation_error_ajax(self):
        error_msg = "my unknown validation error for end_time"
        with mock.patch("course.models.Event.save") as mock_event_save:
            # mock error raised by event.end_time
            mock_event_save.side_effect = (
                ValidationError({"end_time": error_msg}))
            resp = self.post_create_recurring_events_view(
                data=self.get_post_create_recur_evt_data(starting_ordinal=4),
                using_ajax=True)
            self.assertEqual(resp.status_code, 400)

        json_resp = json.loads(resp.content.decode())
        self.assertEqual(json_resp["errors"]["__all__"],
            ["'end_time': [ValidationError(['%s'])]" % error_msg])

        # not created
        self.assertEqual(Event.objects.count(), 0)

    def test_post_success_ajax(self):
        # only tested starting_ordinal specified
        resp = self.post_create_recurring_events_view(
            data=self.get_post_create_recur_evt_data(starting_ordinal=4),
            using_ajax=True)
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
                self.assertEqual(evt.time - t, datetime.timedelta(weeks=1))
                t = evt.time

        json_resp = json.loads(resp.content.decode())
        self.assertEqual(json_resp["message"], "Events created.")

    def test_event_save_unknown_error_ajax(self):
        error_msg = "my unknown error"
        with mock.patch("course.models.Event.save") as mock_event_save:
            mock_event_save.side_effect = RuntimeError(error_msg)
            resp = self.post_create_recurring_events_view(
                data=self.get_post_create_recur_evt_data(
                    starting_ordinal=4), using_ajax=True)
        self.assertEqual(resp.status_code, 400)

        # not created
        self.assertEqual(Event.objects.count(), 0)
        json_resp = json.loads(resp.content.decode())
        self.assertEqual(json_resp["errors"]["__all__"],
            ["RuntimeError: %s. No events created." % error_msg])

    # }}}


class GetRecurringEventsModalFormTest(CalendarTestMixin, TestCase):
    """test calendar.get_recurring_events_modal_form"""
    force_login_student_for_each_test = False

    def setUp(self):
        super(GetRecurringEventsModalFormTest, self).setUp()
        self.c.force_login(self.instructor_participation.user)

    def get_recurring_events_modal_form_url(self, course_identifier=None):
        return self.get_course_view_url(
            "relate-get_recurring_events_modal_form",
            course_identifier)

    def get_recurring_events_modal_form_view(self, course_identifier=None,
                                             using_ajax=True):
        kwargs = {}
        if using_ajax:
            kwargs["HTTP_X_REQUESTED_WITH"] = 'XMLHttpRequest'
        return self.c.get(
            self.get_recurring_events_modal_form_url(course_identifier), **kwargs)

    def test_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_recurring_events_modal_form_view()
            self.assertEqual(resp.status_code, 403)

    def test_post(self):
        resp = self.c.post(self.get_recurring_events_modal_form_url(), data={},
                           HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 403)

    def test_post_non_ajax(self):
        resp = self.c.post(self.get_recurring_events_modal_form_url(), data={})
        self.assertEqual(resp.status_code, 403)

    def test_get_non_ajax(self):
        resp = self.get_recurring_events_modal_form_view(using_ajax=False)
        self.assertEqual(resp.status_code, 403)

    def test_get_success(self):
        resp = self.get_recurring_events_modal_form_view()
        self.assertEqual(resp.status_code, 200)


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
            data=get_prefixed_form_data(
                calendar.RecurringEventForm, form_data))
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

        form = calendar.RecurringEventForm(
            self.course.identifier,
            data=get_prefixed_form_data(
                calendar.RecurringEventForm, form_data))
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
        form = calendar.RecurringEventForm(
            self.course.identifier,
            data=get_prefixed_form_data(
                calendar.RecurringEventForm, form_data))

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


class RenumberEventsTest(CalendarTestMixin, MockAddMessageMixing, TestCase):
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
                                  force_login_instructor=True, using_ajax=False):
        course_identifier = course_identifier or self.get_default_course_identifier()
        if not force_login_instructor:
            user = self.get_logged_in_user()
        else:
            user = self.instructor_participation.user

        kwargs = {}
        if using_ajax:
            kwargs["HTTP_X_REQUESTED_WITH"] = 'XMLHttpRequest'

        with self.temporarily_switch_to_user(user):
            return self.c.post(
                self.get_renumber_events_events_url(course_identifier),
                data, **kwargs)

    def get_post_renumber_evt_data(
            self, starting_ordinal, kind=None, op="submit", **kwargs):

        data = {
            "kind": kind or self.default_event_kind,
            "starting_ordinal": starting_ordinal,
            "preserve_ordinal_order": False}

        data.update(kwargs)
        return get_prefixed_form_data(calendar.RenumberEventsForm, data)

    @classmethod
    def setUpTestData(cls):  # noqa
        super(RenumberEventsTest, cls).setUpTestData()
        now_time = now()
        for i in range(5):
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
        super(RenumberEventsTest, self).setUp()
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

    # {{{ Ajax part

    def test_get_by_ajax_failure(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(self.get_renumber_events_events_url(),
                              HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(resp.status_code, 403)

    def test_post_form_not_valid_ajax(self):
        resp = self.post_renumber_events_view(
            data=self.get_post_renumber_evt_data(
                kind="foo_kind", starting_ordinal=3),
            using_ajax=True
        )
        self.assertEqual(resp.status_code, 400)
        expected_errors = ["Select a valid choice. foo_kind is "
                           "not one of the available choices."]

        json_resp = json.loads(resp.content.decode())
        self.assertEqual(json_resp["errors"]["kind"], expected_errors)

    def test_post_success_ajax(self):
        resp = self.post_renumber_events_view(
            data=self.get_post_renumber_evt_data(starting_ordinal=3),
            using_ajax=True)
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

        json_resp = json.loads(resp.content.decode())
        self.assertEqual(json_resp["message"], "Events renumbered.")

    # }}}


class GetRenumberEventsModalFormTest(CalendarTestMixin, TestCase):
    """test calendar.get_renumber_events_modal_form"""
    force_login_student_for_each_test = False

    def setUp(self):
        super(GetRenumberEventsModalFormTest, self).setUp()
        self.c.force_login(self.instructor_participation.user)

    def get_renumber_events_modal_form_url(self, course_identifier=None):
        return self.get_course_view_url("relate-get_renumber_events_modal_form",
                                        course_identifier)

    def get_renumber_events_modal_form_view(self, course_identifier=None,
                                            using_ajax=True):
        kwargs = {}
        if using_ajax:
            kwargs["HTTP_X_REQUESTED_WITH"] = 'XMLHttpRequest'
        return self.c.get(
            self.get_renumber_events_modal_form_url(course_identifier), **kwargs)

    def test_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_renumber_events_modal_form_view()
            self.assertEqual(resp.status_code, 403)

    def test_post(self):
        resp = self.c.post(self.get_renumber_events_modal_form_url(), data={},
                           HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 403)

    def test_post_non_ajax(self):
        resp = self.c.post(self.get_renumber_events_modal_form_url(), data={})
        self.assertEqual(resp.status_code, 403)

    def test_get_non_ajax(self):
        resp = self.get_renumber_events_modal_form_view(using_ajax=False)
        self.assertEqual(resp.status_code, 403)

    def test_get_success(self):
        resp = self.get_renumber_events_modal_form_view()
        self.assertEqual(resp.status_code, 200)


class ViewCalendarTest(CalendarTestMixin, TestCase):
    """ test calendar.view_calendar """
    force_login_student_for_each_test = True

    def test_no_pperm(self):
        with mock.patch(
                "course.utils.CoursePageContext.has_permission"
        ) as mock_has_pperm:
            mock_has_pperm.return_value = False
            resp = self.get_course_calender_view()
            self.assertEqual(resp.status_code, 403)

    def test_student_non_edit_view_success(self):
        resp = self.get_course_calender_view()
        self.assertEqual(resp.status_code, 200)

    def test_student_edit_view_failure(self):
        resp = self.get_course_calender_view(is_edit_view=True)
        self.assertEqual(resp.status_code, 403)

    def test_instructor_non_edit_view_success(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.get_course_calender_view()
            self.assertEqual(resp.status_code, 200)

    def test_instructor_edit_view_success(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.get_course_calender_view(is_edit_view=True)
            self.assertEqual(resp.status_code, 200)

    def test_default_time(self):
        if self.course.end_date is not None:
            self.course.end_date = (
                    self.default_faked_now.date() + timedelta(days=100))
            self.course.save()

        self.mock_get_now_or_fake_time.return_value = self.default_faked_now

        resp = self.get_course_calender_view()
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "default_date", self.default_faked_now.date().isoformat())

    def test_default_time_after_course_ended(self):
        self.mock_get_now_or_fake_time.return_value = self.default_faked_now

        self.course.end_date = self.default_faked_now.date() - timedelta(days=100)
        self.course.save()
        self.assertTrue(self.course.end_date < self.default_faked_now.date())

        resp = self.get_course_calender_view()
        self.assertEqual(resp.status_code, 200)

        # Calendar's default_date will be course.end_date
        self.assertResponseContextEqual(
            resp, "default_date", self.course.end_date.isoformat())


class FetchEventsTest(CalendarTestMixin, TestCase):
    """test course.calendar.fetch_events"""
    force_login_student_for_each_test = False

    def setUp(self):
        super(FetchEventsTest, self).setUp()
        self.c.force_login(self.instructor_participation.user)

    def fetch_events_url(self, is_edit_view=False, course_identifier=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        kwargs = {"course_identifier": course_identifier}
        if is_edit_view:
            kwargs["mode"] = "edit"
        return reverse("relate-fetch_events", kwargs=kwargs)

    def get_fetch_events(self, is_edit_view=False, course_identifier=None,
                         using_ajax=True):
        course_identifier = course_identifier or self.get_default_course_identifier()
        kwargs = {}
        if using_ajax:
            kwargs["HTTP_X_REQUESTED_WITH"] = 'XMLHttpRequest'
        return self.c.get(
            self.fetch_events_url(is_edit_view, course_identifier), **kwargs)

    def test_view_no_pperm(self):
        with mock.patch(
                "course.utils.CoursePageContext.has_permission"
        ) as mock_has_pperm:
            mock_has_pperm.return_value = False
            resp = self.get_fetch_events()
            self.assertEqual(resp.status_code, 403)

    def test_student_view_success(self):
        self.mock_get_now_or_fake_time.return_value = self.default_faked_now
        with mock.patch("course.calendar.get_events") as mock_get_events:
            mock_get_events.return_value = ([], [])
            with self.temporarily_switch_to_user(self.student_participation.user):
                resp = self.get_fetch_events()
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(mock_get_events.call_count, 1)
                self.assertEqual(
                    mock_get_events.call_args[1]["is_edit_view"], False)

    def test_edit_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_fetch_events(is_edit_view=True)
            self.assertEqual(resp.status_code, 403)

    def test_not_ajax(self):
        resp = self.get_fetch_events(using_ajax=False)
        self.assertEqual(resp.status_code, 403)

    def test_ajax_post(self):
        resp = self.c.post(self.fetch_events_url(), data={},
                           HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 403)

    def test_post(self):
        resp = self.c.post(self.fetch_events_url(), data={})
        self.assertEqual(resp.status_code, 403)

    def test_instructor_fetch_success(self):
        resp = self.get_fetch_events()
        self.assertEqual(resp.status_code, 200)

    def test_instructor_edit_fetch_success(self):
        self.mock_get_now_or_fake_time.return_value = self.default_faked_now
        with mock.patch("course.calendar.get_events") as mock_get_events:
            mock_get_events.return_value = ([], [])
            resp = self.get_fetch_events(is_edit_view=True)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(
                mock_get_events.call_args[1]["is_edit_view"], True)


class GetEventsTest(CalendarTestMixin, TestCase):
    """test course.calendar.get_events"""
    force_login_student_for_each_test = False

    def setUp(self):
        super(GetEventsTest, self).setUp()
        fake_render_to_string = mock.patch("django.template.loader.render_to_string")
        self.mock_render_to_string = fake_render_to_string.start()

        # Note: in this way, the events_info_html in the fetch_event response
        # will always be empty, we test the events_info_html by check the kwargs
        # when calling render_to_string

        # Todo: This only test the behavior of get_events when called
        # in fetch_events. get_events also need to be tested when called in
        # view_calendar.
        self.mock_render_to_string.return_value = ""
        self.addCleanup(fake_render_to_string.stop)
        self.default_pctx = self.get_instructor_pctx()
        # self.c.force_login(self.instructor_participation.user)

    def get_event_delete_form_url(self, event_id):
        return reverse(
            "relate-get_delete_event_modal_form",
            args=[self.course.identifier, event_id])

    def get_event_update_form_url(self, event_id):
        return reverse("relate-get_update_event_modal_form",
                       args=[self.course.identifier, event_id])

    def get_pctx(self, user):
        rf = RequestFactory()
        request = rf.get(self.get_course_page_url())
        request.user = user

        from course.utils import CoursePageContext
        return CoursePageContext(request, self.course.identifier)

    def get_student_pctx(self):
        return self.get_pctx(self.student_participation.user)

    def get_instructor_pctx(self):
        return self.get_pctx(self.instructor_participation.user)

    def get_event_info_list_rendered(self):
        """get the event_info_list rendered from mocked render_to_string call"""
        self.assertTrue(self.mock_render_to_string.call_count > 0)
        return self.mock_render_to_string.call_args[1]["context"]["event_info_list"]

    def test_neither_events_nor_event_file(self):
        self.mock_get_now_or_fake_time.return_value = self.default_faked_now
        __, events_json = calendar.get_events(self.default_pctx)

        self.assertEqual(events_json, [])
        event_info_list = self.get_event_info_list_rendered()
        self.assertEqual(event_info_list, [])

    def test_no_event_file_not_editing(self):
        self.mock_get_now_or_fake_time.return_value = self.default_faked_now

        event1 = factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=self.default_event_time)
        event2 = factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=self.default_event_time + timedelta(hours=1),
            end_time=self.default_event_time + timedelta(hours=2))

        __, events_json = calendar.get_events(self.default_pctx)
        self.assertEqual(len(events_json), 2)
        self.assertDictEqual(
            events_json[0],
            {'id': event1.id, 'start': event1.time.isoformat(),
             'allDay': False,
             'durationEditable': False,
             'title': 'lecture 0'})
        self.assertDictEqual(
            events_json[1],
            {'id': event2.id,
             'start': event2.time.isoformat(),
             'end': event2.end_time.isoformat(),
             'allDay': False,
             'title': 'lecture 1'})

        event_info_list = self.get_event_info_list_rendered()
        self.assertEqual(event_info_list, [])

    def test_no_event_file_editing(self):
        self.mock_get_now_or_fake_time.return_value = self.default_faked_now

        event1 = factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=self.default_event_time,
            end_time=self.default_event_time+timedelta(minutes=1))
        event2 = factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=self.default_event_time + timedelta(hours=1))

        __, events_json = calendar.get_events(self.default_pctx, is_edit_view=True)
        self.assertEqual(len(events_json), 2)
        self.assertDictEqual(
            events_json[0],
            {'id': event1.id,
             'start': event1.time.isoformat(),
             'end': event1.end_time.isoformat(),
             'allDay': False,
             'title': 'lecture 0',
             'show_description': True,
             'str': str(event1),
             'delete_form_url': self.get_event_delete_form_url(event1.id),
             'update_form_url': self.get_event_update_form_url(event1.id)})
        self.assertDictEqual(
            events_json[1],
            {'id': event2.id,
             'start': event2.time.isoformat(),
             'allDay': False,
             'title': 'lecture 1',
             'show_description': True,
             'str': str(event2),
             'delete_form_url': self.get_event_delete_form_url(event2.id),
             'update_form_url': self.get_event_update_form_url(event2.id),
             'durationEditable': False,
             })

        event_info_list = self.get_event_info_list_rendered()
        self.assertEqual(event_info_list, [])

    def test_hidden_event_not_shown_not_editing(self):
        self.mock_get_now_or_fake_time.return_value = self.default_faked_now
        event1 = factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=self.default_event_time)

        factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            shown_in_calendar=False,
            time=self.default_event_time + timedelta(hours=1))

        __, events_json = calendar.get_events(self.default_pctx)

        self.assertEqual(len(events_json), 1)
        self.assertDictEqual(
            events_json[0],
            {'id': event1.id,
             'start': event1.time.isoformat(),
             'durationEditable': False,
             'allDay': False,
             'title': 'lecture 0'})

        event_info_list = self.get_event_info_list_rendered()
        self.assertEqual(event_info_list, [])

    def test_hidden_event_shown_editing(self):
        self.mock_get_now_or_fake_time.return_value = self.default_faked_now
        factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=self.default_event_time)
        event2 = factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            shown_in_calendar=False,
            time=self.default_event_time + timedelta(hours=1))

        __, events_json = calendar.get_events(self.default_pctx, is_edit_view=True)

        self.assertEqual(len(events_json), 2)
        self.assertDictEqual(
            events_json[1],
            {'id': event2.id,
             'start': event2.time.isoformat(),
             'allDay': False,
             'title': 'lecture 1',
             'show_description': False,
             'str': str(event2),
             'delete_form_url': self.get_event_delete_form_url(event2.id),
             'update_form_url': self.get_event_update_form_url(event2.id),
             'durationEditable': False,
             'hidden_in_calendar': True,
             })

        event_info_list = self.get_event_info_list_rendered()
        self.assertEqual(event_info_list, [])

    def test_events_file_with_events_test1(self):
        self.switch_to_fake_commit_sha()

        # pctx.course has been update, regenerate the default_pctx
        default_pctx = self.get_instructor_pctx()

        # lecture 1
        lecture1_start_time = self.default_event_time - timedelta(weeks=1)
        factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=lecture1_start_time, ordinal=1)

        # lecture 2
        factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=self.default_event_time, ordinal=2)

        __, events_json = calendar.get_events(default_pctx)

        self.assertEqual(len(events_json), 2)
        self.assertDictEqual(
            events_json[0],
            {'id': 2, 'start': self.default_event_time.isoformat(),
             'durationEditable': False,
             'allDay': False,
             'title': 'Lecture 2'})

        self.assertDictEqual(
            events_json[1],
            {'id': 1,
             'durationEditable': False,
             'color': "red",
             'start': lecture1_start_time.isoformat(),
             'allDay': False,
             'title': 'Alternative title for lecture 1',
             'url': '#event-1'
             })

        event_info_list = self.get_event_info_list_rendered()

        # lecture 2 doesn't create an EventInfo object
        self.assertEqual(len(event_info_list), 1)

        # check the attributes of EventInfo of lecture 1
        evt_info_dict = event_info_list[0].__dict__
        evt_description = evt_info_dict.pop("description")

        self.assertDictEqual(
            evt_info_dict,
            {"id": 1, "human_title": "Alternative title for lecture 1",
             "start_time": lecture1_start_time,
             "end_time": None})

        # make sure markup_to_html is called
        self.assertIn(
            'href="/course/test-course/flow/prequiz-linear-algebra/start/',
            evt_description)

    def test_events_file_with_events_test2(self):
        self.switch_to_fake_commit_sha()

        # pctx.course has been update, regenerate the default_pctx
        default_pctx = self.get_instructor_pctx()

        self.mock_get_now_or_fake_time.return_value = (
                self.default_event_time + timedelta(minutes=5))

        # lecture 2
        factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=self.default_event_time, ordinal=2)

        # lecture 3
        lecture3_start_time = self.default_event_time + timedelta(weeks=1)
        factories.EventFactory(
            kind=self.default_event_kind, course=self.course,
            time=lecture3_start_time, ordinal=3)

        # test event
        test_start_time = self.default_event_time + timedelta(minutes=1)
        factories.EventFactory(
            kind="test", course=self.course, all_day=True,
            time=test_start_time,
            ordinal=None)

        __, events_json = calendar.get_events(default_pctx)

        self.assertEqual(len(events_json), 3)

        self.assertDictEqual(
            events_json[0],
            {'id': 2, 'start': (lecture3_start_time).isoformat(),
             'allDay': False,
             'durationEditable': False,
             'title': 'Lecture 3'})

        self.assertDictEqual(
            events_json[1],
            {'id': 1, 'start': self.default_event_time.isoformat(),
             'allDay': False,
             'durationEditable': False,
             'title': 'Lecture 2',
             'url': '#event-1'})

        self.assertDictEqual(
            events_json[2],
            {'id': 3, 'start': test_start_time.isoformat(),
             'allDay': True,
             'durationEditable': False,
             'title': 'test'})

        event_info_list = self.get_event_info_list_rendered()

        # only lecture 2 create an EventInfo object
        self.assertEqual(len(event_info_list), 1)

        # check the attributes of EventInfo of lecture 1
        evt_info_dict = event_info_list[0].__dict__
        evt_description = evt_info_dict.pop("description")

        self.assertDictEqual(
            evt_info_dict,
            {"id": 1, "human_title": "Lecture 2",
             "start_time": self.default_event_time,
             "end_time": None})

        self.assertIn('Can you see this?', evt_description)

        # lecture 2's description exceeded show_description_until
        self.mock_get_now_or_fake_time.return_value = (
                lecture3_start_time + timedelta(minutes=5))

        # no EventInfo object
        __, events_json = calendar.get_events(default_pctx)
        event_info_list = self.get_event_info_list_rendered()
        self.assertEqual(event_info_list, [])

    def test_events_file_with_events_test3(self):
        self.switch_to_fake_commit_sha()
        default_pctx = self.get_instructor_pctx()

        exam_end_time = self.default_event_time + timedelta(hours=2)
        factories.EventFactory(
            kind="exam", course=self.course,
            ordinal=None,
            time=self.default_event_time,
            end_time=exam_end_time)

        __, events_json = calendar.get_events(default_pctx)

        self.assertEqual(len(events_json), 1)

        self.assertDictEqual(
            events_json[0],
            {'id': 1,
             'start': self.default_event_time.isoformat(),
             'allDay': False,
             'title': 'Exam',
             'color': 'red',
             'end': exam_end_time.isoformat()})

        event_info_list = self.get_event_info_list_rendered()
        self.assertEqual(event_info_list, [])

    def test_all_day_event(self):
        self.switch_to_fake_commit_sha()
        default_pctx = self.get_instructor_pctx()

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

        __, events_json = calendar.get_events(default_pctx)
        self.assertEqual(len(events_json), 2)

        self.assertDictEqual(
            events_json[1],
            {'id': 1, 'start': lecture2_start_time.isoformat(),
             'allDay': True,
             'title': 'Lecture 2',
             'durationEditable': False,
             'url': '#event-1'})

        # now we add end_time of lecture 2 evt to a time which is not midnight
        lecture2_end_time = lecture2_start_time + timedelta(hours=18)
        lecture2_evt.end_time = lecture2_end_time
        lecture2_evt.save()

        __, events_json = calendar.get_events(default_pctx)

        self.assertEqual(len(events_json), 2)

        self.assertDictEqual(
            events_json[1],
            {'id': 1, 'start': lecture2_start_time.isoformat(),
             'allDay': True,
             'title': 'Lecture 2',
             'url': '#event-1',
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

        __, events_json = calendar.get_events(default_pctx)
        self.assertEqual(len(events_json), 2)

        self.assertDictEqual(
            events_json[1],
            {'id': 1, 'start': lecture2_start_time.isoformat(),
             'allDay': True,
             'title': 'Lecture 2',
             'url': '#event-1',
             'end': lecture2_end_time.isoformat()
             })


class GetLocalTimeWeekdayHourMinuteTest(unittest.TestCase):
    def test(self):
        dt = datetime.datetime(2019, 1, 1, 11, 35, tzinfo=pytz.utc)
        with override_settings(TIME_ZONE="Hongkong"):
            local_time, week_day, hour, minute = (
                calendar.get_local_time_weekday_hour_minute(dt))

            self.assertEqual(as_local_time(dt), local_time)
            self.assertEqual(week_day, 3)
            self.assertEqual(hour, 19)
            self.assertEqual(minute, 35)

        dt = datetime.datetime(2019, 1, 6, 11, 35, tzinfo=pytz.utc)
        with override_settings(TIME_ZONE="Hongkong"):
            local_time, week_day, hour, minute = (
                calendar.get_local_time_weekday_hour_minute(dt))

            self.assertEqual(as_local_time(dt), local_time)
            self.assertEqual(week_day, 1)
            self.assertEqual(hour, 19)
            self.assertEqual(minute, 35)


class CreateEventTest(CalendarTestMixin, TestCase):
    """test calendar.create_event"""

    force_login_student_for_each_test = False

    def setUp(self):
        super(CreateEventTest, self).setUp()
        self.c.force_login(self.instructor_participation.user)

    def get_create_event_url(self, course_identifier=None):
        return self.get_course_view_url("relate-create_event", course_identifier)

    def post_create_event(self, data, course_identifier=None, using_ajax=True):
        kwargs = {}
        if using_ajax:
            kwargs["HTTP_X_REQUESTED_WITH"] = 'XMLHttpRequest'
        return self.c.post(
            self.get_create_event_url(course_identifier), data, **kwargs)

    def get_default_post_data(self, time=None, end_time=None, **kwargs):
        data = {
            'kind': "some_kind",
            'time': self.default_faked_now.strftime(DATE_TIME_PICKER_TIME_FORMAT),
            'shown_in_calendar': True,
            'all_day': False}

        if time is None:
            time = kwargs.pop("time", None)

        if time is not None:
            data["time"] = time.strftime(DATE_TIME_PICKER_TIME_FORMAT)

        if end_time is None:
            end_time = kwargs.pop("end_time", None)

        if end_time is not None:
            data["end_time"] = end_time.strftime(DATE_TIME_PICKER_TIME_FORMAT)

        data.update(kwargs)
        return get_prefixed_form_data(calendar.CreateEventModalForm, data)

    def test_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.post_create_event(data=self.get_default_post_data())
            self.assertEqual(resp.status_code, 403)

    def test_get(self):
        resp = self.c.get(self.get_create_event_url(),
                          HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 403)

    def test_get_non_ajax(self):
        resp = self.c.get(self.get_create_event_url())
        self.assertEqual(resp.status_code, 403)

    def test_post_non_ajax(self):
        resp = self.post_create_event(
            data=self.get_default_post_data(), using_ajax=False)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Event.objects.count(), 0)

    def test_post_success(self):
        resp = self.post_create_event(data=self.get_default_post_data())
        self.assertEqual(resp.status_code, 200)

        events_qs = Event.objects.all()
        self.assertEqual(events_qs.count(), 1)

        event = events_qs[0]

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "Event created: '%s'." % str(event))

    def test_post_form_non_field_error(self):
        event = factories.EventFactory(course=self.course)

        # post create already exist event
        resp = self.post_create_event(
            data=self.get_default_post_data(**event.__dict__))
        self.assertEqual(resp.status_code, 400)

        events_qs = Event.objects.all()
        self.assertEqual(events_qs.count(), 1)

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["errors"]['__all__'],
                         ["'%s' already exists." % str(event)])

    def test_post_form_field_error(self):
        resp = self.post_create_event(data={})
        self.assertEqual(resp.status_code, 400)

        events_qs = Event.objects.all()
        self.assertEqual(events_qs.count(), 0)

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["errors"]['kind'],
                         ['This field is required.'])

    def test_post_form_save_errored(self):
        with mock.patch("course.models.Event.save") as mock_event_save:
            mock_event_save.side_effect = RuntimeError("my custom event save error.")
            resp = self.post_create_event(data=self.get_default_post_data())

        self.assertEqual(resp.status_code, 400)

        events_qs = Event.objects.all()
        self.assertEqual(events_qs.count(), 0)

        json_response = json.loads(resp.content.decode())

        self.assertEqual(json_response['__all__'],
                         ['RuntimeError: my custom event save error.'])


class GetCreateEventModalFormTest(CalendarTestMixin, TestCase):
    """test calendar.get_create_event_modal_form"""
    force_login_student_for_each_test = False

    def setUp(self):
        super(GetCreateEventModalFormTest, self).setUp()
        self.c.force_login(self.instructor_participation.user)

    def get_create_event_modal_form_url(self, course_identifier=None):
        return self.get_course_view_url("relate-get_create_event_modal_form",
                                        course_identifier)

    def get_create_event_modal_form_view(self, course_identifier=None,
                                         using_ajax=True):
        kwargs = {}
        if using_ajax:
            kwargs["HTTP_X_REQUESTED_WITH"] = 'XMLHttpRequest'
        return self.c.get(
            self.get_create_event_modal_form_url(course_identifier), **kwargs)

    def test_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_create_event_modal_form_view()
            self.assertEqual(resp.status_code, 403)

    def test_post(self):
        resp = self.c.post(self.get_create_event_modal_form_url(), data={},
                          HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 403)

    def test_post_non_ajax(self):
        resp = self.c.post(self.get_create_event_modal_form_url(), data={})
        self.assertEqual(resp.status_code, 403)

    def test_get_non_ajax(self):
        resp = self.get_create_event_modal_form_view(using_ajax=False)
        self.assertEqual(resp.status_code, 403)

    def test_get_success(self):
        resp = self.get_create_event_modal_form_view()
        self.assertEqual(resp.status_code, 200)


class DeleteEventFormTest(CalendarTestMixin, TestCase):
    """test course.calendar.DeleteEventForm"""

    def test_delete_event_not_in_recurring_series_ui(self):
        # create 5 recurring events
        self.create_recurring_events(5)
        instance_to_delete = factories.EventFactory(
            course=self.course, kind="some_kind")

        form = calendar.DeleteEventForm(self.course.identifier, instance_to_delete)

        self.assertNotIn("operation", form.fields)

    def test_delete_event_with_no_ordinal_ui(self):
        # create 5 recurring events
        self.create_recurring_events(5)
        instance_to_delete = factories.EventFactory(
            course=self.course, kind="some_kind", ordinal=None)

        form = calendar.DeleteEventForm(self.course.identifier, instance_to_delete)

        self.assertNotIn("operation", form.fields)

    @unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_delete_event_in_recurring_single_series_ui(self):
        # create 5 recurring events
        evt1, __, __, __, evt5 = self.create_recurring_events(5)

        with self.subTest(delete_option="delete single, all and following"):
            form = calendar.DeleteEventForm(self.course.identifier, evt1)

            choices = [choice for choice, __ in form.fields["operation"].choices]
            self.assertListEqual(
                choices,
                ["delete_single", "delete_all", "delete_this_and_following"])

        with self.subTest(delete_option="delete single, all"):
            form = calendar.DeleteEventForm(self.course.identifier, evt5)

            choices = [choice for choice, __ in form.fields["operation"].choices]
            self.assertListEqual(
                choices, ["delete_single", "delete_all"])

    @unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_delete_event_in_recurring_multiple_series_ui(self):
        # create 3 recurring events, first series
        self.create_recurring_events(3)

        # create 5 recurring events, with the same kind, another series
        evt1, __, __, __, evt5 = self.create_recurring_events(
            5, staring_ordinal=4, staring_time_offset_days=2)

        with self.subTest(
                delete_option="delete single, all, following, series, "
                              "and following_in_series"):
            form = calendar.DeleteEventForm(self.course.identifier, evt1)

            choices = [choice for choice, __ in form.fields["operation"].choices]
            self.assertListEqual(
                choices,
                ["delete_single",
                 "delete_all",
                 "delete_this_and_following",
                 "delete_all_in_same_series",
                 "delete_this_and_following_of_same_series"])

        with self.subTest(
                delete_option="delete single, all, series"):
            form = calendar.DeleteEventForm(self.course.identifier, evt5)

            choices = [choice for choice, __ in form.fields["operation"].choices]
            self.assertListEqual(
                choices,
                ["delete_single",
                 "delete_all",
                 "delete_all_in_same_series"])

        # Only evt5 has end_time, it no longer belong to a series,
        # thus no series operation
        evt5.end_time = evt5.time + timedelta(minutes=1)
        evt5.save()
        with self.subTest(
                delete_option="delete single, all"):
            form = calendar.DeleteEventForm(self.course.identifier, evt5)

            choices = [choice for choice, __ in form.fields["operation"].choices]
            self.assertListEqual(
                choices,
                ["delete_single",
                 "delete_all"])

        # Same with above, but can delete following
        evt1.end_time = evt1.time + timedelta(minutes=2)
        evt1.save()
        with self.subTest(
                delete_option="delete single, all, this and following"):
            form = calendar.DeleteEventForm(self.course.identifier, evt1)

            choices = [choice for choice, __ in form.fields["operation"].choices]
            self.assertListEqual(
                choices,
                ["delete_single",
                 "delete_all",
                 "delete_this_and_following"])


class GetDeleteEventModalFormTest(CalendarTestMixin, TestCase):
    """test calendar.get_delete_event_modal_form"""
    force_login_student_for_each_test = False

    def setUp(self):
        super(GetDeleteEventModalFormTest, self).setUp()
        self.event = factories.EventFactory(course=self.course)
        self.c.force_login(self.instructor_participation.user)

    def get_delete_event_modal_form_url(self, event_id, course_identifier=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        return reverse("relate-get_delete_event_modal_form",
                       args=[course_identifier, event_id])

    def get_delete_event_modal_form_view(self, event_id, course_identifier=None,
                                         using_ajax=True):
        kwargs = {}
        if using_ajax:
            kwargs["HTTP_X_REQUESTED_WITH"] = 'XMLHttpRequest'
        return self.c.get(
            self.get_delete_event_modal_form_url(event_id, course_identifier),
            **kwargs)

    def test_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_delete_event_modal_form_view(self.event.id)
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(Event.objects.count(), 1)

    def test_post(self):
        resp = self.c.post(
            self.get_delete_event_modal_form_url(self.event.id), data={},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Event.objects.count(), 1)

    def test_post_non_ajax(self):
        resp = self.c.post(
            self.get_delete_event_modal_form_url(self.event.id), data={})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Event.objects.count(), 1)

    def test_get_non_ajax(self):
        resp = self.get_delete_event_modal_form_view(self.event.id, using_ajax=False)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Event.objects.count(), 1)

    def test_get_success(self):
        resp = self.get_delete_event_modal_form_view(self.event.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 1)


class DeleteEventTest(CalendarTestMixin, TestCase):
    """test calendar.delete_event"""
    force_login_student_for_each_test = False

    def setUp(self):
        super(DeleteEventTest, self).setUp()
        self.c.force_login(self.instructor_participation.user)

        # an event in another course, which should not be deleted
        factories.EventFactory(
            course=factories.CourseFactory(identifier="another-course"))

        # an event with another kind, which should not be deleted
        factories.EventFactory(course=self.course, kind="another_kind")

    def get_delete_event_url(self, event_id, course_identifier=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        return reverse("relate-delete_event", args=[course_identifier, event_id])

    def post_delete_event_view(
            self, event_id, operation=None, data=None, course_identifier=None,
            using_ajax=True):

        if data is None:
            data = {}

        if operation:
            data["operation"] = operation

        data = get_prefixed_form_data(calendar.DeleteEventForm, data)

        kwargs = {}
        if using_ajax:
            kwargs["HTTP_X_REQUESTED_WITH"] = 'XMLHttpRequest'
        return self.c.post(
            self.get_delete_event_url(event_id, course_identifier), data=data,
            **kwargs)

    def test_no_pperm(self):
        event = factories.EventFactory(course=self.course)
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.post_delete_event_view(event.id)
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(Event.objects.count(), 3)

    def test_get_non_ajax(self):
        event = factories.EventFactory(course=self.course)
        resp = self.c.get(self.get_delete_event_url(event.id))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Event.objects.count(), 3)

    def test_get(self):
        event = factories.EventFactory(course=self.course)
        resp = self.c.get(self.get_delete_event_url(event.id),
                          HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Event.objects.count(), 3)

    def test_post_no_ajax(self):
        event = factories.EventFactory(course=self.course)
        resp = self.post_delete_event_view(event.id, using_ajax=False)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Event.objects.count(), 3)

    def test_delete_non_existing_event(self):
        factories.EventFactory(course=self.course)
        resp = self.post_delete_event_view(event_id=1000)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(Event.objects.count(), 3)

    def test_delete_single_with_ordinal_success(self):
        event = factories.EventFactory(course=self.course)
        resp = self.post_delete_event_view(event.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 2)

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "Event '%s' deleted." % str(event))

    def test_delete_single_with_no_oridnal_success(self):
        event = factories.EventFactory(course=self.course, ordinal=None)
        resp = self.post_delete_event_view(event.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 2)

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "Event '%s' deleted." % str(event))

    def test_delete_single_within_single_series_success(self):
        events = self.create_recurring_events(2)
        instance_to_delete = events[0]
        resp = self.post_delete_event_view(
            instance_to_delete.id, operation="delete_single")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 3)

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "Event '%s' deleted." % str(instance_to_delete))

    def test_delete_all_within_single_series_success(self):
        events = self.create_recurring_events(2)
        instance_to_delete = events[0]
        resp = self.post_delete_event_view(
            instance_to_delete.id, operation="delete_all")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 2)

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "All 'lecture' events deleted.")

    def test_delete_this_and_following_within_single_series_success(self):
        events = self.create_recurring_events(3)
        instance_to_delete = events[1]
        resp = self.post_delete_event_view(
            instance_to_delete.id, operation="delete_this_and_following")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 3)

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "2 'lecture' events deleted.")

    def test_delete_all_across_multiple_series_success(self):
        events = self.create_recurring_events(3)
        self.create_recurring_events(5, staring_ordinal=4,
                                     staring_time_offset_days=1)
        instance_to_delete = events[1]
        resp = self.post_delete_event_view(
            instance_to_delete.id, operation="delete_all")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 2)

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "All 'lecture' events deleted.")

    def test_delete_all_within_same_series_success(self):
        events = self.create_recurring_events(3)
        self.create_recurring_events(5, staring_ordinal=4,
                                     staring_time_offset_days=1)
        instance_to_delete = events[1]
        with override_settings(TIME_ZONE="Hongkong"):
            resp = self.post_delete_event_view(
                instance_to_delete.id, operation="delete_all_in_same_series")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(Event.objects.count(), 7)

            json_response = json.loads(resp.content.decode())
            self.assertEqual(json_response["message"],
                             "All 'lecture' events (started at Tue, 08:00) deleted.")

    def test_delete_this_and_following_within_same_series_success(self):
        events = self.create_recurring_events(3)
        self.create_recurring_events(5, staring_ordinal=4,
                                     staring_time_offset_days=1)
        instance_to_delete = events[1]
        with override_settings(TIME_ZONE="Hongkong"):
            resp = self.post_delete_event_view(
                instance_to_delete.id,
                operation="delete_this_and_following_of_same_series")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(Event.objects.count(), 8)

            json_response = json.loads(resp.content.decode())
            self.assertEqual(json_response["message"],
                             "2 'lecture' events (started at Tue, 08:00) deleted.")

    def test_delete_event_in_one_recurring_series_end_time_not_match(self):
        # create 3 recurring events, with the same kind, another series
        evt1, __, __, __, evt5 = self.create_recurring_events(
            5, end_time_minute_duration=15)

        # evt1 and evt5's end_time is updated, so there becomes 2 series
        evt1.end_time += timedelta(hours=1)
        evt1.save()

        evt5.end_time += timedelta(hours=1)
        evt5.save()

        with override_settings(TIME_ZONE="Hongkong"):
            resp = self.post_delete_event_view(
                evt1.id,
                operation="delete_all_in_same_series")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(Event.objects.count(), 5)

            json_response = json.loads(resp.content.decode())
            self.assertEqual(
                json_response["message"],
                "All 'lecture' events (started at Tue, 08:00, ended at "
                "Tue, 09:15) deleted.")

    def test_unknown_delete_errored(self):
        events = self.create_recurring_events(3)
        instance_to_delete = events[1]
        with mock.patch("django.db.models.query.QuerySet.delete") as mock_delete:
            mock_delete.side_effect = RuntimeError("unknown delete error.")
            resp = self.post_delete_event_view(
                instance_to_delete.id,
                operation="delete_all")
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(Event.objects.count(), 5)

            json_response = json.loads(resp.content.decode())
            self.assertEqual(json_response["__all__"],
                             ["RuntimeError: unknown delete error."])

    def test_unknown_delete_operation(self):
        events = self.create_recurring_events(3)
        instance_to_delete = events[1]
        resp = self.post_delete_event_view(
            instance_to_delete.id,
            operation="unknown")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Event.objects.count(), 5)

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["errors"]["operation"],
                         ["Select a valid choice. unknown is not one of "
                         "the available choices."])


class UpdateEventFormTest(CalendarTestMixin, TestCase):
    """test calendar.UpdateEventForm"""
    # force_login_student_for_each_test = False

    def setUp(self):
        super(UpdateEventFormTest, self).setUp()
        # self.c.force_login(self.instructor_participation.user)
        rf = RequestFactory()
        self.request = rf.get(self.get_course_page_url())
        self.request.user = self.instructor_participation.user

    # {{{ test get_ajax_form_helper

    def get_ajax_helper_input_button_names(self, helper):
        return [field.name for field in helper.layout[-1].fields]

    def assertFormAJAXHelperButtonNameEqual(self, form, button_names):  # noqa
        self.assertListEqual(
            self.get_ajax_helper_input_button_names(
                form.get_ajax_form_helper()), button_names)

    def test_get_ajax_form_helper_individual_event_no_ordinal(self):
        event = factories.EventFactory(course=self.course)
        form = calendar.UpdateEventForm(self.course.identifier, event.id)
        self.assertFormAJAXHelperButtonNameEqual(form, ['update', 'cancel'])

    def test_get_ajax_form_helper_individual_event_with_ordinal(self):
        event = factories.EventFactory(course=self.course, ordinal=None)
        form = calendar.UpdateEventForm(self.course.identifier, event.id)
        self.assertFormAJAXHelperButtonNameEqual(form, ['update', 'cancel'])

    def test_get_ajax_form_helper_single_series(self):
        events = self.create_recurring_events(5)
        form = calendar.UpdateEventForm(self.course.identifier, events[0].id)
        self.assertFormAJAXHelperButtonNameEqual(
            form,
            ['update_all', 'update_this_and_following', 'update', 'cancel'])

    def test_get_ajax_form_helper_single_series_not_may_update_this_and_following(self):  # noqa
        events = self.create_recurring_events(5)
        form = calendar.UpdateEventForm(self.course.identifier, events[4].id)
        self.assertFormAJAXHelperButtonNameEqual(
            form,
            ['update_all', 'update', 'cancel'])

    def test_get_ajax_form_helper_multiple_series(self):
        events = self.create_recurring_events(5)
        self.create_recurring_events(3, staring_ordinal=6,
                                     staring_time_offset_days=1)
        form = calendar.UpdateEventForm(self.course.identifier, events[0].id)
        self.assertFormAJAXHelperButtonNameEqual(
            form,
            ['update_series', 'update_this_and_following_in_series',
             'update', 'cancel'])

    def test_get_ajax_form_helper_multiple_series_has_end_time(self):
        events = self.create_recurring_events(5)
        self.create_recurring_events(3, staring_ordinal=6,
                                     staring_time_offset_days=1,
                                     end_time_minute_duration=15)
        form = calendar.UpdateEventForm(self.course.identifier, events[0].id)
        self.assertFormAJAXHelperButtonNameEqual(
            form,
            ['update_series', 'update_this_and_following_in_series',
             'update', 'cancel'])

    def test_events_have_no_correspond_end_time(self):
        events = self.create_recurring_events(2)
        event1 = events[0]
        event1.end_time = event1.time + timedelta(minutes=15)
        event1.save()

        form = calendar.UpdateEventForm(self.course.identifier, event1.id)
        self.assertFormAJAXHelperButtonNameEqual(
            form,
            ['update', 'cancel'])

    def test_get_ajax_form_helper_multiple_series_not_may_update_this_and_following(self):  # noqa
        events = self.create_recurring_events(5)
        self.create_recurring_events(3, staring_ordinal=6,
                                     staring_time_offset_days=1)
        form = calendar.UpdateEventForm(self.course.identifier, events[4].id)
        self.assertFormAJAXHelperButtonNameEqual(
            form,
            ['update_series', 'update', 'cancel'])

    # }}}


class GetUpdateEventModalFormTest(CalendarTestMixin, TestCase):
    """test calendar.get_update_event_modal_form"""
    force_login_student_for_each_test = False

    def setUp(self):
        super(GetUpdateEventModalFormTest, self).setUp()
        self.event = factories.EventFactory(course=self.course)
        self.c.force_login(self.instructor_participation.user)

    def get_update_event_modal_form_url(self, event_id, course_identifier=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        return reverse("relate-get_update_event_modal_form",
                       args=[course_identifier, event_id])

    def get_update_event_modal_form_view(self, event_id, course_identifier=None,
                                         using_ajax=True):
        kwargs = {}
        if using_ajax:
            kwargs["HTTP_X_REQUESTED_WITH"] = 'XMLHttpRequest'
        return self.c.get(
            self.get_update_event_modal_form_url(event_id, course_identifier),
            **kwargs)

    def test_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_update_event_modal_form_view(self.event.id)
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(Event.objects.count(), 1)

    def test_post_non_ajax(self):
        resp = self.c.post(
            self.get_update_event_modal_form_url(self.event.id), data={})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Event.objects.count(), 1)

    def test_get_non_ajax(self):
        resp = self.get_update_event_modal_form_view(self.event.id, using_ajax=False)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Event.objects.count(), 1)

    def test_get_success(self):
        resp = self.get_update_event_modal_form_view(self.event.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 1)

    def test_post_success(self):
        resp = self.c.post(
            self.get_update_event_modal_form_url(self.event.id), data={},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 1)

    def test_post_drop_timedelta_hours_success(self):
        resp = self.c.post(
            self.get_update_event_modal_form_url(self.event.id),
            data={"drop_timedelta_hours": 1},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 1)

    def test_post_drop_timedelta_hours_event_has_end_time_success(self):
        self.event.end_time = self.event.time + timedelta(hours=1)
        self.event.save()
        resp = self.c.post(
            self.get_update_event_modal_form_url(self.event.id),
            data={"drop_timedelta_hours": 1},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 1)

    def test_post_resize_timedelta_hours_failed(self):
        resp = self.c.post(
            self.get_update_event_modal_form_url(self.event.id),
            data={"resize_timedelta_hours": 1},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Event.objects.count(), 1)

    def test_post_resize_timedelta_hours_success(self):
        self.event.end_time = self.event.time + timedelta(hours=1)
        self.event.save()
        resp = self.c.post(
            self.get_update_event_modal_form_url(self.event.id),
            data={"resize_timedelta_hours": 1},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 1)


class UpdateEventTest(CalendarTestMixin, TestCase):
    """test calendar.update_event"""
    force_login_student_for_each_test = False

    def setUp(self):
        super(UpdateEventTest, self).setUp()

        # an event in another course, which should not be edited
        self.another_course_event = factories.EventFactory(
            course=factories.CourseFactory(identifier="another-course"),
            kind=self.default_event_kind,
            time=self.default_faked_now)

        # an event with another kind, which should not be edited
        self.another_kind_event = factories.EventFactory(
            course=self.course, kind="another_kind")

        # this is to make sure other events are not affected during update
        self.another_course_event_dict = get_object_dict(self.another_course_event)
        self.another_kind_event_dict = get_object_dict(self.another_kind_event)

        self.c.force_login(self.instructor_participation.user)

    def assertOtherEventNotAffected(self):  # noqa
        self.another_course_event.refresh_from_db()
        self.another_kind_event.refresh_from_db()
        self.assertDictEqual(
            self.another_course_event_dict,
            get_object_dict(self.another_course_event))
        self.assertDictEqual(
            self.another_kind_event_dict,
            get_object_dict(self.another_kind_event))

    def create_event(self, **kwargs):
        data = {
            "course": self.course,
            "kind": self.default_event_kind,
            'time': self.default_faked_now,
            'shown_in_calendar': True,
            'all_day': False
        }
        data.update(kwargs)
        return factories.EventFactory(**data)

    def get_update_event_url(self, event_id, course_identifier=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        return reverse("relate-update_event", args=[course_identifier, event_id])

    def get_default_post_data(self, event, time=None, end_time=None,
                              operation='update', **kwargs):
        #Note: to remove ordinal, explicitly set ordinal=None

        data = {
            'kind': event.kind,
            'shown_in_calendar': event.shown_in_calendar,
            'all_day': event.all_day,
        }

        if time is None:
            time = kwargs.pop("time", None)

        if time is None:
            time = event.time

        data["time"] = as_local_time(time).strftime(DATE_TIME_PICKER_TIME_FORMAT)

        if end_time is None:
            end_time = kwargs.pop("end_time", None)

        if end_time is None:
            end_time = event.end_time

        if end_time is not None:
            data["end_time"] = (
                as_local_time(end_time).strftime(DATE_TIME_PICKER_TIME_FORMAT))

        try:
            ordinal = kwargs.pop("ordinal")
        except KeyError:
            ordinal = event.ordinal

        if ordinal is not None:
            data["ordinal"] = ordinal

        data.update(kwargs)
        data = get_prefixed_form_data(calendar.UpdateEventForm, data)

        if operation:
            data[operation] = ''

        return data

    def post_update_event_view(
            self, event_id, data, course_identifier=None,
            using_ajax=True):

        kwargs = {}
        if using_ajax:
            kwargs["HTTP_X_REQUESTED_WITH"] = 'XMLHttpRequest'
        return self.c.post(
            self.get_update_event_url(event_id, course_identifier), data=data,
            **kwargs)

    def test_no_pperm(self):
        event = self.create_event()
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.post_update_event_view(event.id, data={})
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(Event.objects.count(), 3)

    def test_get_non_ajax(self):
        event = self.create_event()
        resp = self.c.get(self.get_update_event_url(event.id))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Event.objects.count(), 3)

    def test_get(self):
        event = self.create_event()
        resp = self.c.get(self.get_update_event_url(event.id),
                          HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Event.objects.count(), 3)

    def test_post_no_ajax(self):
        event = self.create_event()
        resp = self.post_update_event_view(event.id, using_ajax=False, data={})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Event.objects.count(), 3)

    def test_update_non_existing_event(self):
        self.create_event()
        resp = self.post_update_event_view(event_id=1000, data={})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(Event.objects.count(), 3)

    def test_update_form_invalid(self):
        event = self.create_event()
        end_time = as_local_time(event.time - timedelta(hours=2))

        resp = self.post_update_event_view(
            event.id, data=self.get_default_post_data(event, end_time=end_time))
        self.assertEqual(resp.status_code, 400)

        event.refresh_from_db()
        self.assertIsNone(event.end_time)

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["errors"]["end_time"],
                         ["End time must not be ahead of start time."])

    def test_update_single_with_ordinal_success(self):
        event = self.create_event()
        end_time = as_local_time(event.time + timedelta(hours=2))

        resp = self.post_update_event_view(
            event.id, data=self.get_default_post_data(event, end_time=end_time))
        self.assertEqual(resp.status_code, 200)

        event.refresh_from_db()
        self.assertEqual(event.end_time, end_time)

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "Event '%s' updated." % str(event))

    def test_update_not_changed(self):
        event = self.create_event()

        resp = self.post_update_event_view(
            event.id,
            data=self.get_default_post_data(event))
        self.assertEqual(resp.status_code, 200)

        event.refresh_from_db()

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"], "No change was made.")

        self.assertOtherEventNotAffected()

    def test_update_single_with_ordinal_success_kind_changed(self):
        event = self.create_event()
        event_str = str(event)

        resp = self.post_update_event_view(
            event.id,
            data=self.get_default_post_data(event, kind="some_kind"))
        self.assertEqual(resp.status_code, 200)

        event.refresh_from_db()

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "Event updated: '%s' -> '%s'" % (event_str, str(event)))
        self.assertOtherEventNotAffected()

    def test_update_single_with_no_ordinal_success(self):
        event = self.create_event(ordinal=None)
        end_time = as_local_time(event.time + timedelta(hours=2))

        resp = self.post_update_event_view(
            event.id, data=self.get_default_post_data(event, end_time=end_time))
        self.assertEqual(resp.status_code, 200)

        event.refresh_from_db()
        self.assertEqual(event.end_time, end_time)

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "Event '%s' updated." % str(event))
        self.assertOtherEventNotAffected()

    def test_update_single_within_single_series_success(self):
        instance_to_update, another_event = self.create_recurring_events(2)

        end_time = as_local_time(instance_to_update.time + timedelta(hours=2))
        resp = self.post_update_event_view(
            instance_to_update.id,
            self.get_default_post_data(instance_to_update, end_time=end_time)
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Event.objects.count(), 4)

        instance_to_update.refresh_from_db()
        self.assertIsNotNone(instance_to_update.end_time)

        another_event.refresh_from_db()
        self.assertIsNone(another_event.end_time)

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "Event '%s' updated." % str(instance_to_update))
        self.assertOtherEventNotAffected()

    def test_update_all_no_endtime_success(self):
        instance_to_update, another_event = self.create_recurring_events(2)

        original_time1 = instance_to_update.time
        original_time2 = another_event.time
        new_time = as_local_time(instance_to_update.time + timedelta(hours=2))

        resp = self.post_update_event_view(
            instance_to_update.id,
            self.get_default_post_data(
                instance_to_update, time=new_time, operation="update_all")
        )
        self.assertEqual(resp.status_code, 200)

        instance_to_update.refresh_from_db()
        self.assertEqual(
            instance_to_update.time - original_time1,
            timedelta(hours=2)
        )

        another_event.refresh_from_db()
        self.assertEqual(
            another_event.time - original_time2,
            timedelta(hours=2)
        )

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "All '%s' events updated."
                         % instance_to_update.kind)

        self.assertOtherEventNotAffected()

    def test_update_all_success(self):
        instance_to_update, another_event = self.create_recurring_events(2)

        end_time = as_local_time(instance_to_update.time + timedelta(hours=2))

        resp = self.post_update_event_view(
            instance_to_update.id,
            self.get_default_post_data(
                instance_to_update, end_time=end_time, operation="update_all")
        )
        self.assertEqual(resp.status_code, 200)

        instance_to_update.refresh_from_db()
        self.assertEqual(
            instance_to_update.end_time - instance_to_update.time,
            timedelta(hours=2)
        )

        another_event.refresh_from_db()
        self.assertEqual(
            another_event.end_time - another_event.time,
            timedelta(hours=2)
        )

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "All '%s' events updated."
                         % instance_to_update.kind)

        self.assertOtherEventNotAffected()

    def test_update_this_and_following_success(self):
        evt1, instance_to_update, evt3 = self.create_recurring_events(3)

        end_time = as_local_time(instance_to_update.time + timedelta(hours=2))

        resp = self.post_update_event_view(
            instance_to_update.id,
            self.get_default_post_data(
                instance_to_update,
                end_time=end_time, operation="update_this_and_following")
        )
        self.assertEqual(resp.status_code, 200)

        evt1.refresh_from_db()
        self.assertIsNone(evt1.end_time)

        instance_to_update.refresh_from_db()
        self.assertEqual(
            instance_to_update.end_time - instance_to_update.time,
            timedelta(hours=2)
        )

        evt3.refresh_from_db()
        self.assertEqual(
            evt3.end_time - evt3.time,
            timedelta(hours=2)
        )

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "2 '%s' events updated."
                         % instance_to_update.kind)

        self.assertOtherEventNotAffected()

    def test_update_all_in_a_series_success(self):
        instance_to_update, another_event = self.create_recurring_events(2)

        self.create_recurring_events(
            5, staring_time_offset_days=1, staring_ordinal=3)

        end_time = as_local_time(instance_to_update.time + timedelta(hours=2))

        with override_settings(TIME_ZONE="Hongkong"):
            resp = self.post_update_event_view(
                instance_to_update.id,
                self.get_default_post_data(
                    instance_to_update, end_time=end_time, operation="update_series")
            )

        self.assertEqual(resp.status_code, 200)

        instance_to_update.refresh_from_db()
        self.assertEqual(
            instance_to_update.end_time - instance_to_update.time,
            timedelta(hours=2)
        )

        another_event.refresh_from_db()
        self.assertEqual(
            another_event.end_time - another_event.time,
            timedelta(hours=2)
        )

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "All '%s' events (started at Tue, 08:00) updated."
                         % (instance_to_update.kind))

        self.assertEqual(
            Event.objects.filter(
                course=self.course,
                kind=self.default_event_kind, end_time__isnull=True).count(),
            5)
        self.assertOtherEventNotAffected()

    def test_update_this_and_following_in_a_series_success(self):
        evt1, instance_to_update, evt3 = self.create_recurring_events(3)

        self.create_recurring_events(
            5, staring_time_offset_days=1, staring_ordinal=4)

        end_time = as_local_time(instance_to_update.time + timedelta(hours=2))

        with override_settings(TIME_ZONE="Hongkong"):
            resp = self.post_update_event_view(
                instance_to_update.id,
                self.get_default_post_data(
                    instance_to_update,
                    end_time=end_time,
                    operation="update_this_and_following_in_series")
            )
        self.assertEqual(resp.status_code, 200)

        evt1.refresh_from_db()
        self.assertIsNone(evt1.end_time)

        instance_to_update.refresh_from_db()
        self.assertEqual(
            instance_to_update.end_time - instance_to_update.time,
            timedelta(hours=2)
        )

        evt3.refresh_from_db()
        self.assertEqual(
            evt3.end_time - evt3.time,
            timedelta(hours=2)
        )

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "2 '%s' events (started at Tue, 08:00) updated."
                         % (instance_to_update.kind))

        self.assertEqual(
            Event.objects.filter(
                course=self.course,
                kind=self.default_event_kind, end_time__isnull=True).count(),
            6)
        self.assertOtherEventNotAffected()

    def test_update_unknown_operation(self):
        instance_to_update, another_event = self.create_recurring_events(2)

        end_time = as_local_time(instance_to_update.time + timedelta(hours=2))

        resp = self.post_update_event_view(
            instance_to_update.id,
            self.get_default_post_data(
                instance_to_update, end_time=end_time, operation="unknown_operation")
        )
        self.assertEqual(resp.status_code, 400)

        self.assertEqual(Event.objects.filter(
            course=self.course, kind=self.default_event_kind,
            end_time__isnull=True).count(),
            2)

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["__all__"],
                         ['SuspiciousOperation: unknown operation'])

        self.assertOtherEventNotAffected()

    def test_update_remove_recurring_event_ordinal(self):
        instance_to_update, another_event = self.create_recurring_events(2)

        resp = self.post_update_event_view(
            instance_to_update.id,
            self.get_default_post_data(
                instance_to_update, ordinal=None, operation="update_all")
        )
        self.assertEqual(resp.status_code, 400)

        self.assertEqual(Event.objects.filter(
            course=self.course, kind=self.default_event_kind,
            end_time__isnull=True).count(),
            2)

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["__all__"],
                         ['RuntimeError: May not do bulk update when '
                          'ordinal is None'])

        self.assertOtherEventNotAffected()

    def test_update_bulk_change_kind(self):
        __, instance_to_update = self.create_recurring_events(2)

        resp = self.post_update_event_view(
            instance_to_update.id,
            self.get_default_post_data(
                instance_to_update, kind="new_kind", operation="update_all")
        )
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(Event.objects.filter(
            course=self.course, kind="new_kind").count(),
            2)

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "All 'lecture' events updated: "
                         "'lecture' -> 'new_kind'.")

        self.assertOtherEventNotAffected()

    def test_update_series_consider_end_time(self):
        # Events with recurring start time but with non-recurring end_time
        # won't be considered as in a same series.
        instance_to_update, another_event = (
            self.create_recurring_events(2, end_time_minute_duration=60))

        self.create_recurring_events(
            5, staring_time_offset_days=1, staring_ordinal=4)

        instance_to_update.end_time += timedelta(hours=1)
        instance_to_update.save()

        with override_settings(TIME_ZONE="Hongkong"):
            resp = self.post_update_event_view(
                instance_to_update.id,
                self.get_default_post_data(
                    instance_to_update, kind="new_kind", operation="update_series")
            )
        self.assertEqual(resp.status_code, 200)

        # only one is updated
        self.assertEqual(Event.objects.filter(
            course=self.course, kind="new_kind").count(),
            1)

        json_response = json.loads(resp.content.decode())
        self.assertEqual(json_response["message"],
                         "All 'lecture' events (started at Tue, 08:00, "
                         "ended at Tue, 10:00) updated: "
                         "'lecture' -> 'new_kind'.")

        self.assertOtherEventNotAffected()

# vim: fdm=marker
