from __future__ import annotations


__copyright__ = "Copyright (C) 2024 University of Illinois Board of Trustees"

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

import json
from datetime import datetime

from django import http
from django.core.exceptions import BadRequest, SuspiciousOperation
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from prairietest.models import (
    AllowEvent,
    DenyEvent,
    Facility,
    save_deny_event,
)
from prairietest.utils import check_signature


@csrf_exempt
def webhook(
            request: http.HttpRequest,
            course_identifier: str,
            facility_id: str,
        ) -> http.HttpResponse:
    body = request.body

    facility = get_object_or_404(
                Facility,
                course__identifier=course_identifier,
                identifier=facility_id,
            )

    sig_valid, msg = check_signature(request.headers, body, facility.secret)
    if not sig_valid:
        raise SuspiciousOperation(f"Invalid PrairieTest signature: {msg}")

    event = json.loads(body)
    api_ver: str = event["api_version"]
    if api_ver != "2023-07-18":
        raise BadRequest(f"Unknown PrairieTest API version: {api_ver}")

    event_id: str = event["id"]
    if (
                AllowEvent.objects.filter(
                    facility=facility, event_id=event_id).exists()
                or DenyEvent.objects.filter(
                    facility=facility, event_id=event_id).exists()
            ):
        return http.HttpResponse(b"OK", content_type="text/plain", status=200)

    evt_type: str = event["type"]
    created = datetime.fromisoformat(event["created"])
    data = event["data"]

    del event

    if evt_type == "allow_access":
        user_uid: str = data["user_uid"]
        exam_uuid: str = data["exam_uuid"]

        has_newer_allows = AllowEvent.objects.filter(
            facility=facility,
            user_uid=user_uid,
            exam_uuid=exam_uuid,
            created__gte=created,
        ).exists()

        if not has_newer_allows:
            allow_evt = AllowEvent(
                facility=facility,
                event_id=event_id,
                created=created,
                user_uid=user_uid,
                user_uin=data["user_uin"],
                exam_uuid=exam_uuid,
                start=datetime.fromisoformat(data["start"]),
                end=datetime.fromisoformat(data["end"]),
                cidr_blocks=data["cidr_blocks"],
            )
            allow_evt.save()

        return http.HttpResponse(b"OK", content_type="text/plain", status=200)

    elif evt_type == "deny_access":
        deny_uuid = data["deny_uuid"]
        has_newer_denies = DenyEvent.objects.filter(
            facility=facility,
            deny_uuid=deny_uuid,
            created__gte=created,
        ).exists()

        if not has_newer_denies:
            deny_evt = DenyEvent(
                facility=facility,
                event_id=event_id,
                created=created,
                deny_uuid=deny_uuid,
                start=datetime.fromisoformat(data["start"]),
                end=datetime.fromisoformat(data["end"]),
                cidr_blocks=data["cidr_blocks"],
            )
            save_deny_event(deny_evt)

        return http.HttpResponse(b"OK", content_type="text/plain", status=200)
    else:
        raise BadRequest(f"Unknown PrairieTest event type: {evt_type}")
