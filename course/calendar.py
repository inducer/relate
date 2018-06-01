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
import datetime
from bootstrap3_datetime.widgets import DateTimePicker
from crispy_forms.layout import (
    Layout, Div, ButtonHolder, Button, Submit, HTML)

from django.utils.translation import (
        ugettext_lazy as _, pgettext_lazy)
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.exceptions import (
    PermissionDenied, ObjectDoesNotExist, ValidationError, SuspiciousOperation)
from django.db import transaction
from django.contrib import messages
from django.urls import reverse
from django.http import JsonResponse
import django.forms as forms

from relate.utils import (
    StyledForm, as_local_time, format_datetime_local, string_concat, StyledModelForm)

from course.views import get_now_or_fake_time
from course.constants import (
        participation_permission as pperm,
        )
from course.models import Event
from course.utils import course_view, render_course_page

# {{{ for mypy

if False:
    from typing import Tuple, Text, Optional, Any, Dict, Iterable, List, Union  # noqa
    from crispy_forms.helper import FormHelper  # noqa
    from django import http  # noqa
    from course.utils import CoursePageContext  # noqa

# }}}


class ModalStyledFormMixin(object):
    ajax_modal_form_template = "modal-form.html"

    @property
    def form_title(self):
        raise NotImplementedError()

    @property
    def modal_id(self):
        raise NotImplementedError()

    def get_ajax_form_helper(self):
        # type: (...) -> FormHelper
        return self.get_form_helper()  # type: ignore

    def render_ajax_modal_form_html(self, request, context=None):
        # type: (http.HttpRequest, Optional[Dict]) -> Text

        # remove possbily added buttons by non-AJAX form
        self.helper.inputs = []  # type: ignore

        from crispy_forms.utils import render_crispy_form
        from django.template.context_processors import csrf
        helper = self.get_ajax_form_helper()
        helper.template = self.ajax_modal_form_template
        if context is None:
            context = {}
        context.update(csrf(request))
        return render_crispy_form(self, helper, context)


class ListTextWidget(forms.TextInput):
    # Widget which allow free text and choices for CharField
    def __init__(self, data_list, name, *args, **kwargs):
        # type: (List[Tuple[Text, Text]], Text, *Any, **Any) -> None

        super(ListTextWidget, self).__init__(*args, **kwargs)
        self._name = name
        self._list = data_list
        self.attrs.update({'list': 'list__%s' % self._name})

    def render(self, name, value, attrs=None, renderer=None):
        text_html = super(ListTextWidget, self).render(
            name, value, attrs=attrs, renderer=renderer)
        data_list = '<datalist id="list__%s">' % self._name
        for item in self._list:
            data_list += '<option value="%s">%s</option>' % (item[0], item[1])
        data_list += '</datalist>'

        return (text_html + data_list)


def get_local_time_weekday_hour_minute(dt):
    # type: (datetime.datetime) -> Tuple[datetime.datetime, int, int, int]

    """Takes a timezone-aware datetime and applies the server timezone, and return
    the local_time, week_day, hour and minute"""

    local_time = as_local_time(dt)

    # https://docs.djangoproject.com/en/dev/ref/models/querysets/#week-day
    # Sunday = 1
    week_day = local_time.weekday() + 2
    if week_day == 8:
        week_day = 1
    hour = local_time.hour
    minute = local_time.minute

    return local_time, week_day, hour, minute


def get_recurring_event_series_time_desc_from_instance(event):
    # type: (Event) -> Text
    series_time_str = _(
        "started at %s"
        % format_datetime_local(
            as_local_time(event.time), format="D, H:i"))

    if event.end_time:
        series_time_str = string_concat(
            series_time_str, ", ",
            _("ended at %s"
              % format_datetime_local(as_local_time(event.end_time),
                                      format="D, H:i")))
    return series_time_str


# {{{ creation

class RecurringEventForm(ModalStyledFormMixin, StyledForm):
    form_title = _("Create recurring events")
    modal_id = "create-recurring-events-modal"

    # This is to avoid field name conflict
    prefix = "recurring"

    kind = forms.CharField(required=True,
            help_text=_("Should be lower_case_with_underscores, no spaces "
                        "allowed."),
            label=pgettext_lazy("Kind of event", "Kind of event"))
    time = forms.DateTimeField(
            widget=DateTimePicker(
                options={"format": "YYYY-MM-DD HH:mm", "sideBySide": True}),
            label=pgettext_lazy("Starting time of event", "Starting time"))
    duration_in_minutes = forms.FloatField(required=False,
            min_value=0,
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
            min_value=0,
            label=pgettext_lazy("Count of recurring events", "Count"))

    def __init__(self, course_identifier, *args, **kwargs):
        # type: (Text, *Any, **Any) -> None
        super(RecurringEventForm, self).__init__(*args, **kwargs)
        self.course_identifier = course_identifier

        exist_event_choices = [(choice, choice) for choice in set(
            Event.objects.filter(
                course__identifier=course_identifier)
            .values_list("kind", flat=True))]
        self.fields['kind'].widget = ListTextWidget(data_list=exist_event_choices,
                                                    name="event_choices")

        self.helper.add_input(
                Submit("submit", _("Create")))

    def get_ajax_form_helper(self):
        helper = self.get_form_helper()
        self.helper.form_action = reverse(
            "relate-create_recurring_events", args=[self.course_identifier])

        # Form media (FullCalendar and mement js) are manually added to page head
        self.helper.include_media = False

        helper.layout = Layout(
            Div(*self.fields, css_class="modal-body"),
            ButtonHolder(
                Submit("submit", _("Create"),
                       css_class="btn btn-md btn-success"),
                Button("cancel", _("Cancel"),
                       css_class="btn btn-md btn-default",
                       data_dismiss="modal"),
                css_class="modal-footer"))
        return helper


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
        except Exception as e:
            if isinstance(e, ValidationError) and "already exists" in str(e):
                raise EventAlreadyExists(
                    _("'%(exist_event)s' already exists")
                    % {'exist_event': evt})
            raise e

        date = time.date()
        if interval == "weekly":
            date += datetime.timedelta(weeks=1)
        elif interval == "biweekly":
            date += datetime.timedelta(weeks=2)
        else:
            raise NotImplementedError()

        time = time.tzinfo.localize(
                datetime.datetime(date.year, date.month, date.day,
                    time.hour, time.minute, time.second))
        del date

        ordinal += 1


