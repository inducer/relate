from __future__ import annotations


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

from sys import intern
from typing import TYPE_CHECKING, Any

from crispy_forms.layout import Submit
from django import (
    forms,
    http,
)
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render  # noqa
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _, pgettext
from pytools.lex import RE as REBase  # noqa

from course.auth import UserSearchWidget
from course.constants import (
    PARTICIPATION_PERMISSION_CHOICES,
    participation_permission as pperm,
)
from course.models import (
    Course,
    Participation,
    ParticipationPermission,
    ParticipationPreapproval,
    ParticipationRole,
    ParticipationTag,
    participation_status,
    user_status,
)
from course.utils import LanguageOverride, course_view, render_course_page
from relate.utils import StyledForm, StyledModelForm, string_concat


# {{{ for mypy

if TYPE_CHECKING:
    import accounts.models
    from course.utils import CoursePageContext

# }}}


# {{{ get_participation_for_{user,request}

def get_participation_for_user(
        user: accounts.models.User, course: Course
        ) -> Participation | None:
    # "wake up" lazy object
    # http://stackoverflow.com/questions/20534577/int-argument-must-be-a-string-or-a-number-not-simplelazyobject  # noqa
    try:
        possible_user = user._wrapped
    except AttributeError:
        pass
    else:
        if isinstance(possible_user, get_user_model()):
            user = possible_user

    if not user.is_authenticated:
        return None

    participations = list(Participation.objects.filter(
            user=user,
            course=course,
            status=participation_status.active
            ))

    # The uniqueness constraint should have ensured that.
    assert len(participations) <= 1

    if len(participations) == 0:
        return None

    return participations[0]


def get_participation_for_request(
        request: http.HttpRequest, course: Course) -> Participation | None:
    return get_participation_for_user(request.user, course)

# }}}


# {{{ get_participation_role_identifiers

def get_participation_role_identifiers(
        course: Course, participation: Participation | None) -> list[str]:
    if participation is None:
        return (
                ParticipationRole.objects.filter(
                    course=course,
                    is_default_for_unenrolled=True)
                .values_list("identifier", flat=True))

    else:
        return [r.identifier for r in participation.roles.all()]

# }}}


# {{{ get_permissions

def get_participation_permissions(
        course: Course,
        participation: Participation | None,
        ) -> frozenset[tuple[str, str | None]]:

    if participation is not None:
        return participation.permissions()
    else:
        from course.models import ParticipationRolePermission

        perm_list = list(
                ParticipationRolePermission.objects.filter(
                    role__is_default_for_unenrolled=True)
                .values_list("permission", "argument"))

        perm = frozenset(
                (permission, argument) if argument else (permission, None)
                for permission, argument in perm_list)

        return perm

# }}}


# {{{ enrollment

