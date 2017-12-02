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
                and not self.first_name or not self.last_name):
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

        from django.conf import settings
        format_method = getattr(
                settings,
                "RELATE_USER_FULL_NAME_FORMAT_METHOD",
                default_fullname)

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

        from django.conf import settings
        mask_method = getattr(
                settings,
                "RELATE_USER_PROFILE_MASK_METHOD",
                default_mask_method)

        return str(mask_method(self)).strip()

    def get_short_name(self):
        "Returns the short name for the user."
        return self.first_name

    def get_email_appellation(self):
        "Return the appellation of the receiver in email."
        from django.conf import settings

        # import the user defined priority list
        customized_priority_list = getattr(
                settings,
                "RELATE_EMAIL_APPELATION_PRIORITY_LIST", [])

        priority_list = []

        # filter out not allowd appellations in customized list
        for e in customized_priority_list:
            if e in ["first_name", "email", "username", "full_name"]:
                priority_list.append(e)

        # make sure the default appellations are included in case
        # user defined appellations are not available.
        for e in ["first_name", "email", "username"]:
            if e not in priority_list:
                priority_list.append(e)

        for attr in priority_list:
            if attr == "full_name":
                appellation = self.get_full_name(allow_blank=True)
            else:
                appellation = getattr(self, attr)

            if appellation:
                return appellation
            else:
                continue

        return _("user")

    def save(self, *args, **kwargs):
        # works around https://code.djangoproject.com/ticket/4136#comment:33
        self.institutional_id = self.institutional_id or None
        super(User, self).save(*args, **kwargs)

# }}}

# vim: foldmethod=marker
