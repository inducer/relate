# -*- coding: utf-8 -*-

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

import six
from six.moves import range

from django.utils.translation import (
        ugettext_lazy as _, pgettext_lazy, string_concat)
from django.contrib.auth.decorators import login_required
from course.utils import course_view, render_course_page
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from django.db import transaction, IntegrityError
from django.contrib import messages  # noqa
import django.forms as forms

from crispy_forms.layout import Submit

import datetime
from bootstrap3_datetime.widgets import DateTimePicker

from relate.utils import StyledForm, as_local_time
from course.constants import (
        participation_permission as pperm,
        )
from course.models import Event


# {{{ creation

class RecurringEventForm(StyledForm):
    kind = forms.CharField(required=True,
            help_text=_("Should be lower_case_with_underscores, no spaces "
                        "allowed."),
            label=pgettext_lazy("Kind of event", "Kind of event"))
    time = forms.DateTimeField(
            widget=DateTimePicker(
                options={"format": "YYYY-MM-DD HH:mm", "sideBySide": True}),
            label=pgettext_lazy("Starting time of event", "Starting time"))
    duration_in_minutes = forms.FloatField(required=False,
            label=_("Duration in minutes"))
    all_day = forms.BooleanField(
                required=False,
                initial=False,
                label=_("All-day event"),
                help_text=_("Only affects the rendering in the class calendar, "
                "in that a start time is not shown"))
    shown_in_calendar = forms.BooleanField(
            required=False,
            initial=True,
            label=_('Shown in calendar'))
    interval = forms.ChoiceField(required=True,
            choices=(
                ("weekly", _("Weekly")),
                ("biweekly", _("Bi-Weekly")),
                ),
            label=pgettext_lazy("Interval of recurring events", "Interval"))
    starting_ordinal = forms.IntegerField(required=False,
            label=pgettext_lazy(
                "Starting ordinal of recurring events", "Starting ordinal"))
    count = forms.IntegerField(required=True,
            label=pgettext_lazy("Count of recurring events", "Count"))

    def __init__(self, *args, **kwargs):
        super(RecurringEventForm, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit", _("Create")))


class EventAlreadyExists(Exception):
    pass


@transaction.atomic
def _create_recurring_events_backend(course, time, kind, starting_ordinal, interval,
        count, duration_in_minutes, all_day, shown_in_calendar):
    ordinal = starting_ordinal

    import datetime

    for i in range(count):
        evt = Event()
        evt.course = course
        evt.kind = kind
        evt.ordinal = ordinal
        evt.time = time
        evt.all_day = all_day
        evt.shown_in_calendar = shown_in_calendar

        if duration_in_minutes:
            evt.end_time = evt.time + datetime.timedelta(
                    minutes=duration_in_minutes)
        try:
            evt.save()
        except IntegrityError:
            raise EventAlreadyExists(
                _("'%(event_kind)s %(event_ordinal)d' already exists") %
                {'event_kind': kind, 'event_ordinal': ordinal})

        date = time.date()
        if interval == "weekly":
            date += datetime.timedelta(weeks=1)
        elif interval == "biweekly":
            date += datetime.timedelta(weeks=2)
        else:
            raise ValueError(
                    string_concat(
                        pgettext_lazy(
                            "Unkown time interval",
                            "unknown interval"),
                        ": %s")
                    % interval)

        time = time.tzinfo.localize(
                datetime.datetime(date.year, date.month, date.day,
                    time.hour, time.minute, time.second))
        del date

        ordinal += 1


@login_required
@course_view
def create_recurring_events(pctx):
    if not pctx.has_permission(pperm.edit_events):
        raise PermissionDenied(_("may not edit events"))

    request = pctx.request

    if request.method == "POST":
        form = RecurringEventForm(request.POST, request.FILES)
        if form.is_valid():
            if form.cleaned_data["starting_ordinal"] is not None:
                starting_ordinal = form.cleaned_data["starting_ordinal"]
                starting_ordinal_specified = True
            else:
                starting_ordinal = 1
                starting_ordinal_specified = False

            while True:
                try:
                    _create_recurring_events_backend(
                            course=pctx.course,
                            time=form.cleaned_data["time"],
                            kind=form.cleaned_data["kind"],
                            starting_ordinal=starting_ordinal,
                            interval=form.cleaned_data["interval"],
                            count=form.cleaned_data["count"],
                            duration_in_minutes=(
                                form.cleaned_data["duration_in_minutes"]),
                            all_day=form.cleaned_data["all_day"],
                            shown_in_calendar=(
                                form.cleaned_data["shown_in_calendar"])
                            )
                except EventAlreadyExists as e:
                    if starting_ordinal_specified:
                        messages.add_message(request, messages.ERROR,
                                string_concat(
                                    "%(err_type)s: %(err_str)s. ",
                                    _("No events created."))
                                % {
                                    "err_type": type(e).__name__,
                                    "err_str": str(e)})
                    else:
                        starting_ordinal += 10
                        continue

                except Exception as e:
                    messages.add_message(request, messages.ERROR,
                            string_concat(
                                "%(err_type)s: %(err_str)s. ",
                                _("No events created."))
                            % {
                                "err_type": type(e).__name__,
                                "err_str": str(e)})
                else:
                    messages.add_message(request, messages.SUCCESS,
                            _("Events created."))

                break
    else:
        form = RecurringEventForm()

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": _("Create recurring events"),
    })