@login_required
@transaction.atomic
def enroll_view(
        request: http.HttpRequest, course_identifier: str) -> http.HttpResponse:
    course = get_object_or_404(Course, identifier=course_identifier)
    user = request.user
    participations = Participation.objects.filter(course=course, user=user)
    if not participations.count():
        participation = None
    else:
        participation = participations.first()

    if participation is not None:
        if participation.status == participation_status.requested:
            messages.add_message(request, messages.ERROR,
                                 _("You have previously sent the enrollment "
                                   "request. Re-sending the request is not "
                                   "allowed."))
            return redirect("relate-course_page", course_identifier)
        elif participation.status == participation_status.denied:
            messages.add_message(request, messages.ERROR,
                                 _("Your enrollment request had been denied. "
                                   "Enrollment is not allowed."))
            return redirect("relate-course_page", course_identifier)
        elif participation.status == participation_status.dropped:
            messages.add_message(request, messages.ERROR,
                                 _("You had been dropped from the course. "
                                   "Re-enrollment is not allowed."))
            return redirect("relate-course_page", course_identifier)
        else:
            assert participation.status == participation_status.active
            messages.add_message(request, messages.ERROR,
                                 _("Already enrolled. Cannot re-enroll."))
        return redirect("relate-course_page", course_identifier)

    if not course.accepts_enrollment:
        messages.add_message(request, messages.ERROR,
                _("Course is not accepting enrollments."))
        return redirect("relate-course_page", course_identifier)

    if request.method != "POST":
        # This can happen if someone tries to refresh the page, or switches to
        # desktop view on mobile.
        messages.add_message(request, messages.ERROR,
                _("Can only enroll using POST request"))
        return redirect("relate-course_page", course_identifier)

    if user.status != user_status.active:
        messages.add_message(request, messages.ERROR,
                _("Your email address is not yet confirmed. "
                "Confirm your email to continue."))
        return redirect("relate-course_page", course_identifier)

    preapproval = None
    if request.user.email:  # pragma: no branch (user email NOT NULL constraint)
        try:
            preapproval = ParticipationPreapproval.objects.get(
                    course=course, email__iexact=request.user.email)
        except ParticipationPreapproval.DoesNotExist:
            pass

    if preapproval is None:
        if user.institutional_id:
            if not (course.preapproval_require_verified_inst_id
                    and not user.institutional_id_verified):
                try:
                    preapproval = ParticipationPreapproval.objects.get(
                            course=course,
                            institutional_id__iexact=user.institutional_id)
                except ParticipationPreapproval.DoesNotExist:
                    pass

    def email_suffix_matches(email: str, suffix: str) -> bool:
        if suffix.startswith("@"):
            return email.endswith(suffix)
        else:
            return email.endswith(f"@{suffix}") or email.endswith(f".{suffix}")

    if (preapproval is None
        and course.enrollment_required_email_suffix
        and not email_suffix_matches(
            user.email, course.enrollment_required_email_suffix)):

        messages.add_message(request, messages.ERROR,
                _("Enrollment not allowed. Please use your '%s' email to "
                "enroll.") % course.enrollment_required_email_suffix)
        return redirect("relate-course_page", course_identifier)

    roles = ParticipationRole.objects.filter(
            course=course,
            is_default_for_new_participants=True)

    if preapproval is not None:
        roles = list(preapproval.roles.all())

    try:
        if course.enrollment_approval_required and preapproval is None:
            participation = handle_enrollment_request(
                    course, user, participation_status.requested,
                    roles, request)

            assert participation is not None

            with LanguageOverride(course=course):
                from relate.utils import render_email_template
                message = render_email_template(
                    "course/enrollment-request-email.txt", {
                        "user": user,
                        "course": course,
                        "admin_uri": mark_safe(
                            request.build_absolute_uri(
                                reverse("relate-edit_participation",
                                        args=(course.identifier, participation.id))))
                    })

                from django.core.mail import EmailMessage
                msg = EmailMessage(
                    string_concat("[%s] ", _("New enrollment request"))
                    % course_identifier,
                    message,
                    getattr(settings, "ENROLLMENT_EMAIL_FROM",
                            settings.ROBOT_EMAIL_FROM),
                    [course.notify_email])

                from relate.utils import get_outbound_mail_connection
                msg.connection = (
                    get_outbound_mail_connection("enroll")
                    if hasattr(settings, "ENROLLMENT_EMAIL_FROM")
                    else get_outbound_mail_connection("robot"))

                msg.send()

            messages.add_message(request, messages.INFO,
                    _("Enrollment request sent. You will receive notification "
                    "by email once your request has been acted upon."))
        else:
            handle_enrollment_request(course, user, participation_status.active,
                                      roles, request)

            messages.add_message(request, messages.SUCCESS,
                    _("Successfully enrolled."))

    except IntegrityError:
        messages.add_message(request, messages.ERROR,
                _("A participation already exists. Enrollment attempt aborted."))

    return redirect("relate-course_page", course_identifier)


@transaction.atomic
def handle_enrollment_request(
        course: Course,
        user: Any,
        status: str,
        roles: list[ParticipationRole] | None,
        request: http.HttpRequest | None = None
        ) -> Participation:
    participations = Participation.objects.filter(course=course, user=user)

    assert participations.count() <= 1
    if participations.count() == 0:
        participation = Participation()
        participation.user = user
        participation.course = course
        participation.status = status
        participation.save()

    else:
        (participation,) = participations
        participation.status = status
        participation.save()

    if roles is not None:
        participation.roles.set(roles)

    if status == participation_status.active:
        send_enrollment_decision(participation, True, request)
    elif status == participation_status.denied:
        send_enrollment_decision(participation, False, request)

    return participation

# }}}


# {{{ admin actions