@course_view
def get_recurring_events_modal_form(pctx):
    # type: (CoursePageContext) -> http.JsonResponse

    if not pctx.has_permission(pperm.edit_events):
        raise PermissionDenied(_("may not edit events"))

    request = pctx.request
    if not (request.is_ajax() and request.method == "GET"):
        raise PermissionDenied(_("only AJAX GET is allowed"))

    recurring_events_form = RecurringEventForm(pctx.course.identifier)

    return JsonResponse(
        {"modal_id": recurring_events_form.modal_id,
         "form_html":
             recurring_events_form.render_ajax_modal_form_html(pctx.request)})


@login_required
@course_view
def create_recurring_events(pctx):
    # type: (CoursePageContext) -> Union[http.HttpResponse, http.JsonResponse]

    if not pctx.has_permission(pperm.edit_events):
        raise PermissionDenied(_("may not edit events"))

    request = pctx.request
    message = None
    message_level = None

    if request.method == "GET" and request.is_ajax():
        raise PermissionDenied(_("may not GET by AJAX"))

    if request.method == "POST":
        form = RecurringEventForm(
            pctx.course.identifier, request.POST, request.FILES)
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
                    message = _("Events created.")
                    message_level = messages.SUCCESS
                except EventAlreadyExists as e:
                    if starting_ordinal_specified:
                        message = (
                                string_concat(
                                    "%(err_type)s: %(err_str)s. ",
                                    _("No events created."))
                                % {
                                    "err_type": type(e).__name__,
                                    "err_str": str(e)})
                        message_level = messages.ERROR
                    else:
                        starting_ordinal += 10
                        continue

                except Exception as e:
                    if isinstance(e, ValidationError):
                        for field, error in e.error_dict.items():
                            try:
                                form.add_error(field, error)
                            except ValueError:
                                # This happens when ValidationError were
                                # raised for fields which don't exist in
                                # RecurringEventForm
                                form.add_error(
                                    "__all__", "'%s': %s" % (field, error))

                        if request.is_ajax():
                            return JsonResponse(
                                {"errors": form.errors, "form_prefix": form.prefix},
                                status=400)
                    else:
                        message = (
                                string_concat(
                                    "%(err_type)s: %(err_str)s. ",
                                    _("No events created."))
                                % {
                                    "err_type": type(e).__name__,
                                    "err_str": str(e)})
                        message_level = messages.ERROR
                break

        else:
            if request.is_ajax():
                return JsonResponse(
                    {"errors": form.errors, "form_prefix": form.prefix}, status=400)

        if request.is_ajax():
            if message_level == messages.ERROR:
                # Rendered as a non-field error in AJAX view
                return JsonResponse(
                    {"errors": {"__all__": [message]},
                     "form_prefix": form.prefix},
                    status=400)
            return JsonResponse(
                {"message": message,
                 "message_level": messages.DEFAULT_TAGS[message_level]})

    else:
        form = RecurringEventForm(pctx.course.identifier)

    if message and message_level:
        messages.add_message(request, message_level, message)
    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": _("Create recurring events"),
    })


class RenumberEventsForm(ModalStyledFormMixin, StyledForm):
    form_title = _("Renumber events")
    modal_id = "renumber-events-modal"

    # This is to avoid field name conflict
    prefix = "renumber"

    kind = forms.ChoiceField(required=True,
            help_text=_("Should be lower_case_with_underscores, no spaces "
                        "allowed."),
            label=pgettext_lazy("Kind of event", "Kind of event"))
    starting_ordinal = forms.IntegerField(required=True, initial=1,
            help_text=_("The starting ordinal of this kind of events"),
            label=pgettext_lazy(
                "Starting ordinal of recurring events", "Starting ordinal"))
    preserve_ordinal_order = forms.BooleanField(
            required=False,
            initial=False,
            help_text=_("Tick to preserve the order of ordinals of "
                        "existing events."),
            label=_("Preserve ordinal order"))

    def __init__(self, course_identifier, *args, **kwargs):
        # type: (Text, *Any, **Any) -> None
        super(RenumberEventsForm, self).__init__(*args, **kwargs)
        self.course_identifier = course_identifier

        renumberable_event_kinds = set(Event.objects.filter(
            course__identifier=self.course_identifier,
            ordinal__isnull=False).values_list("kind", flat=True))
        self.fields['kind'].choices = tuple(
            (kind, kind) for kind in renumberable_event_kinds)

        self.helper.add_input(
                Submit("submit", _("Renumber")))

    def get_ajax_form_helper(self):
        helper = self.get_form_helper()
        self.helper.form_action = reverse(
            "relate-renumber_events", args=[self.course_identifier])

        helper.layout = Layout(
            Div(*self.fields, css_class="modal-body"),
            ButtonHolder(
                Submit("submit", _("Renumber"),
                       css_class="btn btn-md btn-success"),
                Button("cancel", _("Cancel"),
                       css_class="btn btn-md btn-default",
                       data_dismiss="modal"),
                css_class="modal-footer"))
        return helper


