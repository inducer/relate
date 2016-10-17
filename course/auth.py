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

<<<<<<< HEAD
import re
from typing import cast
from django.utils.translation import ugettext_lazy as _
=======
from typing import cast, Text, Any, Optional  # noqa
from django.utils.translation import ugettext_lazy as _, string_concat
>>>>>>> 016ef1d1... Add a functioning git end point (with authentication), needs preview/update integration
from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect, resolve_url)
from django.contrib import messages
import django.forms as forms
from django.core.exceptions import (PermissionDenied, SuspiciousOperation,
        ObjectDoesNotExist, MultipleObjectsReturned)
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Layout, Div, Button
from django.conf import settings
from django.contrib.auth import (get_user_model, REDIRECT_FIELD_NAME,
        login as auth_login, logout as auth_logout)
from django.contrib.auth.forms import \
        AuthenticationForm as AuthenticationFormBase
from django.contrib.auth.decorators import user_passes_test, login_required
from django.urls import reverse
from django.contrib.auth.validators import ASCIIUsernameValidator
from django.utils.http import is_safe_url
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django import http  # noqa

from bootstrap3_datetime.widgets import DateTimePicker

from djangosaml2.backends import Saml2Backend as Saml2BackendBase

from course.constants import (
        user_status,
        participation_status,
        participation_permission as pperm,
        )
from course.models import Participation, ParticipationRole, AuthenticationToken  # noqa
from accounts.models import User
from course.utils import render_course_page, course_view

from relate.utils import StyledForm, StyledModelForm, string_concat, get_site_name
from django_select2.forms import ModelSelect2Widget

if False:
    from typing import Any, Text, Optional  # noqa
    from django.db.models import query  # noqa


# {{{ impersonation

def get_pre_impersonation_user(request):
    is_impersonating = hasattr(
            request, "relate_impersonate_original_user")
    if is_impersonating:
        return request.relate_impersonate_original_user
    return None


def get_impersonable_user_qset(impersonator):
    # type: (User) -> query.QuerySet
    if impersonator.is_superuser:
        return User.objects.exclude(pk=impersonator.pk)

    my_participations = Participation.objects.filter(
        user=impersonator,
        status=participation_status.active)

    impersonable_user_qset = User.objects.none()
    for part in my_participations:
        # Notice: if a TA is not allowed to view participants'
        # profile in one course, then he/she is not able to impersonate
        # any user, even in courses he/she is allow to view profiles
        # of all users.
        if part.has_permission(pperm.view_participant_masked_profile):
            return User.objects.none()
        impersonable_roles = [
            argument
            for perm, argument in part.permissions()
            if perm == pperm.impersonate_role]

        q = (Participation.objects
             .filter(course=part.course,
                     status=participation_status.active,
                     roles__identifier__in=impersonable_roles)
             .select_related("user"))

        # There can be duplicate records. Removing duplicate records is needed
        # only when rendering ImpersonateForm
        impersonable_user_qset = (
            impersonable_user_qset
            | User.objects.filter(pk__in=q.values_list("user__pk", flat=True))
        )

    return impersonable_user_qset


class ImpersonateMiddleware(object):
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if 'impersonate_id' in request.session:
            imp_id = request.session['impersonate_id']
            impersonee = None

            try:
                if imp_id is not None:
                    impersonee = cast(User, get_user_model().objects.get(id=imp_id))
            except ObjectDoesNotExist:
                pass

            may_impersonate = False
            if impersonee is not None:
                if request.user.is_superuser:
                    may_impersonate = True
                else:
                    qset = get_impersonable_user_qset(cast(User, request.user))
                    if qset.filter(pk=cast(User, impersonee).pk).count():
                        may_impersonate = True

            if may_impersonate:
                request.relate_impersonate_original_user = request.user
                request.user = impersonee
            else:
                messages.add_message(request, messages.ERROR,
                        _("Error while impersonating."))

        return self.get_response(request)


class UserSearchWidget(ModelSelect2Widget):
    model = User
    search_fields = [
            'username__icontains',
            'email__icontains',
            'first_name__icontains',
            'last_name__icontains',
            ]

    def label_from_instance(self, u):
        if u.first_name and u.last_name:
            return (
                (
                    "%(full_name)s (%(username)s - %(email)s)"
                    % {
                        "full_name": u.get_full_name(),
                        "email": u.email,
                        "username": u.username
                        }))
        else:
            # for users with "None" fullname
            return (
                (
                    "%(username)s (%(email)s)"
                    % {
                        "email": u.email,
                        "username": u.username
                        }))


