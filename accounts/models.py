# -*- coding: utf-8 -*-

from __future__ import division, unicode_literals

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


from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils.translation import ugettext_lazy as _, pgettext_lazy
from django.utils import timezone
from django.contrib.auth.models import UserManager
from django.contrib.auth.validators import ASCIIUsernameValidator

from course.constants import USER_STATUS_CHOICES


# {{{ user

class User(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(
        _('username'),
        max_length=30,
        unique=True,
        help_text=_(
            'Required. 30 characters or fewer. Letters, digits and @/./+/-/_ only.'),
        validators=[ASCIIUsernameValidator()],
        error_messages={
            'unique': _("A user with that username already exists."),
        },
    )
    first_name = models.CharField(_('first name'), max_length=100, blank=True)
    last_name = models.CharField(_('last name'), max_length=100, blank=True)
    email = models.EmailField(_('email address'), blank=True,
            max_length=100)
    name_verified = models.BooleanField(
        _('Name verified'),
        default=False,
        help_text=_(
            'Indicates that this user\'s name has been verified '
            'as being associated with the individual able to sign '
            'in to this account.'
        ),
    )
    is_active = models.BooleanField(
        pgettext_lazy("User status", "active"),
        default=True,
        help_text=_(
            'Designates whether this user should be treated as active. '
            'Unselect this instead of deleting accounts.'
        ),
    )
    date_joined = models.DateTimeField(_('date joined'), default=timezone.now)

    objects = UserManager()

    is_staff = models.BooleanField(
        _('staff status'),
        default=False,
        help_text=_('Designates whether the user can log into this admin site.'),
    )

    institutional_id = models.CharField(max_length=100,
            verbose_name=_('Institutional ID'),
            blank=True, null=True, unique=True, db_index=True)
    institutional_id_verified = models.BooleanField(
        _('Institutional ID verified'),
        default=False,
        help_text=_(
            'Indicates that this user\'s institutional ID has been verified '
            'as being associated with the individual able to log '
            'in to this account.'
        ),
    )
    status = models.CharField(max_length=50,
            choices=USER_STATUS_CHOICES,
            verbose_name=_('User status'),
            null=True)
    sign_in_key = models.CharField(max_length=50,
            help_text=_("The sign in token sent out in email."),
            null=True, unique=True, db_index=True, blank=True,
            # Translators: the sign in token of the user.
            verbose_name=_('Sign in key'))
    key_time = models.DateTimeField(default=None,
            null=True, blank=True,
            help_text=_("The time stamp of the sign in token."),
            # Translators: the time when the token is sent out.
            verbose_name=_('Key time'))

    editor_mode = models.CharField(max_length=20,
            help_text=_("Which key bindings you prefer when editing "
                        "larger amounts of text or code. "
                        "(If you do not understand what this means, "
                        "leave it as 'Default'.)"),
            choices=(
                ("default", _("Default")),
                ("sublime", "Sublime text"),
                ("emacs", "Emacs"),
                ("vim", "Vim"),
                ),
            default="default",
            # Translators: the text editor used by participants
            verbose_name=_("Editor mode"))

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']

    class Meta:
        verbose_name = _('user')
        verbose_name_plural = _('users')

    def get_full_name(self, allow_blank=True, force_verbose_blank=False):
        if (not allow_blank
                and (not self.first_name or not self.last_name)):
            return None

        def verbose_blank(s):
            if force_verbose_blank:
                if not s:
                    return _("(blank)")
                else:
                    return s
            return s

        def default_fullname(first_name, last_name):
            """
            Returns the first_name plus the last_name, with a space in
            between.
            """
            return '%s %s' % (
                verbose_blank(first_name), verbose_blank(last_name))

        from accounts.utils import relate_user_method_settings
        format_method = relate_user_method_settings.custom_full_name_method
        if format_method is None:
            format_method = default_fullname

        try:
            full_name = format_method(
                verbose_blank(self.first_name), verbose_blank(self.last_name))
        except Exception:
            full_name = default_fullname(
                verbose_blank(self.first_name), verbose_blank(self.last_name))

        return full_name.strip()

    def get_masked_profile(self):
        """
        Returns the masked user profile.
        """

        def default_mask_method(user):
            return "%s%s" % (_("User"), str(user.pk))

        from accounts.utils import relate_user_method_settings
        mask_method = relate_user_method_settings.custom_profile_mask_method
        if mask_method is None:
            mask_method = default_mask_method

        # Intentionally don't fallback if it failed -- let user see the exception.
        result = mask_method(self)
        if not result:
            raise RuntimeError("get_masked_profile should not return None.")
        else:
            result = str(result).strip()
        if not result:
            raise RuntimeError("get_masked_profile should not return "
                               "an empty string.")
        return result

    def get_short_name(self):
        "Returns the short name for the user."
        return self.first_name

    def get_email_appellation(self):
        "Return the appellation of the receiver in email."

        from accounts.utils import relate_user_method_settings
        priority_list = (
            relate_user_method_settings.email_appellation_priority_list)

        for attr in priority_list:
            if attr == "full_name":
                appellation = self.get_full_name(allow_blank=False)
            else:
                appellation = getattr(self, attr)

            if not appellation:
                continue

            return appellation

        return _("user")

    def clean(self):
        super(User, self).clean()

        # email can be None in Django admin when create new user
        if self.email is not None:
            self.email = self.email.strip()

        if self.email:
            qset = self.__class__.objects.filter(email__iexact=self.email)
            if self.pk is not None:
                # In case editing an existing user object
                qset = qset.exclude(pk=self.pk)
            if qset.exists():
                from django.core.exceptions import ValidationError
                raise ValidationError(
                    {"email": _("That email address is already in use.")})

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")

        # This is for backward compatibility.
        # Because user instances are frequently updated when auth_login,
        # reset_password. Without this, no user will be able to login.
        if ((update_fields is not None and "email" in update_fields)
                or self.pk is None):
            self.clean()

        if self.institutional_id is not None:
            self.institutional_id = self.institutional_id.strip()

        # works around https://code.djangoproject.com/ticket/4136#comment:33
        self.institutional_id = self.institutional_id or None
        super(User, self).save(*args, **kwargs)

# }}}

# vim: foldmethod=marker
