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

import datetime

import django.forms as forms
from crispy_forms.layout import Submit
from django.contrib import messages  # noqa
from django.contrib.auth.decorators import login_required
from django.core.exceptions import (
    ObjectDoesNotExist, PermissionDenied, ValidationError,
)
from django.db import transaction
from django.utils.translation import get_language, gettext_lazy as _, pgettext_lazy

from course.constants import participation_permission as pperm
from course.models import Event
from course.utils import course_view, render_course_page
from relate.utils import HTML5DateTimeInput, StyledForm, as_local_time, string_concat


class ListTextWidget(forms.TextInput):
    # Widget which allow free text and choices for CharField
    def __init__(self, data_list, name, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._name = name
        self._list = data_list
        self.attrs.update({"list": "list__%s" % self._name})

    def render(self, name, value, attrs=None, renderer=None):
        text_html = super().render(
            name, value, attrs=attrs, renderer=renderer)
        data_list = '<datalist id="list__%s">' % self._name
        for item in self._list:
            data_list += '<option value="{}">{}</option>'.format(item[0], item[1])
        data_list += "</datalist>"

        return (text_html + data_list)


# {{{ creation

class RecurringEventForm(StyledForm):
    kind = forms.CharField(required=True,
            help_text=_("Should be lower_case_with_underscores, no spaces "
                        "allowed."),
            label=pgettext_lazy("Kind of event", "Kind of event"))
    time = forms.DateTimeField(
            widget=HTML5DateTimeInput(),
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
            label=_("Shown in calendar"))
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
        super().__init__(*args, **kwargs)
        self.course_identifier = course_identifier

        exist_event_choices = [(choice, choice) for choice in set(
            Event.objects.filter(
                course__identifier=course_identifier)
            .values_list("kind", flat=True))]
        self.fields["kind"].widget = ListTextWidget(data_list=exist_event_choices,
                                                    name="event_choices")

        self.helper.add_input(
                Submit("submit", _("Create")))


class EventAlreadyExists(Exception):
    pass


@transaction.atomic
def _create_recurring_events_backend(course, time, kind, starting_ordinal, interval,
        count, duration_in_minutes, all_day, shown_in_calendar):
    ordinal = starting_ordinal
    assert ordinal is not None

    import datetime

    for _i in range(count):
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

        if Event.objects.filter(course=course, kind=kind, ordinal=ordinal).count():
            raise EventAlreadyExists(
                _("'%(exist_event)s' already exists")
                % {"exist_event": evt})

        evt.save()

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


@login_required
@course_view
def create_recurring_events(pctx):
    if not pctx.has_permission(pperm.edit_events):
        raise PermissionDenied(_("may not edit events"))

    request = pctx.request
    message = None
    message_level = None

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
                                    "__all__", f"'{field}': {error}")
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
        form = RecurringEventForm(pctx.course.identifier)

    if message and message_level:
        messages.add_message(request, message_level, message)
    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": _("Create recurring events"),
    })


class RenumberEventsForm(StyledForm):
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
        super().__init__(*args, **kwargs)
        self.course_identifier = course_identifier

        renumberable_event_kinds = set(Event.objects.filter(
            course__identifier=self.course_identifier,
            ordinal__isnull=False).values_list("kind", flat=True))
        self.fields["kind"].choices = tuple(
            (kind, kind) for kind in renumberable_event_kinds)

        self.helper.add_input(
                Submit("submit", _("Renumber")))


@transaction.atomic
@login_required
@course_view
def renumber_events(pctx):
    if not pctx.has_permission(pperm.edit_events):
        raise PermissionDenied(_("may not edit events"))

    request = pctx.request

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

class EventInfo:
    def __init__(self, id, human_title, start_time, end_time, description):
        self.id = id
        self.human_title = human_title
        self.start_time = start_time
        self.end_time = end_time
        self.description = description


def _fullcalendar_lang_code() -> str:
    """
    Return the fallback lang name for js files.
    """

    lang_name = get_language()
    known_fallback_mapping = {
        "zh-hans": "zh-cn",
        "zh-hant": "zh-tw"}
    return known_fallback_mapping.get(lang_name.lower(), lang_name).lower()


@course_view
def view_calendar(pctx):
    if not pctx.has_permission(pperm.view_calendar):
        raise PermissionDenied(_("may not view calendar"))

    # must import locally for mock to work
    from course.views import get_now_or_fake_time
    now = get_now_or_fake_time(pctx.request)

    events_json = []

    from course.content import (
        get_raw_yaml_from_repo, markup_to_html, parse_date_spec,
    )
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

        human_title = str(event)

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
                    human_title = kind_desc["title"].rstrip("{nr}").strip()

        description = None
        show_description = True
        event_desc = event_info_desc.get(str(event))
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
        "fullcalendar_lang_code": _fullcalendar_lang_code()
    })

# }}}

# vim: foldmethod=marker