class ImpersonateForm(StyledForm):
    def __init__(self, *args, **kwargs):
        # type:(*Any, **Any) -> None

        qset = kwargs.pop("impersonable_qset")
        super(ImpersonateForm, self).__init__(*args, **kwargs)

        self.fields["user"] = forms.ModelChoiceField(
                queryset=qset,
                required=True,
                help_text=_("Select user to impersonate."),
                widget=UserSearchWidget(queryset=qset),
                label=_("User"))

        self.fields["add_impersonation_header"] = forms.BooleanField(
                required=False,
                initial=True,
                label=_("Add impersonation header"),
                help_text=_("Add impersonation header to every page rendered "
                    "while impersonating, as a reminder that impersonation "
                    "is in progress."))

        self.helper.add_input(Submit("submit", _("Impersonate")))


def impersonate(request):
    # type: (http.HttpRequest) -> http.HttpResponse
    if not request.user.is_authenticated:
        raise PermissionDenied()

    impersonable_user_qset = get_impersonable_user_qset(cast(User, request.user))
    if not impersonable_user_qset.count():
        raise PermissionDenied()

    if hasattr(request, "relate_impersonate_original_user"):
        messages.add_message(request, messages.ERROR,
                _("Already impersonating someone."))
        return redirect("relate-home")

    # Remove duplicate and sort
    # order_by().distinct() directly on impersonable_user_qset will not work
    qset = (User.objects
            .filter(pk__in=impersonable_user_qset.values_list("pk", flat=True))
            .order_by("last_name", "first_name", "username"))
    if request.method == 'POST':
        form = ImpersonateForm(request.POST, impersonable_qset=qset)
        if form.is_valid():
            impersonee = form.cleaned_data["user"]

            request.session['impersonate_id'] = impersonee.id
            request.session['relate_impersonation_header'] = form.cleaned_data[
                    "add_impersonation_header"]

            # Because we'll likely no longer have access to this page.
            return redirect("relate-home")

    else:
        form = ImpersonateForm(impersonable_qset=qset)

    return render(request, "generic-form.html", {
        "form_description": _("Impersonate user"),
        "form": form
        })


def stop_impersonating(request):
    # type: (http.HttpRequest) -> http.JsonResponse
    if not request.is_ajax() or request.method != "POST":
        raise PermissionDenied(_("only AJAX POST is allowed"))

    if not request.user.is_authenticated:
        raise PermissionDenied()

    if "stop_impersonating" not in request.POST:
        raise SuspiciousOperation(_("odd POST parameters"))

    if not hasattr(request, "relate_impersonate_original_user"):
        # prevent user without pperm to stop_impersonating
        my_participations = Participation.objects.filter(
            user=request.user,
            status=participation_status.active)

        may_impersonate = False
        for part in my_participations:
            perms = [
                perm
                for perm, argument in part.permissions()
                if perm == pperm.impersonate_role]
            if any(perms):
                may_impersonate = True
                break

        if not may_impersonate:
            raise PermissionDenied(_("may not stop impersonating"))

        messages.add_message(request, messages.ERROR,
                _("Not currently impersonating anyone."))
        return http.JsonResponse({})

    del request.session['impersonate_id']
    messages.add_message(request, messages.INFO,
            _("No longer impersonating anyone."))
    return http.JsonResponse({"result": "success"})


def impersonation_context_processor(request):
    return {
            "currently_impersonating":
            hasattr(request, "relate_impersonate_original_user"),
            "add_impersonation_header":
            request.session.get("relate_impersonation_header", True),
            }

# }}}


def make_sign_in_key(user):
    # type: (User) -> Text
<<<<<<< HEAD
=======

>>>>>>> 016ef1d1... Add a functioning git end point (with authentication), needs preview/update integration
    # Try to ensure these hashes aren't guessable.
    import random
    import hashlib
    from time import time
    m = hashlib.sha1()
    m.update(user.email.encode("utf-8"))
    m.update(hex(random.getrandbits(128)).encode())
    m.update(str(time()).encode("utf-8"))
    return m.hexdigest()


def logout_confirmation_required(
        func=None, redirect_field_name=REDIRECT_FIELD_NAME,
        logout_confirmation_url='relate-logout-confirmation'):
    """
    Decorator for views that checks that no user is logged in.
    If a user is currently logged in, redirect him/her to the logout
    confirmation page.
    """
    actual_decorator = user_passes_test(
        lambda u: u.is_anonymous,
        login_url=logout_confirmation_url,
        redirect_field_name=redirect_field_name
    )
    if func:
        return actual_decorator(func)
    return actual_decorator


class EmailedTokenBackend(object):
    def authenticate(self, request, user_id=None, token=None):
        users = get_user_model().objects.filter(
                id=user_id, sign_in_key=token)

        assert users.count() <= 1
        if users.count() == 0:
            return None

        (user,) = users

        user.status = user_status.active
        user.sign_in_key = None
        user.save()

        return user

    def get_user(self, user_id):
        try:
            return get_user_model().objects.get(pk=user_id)
        except get_user_model().DoesNotExist:
            return None


# {{{ choice