@course_view
def get_renumber_events_modal_form(pctx):
    # type: (CoursePageContext) -> http.JsonResponse

    if not pctx.has_permission(pperm.edit_events):
        raise PermissionDenied(_("may not edit events"))

    request = pctx.request
    if not (request.is_ajax() and request.method == "GET"):
        raise PermissionDenied(_("only AJAX GET is allowed"))

    renumber_events_form = RenumberEventsForm(pctx.course.identifier)

    return JsonResponse(
        {"modal_id": renumber_events_form.modal_id,
         "form_html":
             renumber_events_form.render_ajax_modal_form_html(pctx.request)})


@transaction.atomic
@login_required
@course_view
def renumber_events(pctx):
    # type: (CoursePageContext) -> Union[http.HttpResponse, http.JsonResponse]

    if not pctx.has_permission(pperm.edit_events):
        raise PermissionDenied(_("may not edit events"))

    request = pctx.request

    if request.method == "GET" and request.is_ajax():
        raise PermissionDenied(_("may not GET by AJAX"))

    message = None
    message_level = None

    if request.method == "POST":
        form = RenumberEventsForm(
            pctx.course.identifier, request.POST, request.FILES)
        if form.is_valid():
            kind = form.cleaned_data["kind"]
            order_field = "time"
            if form.cleaned_data["preserve_ordinal_order"]:
                order_field = "ordinal"
            events = list(
                Event.objects.filter(
                    course=pctx.course, kind=kind,

                    # there might be event with the same kind but no ordinal,
                    # we don't renumber that
                    ordinal__isnull=False)
                .order_by(order_field))

            assert events
            queryset = (Event.objects.filter(
                course=pctx.course, kind=kind,

                # there might be event with the same kind but no ordinal,
                # we don't renumber that
                ordinal__isnull=False))

            queryset.delete()

            ordinal = form.cleaned_data["starting_ordinal"]
            for event in events:
                new_event = Event()
                new_event.course = pctx.course
                new_event.kind = kind
                new_event.ordinal = ordinal
                new_event.time = event.time
                new_event.end_time = event.end_time
                new_event.all_day = event.all_day
                new_event.shown_in_calendar = event.shown_in_calendar
                new_event.save()

                ordinal += 1

            message = _("Events renumbered.")
            message_level = messages.SUCCESS

            if request.is_ajax():
                return JsonResponse(
                    {"message": message,
                     "message_level": messages.DEFAULT_TAGS[message_level]})

        else:
            if request.is_ajax():
                return JsonResponse(
                    {"errors": form.errors, "form_prefix": form.prefix}, status=400)
    else:
        form = RenumberEventsForm(pctx.course.identifier)

    if messages and message_level:
        messages.add_message(request, message_level, message)
    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": _("Renumber events"),
    })

# }}}


# {{{ calendar

class EventInfo(object):
    def __init__(self, id, human_title, start_time, end_time, description):
        # type: (int, Text, datetime.datetime, datetime.datetime, Text) -> None
        self.id = id
        self.human_title = human_title
        self.start_time = start_time
        self.end_time = end_time
        self.description = description


@course_view
def view_calendar(pctx, mode=None):
    # type: (CoursePageContext, Optional[Text]) -> http.HttpResponse

    if not pctx.has_permission(pperm.view_calendar):
        raise PermissionDenied(_("may not view calendar"))

    is_edit_view = bool(mode == "edit")
    if is_edit_view and not pctx.has_permission(pperm.edit_events):
        raise PermissionDenied(_("may not edit calendar"))

    now = get_now_or_fake_time(pctx.request)
    default_date = now.date()
    if pctx.course.end_date is not None and default_date > pctx.course.end_date:
        default_date = pctx.course.end_date

    return render_course_page(pctx, "course/calendar.html", {
        "is_edit_view": is_edit_view,
        "default_date": default_date.isoformat(),

        # Wrappers used by JavaScript template (tmpl) so as not to
        # conflict with Django template's tag wrapper
        "JQ_OPEN": '{%',
        'JQ_CLOSE': '%}',
    })