def decide_enrollment(approved, modeladmin, request, queryset):
    count = 0

    for participation in queryset:
        if participation.status != participation_status.requested:
            continue

        if approved:
            participation.status = participation_status.active
        else:
            participation.status = participation_status.denied
        participation.save()

        send_enrollment_decision(participation, approved, request)

        count += 1

    messages.add_message(request, messages.INFO,
            # Translators: how many enroll requests have ben processed.
            _("%d requests processed.") % count)


def send_enrollment_decision(
        participation: Participation,
        approved: bool,
        request: http.HttpRequest | None = None) -> None:
    course = participation.course
    with LanguageOverride(course=course):
        if request:
            course_uri = request.build_absolute_uri(
                    reverse("relate-course_page",
                        args=(course.identifier,)))
        else:
            # This will happen when this method is triggered by
            # a model signal which doesn't contain a request object.
            from urllib.parse import urljoin
            course_uri = urljoin(settings.RELATE_BASE_URL,
                                 course.get_absolute_url())

        from relate.utils import render_email_template
        message = render_email_template("course/enrollment-decision-email.txt", {
            "user": participation.user,
            "approved": approved,
            "course": course,
            "course_uri": course_uri
            })

        from django.core.mail import EmailMessage
        email_kwargs = {}
        if settings.RELATE_EMAIL_SMTP_ALLOW_NONAUTHORIZED_SENDER:
            from_email = course.get_from_email()
        else:
            from_email = getattr(settings, "ENROLLMENT_EMAIL_FROM",
                                 settings.ROBOT_EMAIL_FROM)
            from relate.utils import get_outbound_mail_connection
            email_kwargs.update(
                {"connection": (
                    get_outbound_mail_connection("enroll")
                    if hasattr(settings, "ENROLLMENT_EMAIL_FROM")
                    else get_outbound_mail_connection("robot"))})

        msg = EmailMessage(
                string_concat("[%s] ", _("Your enrollment request"))
                % course.identifier,
                message,
                from_email,
                [participation.user.email],
                **email_kwargs)
        msg.bcc = [course.notify_email]
        msg.send()


def approve_enrollment(modeladmin, request, queryset):
    decide_enrollment(True, modeladmin, request, queryset)

approve_enrollment.short_description = pgettext("Admin", "Approve enrollment")  # type:ignore  # noqa


def deny_enrollment(modeladmin, request, queryset):
    decide_enrollment(False, modeladmin, request, queryset)

deny_enrollment.short_description = _("Deny enrollment")  # type:ignore  # noqa

# }}}


# {{{ preapprovals

class BulkPreapprovalsForm(StyledForm):
    def __init__(self, course, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["roles"] = forms.ModelMultipleChoiceField(
                queryset=(
                    ParticipationRole.objects
                    .filter(course=course)
                    ),
                label=_("Roles"))
        self.fields["preapproval_type"] = forms.ChoiceField(
                choices=(
                    ("email", _("Email")),
                    ("institutional_id", _("Institutional ID")),
                    ),
                initial="email",
                label=_("Preapproval type"))
        self.fields["preapproval_data"] = forms.CharField(
                required=True, widget=forms.Textarea,
                help_text=_("Enter fully qualified data according to the "
                            "'Preapproval type' you selected, one per line."),
                label=_("Preapproval data"))

        self.helper.add_input(
                Submit("submit", _("Preapprove")))


@login_required
@transaction.atomic
@course_view
def create_preapprovals(pctx):
    if not pctx.has_permission(pperm.preapprove_participation):
        raise PermissionDenied(_("may not preapprove participation"))

    request = pctx.request

    if request.method == "POST":
        form = BulkPreapprovalsForm(pctx.course, request.POST)
        if form.is_valid():

            created_count = 0
            exist_count = 0
            pending_approved_count = 0

            roles = form.cleaned_data["roles"]
            preapp_type = form.cleaned_data["preapproval_type"]

            for ln in form.cleaned_data["preapproval_data"].split("\n"):
                ln = ln.strip()

                if not ln:
                    continue

                preapp_filter_kwargs = {f"{preapp_type}__iexact": ln}

                try:
                    ParticipationPreapproval.objects.get(
                        course=pctx.course, **preapp_filter_kwargs)
                except ParticipationPreapproval.DoesNotExist:

                    # approve if ln is requesting enrollment
                    user_filter_kwargs = {f"user__{preapp_type}__iexact": ln}
                    if preapp_type == "institutional_id":
                        if pctx.course.preapproval_require_verified_inst_id:
                            user_filter_kwargs.update(
                                {"user__institutional_id_verified": True})

                    try:
                        pending = Participation.objects.get(
                                course=pctx.course,
                                status=participation_status.requested,
                                **user_filter_kwargs)

                    except Participation.DoesNotExist:
                        pass

                    else:
                        pending.status = participation_status.active
                        pending.save()
                        send_enrollment_decision(pending, True, request)
                        pending_approved_count += 1

                else:
                    exist_count += 1
                    continue

                preapproval = ParticipationPreapproval()
                if preapp_type == "email":
                    preapproval.email = ln
                else:
                    assert preapp_type == "institutional_id"
                    preapproval.institutional_id = ln
                preapproval.course = pctx.course
                preapproval.creator = request.user
                preapproval.save()
                preapproval.roles.set(roles)

                created_count += 1

            messages.add_message(request, messages.INFO,
                    _(
                        "%(n_created)d preapprovals created, "
                        "%(n_exist)d already existed, "
                        "%(n_requested_approved)d pending requests approved.")
                    % {
                        "n_created": created_count,
                        "n_exist": exist_count,
                        "n_requested_approved": pending_approved_count
                        })
            return redirect("relate-course_page", pctx.course.identifier)

    else:
        form = BulkPreapprovalsForm(pctx.course)

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": _("Create Participation Preapprovals"),
    })

