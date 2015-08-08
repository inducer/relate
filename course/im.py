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

from django.utils.translation import (
        ugettext as _, pgettext_lazy)
from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.contrib import messages  # noqa
from django.core.exceptions import PermissionDenied
import django.forms as forms

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from course.models import (
        participation_role,
        InstantMessage)

from course.utils import course_view, render_course_page

import sleekxmpp

import threading


# {{{ instant message

class InstantMessageForm(forms.Form):
    message = forms.CharField(required=True, max_length=200,
            label=pgettext_lazy("Instant message", "Message"))

    def __init__(self, *args, **kwargs):
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        self.helper.add_input(
                Submit("submit",
                    # Translators: literals in this file are about
                    # the instant messaging function.
                    pgettext_lazy("Send instant messages", "Send"),
                    css_class="col-lg-offset-2"))

        super(InstantMessageForm, self).__init__(*args, **kwargs)


_xmpp_connections = {}
_disconnectors = []


class CourseXMPP(sleekxmpp.ClientXMPP):
    def __init__(self, jid, password, recipient_jid):
        sleekxmpp.ClientXMPP.__init__(self, jid, password)
        self.recipient_jid = recipient_jid

        self.add_event_handler("session_start", self.start)
        self.add_event_handler("changed_status", self.wait_for_presences)

        self.received = set()

        self.presences_received = threading.Event()

    def start(self, event):
        self.send_presence()
        self.get_roster()

    def is_recipient_online(self):
        groups = self.client_roster.groups()
        for group in groups:
            for jid in groups[group]:
                if jid != self.recipient_jid:
                    continue

                connections = self.client_roster.presence(jid)
                for res, pres in connections.items():
                    return True

        return False

    def wait_for_presences(self, pres):
        """
        Track how many roster entries have received presence updates.
        """
        self.received.add(pres['from'].bare)
        if len(self.received) >= len(self.client_roster.keys()):
            self.presences_received.set()
        else:
            self.presences_received.clear()


class Disconnector(object):
    def __init__(self, xmpp, course):
        self.timer = None
        self.xmpp = xmpp
        self.course = course

        self.timer = threading.Timer(60, self)
        self.timer.start()

    def __call__(self):
        # print "EXPIRING XMPP", self.course.pk
        del _xmpp_connections[self.course.pk]
        self.xmpp.disconnect(wait=True)
        _disconnectors.remove(self)


def get_xmpp_connection(course):
    try:
        return _xmpp_connections[course.pk]
    except KeyError:
        xmpp = CourseXMPP(
                course.course_xmpp_id,
                course.course_xmpp_password,
                course.recipient_xmpp_id)
        if xmpp.connect():
            xmpp.process()
        else:
            raise RuntimeError(_("unable to connect"))

        _xmpp_connections[course.pk] = xmpp

        xmpp.presences_received.wait(5)
        xmpp.is_recipient_online()

        _disconnectors.append(Disconnector(xmpp, course))

        return xmpp


@course_view
def send_instant_message(pctx):
    if pctx.role not in [
            participation_role.student,
            participation_role.teaching_assistant,
            participation_role.instructor]:
        raise PermissionDenied(_("only enrolled folks may do that"))

    request = pctx.request
    course = pctx.course

    if not course.course_xmpp_id:
        messages.add_message(request, messages.ERROR,
                _("Instant messaging is not enabled for this course."))

        return redirect("relate-course_page", pctx.course_identifier)

    xmpp = get_xmpp_connection(pctx.course)
    if xmpp.is_recipient_online():
        form_text = _("Recipient is <span class='label label-success'>"
                      "Online</span>.")
    else:
        form_text = _("Recipient is <span class='label label-danger'>"
                      "Offline</span>.")
    form_text = "<div class='well'>%s</div>" % form_text

    if request.method == "POST":
        form = InstantMessageForm(request.POST, request.FILES)
        if form.is_valid():
            msg = InstantMessage()
            msg.participation = pctx.participation
            msg.text = form.cleaned_data["message"]
            msg.save()

            try:
                if not course.recipient_xmpp_id:
                    raise RuntimeError(_("no recipient XMPP ID"))

                if not course.course_xmpp_password:
                    raise RuntimeError(_("no XMPP password"))

                xmpp.send_message(
                        mto=course.recipient_xmpp_id,
                        mbody=form.cleaned_data["message"],
                        mtype='chat')

            except Exception:
                from traceback import print_exc
                print_exc()

                messages.add_message(request, messages.ERROR,
                        _("An error occurred while sending the message. "
                          "Sorry."))
            else:
                messages.add_message(request, messages.SUCCESS,
                        _("Message sent."))
                form = InstantMessageForm()

    else:
        form = InstantMessageForm()

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_text": form_text,
        "form_description": _("Send instant message"),
    })

# }}}

# vim: foldmethod=marker