def get_events(pctx, is_edit_view=False):
    # type: (CoursePageContext, bool) -> Tuple[Text, List]

    events_json = []

    if is_edit_view:
        assert pctx.has_permission(pperm.edit_events)

    from course.content import (
        get_raw_yaml_from_repo, markup_to_html, parse_date_spec)
    try:
        event_descr = get_raw_yaml_from_repo(pctx.repo,
                pctx.course.events_file, pctx.course_commit_sha)
    except ObjectDoesNotExist:
        event_descr = {}

    event_kinds_desc = event_descr.get("event_kinds", {})
    event_info_desc = event_descr.get("events", {})

    event_info_list = []

    filter_kwargs = {"course": pctx.course}

    if not is_edit_view:
        # exclude hidden events when not is_edit_view
        filter_kwargs["shown_in_calendar"] = True

    events = sorted(
            Event.objects.filter(**filter_kwargs),
            key=lambda evt: (
                -evt.time.year, -evt.time.month, -evt.time.day,
                evt.time.hour, evt.time.minute, evt.time.second))

    now = get_now_or_fake_time(pctx.request)

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
        else:
            # Disable duration edit in FullCalendar js for events without end_time
            event_json["durationEditable"] = False

        if kind_desc is not None:
            if "color" in kind_desc:
                event_json["color"] = kind_desc["color"]
            if "title" in kind_desc:
                if event.ordinal is not None:
                    human_title = kind_desc["title"].format(nr=event.ordinal)
                else:
                    human_title = kind_desc["title"].rstrip("{nr}").strip()

        if is_edit_view:
            if not event.shown_in_calendar:
                event_json["hidden_in_calendar"] = True
            event_json["delete_form_url"] = reverse(
                "relate-get_delete_event_modal_form",
                args=[pctx.course.identifier, event.id])
            event_json["update_form_url"] = reverse(
                "relate-get_update_event_modal_form",
                args=[pctx.course.identifier, event.id])
            event_json["str"] = str(event)

        description = None
        show_description = True and event.shown_in_calendar
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
        if is_edit_view:
            event_json['show_description'] = show_description

        if description and (show_description or is_edit_view):
            # Fixme: participation with pperm.edit_events will
            # always see the url (both edit view and normal view)
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
                        description=description,
                        ))

        events_json.append(event_json)

    from django.template.loader import render_to_string
    events_info_html = render_to_string(
        "course/events_info.html",
        context={"event_info_list": event_info_list,
                 "is_edit_view": is_edit_view},
        request=pctx.request)

    return events_info_html, events_json


@course_view
def fetch_events(pctx, mode=None):
    # type: (CoursePageContext, Optional[Text]) -> http.JsonResponse

    if not pctx.has_permission(pperm.view_calendar):
        raise PermissionDenied(_("may not fetch events"))

    is_edit_view = bool(mode == "edit")
    if is_edit_view and not pctx.has_permission(pperm.edit_events):
        raise PermissionDenied(_("may not fetch events as edit view"))

    request = pctx.request
    if not (request.is_ajax() and request.method == "GET"):
        raise PermissionDenied(_("only AJAX GET is allowed"))

    events_info_html, events_json = get_events(pctx, is_edit_view=is_edit_view)

    return JsonResponse(
        {"events_json": events_json,
         "events_info_html": events_info_html},
        safe=False)

# }}}


class CreateEventModalForm(ModalStyledFormMixin, StyledModelForm):
    form_title = _("Create a event")
    modal_id = "create-event-modal"
    prefix = "create"

    kind = forms.CharField(
        required=True,
        help_text=_(
            "Should be lower_case_with_underscores, no spaces "
            "allowed."),
        label=pgettext_lazy("Kind of event", "Kind of event"))

    class Meta:
        model = Event
        fields = ['kind', 'ordinal', 'time',
                  'end_time', 'all_day', 'shown_in_calendar']
        widgets = {
            "time": DateTimePicker(options={"format": "YYYY-MM-DD HH:mm"}),
            "end_time": DateTimePicker(options={"format": "YYYY-MM-DD HH:mm"}),
        }

    def __init__(self, course_identifier, *args, **kwargs):
        # type: (Text, *Any, **Any) -> None
        super(CreateEventModalForm, self).__init__(*args, **kwargs)
        self.fields["shown_in_calendar"].help_text = (
            _("Shown in students' calendar"))

        self.course_identifier = course_identifier

        exist_event_choices = [(choice, choice) for choice in set(
            Event.objects.filter(
                course__identifier=course_identifier,

                # only events with ordinals
                ordinal__isnull=False)
            .values_list("kind", flat=True))]
        self.fields['kind'].widget = ListTextWidget(data_list=exist_event_choices,
                                                    name="event_create_choices")

    def get_ajax_form_helper(self):
        helper = self.get_form_helper()

        self.helper.form_action = reverse(
            "relate-create_event", args=[self.course_identifier])

        # Form media (FullCalendar and mement js) are manually added to page head
        self.helper.include_media = False

        helper.layout = Layout(
            Div(*self.fields, css_class="modal-body"),
            ButtonHolder(
                Submit("save", _("Save"),
                       css_class="btn btn-md btn-success"),
                Button("cancel", _("Cancel"),
                       css_class="btn btn-md btn-default",
                       data_dismiss="modal"),
                css_class="modal-footer"
            )
        )
        return helper

    def clean(self):
        super(CreateEventModalForm, self).clean()

        kind = self.cleaned_data.get("kind")
        ordinal = self.cleaned_data.get('ordinal')
        if kind is not None:
            filter_kwargs = {"course__identifier": self.course_identifier,
                             "kind": kind}
            if ordinal is not None:
                filter_kwargs["ordinal"] = ordinal
            else:
                filter_kwargs["ordinal__isnull"] = True

            qset = Event.objects.filter(**filter_kwargs)
            if qset.count():
                from django.forms import ValidationError
                raise ValidationError(
                    _("'%(exist_event)s' already exists.")
                    % {'exist_event': qset[0]})