@logout_confirmation_required
def sign_in_choice(request, redirect_field_name=REDIRECT_FIELD_NAME):
    redirect_to = request.POST.get(redirect_field_name,
                                   request.GET.get(redirect_field_name, ''))
    next_uri = ""
    if redirect_to:
        next_uri = "?%s=%s" % (redirect_field_name, redirect_to)

    return render(request, "sign-in-choice.html", {"next_uri": next_uri})

# }}}


# {{{ conventional login

class LoginForm(AuthenticationFormBase):
    def __init__(self, *args, **kwargs):
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        self.helper.add_input(Submit("submit", _("Sign in")))

        super(LoginForm, self).__init__(*args, **kwargs)


@sensitive_post_parameters()
@csrf_protect
@never_cache
@logout_confirmation_required
def sign_in_by_user_pw(request, redirect_field_name=REDIRECT_FIELD_NAME):
    """
    Displays the login form and handles the login action.
    """
    if not settings.RELATE_SIGN_IN_BY_USERNAME_ENABLED:
        messages.add_message(request, messages.ERROR,
                _("Username-based sign-in is not being used"))
        return redirect("relate-sign_in_choice")

    redirect_to = request.POST.get(redirect_field_name,
                                   request.GET.get(redirect_field_name, ''))

    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():

            # Ensure the user-originating redirection url is safe.
            if not is_safe_url(
                    url=redirect_to,
                    allowed_hosts=set([request.get_host()]),
                    require_https=request.is_secure()):
                redirect_to = resolve_url("relate-home")

            user = form.get_user()

            # Okay, security check complete. Log the user in.
            auth_login(request, user)

            return HttpResponseRedirect(redirect_to)
    else:
        form = LoginForm(request)

    next_uri = ""
    if redirect_to:
        next_uri = "?%s=%s" % (redirect_field_name, redirect_to)

    context = {
        'form': form,
        redirect_field_name: redirect_to,
        'next_uri': next_uri,
    }

    return TemplateResponse(request, "course/login.html", context)


class SignUpForm(StyledModelForm):
    username = forms.CharField(required=True, max_length=30,
            label=_("Username"),
            validators=[ASCIIUsernameValidator()])

    class Meta:
        model = get_user_model()
        fields = ("email",)

    def __init__(self, *args, **kwargs):
        super(SignUpForm, self).__init__(*args, **kwargs)

        self.fields["email"].required = True

        self.helper.add_input(
                Submit("submit", _("Send email")))


@logout_confirmation_required
def sign_up(request):
    if not settings.RELATE_REGISTRATION_ENABLED:
        raise SuspiciousOperation(
                _("self-registration is not enabled"))

    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            if get_user_model().objects.filter(
                    username=form.cleaned_data["username"]).count():
                messages.add_message(request, messages.ERROR,
                        _("A user with that username already exists."))

            else:
                email = form.cleaned_data["email"]
                user = get_user_model()(
                        email=email,
                        username=form.cleaned_data["username"])

                user.set_unusable_password()
                user.status = user_status.unconfirmed
                user.sign_in_key = make_sign_in_key(user)
                user.save()

                from relate.utils import render_email_template
                message = render_email_template("course/sign-in-email.txt", {
                    "user": user,
                    "sign_in_uri": request.build_absolute_uri(
                        reverse(
                            "relate-reset_password_stage2",
                            args=(user.id, user.sign_in_key,))
                        + "?to_profile=1"),
                    "home_uri": request.build_absolute_uri(
                        reverse("relate-home"))
                    })

                from django.core.mail import EmailMessage
                msg = EmailMessage(
                        string_concat("[%s] " % _(get_site_name()),
                                      _("Verify your email")),
                        message,
                        getattr(settings, "NO_REPLY_EMAIL_FROM",
                                settings.ROBOT_EMAIL_FROM),
                        [email])

                from relate.utils import get_outbound_mail_connection
                msg.connection = (
                        get_outbound_mail_connection("no_reply")
                        if hasattr(settings, "NO_REPLY_EMAIL_FROM")
                        else get_outbound_mail_connection("robot"))
                msg.send()

                messages.add_message(request, messages.INFO,
                        _("Email sent. Please check your email and click "
                        "the link."))

                return redirect("relate-home")
        else:
            if ("email" in form.errors
                    and "That email address is already in use."
                    in form.errors["email"]):
                messages.add_message(request, messages.ERROR,
                        _("That email address is already in use. "
                        "Would you like to "
                        "<a href='%s'>reset your password</a> instead?")
                        % reverse(
                            "relate-reset_password"))

    else:
        form = SignUpForm()

    return render(request, "generic-form.html", {
        "form_description": _("Sign up"),
        "form": form
        })