# }}}


# {{{ participation query parsing

# {{{ lexer data

_and = intern("and")
_or = intern("or")
_not = intern("not")
_openpar = intern("openpar")
_closepar = intern("closepar")

_id = intern("id")
_email = intern("email")
_email_contains = intern("email_contains")
_user = intern("user")
_user_contains = intern("user_contains")
_institutional_id = intern("institutional_id")
_institutional_id_contains = intern("institutional_id__contains")
_tagged = intern("tagged")
_role = intern("role")
_status = intern("status")
_has_started = intern("has_started")
_has_submitted = intern("has_submitted")
_whitespace = intern("whitespace")

# }}}


class RE(REBase):
    def __init__(self, s: str) -> None:
        import re
        super().__init__(s, re.UNICODE)


_LEX_TABLE = [
    (_and, RE(r"and\b")),
    (_or, RE(r"or\b")),
    (_not, RE(r"not\b")),
    (_openpar, RE(r"\(")),
    (_closepar, RE(r"\)")),

    # TERMINALS
    (_id, RE(r"id:([0-9]+)")),
    (_email, RE(r"email:([^ \t\n\r\f\v)]+)")),
    (_email_contains, RE(r"email-contains:([^ \t\n\r\f\v)]+)")),
    (_user, RE(r"username:([^ \t\n\r\f\v)]+)")),
    (_user_contains, RE(r"username-contains:([^ \t\n\r\f\v)]+)")),
    (_institutional_id, RE(r"institutional-id:([^ \t\n\r\f\v)]+)")),
    (_institutional_id_contains,
            RE(r"institutional-id-contains:([^ \t\n\r\f\v)]+)")),
    (_tagged, RE(r"tagged:([-\w]+)")),
    (_role, RE(r"role:(\w+)")),
    (_status, RE(r"status:(\w+)")),
    (_has_started, RE(r"has-started:([-_\w]+)")),
    (_has_submitted, RE(r"has-submitted:([-_\w]+)")),

    (_whitespace, RE("[ \t]+")),
    ]


_TERMINALS = ([
    _id, _email, _email_contains, _user, _user_contains, _tagged, _role, _status,
    _institutional_id, _institutional_id_contains
])

# {{{ operator precedence

_PREC_OR = 10
_PREC_AND = 20
_PREC_NOT = 30

# }}}


# {{{ parser

