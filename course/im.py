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

from typing import Dict, List  # noqa

import django.forms as forms
import slixmpp
from asgiref.sync import async_to_sync
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from django.contrib import messages  # noqa
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render  # noqa
from django.utils.translation import gettext as _, pgettext_lazy

from course.constants import participation_permission as pperm
from course.models import Course  # noqa
from course.models import InstantMessage
from course.utils import course_view, render_course_page


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
                    pgettext_lazy("Send instant messages", "Send")))

        super().__init__(*args, **kwargs)


# based on https://slixmpp.readthedocs.io/en/latest/getting_started/sendlogout.html
class SendMsgBot(slixmpp.ClientXMPP):
    """
    A basic Slixmpp bot that will log in, send a message,
    and then log out.
    """

    def __init__(self, jid, password, recipient, message):
        slixmpp.ClientXMPP.__init__(self, jid, password)

        # The message we wish to send, and the JID that
        # will receive it.
        self.recipient = recipient
        self.msg = message

        # The session_start event will be triggered when
        # the bot establishes its connection with the server
        # and the XML streams are ready for use. We want to
        # listen for this event so that we we can initialize
        # our roster.
        self.add_event_handler("session_start", self.start)

    async def start(self, event):
        """
        Process the session_start event.

        Typical actions for the session_start event are
        requesting the roster and broadcasting an initial
        presence stanza.

        Arguments:
            event -- An empty dictionary. The session_start
                     event does not provide any additional
                     data.
        """
        self.send_presence()
        await self.get_roster()

        self.send_message(mto=self.recipient,
                          mbody=self.msg,
                          mtype="chat")

        self.disconnect()


@async_to_sync
async def _send_xmpp_msg(xmpp_id, password, recipient_xmpp_id, message):
    xmpp = SendMsgBot(
            xmpp_id, password, recipient_xmpp_id, message)
    xmpp.register_plugin("xep_0030")  # Service Discovery
    xmpp.register_plugin("xep_0199")  # XMPP Ping

    # Connect to the XMPP server and start processing XMPP stanzas.
    xmpp.connect()
    await xmpp.disconnected


@course_view
def send_instant_message(pctx):
    if not pctx.has_permission(pperm.send_instant_message):
        raise PermissionDenied(_("may not send instant message"))

    request = pctx.request
    course = pctx.course

    if not course.course_xmpp_id:
        messages.add_message(request, messages.ERROR,
                _("Instant messaging is not enabled for this course."))

        return redirect("relate-course_page", pctx.course_identifier)

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

                _send_xmpp_msg(
                    xmpp_id=course.course_xmpp_id,
                    password=course.course_xmpp_password,
                    recipient_xmpp_id=course.recipient_xmpp_id,
                    message=form.cleaned_data["message"])
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
        "form_description": _("Send instant message"),
    })

# }}}

# vim: foldmethod=marker
