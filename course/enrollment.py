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

from six.moves import intern

from django.utils.translation import (
        ugettext_lazy as _,
        pgettext,
        string_concat)
from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.conf import settings
from django.core.urlresolvers import reverse
from django.db import transaction
from django import forms
from django.utils import translation

from crispy_forms.layout import Submit

from course.models import (
        user_status,
        Course,
        Participation, ParticipationPreapproval,
        ParticipationTag,
        participation_role, participation_status,
        PARTICIPATION_ROLE_CHOICES)

from course.views import get_role_and_participation
from course.utils import course_view, render_course_page

from relate.utils import StyledForm

from pytools.lex import RE as REBase


# {{{ enrollment

@login_required
@transaction.atomic
def enroll(request, course_identifier):
    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(request, course)

    if role != participation_role.unenrolled:
        messages.add_message(request, messages.ERROR,
                _("Already enrolled. Cannot re-renroll."))
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

    user = request.user
    if (course.enrollment_required_email_suffix
            and user.status != user_status.active):
        messages.add_message(request, messages.ERROR,
                _("Your email address is not yet confirmed. "
                "Confirm your email to continue."))
        return redirect("relate-course_page", course_identifier)

    preapproval = None
    if request.user.email:
        try:
            preapproval = ParticipationPreapproval.objects.get(
                    course=course, email__iexact=request.user.email)
        except ParticipationPreapproval.DoesNotExist:
            if user.institutional_id:
                if not (course.preapproval_require_verified_inst_id
                        and not user.institutional_id_verified):
                    try:
                        preapproval = ParticipationPreapproval.objects.get(
                                course=course,
                                institutional_id__iexact=user.institutional_id)
                    except ParticipationPreapproval.DoesNotExist:
                        pass
            pass

    if (
            preapproval is None
            and course.enrollment_required_email_suffix
            and not user.email.endswith(course.enrollment_required_email_suffix)):

        messages.add_message(request, messages.ERROR,
                _("Enrollment not allowed. Please use your '%s' email to "
                "enroll.") % course.enrollment_required_email_suffix)
        return redirect("relate-course_page", course_identifier)

    def enroll(status, role):
        participations = Participation.objects.filter(course=course, user=user)

        assert participations.count() <= 1
        if participations.count() == 0:
            participation = Participation()
            participation.user = user
            participation.course = course
            participation.role = role
            participation.status = status
            participation.save()
        else:
            (participation,) = participations
            participation.status = status
            participation.save()

        return participation

    role = participation_role.student

    if preapproval is not None:
        role = preapproval.role

    if course.enrollment_approval_required and preapproval is None:
        enroll(participation_status.requested, role)

        with translation.override(settings.RELATE_ADMIN_EMAIL_LOCALE):
            from django.template.loader import render_to_string
            message = render_to_string("course/enrollment-request-email.txt", {
                "user": user,
                "course": course,
                "admin_uri": request.build_absolute_uri(
                        reverse("admin:course_participation_changelist")
                        + "?status__exact=requested")
                })

            from django.core.mail import send_mail
            send_mail(
                    string_concat("[%s] ", _("New enrollment request"))
                    % course_identifier,
                    message,
                    settings.ROBOT_EMAIL_FROM,
                    recipient_list=[course.notify_email])

        messages.add_message(request, messages.INFO,
                _("Enrollment request sent. You will receive notifcation "
                "by email once your request has been acted upon."))
    else:
        enroll(participation_status.active, role)

        messages.add_message(request, messages.SUCCESS,
                _("Successfully enrolled."))

    return redirect("relate-course_page", course_identifier)

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


def send_enrollment_decision(participation, approved, request):
        with translation.override(settings.RELATE_ADMIN_EMAIL_LOCALE):
            course = participation.course
            from django.template.loader import render_to_string
            message = render_to_string("course/enrollment-decision-email.txt", {
                "user": participation.user,
                "approved": approved,
                "course": course,
                "course_uri": request.build_absolute_uri(
                        reverse("relate-course_page",
                            args=(course.identifier,)))
                })

            from django.core.mail import EmailMessage
            msg = EmailMessage(
                    string_concat("[%s] ", _("Your enrollment request"))
                    % course.identifier,
                    message,
                    course.from_email,
                    [participation.user.email])
            msg.bcc = [course.notify_email]
            msg.send()