def parse_query(course, expr_str):
    from django.db.models import Q

    def parse_terminal(pstate):
        next_tag = pstate.next_tag()
        if next_tag is _id:
            result = Q(user__id=int(pstate.next_match_obj().group(1)))
            pstate.advance()
            return result

        elif next_tag is _email:
            result = Q(user__email__iexact=pstate.next_match_obj().group(1))
            pstate.advance()
            return result

        elif next_tag is _email_contains:
            result = Q(user__email__icontains=pstate.next_match_obj().group(1))
            pstate.advance()
            return result

        elif next_tag is _user:
            result = Q(user__username__exact=pstate.next_match_obj().group(1))
            pstate.advance()
            return result

        elif next_tag is _user_contains:
            result = Q(user__username__contains=pstate.next_match_obj().group(1))
            pstate.advance()
            return result

        elif next_tag is _institutional_id:
            result = Q(
                user__institutional_id__iexact=pstate.next_match_obj().group(1))
            pstate.advance()
            return result

        elif next_tag is _institutional_id_contains:
            result = Q(
                user__institutional_id__icontains=pstate.next_match_obj().group(1))
            pstate.advance()
            return result

        elif next_tag is _tagged:
            ptag, _created = ParticipationTag.objects.get_or_create(
                    course=course,
                    name=pstate.next_match_obj().group(1))

            result = Q(tags__pk=ptag.pk)

            pstate.advance()
            return result

        elif next_tag is _role:
            name_map = {"teaching_assistant": "ta"}
            name = pstate.next_match_obj().group(1)
            prole, _created = ParticipationRole.objects.get_or_create(
                    course=course,
                    identifier=name_map.get(name, name))

            result = Q(roles__pk=prole.pk)

            pstate.advance()
            return result

        elif next_tag is _status:
            result = Q(status=pstate.next_match_obj().group(1))

            pstate.advance()
            return result

        elif next_tag is _has_started:
            flow_id = pstate.next_match_obj().group(1)
            result = (
                    Q(flow_sessions__flow_id=flow_id)
                    & Q(flow_sessions__course=course))
            pstate.advance()
            return result

        elif next_tag is _has_submitted:
            flow_id = pstate.next_match_obj().group(1)
            result = (
                    Q(flow_sessions__flow_id=flow_id)
                    & Q(flow_sessions__course=course)
                    & Q(flow_sessions__in_progress=False))
            pstate.advance()
            return result

        else:
            pstate.expected("terminal")

    def inner_parse(pstate, min_precedence=0):
        pstate.expect_not_end()

        if pstate.is_next(_not):
            pstate.advance()
            left_query = ~inner_parse(pstate, _PREC_NOT)
        elif pstate.is_next(_openpar):
            pstate.advance()
            left_query = inner_parse(pstate)
            pstate.expect(_closepar)
            pstate.advance()
        else:
            left_query = parse_terminal(pstate)

        did_something = True
        while did_something:
            did_something = False
            if pstate.is_at_end():
                return left_query

            next_tag = pstate.next_tag()

            if next_tag is _and and _PREC_AND > min_precedence:
                pstate.advance()
                left_query = left_query & inner_parse(pstate, _PREC_AND)
                did_something = True
            elif next_tag is _or and _PREC_OR > min_precedence:
                pstate.advance()
                left_query = left_query | inner_parse(pstate, _PREC_OR)
                did_something = True
            elif (next_tag in [*_TERMINALS, _not, _openpar]
                    and _PREC_AND > min_precedence):
                left_query = left_query & inner_parse(pstate, _PREC_AND)
                did_something = True

        return left_query

    from pytools.lex import LexIterator, lex
    pstate = LexIterator(
        [(tag, s, idx, matchobj)
         for (tag, s, idx, matchobj) in lex(_LEX_TABLE, expr_str, match_objects=True)
         if tag is not _whitespace], expr_str)

    if pstate.is_at_end():
        pstate.raise_parse_error("unexpected end of input")

    result = inner_parse(pstate)
    if not pstate.is_at_end():
        pstate.raise_parse_error("leftover input after completed parse")

    return result

# }}}

# }}}


# {{{ participation query