@course_view
def get_create_event_modal_form(pctx):
    # type: (CoursePageContext) -> http.JsonResponse

    if not pctx.has_permission(pperm.edit_events):
        raise PermissionDenied(_("may not edit events"))

    request = pctx.request
    if not (request.is_ajax() and request.method == "GET"):
        raise PermissionDenied(_("only AJAX GET is allowed"))

    new_event_form = CreateEventModalForm(pctx.course.identifier)

    return JsonResponse(
        {"modal_id": new_event_form.modal_id,
         "form_html": new_event_form.render_ajax_modal_form_html(pctx.request)})


@course_view
@transaction.atomic()
def create_event(pctx):
    # type: (CoursePageContext) -> http.JsonResponse

    if not pctx.has_permission(pperm.edit_events):
        raise PermissionDenied(_("may not edit events"))

    request = pctx.request
    if not request.is_ajax() or request.method != "POST":
        raise PermissionDenied(_("only AJAX POST is allowed"))

    form = CreateEventModalForm(
        pctx.course.identifier, request.POST, request.FILES)

    if form.is_valid():
        try:
            instance = form.save(commit=False)
            instance.course = pctx.course
            instance.save()

            message = (_("Event created: '%s'.") % str(instance))
            return JsonResponse({"message": message})
        except Exception as e:

            # return the error as a non-field error
            return JsonResponse(
                {"__all__": ["%s: %s" % (type(e).__name__, str(e))]}, status=400)
    else:
        return JsonResponse(
            {"errors": form.errors, "form_prefix": form.prefix}, status=400)


class DeleteEventForm(ModalStyledFormMixin, StyledModelForm):
    form_title = _("Delete event")
    modal_id = "delete-event-modal"
    prefix = "delete"

    class Meta:
        model = Event
        fields = []  # type: List

    def __init__(self, course_identifier, instance_to_delete, *args, **kwargs):
        # type: (Text, Event, *Any, **Any) -> None
        super(DeleteEventForm, self).__init__(*args, **kwargs)

        self.course_identifier = course_identifier

        hint = _("Are you sure to delete event '%s'?") % str(instance_to_delete)

        if instance_to_delete.ordinal is not None:
            events_of_same_kind = Event.objects.filter(
                course__identifier=course_identifier,
                kind=instance_to_delete.kind, ordinal__isnull=False)
            if events_of_same_kind.count() > 1:
                choices = [
                    ("delete_single",
                     _("Delete event '%s'") % str(instance_to_delete)),
                    ('delete_all',
                     _("Delete all '%s' events") % instance_to_delete.kind),
                ]

                if events_of_same_kind.filter(
                        time__gt=instance_to_delete.time).count():
                    choices.append(
                        ('delete_this_and_following',
                         _("Delete this and following '%s' events")
                         % instance_to_delete.kind),
                    )

                local_time, week_day, hour, minute = (
                    get_local_time_weekday_hour_minute(instance_to_delete.time))

                events_of_same_kind_and_weekday_time = (
                    Event.objects.filter(
                        course__identifier=course_identifier,
                        kind=instance_to_delete.kind,
                        time__week_day=week_day,
                        time__hour=hour,
                        time__minute=minute,
                        end_time__isnull=instance_to_delete.end_time is None,
                        shown_in_calendar=instance_to_delete.shown_in_calendar
                    ))
                if instance_to_delete.end_time:
                    end_local_time, end_week_day, end_hour, end_minute = (
                        get_local_time_weekday_hour_minute(
                            instance_to_delete.end_time))
                    events_of_same_kind_and_weekday_time = (
                        events_of_same_kind_and_weekday_time
                        .filter(end_time__isnull=False)
                        .filter(
                            end_time__week_day=end_week_day,
                            end_time__hour=end_hour,
                            end_time__minute=end_minute))

                series_time_desc = (
                    get_recurring_event_series_time_desc_from_instance(
                        instance_to_delete))

                if (events_of_same_kind.count()
                        > events_of_same_kind_and_weekday_time.count() > 1):

                    choices.append(
                        ("delete_all_in_same_series",
                         _("Delete all '%(kind)s' events "
                           "(%(time)s).")
                         % {"kind": instance_to_delete.kind,
                            "time": series_time_desc}))

                    if events_of_same_kind_and_weekday_time.filter(
                            time__gt=instance_to_delete.time).count():
                        choices.append(
                            ("delete_this_and_following_of_same_series",
                             _("Delete this and following '%(kind)s' events "
                               "(%(time)s).")
                             % {"kind": instance_to_delete.kind,
                                "time": series_time_desc}))

                self.fields["operation"] = (
                    forms.ChoiceField(
                        choices=choices, widget=forms.RadioSelect(), required=True,
                        initial="delete_single",
                        label=_("Operation")))
                hint = _("Select your operation:")

        self.instance_to_delete = instance_to_delete
        self.hint = hint

    def get_ajax_form_helper(self):
        helper = super(DeleteEventForm, self).get_ajax_form_helper()

        self.helper.form_action = reverse(
            "relate-delete_event", args=[
                self.course_identifier, self.instance_to_delete.pk])

        helper.layout = Layout(
            Div(*self.fields, css_class="modal-body"),
            ButtonHolder(
                Submit("submit", _("Delete"),
                       css_class="btn btn-md btn-danger"),
                Button("cancel", _("Cancel"),
                       css_class="btn btn-md btn-default",
                       data_dismiss="modal"),
                css_class="modal-footer"))
        helper.layout[0].insert(0, HTML(self.hint))
        return helper


