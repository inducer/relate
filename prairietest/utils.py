from __future__ import annotations


__copyright__ = """
Copyright (C) 2024 University of Illinois Board of Trustees
Copyright (C) 2024 PrairieTest, Inc.
"""

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

The following license applies to the PrairieTest-derived code below:

Example Python code snippets on this page are provided by PrairieLearn, Inc. and are
released under the [CC0 1.0 Universal (CC0 1.0) Public Domain Dedication](
https://creativecommons.org/publicdomain/zero/1.0/). You may copy, modify, and
distribute these code snippets, even for commercial purposes, all without asking
permission and without attribution. The code snippets are provided as-is, without
any warranty, and PrairieLearn, Inc. disclaims all liability for any damages
resulting from their use.

(via a response from Matt West on the PrairieLearn Slack space.)
"""

import hashlib
import hmac
import time
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from functools import lru_cache
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_network
from zoneinfo import ZoneInfo

from django.db.models import Q

from course.models import Course
from prairietest.models import AllowEvent, DenyEvent, MostRecentDenyEvent


# {{{ begin code copied from PrairieTest docs

# Source:
# https://us.prairietest.com/pt/docs/api/exam-access
# Retrieved Sep 10, 2024
# included with light modifications (type annotation, linter conformance)

def check_signature(
            headers: Mapping[str, str],
            body: bytes,
            secret: str,
            *, now_timestamp: float | None = None,
        ) -> tuple[bool, str]:
    """Check the signature of a webhook event.

    Arguments:
    headers -- a dictionary of HTTP headers from the webhook request
    body -- the body of the webhook request (as a bytes object)
    secret -- the shared secret string

    Returns:
    A tuple (signature_ok, message) where signature_ok is True if the signature
    is valid, False otherwise,
    and message is a string describing the reason for the failure (if any).
    """
    if "PrairieTest-Signature" not in headers:
        return False, "Missing PrairieTest-Signature header"
    prairietest_signature = headers["PrairieTest-Signature"]

    # get the timestamp
    timestamp = None
    for block in prairietest_signature.split(","):
        if block.startswith("t="):
            timestamp = block[2:]
            break
    if timestamp is None:
        return False, "Missing timestamp in PrairieTest-Signature"

    # check the timestamp
    try:
        timestamp_val = int(timestamp)
    except ValueError:
        return False, "Invalid timestamp in PrairieTest-Signature"
    if now_timestamp is None:
        now_timestamp = time.time()
    if abs(timestamp_val - now_timestamp) > 3000:
        return False, "Timestamp in PrairieTest-Signature is too old or too new"

    # get the signature
    signature = None
    for block in prairietest_signature.split(","):
        if block.startswith("v1="):
            signature = block[3:]
            break
    if signature is None:
        return False, "Missing v1 signature in PrairieTest-Signature"

    # check the signature
    signed_payload = bytes(timestamp, "ascii") + b"." + body
    expected_signature = hmac.new(
            secret.encode("utf-8"), signed_payload, hashlib.sha256).digest().hex()
    if signature != expected_signature:
        return False, "Incorrect v1 signature in PrairieTest-Signature"

    # everything checks out
    return True, ""

# }}}


def has_access_to_exam(
            course: Course,
            user_uid: str,
            exam_uuid: str,
            now: datetime,
            ip_address: IPv4Address | IPv6Address
        ) -> None | AllowEvent:
    facility_id_to_most_recent_allow_event: dict[int, AllowEvent] = {}
    for allow_event in AllowEvent.objects.filter(
                facility__course=course,
                user_uid=user_uid,
                exam_uuid=exam_uuid
            ).order_by("created").prefetch_related("facility"):
        facility_id_to_most_recent_allow_event[
                allow_event.facility.id] = allow_event

    for allow_event in facility_id_to_most_recent_allow_event.values():
        if now < allow_event.start or allow_event.end < now:
            return None

        if any(
                ip_address in ip_network(cidr_block)
                for cidr_block in allow_event.cidr_blocks):
            return allow_event

    return None


def denials_at(
            now: datetime,
            course: Course | None = None,
        ) -> Sequence[DenyEvent]:
    qs = MostRecentDenyEvent.objects.all()
    if course is not None:
        qs = qs.filter(event__facility__course=course)

    return [
        mrde.event
        for mrde in qs.filter(
            Q(end__gte=now) & Q(event__start__lte=now)
        ).prefetch_related(
            "event",
            "event__facility",
            "event__facility__course")
    ]


def _get_denials_at(
            now_bucket: int,
            course_id: int | None,
        ) -> Mapping[tuple[int, str], Collection[IPv6Network | IPv4Network]]:
    from django.conf import settings
    tz = ZoneInfo(settings.TIME_ZONE)

    deny_events = denials_at(
        datetime.fromtimestamp(now_bucket, tz=tz),
        Course.objects.get(id=course_id) if course_id is not None else None,
    )
    result: dict[tuple[int, str], set[IPv6Network | IPv4Network]] = {}
    for devt in deny_events:
        result.setdefault(
            (devt.facility.course.id, devt.facility.identifier),
            set()
        ).update(ip_network(cidr_block) for cidr_block in devt.cidr_blocks)

    return result


_get_denials_at_cached = lru_cache(10)(_get_denials_at)


def denied_ip_networks_at(
            now: datetime | None = None,
            course: Course | None = None,
            cache: bool = True,
        ) -> Mapping[tuple[int, str], Collection[IPv6Network | IPv4Network]]:
    """
    :returns: a mapping from (course_id, test_facility_id) to a collection of
         networks.
    """
    if now is None:
        from django.utils import timezone
        now = timezone.now()

    if not cache:
        get_denials = _get_denials_at
    else:
        get_denials = _get_denials_at_cached

    return get_denials(
        int(now.timestamp() // 60) * 60,
        course.id if course else None,
        )