class ParticipationQueryForm(StyledForm):
    queries = forms.CharField(
            required=True,
            widget=forms.Textarea,
            help_text=string_concat(
                _("Enter queries, one per line. Union of results is shown."), " ",
                _("Allowed"), ": ",
                "<code>and</code>, "
                "<code>or</code>, "
                "<code>not</code>, "
                "<code>id:1234</code>, "
                "<code>email:a@b.com</code>, "
                "<code>email-contains:abc</code>, "
                "<code>username:abc</code>, "
                "<code>username-contains:abc</code>, "
                "<code>institutional-id:2015abcd</code>, "
                "<code>institutional-id-contains:2015</code>, "
                "<code>tagged:abc</code>, "
                "<code>role:instructor|teaching_assistant|"
                "student|observer|auditor</code>, "
                "<code>status:requested|active|dropped|denied</code>|"
                "<code>has-started:flow_id</code>|"
                "<code>has-submitted:flow_id</code>."
                ),
            label=_("Queries"))
    op = forms.ChoiceField(
            choices=(
                ("apply_tag", _("Apply tag")),
                ("remove_tag", _("Remove tag")),
                ("drop", _("Drop")),
                ),
            label=_("Operation"),
            required=True)
    tag = forms.CharField(label=_("Tag"),
            help_text=_("Tag to apply or remove"),
            required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("list", _("List")))
        self.helper.add_input(
                Submit("apply", _("Apply operation")))

    def clean_tag(self):
        tag = self.cleaned_data.get("tag")

        if tag:
            if not tag.isidentifier():
                self.add_error(
                    "tag",
                    _("Name contains invalid characters."))
        return tag


@login_required
@transaction.atomic
@course_view
def query_participations(pctx):
    if (
            not pctx.has_permission(pperm.query_participation)
            or pctx.has_permission(pperm.view_participant_masked_profile)):
        raise PermissionDenied(_("may not query participations"))

    request = pctx.request

    result = None

    if request.method == "POST":
        form = ParticipationQueryForm(request.POST)
        if form.is_valid():
            parsed_query = None
            try:
                for lineno, q in enumerate(  # noqa: B007
                        form.cleaned_data["queries"].split("\n")):
                    q = q.strip()

                    if not q:
                        continue

                    parsed_subquery = parse_query(pctx.course, q)
                    if parsed_query is None:
                        parsed_query = parsed_subquery
                    else:
                        parsed_query = parsed_query | parsed_subquery

            except Exception as e:
                messages.add_message(request, messages.ERROR,
                        _("Error in line %(lineno)d: %(error_type)s: %(error)s")
                        % {
                            "lineno": lineno+1,
                            "error_type": type(e).__name__,
                            "error": str(e),
                            })

                parsed_query = None

            if parsed_query is not None:
                result = list(Participation.objects
                        .filter(course=pctx.course)
                        .filter(parsed_query)
                        .order_by("user__username")
                        .select_related("user")
                        .prefetch_related("tags"))

                if "apply" in request.POST:

                    if form.cleaned_data["op"] == "apply_tag":
                        ptag, __ = ParticipationTag.objects.get_or_create(
                                course=pctx.course, name=form.cleaned_data["tag"])
                        for p in result:
                            p.tags.add(ptag)
                    elif form.cleaned_data["op"] == "remove_tag":
                        ptag, __ = ParticipationTag.objects.get_or_create(
                                course=pctx.course, name=form.cleaned_data["tag"])
                        for p in result:
                            p.tags.remove(ptag)
                    else:
                        assert form.cleaned_data["op"] == "drop"
                        for p in result:
                            p.status = participation_status.dropped
                            p.save()

                    messages.add_message(request, messages.INFO,
                            "Operation successful on %d participations."
                            % len(result))

    else:
        form = ParticipationQueryForm()

    return render_course_page(pctx, "course/query-participations.html", {
        "form": form,
        "result": result,
    })

# }}}


# {{{ edit_participation