def approve_enrollment(modeladmin, request, queryset):
    decide_enrollment(True, modeladmin, request, queryset)

approve_enrollment.short_description = pgettext("Admin", "Approve enrollment")


def deny_enrollment(modeladmin, request, queryset):
    decide_enrollment(False, modeladmin, request, queryset)

deny_enrollment.short_description = _("Deny enrollment")

# }}}


# {{{ preapprovals

class BulkPreapprovalsForm(StyledForm):
    role = forms.ChoiceField(
            choices=PARTICIPATION_ROLE_CHOICES,
            initial=participation_role.student,
            label=_("Role"))
    preapproval_type = forms.ChoiceField(
            choices=(
                ("email", _("Email")),
                ("institutional_id", _("Institutional ID")),
                ),
            initial="email",
            label=_("Preapproval type"))
    preapproval_data = forms.CharField(required=True, widget=forms.Textarea,
            help_text=_("Enter fully qualified data according to \"Preapproval"
                        "type\" you selected, one per line."),
            label=_("Preapproval data"))

    def __init__(self, *args, **kwargs):
        super(BulkPreapprovalsForm, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit", _("Preapprove")))


@login_required
@transaction.atomic
@course_view
def create_preapprovals(pctx):
    if pctx.role != participation_role.instructor:
        raise PermissionDenied(_("only instructors may do that"))

    request = pctx.request

    if request.method == "POST":
        form = BulkPreapprovalsForm(request.POST)
        if form.is_valid():

            created_count = 0
            exist_count = 0
            pending_approved_count = 0

            role = form.cleaned_data["role"]
            for l in form.cleaned_data["preapproval_data"].split("\n"):
                l = l.strip()
                preapp_type = form.cleaned_data["preapproval_type"]

                if not l:
                    continue

                if preapp_type == "email":

                    try:
                        preapproval = ParticipationPreapproval.objects.get(
                                email__iexact=l,
                                course=pctx.course)
                    except ParticipationPreapproval.DoesNotExist:

                        # approve if l is requesting enrollment
                        try:
                            pending_participation = Participation.objects.get(
                                    course=pctx.course,
                                    status=participation_status.requested,
                                    user__email__iexact=l)

                        except Participation.DoesNotExist:
                            pass

                        else:
                            pending_participation.status = participation_status.active
                            pending_participation.save()
                            send_enrollment_decision(
                                    pending_participation, True, request)
                            pending_approved_count += 1

                    else:
                        exist_count += 1
                        continue

                    preapproval = ParticipationPreapproval()
                    preapproval.email = l
                    preapproval.course = pctx.course
                    preapproval.role = role
                    preapproval.creator = request.user
                    preapproval.save()

                    created_count += 1

                elif preapp_type == "institutional_id":

                    try:
                        preapproval = ParticipationPreapproval.objects.get(
                                course=pctx.course, institutional_id__iexact=l)
                        # FIXME :
                        """
                           When an exist preapproval is submit, and if the tutor change the
                           requirement of preapproval_require_verified_inst_id of the
                           course from True to False, some pending requests which did not
                           provided valid inst_id will still be pending.

                           BTW, it is also the case when the tutor changed the
                           enrollment_required_email_suffix from "@what.com" to "".
                        """
                    except ParticipationPreapproval.DoesNotExist:

                        # approve if l is requesting enrollment
                        try:
                            pending_participation = Participation.objects.get(
                                    course=pctx.course,
                                    status=participation_status.requested,
                                    user__institutional_id__iexact=l)
                            if (
                                    pctx.course.preapproval_require_verified_inst_id
                                    and not pending_participation.user.institutional_id_verified):
                                raise Participation.DoesNotExist

                        except Participation.DoesNotExist:
                            pass

                        else:
                            pending_participation.status = participation_status.active
                            pending_participation.save()
                            send_enrollment_decision(
                                    pending_participation, True, request)
                            pending_approved_count += 1

                    else:
                        exist_count += 1
                        continue

                    preapproval = ParticipationPreapproval()
                    preapproval.institutional_id = l
                    preapproval.course = pctx.course
                    preapproval.role = role
                    preapproval.creator = request.user
                    preapproval.save()

                    created_count += 1

            messages.add_message(request, messages.INFO,
                    _(
                        "%(n_created)d preapprovals created, "
                        "%(n_exist)d already existed, "
                        "%(n_requested_approved)d pending requests approved.")
                    % {
                        'n_created': created_count,
                        'n_exist': exist_count,
                        'n_requested_approved': pending_approved_count
                        })
            return redirect("relate-course_page", pctx.course.identifier)

    else:
        form = BulkPreapprovalsForm()

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
_tagged = intern("tagged")
_whitespace = intern("whitespace")

# }}}


class RE(REBase):
    def __init__(self, s):
        import re
        super(RE, self).__init__(s, re.UNICODE)


_LEX_TABLE = [
    (_and, RE(r"and\b")),
    (_or, RE(r"or\b")),
    (_not, RE(r"not\b")),
    (_openpar, RE(r"\(")),
    (_closepar, RE(r"\)")),

    # TERMINALS
    (_id, RE(r"id:([0-9]+)")),
    (_email, RE(r"email:(\S+)")),
    (_email_contains, RE(r"email-contains:(\S+)")),
    (_user, RE(r"username:(\S+)")),
    (_user_contains, RE(r"username-contains:(\S+)")),
    (_tagged, RE(r"tagged:([-\w]+)")),

    (_whitespace, RE("[ \t]+")),
    ]


_TERMINALS = ([
    _id, _email, _email_contains, _user, _user_contains, ])

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

        elif next_tag is _tagged:
            ptag = ParticipationTag.objects.get_or_create(
                    course=course,
                    name=pstate.next_match_obj().group(1))

            result = Q(tags__pk=ptag.pk)

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
            elif (next_tag in _TERMINALS + [_not, _openpar]
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
            help_text=_(
                "Enter queries, one per line. "
                "Allowed: "
                "<code>and</code>, "
                "<code>or</code>, "
                "<code>not</code>, "
                "<code>id:1234</code>, "
                "<code>email:a@b.com</code>, "
                "<code>email-contains:abc</code>, "
                "<code>username:abc</code>, "
                "<code>username-contains:abc</code>, "
                "<code>tagged:abc</code>."
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
        super(ParticipationQueryForm, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("list", _("List")))
        self.helper.add_input(
                Submit("apply", _("Apply operation")))


@login_required
@transaction.atomic
@course_view
def query_participations(pctx):
    if pctx.role != participation_role.instructor:
        raise PermissionDenied(_("only instructors may do that"))

    request = pctx.request

    result = None

    if request.method == "POST":
        form = ParticipationQueryForm(request.POST)
        if form.is_valid():
            parsed_query = None
            try:
                for lineno, q in enumerate(form.cleaned_data["queries"].split("\n")):
                    if not q.strip():
                        continue

                    parsed_subquery = parse_query(pctx.course, q)
                    if parsed_query is None:
                        parsed_query = parsed_subquery
                    else:
                        parsed_query = parsed_query | parsed_subquery

            except RuntimeError as e:
                messages.add_message(request, messages.ERROR,
                        _("Error in line %(lineno)d: %(error)s")
                        % {
                            "lineno": lineno+1,
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
                    elif form.cleaned_data["op"] == "drop":
                        for p in result:
                            p.status = participation_status.dropped
                            p.save()
                    else:
                        raise RuntimeError("unexpected operation")

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

# vim: foldmethod=marker
