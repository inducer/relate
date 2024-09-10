from __future__ import annotations


__copyright__ = """
Copyright (C) 2024 University of Illinois Board of Trustees
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

The license for the code marked as copied from the PrairieTest docs
is unknown.
"""


from datetime import timedelta
from ipaddress import ip_address
from uuid import uuid1

import pytest
from django.utils.timezone import now as tz_now

from course.models import Course
from prairietest.models import AllowEvent, DenyEvent, Facility, save_deny_event
from prairietest.utils import (
    check_signature,
    denied_ip_networks_at,
    has_access_to_exam,
)


# {{{ test signature checking against real-life PT data

_TEST_SIG_BODY = b"""{
  "id": "38f7057a-2e3a-477d-b325-addc2da1f07d",
  "api_version": "2023-07-18",
  "created": "2024-09-13T17:06:05.175Z",
  "type": "allow_access",
  "data": {
    "end": "2024-09-13T17:15:41.709Z",
    "start": "2024-09-13T17:00:41.709Z",
    "user_uid": "andreask@illinois.edu",
    "user_uin": "676896347",
    "exam_uuid": "d1936a77-341d-49ab-ac9b-1291afaaf87a",
    "cidr_blocks": [
      "0.0.0.0/0"
    ]
  }
}"""


def test_check_signature():
    valid, msg = check_signature(
        {"PrairieTest-Signature":
            "t=1726247206,"
            "v1=149ff0fbabc55558d081cbb64b61ef2248ba71e1d912bab7a19684f2b30afc31"
        },
        _TEST_SIG_BODY,
        secret="xADEAxO8RjRysTu9YN8olCk5ZcpVQwvoTpCNs4jD2sAzU4YR",
        now_timestamp=1726247206
    )
    assert valid
    assert not msg

# }}}


# {{{ fixtures

@pytest.fixture
def fix_course():
    course = Course(
        identifier="cs123-f24",
        name="Sample Course",
        number="CS123",
        time_period="Fall 2024",
        git_source="https://github.com/inducer/relate-sample.git",
        from_email="andreask@illinois.edu",
        notify_email="andreask@illinois.edu",
        active_git_commit_sha="abcabc",
    )
    course.save()
    return course


@pytest.fixture
def fix_facility(fix_course) -> Facility:
    tf = Facility(
        course=fix_course,
        identifier="cbtf",
        secret="abc123",
    )
    tf.save()
    return tf

# }}}


@pytest.mark.django_db
def test_allow_event_processing(fix_facility):
    course = fix_facility.course
    uid = "test@illinois.edu"
    exam1_uuid = str(uuid1())
    exam2_uuid = str(uuid1())
    now = tz_now()

    assert not has_access_to_exam(
                    course, uid, exam1_uuid, now, ip_address("192.168.123.32"))

    aevt = AllowEvent(
        facility=fix_facility,
        event_id=uuid1(),
        created=now,
        received_time=now,

        user_uid=uid,
        user_uin="1234",
        exam_uuid=exam1_uuid,
        start=now - timedelta(hours=1),
        end=now + timedelta(hours=1),
        cidr_blocks=["192.168.123.32/27"],
        )
    aevt.save()

    ip_addr = ip_address("192.168.123.32")

    assert has_access_to_exam(
            course, uid, exam1_uuid, now, ip_addr)
    assert has_access_to_exam(
            course, uid, exam1_uuid, now + timedelta(minutes=30),
            ip_addr)
    assert not has_access_to_exam(
            course, "joe@illinois.edu", exam1_uuid, now, ip_addr)
    assert not has_access_to_exam(
            course, uid, exam2_uuid, now, ip_addr)
    assert not has_access_to_exam(
            course, uid, exam1_uuid, now - timedelta(hours=2),
            ip_addr)
    assert not has_access_to_exam(
            course, uid, exam1_uuid, now + timedelta(hours=2),
            ip_addr)
    assert not has_access_to_exam(
            course, uid, exam1_uuid, now, ip_address("192.168.123.31"))

    # override for shorter duration
    aevt.pk = None
    aevt.created = now + timedelta(minutes=1)
    aevt.end = now + timedelta(minutes=10)
    aevt.save()

    assert has_access_to_exam(
            course, uid, exam1_uuid, now + timedelta(minutes=5),
            ip_addr)
    assert not has_access_to_exam(
            course, uid, exam1_uuid, now + timedelta(minutes=30),
            ip_addr)

    # no-op override from the past
    aevt.pk = None
    aevt.created = now - timedelta(minutes=1)
    aevt.end = now + timedelta(hours=1)
    aevt.save()

    assert has_access_to_exam(
            course, uid, exam1_uuid, now + timedelta(minutes=5),
            ip_addr)
    assert not has_access_to_exam(
            course, uid, exam1_uuid, now + timedelta(minutes=30),
            ip_addr)


@pytest.mark.django_db
def test_deny_event_processing(fix_facility):
    deny1_uuid = str(uuid1())
    now = tz_now()

    devt = DenyEvent(
        facility=fix_facility,
        event_id=uuid1(),
        created=now,
        received_time=now,

        deny_uuid=deny1_uuid,
        start=now - timedelta(hours=1),
        end=now + timedelta(hours=1),

        cidr_blocks=["192.168.123.32/27"],
    )
    save_deny_event(devt)

    from functools import partial
    denied_at = partial(denied_ip_networks_at, cache=False)

    assert denied_at(now)
    assert not denied_at(now + timedelta(hours=2))
    assert not denied_at(now - timedelta(hours=2))

    # no-op override from the past
    devt.pk = None
    devt.created = now - timedelta(minutes=1)
    devt.end = now + timedelta(minutes=30)
    save_deny_event(devt)

    # using never-asked query to avoid lru_cache
    assert denied_at(now + timedelta(minutes=40))

    # override from the future
    devt.pk = None
    devt.created = now + timedelta(minutes=1)
    devt.end = now + timedelta(minutes=30)
    save_deny_event(devt)

    assert not denied_at(now + timedelta(minutes=42))