class ResetPasswordFormByEmail(StyledForm):
    email = forms.EmailField(required=True, label=_("Email"),
                             max_length=User._meta.get_field('email').max_length)

    def __init__(self, *args, **kwargs):
        super(ResetPasswordFormByEmail, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit", _("Send email")))


class ResetPasswordFormByInstid(StyledForm):
    instid = forms.CharField(max_length=100,
                              required=True,
                              label=_("Institutional ID"))

    def __init__(self, *args, **kwargs):
        super(ResetPasswordFormByInstid, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit", _("Send email")))


def masked_email(email):
    # return a masked email address
    at = email.find('@')
    return email[:2] + "*" * (len(email[3:at])-1) + email[at-1:]


@logout_confirmation_required
def reset_password(request, field="email"):
    if not settings.RELATE_REGISTRATION_ENABLED:
        raise SuspiciousOperation(
                _("self-registration is not enabled"))

    # return form class by string of class name
    ResetPasswordForm = globals()["ResetPasswordFormBy" + field.title()]  # noqa
    if request.method == 'POST':
        form = ResetPasswordForm(request.POST)
        user = None
        if form.is_valid():
            exist_users_with_same_email = False
            if field == "instid":
                inst_id = form.cleaned_data["instid"]
                try:
                    user = get_user_model().objects.get(
                            institutional_id__iexact=inst_id)
                except ObjectDoesNotExist:
                    pass

            if field == "email":
                email = form.cleaned_data["email"]
                try:
                    user = get_user_model().objects.get(email__iexact=email)
                except ObjectDoesNotExist:
                    pass
                except MultipleObjectsReturned:
                    exist_users_with_same_email = True

            if exist_users_with_same_email:
                # This is for backward compatibility.
                messages.add_message(request, messages.ERROR,
                        _("Failed to send an email: multiple users were "
                          "unexpectedly using that same "
                          "email address. Please "
                          "contact site staff."))
            else:
                if user is None:
                    FIELD_DICT = {  # noqa
                            "email": _("email address"),
                            "instid": _("institutional ID")
                            }
                    messages.add_message(request, messages.ERROR,
                            _("That %(field)s doesn't have an "
                                "associated user account. Are you "
                                "sure you've registered?")
                            % {"field": FIELD_DICT[field]})
                else:
                    if not user.email:
                        messages.add_message(request, messages.ERROR,
                                _("The account with that institution ID "
                                    "doesn't have an associated email."))
                    else:
                        email = user.email
                        user.sign_in_key = make_sign_in_key(user)
                        user.save()

                        from relate.utils import render_email_template
                        message = render_email_template(
                            "course/sign-in-email.txt", {
                                "user": user,
                                "sign_in_uri": request.build_absolute_uri(
                                    reverse(
                                        "relate-reset_password_stage2",
                                        args=(user.id, user.sign_in_key,))),
                                "home_uri": request.build_absolute_uri(
                                    reverse("relate-home"))
                            })
                        from django.core.mail import EmailMessage
                        msg = EmailMessage(
                                string_concat("[%s] " % _(get_site_name()),
                                              _("Password reset")),
                                message,
                                getattr(settings, "NO_REPLY_EMAIL_FROM",
                                        settings.ROBOT_EMAIL_FROM),
                                [email])

                        from relate.utils import get_outbound_mail_connection
                        msg.connection = (
                                get_outbound_mail_connection("no_reply")
                                if hasattr(settings, "NO_REPLY_EMAIL_FROM")
                                else get_outbound_mail_connection("robot"))
                        msg.send()

                        if field == "instid":
                            messages.add_message(request, messages.INFO,
                                _("The email address associated with that "
                                  "account is %s.")
                                % masked_email(email))

                        messages.add_message(request, messages.INFO,
                                _("Email sent. Please check your email and "
                                  "click the link."))

                        return redirect("relate-home")
    else:
        form = ResetPasswordForm()

    return render(request, "reset-passwd-form.html", {
        "field": field,
        "form_description":
            _("Password reset on %(site_name)s")
            % {"site_name": _(get_site_name())},
        "form": form
        })


class ResetPasswordStage2Form(StyledForm):
    password = forms.CharField(widget=forms.PasswordInput(),
                              label=_("Password"))
    password_repeat = forms.CharField(widget=forms.PasswordInput(),
                              label=_("Password confirmation"))

    def __init__(self, *args, **kwargs):
        super(ResetPasswordStage2Form, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit_user", _("Update")))

    def clean(self):
        cleaned_data = super(ResetPasswordStage2Form, self).clean()
        password = cleaned_data.get("password")
        password_repeat = cleaned_data.get("password_repeat")
        if password and password != password_repeat:
            self.add_error("password_repeat",
                    _("The two password fields didn't match."))


@logout_confirmation_required
def reset_password_stage2(request, user_id, sign_in_key):
    if not settings.RELATE_REGISTRATION_ENABLED:
        raise SuspiciousOperation(
                _("self-registration is not enabled"))

    def check_sign_in_key(user_id, token):
        user = get_user_model().objects.get(id=user_id)
        return user.sign_in_key == token

    try:
        if not check_sign_in_key(user_id=int(user_id), token=sign_in_key):
            messages.add_message(request, messages.ERROR,
                    _("Invalid sign-in token. Perhaps you've used an old token "
                    "email?"))
            raise PermissionDenied(_("invalid sign-in token"))
    except get_user_model().DoesNotExist:
        messages.add_message(request, messages.ERROR, _("Account does not exist."))
        raise PermissionDenied(_("invalid sign-in token"))

    if request.method == 'POST':
        form = ResetPasswordStage2Form(request.POST)
        if form.is_valid():
            from django.contrib.auth import authenticate, login
            user = authenticate(user_id=int(user_id), token=sign_in_key)
            if user is None:
                messages.add_message(request, messages.ERROR,
                     _("Invalid sign-in token. Perhaps you've used an old token "
                     "email?"))
                raise PermissionDenied(_("invalid sign-in token"))

            if not user.is_active:
                messages.add_message(request, messages.ERROR,
                        _("Account disabled."))
                raise PermissionDenied(_("invalid sign-in token"))

            user.set_password(form.cleaned_data["password"])
            user.save()

            login(request, user)

            if (not (user.first_name and user.last_name)
                    or "to_profile" in request.GET):
                messages.add_message(request, messages.INFO,
                        _("Successfully signed in. "
                        "Please complete your registration information below."))

                return redirect(
                       reverse("relate-user_profile")+"?first_login=1")
            else:
                messages.add_message(request, messages.INFO,
                        _("Successfully signed in."))

                return redirect("relate-home")
    else:
        form = ResetPasswordStage2Form()

    return render(request, "generic-form.html", {
        "form_description":
            _("Password reset on %(site_name)s")
            % {"site_name": _(get_site_name())},
        "form": form
        })

# }}}


# {{{ email sign-in flow

class SignInByEmailForm(StyledForm):
    email = forms.EmailField(required=True, label=_("Email"),
            # For now, until we upgrade to a custom user model.
            max_length=User._meta.get_field('email').max_length)

    def __init__(self, *args, **kwargs):
        super(SignInByEmailForm, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit", _("Send sign-in email")))


@logout_confirmation_required
def sign_in_by_email(request):
    if not settings.RELATE_SIGN_IN_BY_EMAIL_ENABLED:
        messages.add_message(request, messages.ERROR,
                _("Email-based sign-in is not being used"))
        return redirect("relate-sign_in_choice")

    if request.method == 'POST':
        form = SignInByEmailForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            user, created = get_user_model().objects.get_or_create(
                    email__iexact=email,
                    defaults=dict(username=email, email=email))

            if created:
                user.set_unusable_password()

            user.status = user_status.unconfirmed,
            user.sign_in_key = make_sign_in_key(user)
            user.save()

            from relate.utils import render_email_template
            message = render_email_template("course/sign-in-email.txt", {
                "user": user,
                "sign_in_uri": request.build_absolute_uri(
                    reverse(
                        "relate-sign_in_stage2_with_token",
                        args=(user.id, user.sign_in_key,))),
                "home_uri": request.build_absolute_uri(reverse("relate-home"))
                })
            from django.core.mail import EmailMessage
            msg = EmailMessage(
                    _("Your %(relate_site_name)s sign-in link")
                    % {"relate_site_name": _(get_site_name())},
                    message,
                    getattr(settings, "NO_REPLY_EMAIL_FROM",
                            settings.ROBOT_EMAIL_FROM),
                    [email])

            from relate.utils import get_outbound_mail_connection
            msg.connection = (
                get_outbound_mail_connection("no_reply")
                if hasattr(settings, "NO_REPLY_EMAIL_FROM")
                else get_outbound_mail_connection("robot"))
            msg.send()

            messages.add_message(request, messages.INFO,
                    _("Email sent. Please check your email and click the link."))

            return redirect("relate-home")
    else:
        form = SignInByEmailForm()

    return render(request, "course/login-by-email.html", {
        "form_description": "",
        "form": form
        })


@logout_confirmation_required
def sign_in_stage2_with_token(request, user_id, sign_in_key):
    if not settings.RELATE_SIGN_IN_BY_EMAIL_ENABLED:
        messages.add_message(request, messages.ERROR,
                _("Email-based sign-in is not being used"))
        return redirect("relate-sign_in_choice")

    from django.contrib.auth import authenticate, login
    user = authenticate(user_id=int(user_id), token=sign_in_key)
    if user is None:
        if not get_user_model().objects.filter(pk=int(user_id)).count():
            messages.add_message(request, messages.ERROR,
                _("Account does not exist."))
        else:
            messages.add_message(request, messages.ERROR,
                    _("Invalid sign-in token. Perhaps you've used an old "
                    "token email?"))
        raise PermissionDenied(_("invalid sign-in token"))

    if not user.is_active:
        messages.add_message(request, messages.ERROR,
                _("Account disabled."))
        raise PermissionDenied(_("invalid sign-in token"))

    login(request, user)

    if not (user.first_name and user.last_name):
        messages.add_message(request, messages.INFO,
                _("Successfully signed in. "
                "Please complete your registration information below."))

        return redirect(
               reverse("relate-user_profile")+"?first_login=1")
    else:
        messages.add_message(request, messages.INFO,
                _("Successfully signed in."))

        return redirect("relate-home")

# }}}


# {{{ user profile

def is_inst_id_editable_before_validation():
    # type: () -> bool
    return getattr(
        settings, "RELATE_EDITABLE_INST_ID_BEFORE_VERIFICATION", True)


class UserForm(StyledModelForm):
    institutional_id_confirm = forms.CharField(
            max_length=100,
            label=_("Institutional ID Confirmation"),
            required=False)

    class Meta:
        model = get_user_model()
        fields = ("first_name", "last_name", "institutional_id",
                "editor_mode")

    def __init__(self, *args, **kwargs):
        self.is_inst_id_locked = kwargs.pop('is_inst_id_locked')
        super(UserForm, self).__init__(*args, **kwargs)

        if self.instance.name_verified:
            self.fields["first_name"].disabled = True
            self.fields["last_name"].disabled = True

        if self.is_inst_id_locked:
            self.fields["institutional_id"].disabled = True
            self.fields["institutional_id_confirm"].disabled = True
        else:
            self.fields["institutional_id_confirm"].initial = (
                self.instance.institutional_id)

        self.fields["institutional_id"].help_text = (
                _("The unique ID your university or school provided, "
                    "which may be used by some courses to verify "
                    "eligibility to enroll. "
                    "<b>Once %(submitted_or_verified)s, it cannot be "
                    "changed</b>.")
                % {"submitted_or_verified":
                   is_inst_id_editable_before_validation()
                   and _("verified") or _("submitted")})

        # {{ build layout
        name_fields_layout = ["last_name", "first_name"]
        fields_layout = [Div(*name_fields_layout, css_class="well")]

        if getattr(settings, "RELATE_SHOW_INST_ID_FORM", True):
            inst_field_group_layout = ["institutional_id"]
            if not self.is_inst_id_locked:
                inst_field_group_layout.append("institutional_id_confirm")
            fields_layout.append(Div(*inst_field_group_layout, css_class="well",
                                     css_id="institutional_id_block"))
        else:
            # This is needed for django-crispy-form version < 1.7
            self.fields["institutional_id"].widget = forms.HiddenInput()

        if getattr(settings, "RELATE_SHOW_EDITOR_FORM", True):
            fields_layout.append(Div("editor_mode", css_class="well"))
        else:
            # This is needed for django-crispy-form version < 1.7
            self.fields["editor_mode"].widget = forms.HiddenInput()

        self.helper.layout = Layout(*fields_layout)

        self.helper.add_input(
                Submit("submit_user", _("Update")))

        self.helper.add_input(
                Button("signout", _("Sign out"), css_class="btn btn-danger",
                       onclick=(
                           "window.location.href='%s'"
                           % reverse("relate-logout"))))
        # }}}

    def clean_institutional_id_confirm(self):
        inst_id_confirmed = self.cleaned_data.get("institutional_id_confirm")

        if not self.is_inst_id_locked:
            inst_id = self.cleaned_data.get("institutional_id")
            if inst_id and not inst_id_confirmed:
                raise forms.ValidationError(_("This field is required."))
            if any([inst_id, inst_id_confirmed]) and inst_id != inst_id_confirmed:
                raise forms.ValidationError(_("Inputs do not match."))
        return inst_id_confirmed


@login_required
def user_profile(request):
    user_form = None

    def is_inst_id_locked(user):
        if is_inst_id_editable_before_validation():
            return True if (user.institutional_id
                    and user.institutional_id_verified) else False
        else:
            return True if user.institutional_id else False

    def is_requesting_inst_id():
        return not is_inst_id_locked(request.user) and (
            request.GET.get("first_login")
            or (request.GET.get("set_inst_id")
                and request.GET.get("referer")))

    if request.method == "POST":
        if "submit_user" in request.POST:
            user_form = UserForm(
                    request.POST,
                    instance=request.user,
                    is_inst_id_locked=is_inst_id_locked(request.user),
            )
            if user_form.is_valid():
                if user_form.has_changed():
                    user_form.save()
                    messages.add_message(request, messages.SUCCESS,
                            _("Profile data updated."))
                    request.user.refresh_from_db()

                else:
                    messages.add_message(request, messages.INFO,
                            _("No change was made on your profile."))

                if request.GET.get("first_login"):
                    return redirect("relate-home")

                if (request.GET.get("set_inst_id")
                        and request.GET.get("referer")):
                    return redirect(request.GET["referer"])

                user_form = UserForm(
                    instance=request.user,
                    is_inst_id_locked=is_inst_id_locked(request.user),
                )

    if user_form is None:
        request.user.refresh_from_db()
        user_form = UserForm(
            instance=request.user,
            is_inst_id_locked=is_inst_id_locked(request.user),
        )

    return render(request, "user-profile-form.html", {
        "form": user_form,
        "form_description": _("User Profile"),
        "is_requesting_inst_id": is_requesting_inst_id(),
        "enable_profile_form_js": (
            not is_inst_id_locked(request.user)
            and getattr(settings, "RELATE_SHOW_INST_ID_FORM", True))
        })

# }}}


# {{{ SAML auth backend

# This ticks the 'verified' boxes once we've receive attribute assertions
# through SAML2.

class Saml2Backend(Saml2BackendBase):
    def _set_attribute(self, obj, attr, value):
        mod = super(Saml2Backend, self)._set_attribute(obj, attr, value)

        if attr == "institutional_id":
            if not obj.institutional_id_verified:
                obj.institutional_id_verified = True
                mod = True

        if attr in ["first_name", "last_name"]:
            if not obj.name_verified:
                obj.name_verified = True
                mod = True

        if attr == "email":
            from course.constants import user_status
            if obj.status != user_status.active:
                obj.status = user_status.active
                mod = True

        return mod

# }}}


# {{{ sign-out

def sign_out_confirmation(request, redirect_field_name=REDIRECT_FIELD_NAME):
    if not request.user.is_authenticated:
        messages.add_message(request, messages.ERROR,
                             _("You've already signed out."))
        return redirect("relate-home")

    redirect_to = request.POST.get(redirect_field_name,
                                   request.GET.get(redirect_field_name, ''))

    next_uri = ""
    if redirect_to:
        next_uri = "?%s=%s" % (redirect_field_name, redirect_to)

    return render(request, "sign-out-confirmation.html",
                  {"next_uri": next_uri})


@never_cache
def sign_out(request, redirect_field_name=REDIRECT_FIELD_NAME):
    if not request.user.is_authenticated:
        messages.add_message(request, messages.ERROR,
                             _("You've already signed out."))
        return redirect("relate-home")

    redirect_to = request.POST.get(redirect_field_name,
                                   request.GET.get(redirect_field_name, ''))
    response = None

    if settings.RELATE_SIGN_IN_BY_SAML2_ENABLED:
        from djangosaml2.views import _get_subject_id, logout as saml2_logout
        if _get_subject_id(request.session) is not None:
            response = saml2_logout(request)

    auth_logout(request)

    if response is not None:
        return response
    elif redirect_to:
        return redirect(redirect_to)
    else:
        return redirect("relate-home")

# }}}


# {{{ API auth

class APIError(Exception):
    pass


def find_matching_token(
        course_identifier=None, token_id=None, token_hash_str=None,
        now_datetime=None):
    try:
        token = AuthenticationToken.objects.get(
                id=token_id,
                participation__course__identifier=course_identifier)
    except AuthenticationToken.DoesNotExist:
        return None

    from django.contrib.auth.hashers import check_password
    if not check_password(token_hash_str, token.token_hash):
        return None

    if token.revocation_time is not None:
        return None
    if token.valid_until is not None and now_datetime > token.valid_until:
        return None

    return token


class APIBearerTokenBackend(object):
    def authenticate(self, request, course_identifier=None, token_id=None,
            token_hash_str=None, now_datetime=None):
        token = find_matching_token(course_identifier, token_id, token_hash_str,
                now_datetime)
        if token is None:
            return None

        token.last_use_time = now_datetime
        token.save()

        return token.user

    def get_user(self, user_id):
        try:
            return get_user_model().objects.get(pk=user_id)
        except get_user_model().DoesNotExist:
            return None


AUTH_HEADER_RE = re.compile("^Token ([0-9]+)_([a-z0-9]+)$")


class APIContext(object):
    def __init__(self, request, token):
        self.request = request

        self.token = token
        self.participation = token.participation
        self.course = self.participation.course

        restrict_to_role = token.restrict_to_participation_role
        if restrict_to_role is not None:
            role_restriction_ok = False

            if restrict_to_role in token.participation.roles.all():
                role_restriction_ok = True

            if not role_restriction_ok and self.participation.has_permission(
                    pperm.impersonate_role, restrict_to_role.identifier):
                role_restriction_ok = True

            if not role_restriction_ok:
                raise PermissionDenied(
                        "API token specifies invalid role restriction")

        self.restrict_to_role = restrict_to_role

    def has_permission(self, perm, argument=None):
        # type: (Text, Optional[Text]) -> bool
        if self.restrict_to_role is None:
            return self.participation.has_permission(perm, argument)
        else:
            return self.restrict_to_role.has_permission(perm, argument)


def with_course_api_auth(f):
    def wrapper(request, course_identifier, *args, **kwargs):
        from django.utils.timezone import now
        now_datetime = now()

        try:
            auth_header = request.META.get("HTTP_AUTHORIZATION", None)
            if auth_header is None:
                raise PermissionDenied("No Authorization header provided")

            match = AUTH_HEADER_RE.match(auth_header)
            if match is None:
                raise PermissionDenied("ill-formed Authorization header")

            auth_data = dict(
                    course_identifier=course_identifier,
                    token_id=int(match.group(1)),
                    token_hash_str=match.group(2),
                    now_datetime=now_datetime)

            # FIXME: Redundant db roundtrip
            token = find_matching_token(**auth_data)
            if token is None:
                raise PermissionDenied("invalid authentication token")

            from django.contrib.auth import authenticate, login
            user = authenticate(**auth_data)

            assert user is not None

            login(request, user)

            response = f(
                    APIContext(request, token),
                    course_identifier, *args, **kwargs)
        except PermissionDenied as e:
            return http.HttpResponseForbidden(
                    "403 Forbidden: " + str(e))
        except APIError as e:
            return http.HttpResponseBadRequest(
                    "400 Bad Request: " + str(e))

        return response

    from functools import update_wrapper
    update_wrapper(wrapper, f)

    return wrapper

# }}}


# {{{ manage API auth tokens

class AuthenticationTokenForm(StyledModelForm):
    class Meta:
        model = AuthenticationToken
        fields = (
                "restrict_to_participation_role",
                "description",
                "valid_until",
                )

        widgets = {
                "valid_until": DateTimePicker(options={"format": "YYYY-MM-DD"})
                }

    def __init__(self, participation, *args, **kwargs):
        # type: (Participation, *Any, **Any) -> None
        super(AuthenticationTokenForm, self).__init__(*args, **kwargs)
        self.participation = participation

        allowable_role_ids = (
                set(role.id for role in participation.roles.all())
                | set(
                        prole.id
                        for prole in ParticipationRole.objects.filter(
                            course=participation.course)
                        if participation.has_permission(
                            pperm.impersonate_role, prole.identifier))
                )

        self.fields["restrict_to_participation_role"].queryset = (
                ParticipationRole.objects.filter(
                    id__in=list(allowable_role_ids)
                    ))

        self.helper.add_input(Submit("create", _("Create")))


@course_view
def manage_authentication_tokens(pctx):
    # type: (http.HttpRequest) -> http.HttpResponse

    request = pctx.request

    if not request.user.is_authenticated:
        raise PermissionDenied()

    from course.views import get_now_or_fake_time
    now_datetime = get_now_or_fake_time(request)

    if request.method == 'POST':
        form = AuthenticationTokenForm(pctx.participation, request.POST)

        revoke_prefix = "revoke_"
        revoke_post_args = [key for key in request.POST if key.startswith("revoke_")]

        if revoke_post_args:
            token_id = int(revoke_post_args[0][len(revoke_prefix):])

            auth_token = get_object_or_404(AuthenticationToken,
                    id=token_id,
                    user=request.user)

            auth_token.revocation_time = now_datetime
            auth_token.save()

            form = AuthenticationTokenForm(pctx.participation)

        elif "create" in request.POST:
            if form.is_valid():
                token = make_sign_in_key(request.user)

                from django.contrib.auth.hashers import make_password
                auth_token = AuthenticationToken(
                        user=pctx.request.user,
                        participation=pctx.participation,
                        restrict_to_participation_role=form.cleaned_data[
                            "restrict_to_participation_role"],
                        description=form.cleaned_data["description"],
                        valid_until=form.cleaned_data["valid_until"],
                        token_hash=make_password(token))
                auth_token.save()

                user_token = "%d_%s" % (auth_token.id, token)

                messages.add_message(request, messages.SUCCESS,
                        _("A new authentication token has been created: %s. "
                            "Please save this token, as you will not be able "
                            "to retrieve it later.")
                        % user_token)
        else:
            messages.add_message(request, messages.ERROR,
                    _("Could not find which button was pressed."))

    else:
        form = AuthenticationTokenForm(pctx.participation)

    from django.db.models import Q

    from datetime import timedelta
    tokens = AuthenticationToken.objects.filter(
            user=request.user,
            participation__course=pctx.course,
            ).filter(
                Q(revocation_time=None)
                | Q(revocation_time__gt=now_datetime - timedelta(weeks=1)))

    return render_course_page(pctx, "course/manage-auth-tokens.html", {
        "form": form,
        "new_token_message": "",
        "tokens": tokens,
        })

# }}}

# vim: foldmethod=marker
