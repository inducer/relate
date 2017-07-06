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

from typing import cast
from django.utils.translation import ugettext_lazy as _, string_concat
from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect, resolve_url)
from django.contrib import messages
import django.forms as forms
from django.core.exceptions import (PermissionDenied, SuspiciousOperation,
        ObjectDoesNotExist)
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit, Layout, Div
from django.conf import settings
from django.contrib.auth import (get_user_model, REDIRECT_FIELD_NAME,
        login as auth_login, logout as auth_logout)
from django.contrib.auth.forms import \
        AuthenticationForm as AuthenticationFormBase
from django.contrib.sites.shortcuts import get_current_site
from django.contrib.auth.decorators import user_passes_test
from django.urls import reverse
from django.contrib.auth.validators import ASCIIUsernameValidator
from django.utils.http import is_safe_url
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django import http  # noqa

from djangosaml2.backends import Saml2Backend as Saml2BackendBase

from course.constants import (
        user_status,
        participation_status,
        participation_permission as pperm,
        )
from course.models import Participation, Course  # noqa
from accounts.models import User

from relate.utils import StyledForm, StyledModelForm
from django_select2.forms import ModelSelect2Widget

if False:
    from typing import Any, Optional, Text  # noqa


# {{{ impersonation

def get_pre_impersonation_user(request):
    is_impersonating = hasattr(
            request, "relate_impersonate_original_user")
    if is_impersonating:
        return request.relate_impersonate_original_user
    return None


def may_impersonate(impersonator, impersonee):
    # type: (User, User) -> bool
    if impersonator.is_superuser:
        return True

    my_participations = Participation.objects.filter(
            user=impersonator,
            status=participation_status.active)

    for part in my_participations:
        # FIXME: if a TA is not allowed to view participants'
        # profile in one course, then he/she is not able to impersonate
        # any user, even in courses he/she is allow to view profiles
        # of all users.
        if part.has_permission(pperm.view_participant_masked_profile):
            return False
        impersonable_roles = [
                argument
                for perm, argument in part.permissions()
                if perm == pperm.impersonate_role]

        if Participation.objects.filter(
                course=part.course,
                status=participation_status.active,
                roles__identifier__in=impersonable_roles,
                user=impersonee).count():
            return True

    return False


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

            if impersonee is not None:
                if may_impersonate(cast(User, request.user), impersonee):
                    request.relate_impersonate_original_user = request.user
                    request.user = impersonee
                else:
                    messages.add_message(request, messages.ERROR,
                            _("Error while impersonating."))

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
        return (
            (
                # Translators: information displayed when selecting
                # userfor impersonating. Customize how the name is
                # shown, but leave email first to retain usability
                # of form sorted by last name.
                "%(full_name)s (%(username)s - %(email)s)"
                % {
                    "full_name": u.get_full_name(),
                    "email": u.email,
                    "username": u.username
                    }))