@course_view
def get_delete_event_modal_form(pctx, event_id):
    # type: (CoursePageContext, int) -> http.JsonResponse

    if not pctx.has_permission(pperm.edit_events):
        raise PermissionDenied(_("may not edit events"))

    request = pctx.request
    if not (request.is_ajax() and request.method == "GET"):
        raise PermissionDenied(_("only AJAX GET is allowed"))

    event_id = int(event_id)
    instance_to_delete = get_object_or_404(Event, course=pctx.course, id=event_id)

    form = DeleteEventForm(
        pctx.course.identifier, instance_to_delete, instance=instance_to_delete)

    return JsonResponse(
        {"form_html": form.render_ajax_modal_form_html(pctx.request)})


@course_view
@transaction.atomic()
def delete_event(pctx, event_id):
    # type: (CoursePageContext, int) -> http.JsonResponse

    if not pctx.has_permission(pperm.edit_events):
        raise PermissionDenied(_("may not edit events"))

    request = pctx.request
    if not request.is_ajax() or request.method != "POST":
        raise PermissionDenied(_("only AJAX POST is allowed"))

    event_id = int(event_id)
    event_qs = Event.objects.filter(course=pctx.course, pk=event_id)
    if not event_qs.count():
        from django.http import Http404
        raise Http404()
    else:
        instance_to_delete, = event_qs
        form = DeleteEventForm(
            pctx.course.identifier, instance_to_delete,
            request.POST, instance=instance_to_delete)

        local_time, week_day, hour, minute = (
            get_local_time_weekday_hour_minute(instance_to_delete.time))

        events_of_same_kind_and_weekday_time = (
            Event.objects.filter(
                course__identifier=pctx.course.identifier,
                kind=instance_to_delete.kind,
                time__week_day=week_day,
                time__hour=hour,
                time__minute=minute,
                end_time__isnull=instance_to_delete.end_time is None,
                shown_in_calendar=instance_to_delete.shown_in_calendar
            ))
        if instance_to_delete.end_time:
            end_local_time, end_week_day, end_hour, end_minute = (
                get_local_time_weekday_hour_minute(
                    instance_to_delete.end_time))
            events_of_same_kind_and_weekday_time = (
                events_of_same_kind_and_weekday_time
                .filter(end_time__isnull=False)
                .filter(
                    end_time__week_day=end_week_day,
                    end_time__hour=end_hour,
                    end_time__minute=end_minute))

        series_time_desc = (
            get_recurring_event_series_time_desc_from_instance(
                instance_to_delete))

        if form.is_valid():
            operation = form.cleaned_data.get("operation")

            if operation == "delete_this_and_following":
                qset = Event.objects.filter(
                    course=pctx.course, kind=instance_to_delete.kind,
                    time__gte=instance_to_delete.time)
                message = _("%(number)d '%(kind)s' events deleted."
                            ) % {"number": qset.count(),
                                 "kind": instance_to_delete.kind}
            elif operation == "delete_all":
                qset = Event.objects.filter(
                    course=pctx.course, kind=instance_to_delete.kind,
                    ordinal__isnull=False)
                message = _("All '%(kind)s' events deleted."
                            ) % {"kind": instance_to_delete.kind}
            elif operation == "delete_all_in_same_series":
                qset = events_of_same_kind_and_weekday_time
                message = _(
                    "All '%(kind)s' events (%(time)s) deleted."
                    % {"time": series_time_desc,
                       "kind": instance_to_delete.kind})
            elif operation == "delete_this_and_following_of_same_series":
                qset = events_of_same_kind_and_weekday_time.filter(
                    time__gte=instance_to_delete.time)
                message = _("%(number)d '%(kind)s' events "
                            "(%(time)s) deleted."
                            % {"number": qset.count(),
                               "kind": instance_to_delete.kind,
                               "time": series_time_desc})
            else:
                # operation is None or operation == "delete_single":
                qset = event_qs
                message = _("Event '%s' deleted.") % str(instance_to_delete)

            try:
                qset.delete()
                return JsonResponse({"message": message})
            except Exception as e:
                return JsonResponse(
                    {"__all__": ["%s: %s" % (type(e).__name__, str(e))]},
                    status=400)

        else:
            return JsonResponse(
                {"errors": form.errors, "form_prefix": form.prefix}, status=400)


