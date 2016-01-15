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


from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils.translation import ugettext_lazy as _, pgettext_lazy
from django.utils import timezone
from django.contrib.auth.models import UserManager
from django.core import validators

from course.constants import USER_STATUS_CHOICES


# {{{ user

class User(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(
        _('username'),
        max_length=30,
        unique=True,
        help_text=_(
            'Required. 30 characters or fewer. Letters, digits and @/./+/-/_ only.'),
        validators=[
            validators.RegexValidator(
                r'^[\w.@+-]+$',
                _('Enter a valid username. This value may contain only '
                  'letters, numbers ' 'and @/./+/-/_ characters.')
            ),
        ],
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
            unique=True,
            verbose_name=_('Institutional ID'),
            blank=True, null=True, default=None)
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

    def get_full_name(self):
        """
        Returns the first_name plus the last_name, with a space in between.
        """
        full_name = '%s %s' % (self.first_name, self.last_name)
        return full_name.strip()

    def get_short_name(self):
        "Returns the short name for the user."
        return self.first_name

# }}}

# vim: foldmethod=marker
