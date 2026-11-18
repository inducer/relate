from __future__ import annotations


__copyright__ = "Copyright (C) 2026 University of Illinois Board of Trustees"

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

from typing import TYPE_CHECKING

from django.db.models import Q

from course.constants import ParticipationPermission as PPerm
from course.models import (
    Participation,
    ParticipationPermission,
    ParticipationRolePermission,
)


if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest

    from course.models import Course


def stats_only_participants(request: HttpRequest) -> bool:
    return request.GET.get("stats_only_participants") != "0"


def get_gradebook_participations(
        course: Course, stats_only: bool = True) -> QuerySet[Participation]:
    participations = Participation.objects.filter(course=course)
    if stats_only:
        # Permissions may be granted by roles or individually. Deduplicate
        # participants with multiple matching roles.
        role_permissions = ParticipationRolePermission.objects.filter(
                role__course=course,
                permission=PPerm.included_in_grade_statistics).filter(
                    Q(argument__isnull=True) | Q(argument=""))
        individual_permissions = ParticipationPermission.objects.filter(
                permission=PPerm.included_in_grade_statistics).filter(
                    Q(argument__isnull=True) | Q(argument=""))
        participations = participations.filter(
                Q(roles__in=role_permissions.values("role_id"))
                | Q(pk__in=individual_permissions.values("participation_id"))
                                ).distinct()
    return participations