class RenumberEventsForm(StyledForm):
    kind = forms.CharField(required=True,
            help_text=_("Should be lower_case_with_underscores, no spaces "
                        "allowed."),
            label=pgettext_lazy("Kind of event", "Kind of event"))
    starting_ordinal = forms.IntegerField(required=True, initial=1,
            label=pgettext_lazy(
                "Starting ordinal of recurring events", "Starting ordinal"))

    def __init__(self, *args, **kwargs):
        super(RenumberEventsForm, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit", _("Renumber")))


@transaction.atomic
@login_required
@course_view
def renumber_events(pctx):
    if not pctx.has_permission(pperm.edit_events):
        raise PermissionDenied(_("may not edit events"))

    request = pctx.request

    if request.method == "POST":
        form = RenumberEventsForm(request.POST, request.FILES)
        if form.is_valid():
            events = list(Event.objects
                    .filter(course=pctx.course, kind=form.cleaned_data["kind"])
                    .order_by('time'))

            if events:
                queryset = (Event.objects
                    .filter(course=pctx.course, kind=form.cleaned_data["kind"]))

                queryset.delete()

                ordinal = form.cleaned_data["starting_ordinal"]
                for event in events:
                    new_event = Event()
                    new_event.course = pctx.course
                    new_event.kind = form.cleaned_data["kind"]
                    new_event.ordinal = ordinal
                    new_event.time = event.time
                    new_event.end_time = event.end_time
                    new_event.all_day = event.all_day
                    new_event.shown_in_calendar = event.shown_in_calendar
                    new_event.save()

                    ordinal += 1

                messages.add_message(request, messages.SUCCESS,
                        _("Events renumbered."))
            else:
                messages.add_message(request, messages.ERROR,
                        _("No events found."))

    else:
        form = RenumberEventsForm()

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": _("Renumber events"),
    })

# }}}


# {{{ calendar

class EventInfo(object):
    def __init__(self, id, human_title, start_time, end_time, description):
        self.id = id
        self.human_title = human_title
        self.start_time = start_time
        self.end_time = end_time
        self.description = description


@course_view
def view_calendar(pctx):
    from course.content import markup_to_html, parse_date_spec

    from course.views import get_now_or_fake_time
    now = get_now_or_fake_time(pctx.request)

    if not pctx.has_permission(pperm.view_calendar):
        raise PermissionDenied(_("may not view calendar"))

    events_json = []

    from course.content import get_raw_yaml_from_repo
    try:
        event_descr = get_raw_yaml_from_repo(pctx.repo,
                pctx.course.events_file, pctx.course_commit_sha)
    except ObjectDoesNotExist:
        event_descr = {}

    event_kinds_desc = event_descr.get("event_kinds", {})
    event_info_desc = event_descr.get("events", {})

    event_info_list = []

    events = sorted(
            Event.objects
            .filter(
                course=pctx.course,
                shown_in_calendar=True),
            key=lambda evt: (
                -evt.time.year, -evt.time.month, -evt.time.day,
                evt.time.hour, evt.time.minute, evt.time.second))

    for event in events:
        kind_desc = event_kinds_desc.get(event.kind)

        human_title = six.text_type(event)

        event_json = {
                "id": event.id,
                "start": event.time.isoformat(),
                "allDay": event.all_day,
                }
        if event.end_time is not None:
            event_json["end"] = event.end_time.isoformat()

        if kind_desc is not None:
            if "color" in kind_desc:
                event_json["color"] = kind_desc["color"]
            if "title" in kind_desc:
                if event.ordinal is not None:
                    human_title = kind_desc["title"].format(nr=event.ordinal)
                else:
                    human_title = kind_desc["title"]

        description = None
        show_description = True
        event_desc = event_info_desc.get(six.text_type(event))
        if event_desc is not None:
            if "description" in event_desc:
                description = markup_to_html(
                        pctx.course, pctx.repo, pctx.course_commit_sha,
                        event_desc["description"])

            if "title" in event_desc:
                human_title = event_desc["title"]

            if "color" in event_desc:
                event_json["color"] = event_desc["color"]

            if "show_description_from" in event_desc:
                ds = parse_date_spec(
                        pctx.course, event_desc["show_description_from"])
                if now < ds:
                    show_description = False

            if "show_description_until" in event_desc:
                ds = parse_date_spec(
                        pctx.course, event_desc["show_description_until"])
                if now > ds:
                    show_description = False

        event_json["title"] = human_title

        if show_description and description:
            event_json["url"] = "#event-%d" % event.id

            start_time = event.time
            end_time = event.end_time

            if event.all_day:
                start_time = start_time.date()
                if end_time is not None:
                    local_end_time = as_local_time(end_time)
                    end_midnight = datetime.time(tzinfo=local_end_time.tzinfo)
                    if local_end_time.time() == end_midnight:
                        end_time = (end_time - datetime.timedelta(days=1)).date()
                    else:
                        end_time = end_time.date()

            event_info_list.append(
                    EventInfo(
                        id=event.id,
                        human_title=human_title,
                        start_time=start_time,
                        end_time=end_time,
                        description=description
                        ))

        events_json.append(event_json)

    default_date = now.date()
    if pctx.course.end_date is not None and default_date > pctx.course.end_date:
        default_date = pctx.course.end_date

    from json import dumps
    return render_course_page(pctx, "course/calendar.html", {
        "events_json": dumps(events_json),
        "event_info_list": event_info_list,
        "default_date": default_date.isoformat(),
    })

# }}}

# vim: foldmethod=marker