class UpdateEventForm(ModalStyledFormMixin, StyledModelForm):
    @property
    def form_title(self):
        return _("Update event '%s'" % str(Event.objects.get(id=self.event_id)))

    modal_id = "update-event-modal"
    prefix = "update"

    class Meta:
        model = Event
        fields = ['kind', 'ordinal', 'time',
                  'end_time', 'all_day', 'shown_in_calendar']
        widgets = {
            "time": DateTimePicker(options={"format": "YYYY-MM-DD HH:mm"}),
            "end_time": DateTimePicker(options={"format": "YYYY-MM-DD HH:mm"}),
        }

    def __init__(self, course_identifier, event_id, *args, **kwargs):
        # type: (Text, int, *Any, **Any) -> None
        super(UpdateEventForm, self).__init__(*args, **kwargs)

        self.course_identifier = course_identifier
        self.event_id = event_id

    def get_ajax_form_helper(self):
        helper = super(UpdateEventForm, self).get_ajax_form_helper()
        self.helper.form_action = reverse(
            "relate-update_event", args=[self.course_identifier, self.event_id])

        update_button = Submit("update", _("Update"),
                               css_class="btn btn-md btn-success")

        update_all_button = Submit(
            "update_all", _("Update all"),
            css_class="btn btn-md btn-success")

        update_this_and_following_button = Submit(
            "update_this_and_following", _("Update this and following"),
            css_class="btn btn-md btn-success")

        update_series = Submit("update_series",
                               _("Update series"),
                               css_class="btn btn-md btn-success")

        update_this_and_following_in_series_button = Submit(
            "update_this_and_following_in_series",
            _("Update this and following in series"),
            css_class="btn btn-md btn-success")

        cancel_button = Button("cancel", _("Cancel"),
                               css_class="btn btn-md btn-default",
                               data_dismiss="modal")

        instance_to_update = Event.objects.get(id=self.event_id)
        may_update_all = False
        may_update_following = False
        may_update_series = False
        may_update_following_in_series = False

        if instance_to_update.ordinal is not None:
            events_of_same_kind = Event.objects.filter(
                course__identifier=self.course_identifier,
                kind=instance_to_update.kind, ordinal__isnull=False)
            if events_of_same_kind.count() > 1:

                start_local_time, start_week_day, start_hour, start_minute = (
                    get_local_time_weekday_hour_minute(instance_to_update.time))

                events_of_same_kind_and_weekday_time = (
                    Event.objects.filter(
                        course__identifier=self.course_identifier,
                        kind=instance_to_update.kind,
                        time__week_day=start_week_day,
                        time__hour=start_hour,
                        time__minute=start_minute,
                        end_time__isnull=instance_to_update.end_time is None,
                        shown_in_calendar=instance_to_update.shown_in_calendar
                    ))
                if instance_to_update.end_time:
                    end_local_time, end_week_day, end_hour, end_minute = (
                        get_local_time_weekday_hour_minute(
                            instance_to_update.end_time))
                    events_of_same_kind_and_weekday_time = (
                        events_of_same_kind_and_weekday_time
                        .filter(end_time__isnull=False)
                        .filter(
                            end_time__week_day=end_week_day,
                            end_time__hour=end_hour,
                            end_time__minute=end_minute))

                if (events_of_same_kind.count()
                        > events_of_same_kind_and_weekday_time.count() > 1):
                    may_update_series = True
                    if events_of_same_kind_and_weekday_time.filter(
                            time__gt=instance_to_update.time).count():
                        may_update_following_in_series = True
                elif (events_of_same_kind.count()
                      == events_of_same_kind_and_weekday_time.count() > 1):
                    may_update_all = True
                    if events_of_same_kind_and_weekday_time.filter(
                            time__gt=instance_to_update.time).count():
                        may_update_following = True

        button_holder = ButtonHolder()
        if may_update_all:
            button_holder.append(update_all_button)
            if may_update_following:
                button_holder.append(update_this_and_following_button)
        elif may_update_series:
            button_holder.append(update_series)
            if may_update_following_in_series:
                button_holder.append(update_this_and_following_in_series_button)

        button_holder.append(update_button)
        button_holder.append(cancel_button)

        button_holder.css_class = "modal-footer"

        helper.layout = Layout(
            Div(*self.fields, css_class="modal-body"),
            button_holder)
        return helper


@course_view
def get_update_event_modal_form(pctx, event_id):
    # type: (CoursePageContext, int) -> http.JsonResponse

    if not pctx.has_permission(pperm.edit_events):
        raise PermissionDenied(_("may not edit events"))

    request = pctx.request
    if not request.is_ajax():
        raise PermissionDenied(_("only AJAX request is allowed"))

    event_id = int(event_id)
    instance_to_update = get_object_or_404(Event, course=pctx.course, id=event_id)

    if request.method == "POST":
        # when drag-n-drop the event
        drop_timedelta_hours = float(request.POST.get("drop_timedelta_hours", 0))

        # when 'resize', i.e., change end_time of the event
        resize_timedelta_hours = float(
            request.POST.get("resize_timedelta_hours", 0))

        assert not (drop_timedelta_hours and resize_timedelta_hours)

        if drop_timedelta_hours:
            instance_to_update.time += datetime.timedelta(hours=drop_timedelta_hours)
            if instance_to_update.end_time is not None:
                instance_to_update.end_time += (
                    datetime.timedelta(hours=drop_timedelta_hours))

        if resize_timedelta_hours:
            if not instance_to_update.end_time:
                raise SuspiciousOperation(
                    "may not resize events which has no end_time")
            instance_to_update.end_time += (
                datetime.timedelta(hours=resize_timedelta_hours))

        form = UpdateEventForm(
            pctx.course.identifier, event_id, instance=instance_to_update)
        for field_name, __ in form.fields.items():
            if field_name not in ["time", "end_time"]:
                form.fields[field_name].widget = forms.HiddenInput()
    else:
        form = UpdateEventForm(
            pctx.course.identifier, event_id, instance=instance_to_update)

    return JsonResponse(
        {"form_html": form.render_ajax_modal_form_html(pctx.request)})