class EditParticipationForm(StyledModelForm):

    def __init__(self, add_new: bool, pctx: CoursePageContext,
            *args: Any, **kwargs: Any) -> None:
        if not add_new:
            kwargs.setdefault("initial", {})["individual_permissions"] = (
                    list(kwargs["instance"].individual_permissions.all()))

        super().__init__(*args, **kwargs)

        participation = self.instance

        self.fields["status"].disabled = True
        self.fields["preview_git_commit_sha"].disabled = True
        self.fields["enroll_time"].disabled = True

        if not add_new:
            self.fields["user"].disabled = True
        else:
            participation_users = Participation.objects.filter(
                course=participation.course).values_list("user__pk", flat=True)
            self.fields["user"].queryset = (
                get_user_model().objects.exclude(pk__in=participation_users)
            )
        self.add_new = add_new

        may_edit_permissions = pctx.has_permission(pperm.edit_course_permissions)
        if not may_edit_permissions:
            self.fields["roles"].disabled = True

        self.fields["roles"].queryset = (
                ParticipationRole.objects.filter(
                    course=participation.course))
        self.fields["tags"].queryset = (
                ParticipationTag.objects.filter(
                    course=participation.course))

        self.fields["individual_permissions"] = forms.MultipleChoiceField(
                choices=PARTICIPATION_PERMISSION_CHOICES,
                disabled=not may_edit_permissions,
                widget=forms.CheckboxSelectMultiple,
                help_text=_("Permissions for this participant in addition to those "
                    "granted by their role"),
                required=False)

        self.helper.add_input(
                Submit("submit", _("Update")))
        if participation.status != participation_status.active:
            self.helper.add_input(
                    Submit("approve", _("Approve"), css_class="btn-success"))
            if participation.status == participation_status.requested:
                self.helper.add_input(
                        Submit("deny", _("Deny"), css_class="btn-danger"))
        else:
            self.helper.add_input(
                    Submit("drop", _("Drop"), css_class="btn-danger"))

    def clean_user(self):
        user = self.cleaned_data["user"]
        if not self.add_new:
            return user
        if user.status == user_status.active:
            return user

        raise forms.ValidationError(
            _("This user has not confirmed his/her email."))

    def save(self) -> Participation:

        inst = super().save()

        (ParticipationPermission.objects
                .filter(participation=self.instance)
                .delete())

        pps = []
        for perm in self.cleaned_data["individual_permissions"]:
            pp = ParticipationPermission(
                        participation=self.instance,
                        permission=perm)
            pp.save()
            pps.append(pp)
        self.instance.individual_permissions.set(pps)

        return inst

    class Meta:
        model = Participation
        exclude = (
                "role",
                "course",
                )

        widgets = {
                "user": UserSearchWidget,
                }


@course_view
def edit_participation(
        pctx: CoursePageContext, participation_id: int) -> http.HttpResponse:
    if not pctx.has_permission(pperm.edit_participation):
        raise PermissionDenied()

    request = pctx.request

    num_participation_id = int(participation_id)

    if num_participation_id == -1:
        participation = Participation(
                course=pctx.course,
                status=participation_status.active)
        add_new = True
    else:
        participation = get_object_or_404(Participation, id=num_participation_id)
        add_new = False

    if participation.course.id != pctx.course.id:
        raise SuspiciousOperation("may not edit participation in different course")

    if request.method == "POST":
        form = EditParticipationForm(
                add_new, pctx, request.POST, instance=participation)
        reset_form = False

        try:
            if form.is_valid():
                if "submit" in request.POST:
                    form.save()

                    messages.add_message(request, messages.SUCCESS,
                            _("Changes saved."))

                elif "approve" in request.POST:

                    # FIXME: Double-saving
                    participation = form.save()
                    participation.status = participation_status.active
                    participation.save()
                    reset_form = True

                    send_enrollment_decision(participation, True, pctx.request)

                    messages.add_message(request, messages.SUCCESS,
                            _("Successfully enrolled."))

                elif "deny" in request.POST:

                    # FIXME: Double-saving
                    participation = form.save()
                    participation.status = participation_status.denied
                    participation.save()
                    reset_form = True

                    send_enrollment_decision(participation, False, pctx.request)

                    messages.add_message(request, messages.SUCCESS,
                            _("Successfully denied."))

                elif "drop" in request.POST:
                    # FIXME: Double-saving
                    participation = form.save()
                    participation.status = participation_status.dropped
                    participation.save()
                    reset_form = True

                    messages.add_message(request, messages.SUCCESS,
                            _("Successfully dropped."))
        except IntegrityError as e:
            messages.add_message(request, messages.ERROR,
                    _("A data integrity issue was detected when saving "
                        "this participation. Maybe a participation for "
                        "this user already exists? (%s)")
                    % str(e))

        if reset_form:
            form = EditParticipationForm(
                    add_new, pctx, instance=participation)
    else:
        form = EditParticipationForm(add_new, pctx, instance=participation)

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form_description": _("Edit Participation"),
        "form": form
        })

# }}}

# vim: foldmethod=marker