class ImpersonateForm(StyledForm):
    def __init__(self, *args, **kwargs):
        # type:(*Any, **Any) -> None

        super(ImpersonateForm, self).__init__(*args, **kwargs)

        self.fields["user"] = forms.ModelChoiceField(
                queryset=User.objects.order_by("last_name"),
                required=True,
                help_text=_("Select user to impersonate."),
                widget=UserSearchWidget(),
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

    if hasattr(request, "relate_impersonate_original_user"):
        messages.add_message(request, messages.ERROR,
                _("Already impersonating someone."))
        return redirect("relate-stop_impersonating")

    if request.method == 'POST':
        form = ImpersonateForm(request.POST)
        if form.is_valid():
            impersonee = form.cleaned_data["user"]

            if may_impersonate(cast(User, request.user), cast(User, impersonee)):
                request.session['impersonate_id'] = impersonee.id
                request.session['relate_impersonation_header'] = form.cleaned_data[
                        "add_impersonation_header"]

                # Because we'll likely no longer have access to this page.
                return redirect("relate-home")
            else:
                messages.add_message(request, messages.ERROR,
                        _("Impersonating that user is not allowed."))

    else:
        form = ImpersonateForm()

    return render(request, "generic-form.html", {
        "form_description": _("Impersonate user"),
        "form": form
        })


class StopImpersonatingForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.helper = FormHelper()
        super(StopImpersonatingForm, self).__init__(*args, **kwargs)

        self.helper.add_input(Submit("submit", _("Stop impersonating")))


def stop_impersonating(request):
    if not hasattr(request, "relate_impersonate_original_user"):
        messages.add_message(request, messages.ERROR,
                _("Not currently impersonating anyone."))
        return redirect("relate-home")

    if request.method == 'POST':
        form = StopImpersonatingForm(request.POST)
        if form.is_valid():
            messages.add_message(request, messages.INFO,
                    _("No longer impersonating anyone."))
            del request.session['impersonate_id']

            # Because otherwise the header will show stale data.
            return redirect("relate-home")
    else:
        form = StopImpersonatingForm()

    return render(request, "generic-form.html", {
        "form_description": _("Stop impersonating user"),
        "form": form
        })


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
    # Try to ensure these hashes aren't guessable.
    import random
    import hashlib
    from time import time
    m = hashlib.sha1()
    m.update(user.email.encode("utf-8"))
    m.update(hex(random.getrandbits(128)).encode())
    m.update(str(time()).encode("utf-8"))
    return m.hexdigest()


def check_sign_in_key(user_id, token):
    users = get_user_model().objects.filter(
            id=user_id, sign_in_key=token)

    assert users.count() <= 1
    if users.count() == 0:
        return False

    return True


class TokenBackend(object):
    def authenticate(self, user_id=None, token=None):
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

@user_passes_test(
        lambda user: not user.username,
        login_url='relate-logout-confirmation')
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
@user_passes_test(
        lambda user: not user.username,
        login_url='relate-logout-confirmation')
def sign_in_by_user_pw(request, redirect_field_name=REDIRECT_FIELD_NAME):
    """
    Displays the login form and handles the login action.
    """
    redirect_to = request.POST.get(redirect_field_name,
                                   request.GET.get(redirect_field_name, ''))

    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():

            # Ensure the user-originating redirection url is safe.
            if not is_safe_url(url=redirect_to, host=request.get_host()):
                redirect_to = resolve_url(settings.LOGIN_REDIRECT_URL)

            user = form.get_user()

            # Okay, security check complete. Log the user in.
            auth_login(request, user)

            return HttpResponseRedirect(redirect_to)
    else:
        form = LoginForm(request)

    current_site = get_current_site(request)

    next_uri = ""
    if redirect_to:
        next_uri = "?%s=%s" % (redirect_field_name, redirect_to)

    context = {
        'form': form,
        redirect_field_name: redirect_to,
        'site': current_site,
        'site_name': current_site.name,
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


@user_passes_test(
        lambda user: not user.username,
        login_url='relate-logout-confirmation')
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

            elif get_user_model().objects.filter(
                    email__iexact=form.cleaned_data["email"]).count():
                messages.add_message(request, messages.ERROR,
                        _("That email address is already in use. "
                        "Would you like to "
                        "<a href='%s'>reset your password</a> instead?")
                        % reverse(
                            "relate-reset_password")),
            else:
                email = form.cleaned_data["email"]
                user = get_user_model()(
                        email=email,
                        username=form.cleaned_data["username"])

                user.set_unusable_password()
                user.status = user_status.unconfirmed
                user.sign_in_key = make_sign_in_key(user)
                user.save()

                from django.template.loader import render_to_string
                message = render_to_string("course/sign-in-email.txt", {
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
                        string_concat("[", _("RELATE"), "] ",
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


@user_passes_test(
        lambda user: not user.username,
        login_url='relate-logout-confirmation')
def reset_password(request, field="email"):
    if not settings.RELATE_REGISTRATION_ENABLED:
        raise SuspiciousOperation(
                _("self-registration is not enabled"))

    # return form class by string of class name
    ResetPasswordForm = globals()["ResetPasswordFormBy" + field.title()]  # noqa
    if request.method == 'POST':
        form = ResetPasswordForm(request.POST)
        if form.is_valid():
            if field == "instid":
                inst_id = form.cleaned_data["instid"]
                try:
                    user = get_user_model().objects.get(
                            institutional_id__iexact=inst_id)
                except ObjectDoesNotExist:
                    user = None

            if field == "email":
                email = form.cleaned_data["email"]
                try:
                    user = get_user_model().objects.get(email__iexact=email)
                except ObjectDoesNotExist:
                    user = None

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
                    # happens when a user have an inst_id but have no email.
                    messages.add_message(request, messages.ERROR,
                            _("The account with that institution ID "
                                "doesn't have an associated email."))
                else:
                    email = user.email
                    user.sign_in_key = make_sign_in_key(user)
                    user.save()

                    from django.template.loader import render_to_string
                    message = render_to_string("course/sign-in-email.txt", {
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
                            string_concat("[", _("RELATE"), "] ",
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
            % {"site_name": _("RELATE")},
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


@user_passes_test(
        lambda user: not user.username,
        login_url='relate-logout-confirmation')
def reset_password_stage2(request, user_id, sign_in_key):
    if not settings.RELATE_REGISTRATION_ENABLED:
        raise SuspiciousOperation(
                _("self-registration is not enabled"))

    if not check_sign_in_key(user_id=int(user_id), token=sign_in_key):
        messages.add_message(request, messages.ERROR,
                _("Invalid sign-in token. Perhaps you've used an old token "
                "email?"))
        raise PermissionDenied(_("invalid sign-in token"))

    if request.method == 'POST':
        form = ResetPasswordStage2Form(request.POST)
        if form.is_valid():
            from django.contrib.auth import authenticate, login
            user = authenticate(user_id=int(user_id), token=sign_in_key)
            if user is None:
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
            % {"site_name": _("RELATE")},
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


@user_passes_test(
        lambda user: not user.username,
        login_url='relate-logout-confirmation')
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

            from django.template.loader import render_to_string
            message = render_to_string("course/sign-in-email.txt", {
                "user": user,
                "sign_in_uri": request.build_absolute_uri(
                    reverse(
                        "relate-sign_in_stage2_with_token",
                        args=(user.id, user.sign_in_key,))),
                "home_uri": request.build_absolute_uri(reverse("relate-home"))
                })
            from django.core.mail import EmailMessage
            msg = EmailMessage(
                    _("Your %(RELATE)s sign-in link") % {"RELATE": _("RELATE")},
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


@user_passes_test(
        lambda user: not user.username,
        login_url='relate-logout-confirmation')
def sign_in_stage2_with_token(request, user_id, sign_in_key):
    if not settings.RELATE_SIGN_IN_BY_EMAIL_ENABLED:
        messages.add_message(request, messages.ERROR,
                _("Email-based sign-in is not being used"))
        return redirect("relate-sign_in_choice")

    from django.contrib.auth import authenticate, login
    user = authenticate(user_id=int(user_id), token=sign_in_key)
    if user is None:
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

EDITABLE_INST_ID_BEFORE_VERIFICATION = \
        settings.RELATE_EDITABLE_INST_ID_BEFORE_VERIFICATION


class UserForm(StyledModelForm):
    institutional_id_confirm = forms.CharField(
            max_length=100,
            label=_("Institutional ID Confirmation"),
            required=False)
    no_institutional_id = forms.BooleanField(
            label=_("I have no Institutional ID"),
            help_text=_("Check the checkbox if you are not a student "
                        "or you forget your institutional id."),
            required=False,
            initial=False)

    class Meta:
        model = get_user_model()
        fields = ("first_name", "last_name", "institutional_id",
                "editor_mode")

    def __init__(self, *args, **kwargs):
        self.is_inst_id_locked = is_inst_id_locked =\
                kwargs.pop('is_inst_id_locked')
        super(UserForm, self).__init__(*args, **kwargs)

        self.helper.layout = Layout(
                Div("first_name", "last_name", css_class="well"),
                Div("institutional_id", css_class="well"),
                Div("editor_mode", css_class="well")
                )

        self.fields["institutional_id"].help_text = (
                _("The unique ID your university or school provided, "
                    "which may be used by some courses to verify "
                    "eligibility to enroll. "
                    "<b>Once %(submitted_or_verified)s, it cannot be "
                    "changed</b>.")
                % {"submitted_or_verified":
                    EDITABLE_INST_ID_BEFORE_VERIFICATION
                    and _("verified") or _("submitted")})

        def adjust_layout(is_inst_id_locked):
            if not is_inst_id_locked:
                self.helper.layout[1].insert(1, "institutional_id_confirm")
                self.helper.layout[1].insert(0, "no_institutional_id")
                self.fields["institutional_id_confirm"].initial = \
                        self.instance.institutional_id
            else:
                self.fields["institutional_id"].widget.\
                        attrs['disabled'] = True
            if not settings.RELATE_SHOW_INST_ID_FORM:
                self.helper.layout[1].css_class = 'well hidden'
            if not settings.RELATE_SHOW_EDITOR_FORM:
                self.helper.layout[2].css_class = 'well hidden'

        if self.instance.name_verified:
            self.fields["first_name"].widget.attrs['disabled'] = True
            self.fields["last_name"].widget.attrs['disabled'] = True

        adjust_layout(is_inst_id_locked)

        self.helper.add_input(
                Submit("submit_user", _("Update")))

    def clean_institutional_id(self):
        inst_id = self.cleaned_data['institutional_id'].strip()
        if self.is_inst_id_locked:
            # Disabled fields are not part of form submit--so simply
            # assume old value. At the same time, prevent smuggled-in
            # POST parameters.
            return self.instance.institutional_id
        else:
            return inst_id

    def clean_first_name(self):
        first_name = self.cleaned_data['first_name']
        if self.instance.name_verified:
            # Disabled fields are not part of form submit--so simply
            # assume old value. At the same time, prevent smuggled-in
            # POST parameters.
            return self.instance.first_name
        else:
            return first_name

    def clean_last_name(self):
        last_name = self.cleaned_data['last_name']
        if self.instance.name_verified:
            # Disabled fields are not part of form submit--so simply
            # assume old value. At the same time, prevent smuggled-in
            # POST parameters.
            return self.instance.last_name
        else:
            return last_name

    def clean_institutional_id_confirm(self):
        inst_id_confirmed = self.cleaned_data.get(
                "institutional_id_confirm")

        if not self.is_inst_id_locked:
            inst_id = self.cleaned_data.get("institutional_id")
            if inst_id and not inst_id_confirmed:
                raise forms.ValidationError(_("This field is required."))
            if not inst_id == inst_id_confirmed:
                raise forms.ValidationError(_("Inputs do not match."))
        return inst_id_confirmed


def user_profile(request):
    if not request.user.is_authenticated:
        raise PermissionDenied()

    user_form = None

    def is_inst_id_locked(user):
        if EDITABLE_INST_ID_BEFORE_VERIFICATION:
            return True if (user.institutional_id
                    and user.institutional_id_verified) else False
        else:
            return True if user.institutional_id else False

    if request.method == "POST":
        if "submit_user" in request.POST:
            user_form = UserForm(
                    request.POST,
                    instance=request.user,
                    is_inst_id_locked=is_inst_id_locked(request.user),
            )
            if user_form.is_valid():
                user_form.save()

                messages.add_message(request, messages.INFO,
                        _("Profile data saved."))
                if request.GET.get("first_login"):
                    return redirect("relate-home")
                if (request.GET.get("set_inst_id")
                        and request.GET["referer"]):
                    return redirect(request.GET["referer"])

                user_form = UserForm(
                        instance=request.user,
                        is_inst_id_locked=is_inst_id_locked(request.user))

    if user_form is None:
            user_form = UserForm(
                    instance=request.user,
                    is_inst_id_locked=is_inst_id_locked(request.user),
            )

    return render(request, "user-profile-form.html", {
        "is_inst_id_locked": is_inst_id_locked(request.user),
        "enable_inst_id_if_not_locked": (
            request.GET.get("first_login")
            or (request.GET.get("set_inst_id")
                and request.GET["referer"])
            ),
        "user_form": user_form,
        })

# }}}


# {{{ manage auth token

class AuthenticationTokenForm(StyledForm):
    def __init__(self, *args, **kwargs):
        # type: (*Any, **Any) -> None
        super(AuthenticationTokenForm, self).__init__(*args, **kwargs)

        self.helper.add_input(Submit("reset", _("Reset")))


def manage_authentication_token(request):
    # type: (http.HttpRequest) -> http.HttpResponse
    if not request.user.is_authenticated:
        raise PermissionDenied()

    if request.method == 'POST':
        form = AuthenticationTokenForm(request.POST)
        if form.is_valid():
            token = make_sign_in_key(request.user)
            from django.contrib.auth.hashers import make_password
            request.user.git_auth_token_hash = make_password(token)
            request.user.save()

            messages.add_message(request, messages.SUCCESS,
                    _("A new authentication token has been set: %s.")
                    % token)

    else:
        if request.user.git_auth_token_hash is not None:
            messages.add_message(request, messages.INFO,
                    _("An authentication token has previously been set."))
        else:
            messages.add_message(request, messages.INFO,
                    _("No authentication token has previously been set."))

        form = AuthenticationTokenForm()

    return render(request, "generic-form.html", {
        "form_description": _("Manage Git Authentication Token"),
        "form": form
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
    redirect_to = request.POST.get(redirect_field_name,
                                   request.GET.get(redirect_field_name, ''))

    next_uri = ""
    if redirect_to:
        next_uri = "?%s=%s" % (redirect_field_name, redirect_to)

    return render(request, "sign-out-confirmation.html",
                  {"next_uri": next_uri})


@never_cache
def sign_out(request, redirect_field_name=REDIRECT_FIELD_NAME):

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

# vim: foldmethod=marker