@course_view
@transaction.atomic()
def update_event(pctx, event_id):
    # type: (CoursePageContext, int) -> http.JsonResponse

    if not pctx.has_permission(pperm.edit_events):
        raise PermissionDenied(_("may not edit events"))

    request = pctx.request
    if not request.is_ajax() or request.method != "POST":
        raise PermissionDenied(_("only AJAX POST is allowed"))

    event_id = int(event_id)
    instance_to_update = get_object_or_404(Event, course=pctx.course, id=event_id)
    original_str = str(instance_to_update)
    series_time_desc = (
        get_recurring_event_series_time_desc_from_instance(instance_to_update))

    local_time, week_day, hour, minute = (
        get_local_time_weekday_hour_minute(instance_to_update.time))

    form = UpdateEventForm(
        pctx.course.identifier, event_id, request.POST, request.FILES)

    if form.is_valid():
        try:
            temp_instance = form.save(commit=False)
            if (temp_instance.time == instance_to_update.time
                    and temp_instance.end_time == instance_to_update.end_time
                    and temp_instance.kind == instance_to_update.kind
                    and temp_instance.ordinal == instance_to_update.ordinal
                    and temp_instance.all_day == instance_to_update.all_day
                    and temp_instance.shown_in_calendar
                    == instance_to_update.shown_in_calendar):
                return JsonResponse(
                    {"message": _("No change was made."),
                     "message_level": messages.DEFAULT_TAGS[messages.WARNING]
                     })

            temp_instance.course = pctx.course
            new_event_timedelta = temp_instance.time - instance_to_update.time
            new_duration = None
            if temp_instance.end_time is not None:
                new_duration = temp_instance.end_time - temp_instance.time

            events_of_same_kind_and_weekday_time = (
                Event.objects.filter(
                    course__identifier=pctx.course.identifier,
                    kind=instance_to_update.kind,
                    time__week_day=week_day,
                    time__hour=hour,
                    time__minute=minute,
                    end_time__isnull=instance_to_update.end_time is None,
                    shown_in_calendar=instance_to_update.shown_in_calendar
                ))

            if instance_to_update.end_time is not None:
                end_local_time, end_week_day, end_hour, end_minute = (
                    get_local_time_weekday_hour_minute(
                        instance_to_update.end_time))
                events_of_same_kind_and_weekday_time = (
                    events_of_same_kind_and_weekday_time
                    .filter(end_time__isnull=False)
                    .filter(end_time__week_day=end_week_day,
                            end_time__hour=end_hour,
                            end_time__minute=end_minute))

            if "update" in request.POST:
                instance_to_update.time = temp_instance.time
                instance_to_update.end_time = temp_instance.end_time
                instance_to_update.kind = temp_instance.kind
                instance_to_update.ordinal = temp_instance.ordinal
                instance_to_update.all_day = temp_instance.all_day
                instance_to_update.shown_in_calendar = (
                    temp_instance.shown_in_calendar)

                assert instance_to_update.course == pctx.course
                instance_to_update.save()

                if original_str == str(temp_instance):
                    message = _("Event '%s' updated.") % str(instance_to_update)
                else:
                    message = string_concat(
                        _("Event updated"),
                        ": '%(original_event)s' -> '%(new_event)s'"
                        % {"original_event": original_str,
                           "new_event": str(temp_instance)})
            else:
                if original_str == str(temp_instance):
                    changes = "."
                else:
                    changes = (
                            ": '%s' -> '%s'."
                            % (instance_to_update.kind, temp_instance.kind))

                if "update_all" in request.POST:
                    events_to_update = (
                        events_of_same_kind_and_weekday_time.filter(
                            kind=instance_to_update.kind))
                    message = string_concat(
                        _("All '%(kind)s' events updated"
                          % {"kind": instance_to_update.kind}),
                        changes)

                elif "update_this_and_following" in request.POST:
                    events_to_update = events_of_same_kind_and_weekday_time.filter(
                        kind=instance_to_update.kind,
                        time__gte=instance_to_update.time)
                    message = string_concat(
                        _("%(number)d '%(kind)s' events updated"
                          % {"number": events_to_update.count(),
                             "kind": instance_to_update.kind}),
                        changes)

                elif "update_series" in request.POST:
                    events_to_update = events_of_same_kind_and_weekday_time
                    message = string_concat(
                        _("All '%(kind)s' events (%(time)s) updated"
                          % {"time": series_time_desc,
                              "kind": instance_to_update.kind}),
                        changes)

                elif "update_this_and_following_in_series" in request.POST:
                    events_to_update = events_of_same_kind_and_weekday_time.filter(
                        time__gte=instance_to_update.time)
                    message = string_concat(
                        _("%(number)d '%(kind)s' events "
                          "(%(time)s) updated"
                          % {"number": events_to_update.count(),
                             "kind": instance_to_update.kind,
                             "time": series_time_desc}),
                        changes)
                else:
                    raise SuspiciousOperation(_("unknown operation"))

                if temp_instance.ordinal is None and events_to_update.count() > 1:
                    raise RuntimeError(
                        _("May not do bulk update when ordinal is None"))

                new_event_ordinal_delta = (
                        temp_instance.ordinal - instance_to_update.ordinal)

                for event in events_to_update:
                    assert event.course == pctx.course
                    event.kind = temp_instance.kind

                    # This might result in IntegrityError
                    event.ordinal += new_event_ordinal_delta

                    event.time = (
                            event.time + new_event_timedelta)
                    event.all_day = temp_instance.all_day
                    event.shown_in_calendar = temp_instance.shown_in_calendar
                    if new_duration is not None:
                        event.end_time = event.time + new_duration
                    else:
                        event.end_time = None
                    event.save()

            return JsonResponse(
                {"message": message,
                 "message_level": messages.DEFAULT_TAGS[messages.SUCCESS]})

        except Exception as e:
            return JsonResponse(
                {"__all__": ["%s: %s" % (type(e).__name__, str(e))]}, status=400)
    else:
        return JsonResponse(
            {"errors": form.errors, "form_prefix": form.prefix}, status=400)

# vim: foldmethod=marker
