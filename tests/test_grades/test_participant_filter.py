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

import csv
from html.parser import HTMLParser
from io import StringIO
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from course.constants import ParticipationPermission as PPerm, ParticipationStatus
from course.gradebook import get_gradebook_participations, stats_only_participants
from course.grades import get_grade_table
from course.models import (
    FlowSession,
    GradingOpportunity,
    ParticipationPermission,
    ParticipationRole,
    ParticipationRolePermission,
)
from tests import factories
from tests.base_test_mixins import SingleCoursePageTestMixin


if TYPE_CHECKING:
    from django.http import HttpResponse


FILTER = "stats_only_participants"
FILTER_VALUES = (None, "1", "0")


def filter_query(value: str | None) -> dict[str, str]:
    return {} if value is None else {FILTER: value}


class LinkParser(HTMLParser):
    def __init__(self, content: bytes):
        super().__init__()
        self.links: list[str] = []
        self.feed(content.decode())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag == "a":
            href = dict(attrs).get("href")
            if href is not None:
                self.links.append(href)


class ParticipantFilterHelperTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.course = factories.CourseFactory()
        cls.roles = [
            ParticipationRole.objects.create(course=cls.course, identifier=identifier)
            for identifier in ("statistics-null", "statistics-empty", "other")
        ]
        for role, argument in zip(cls.roles[:2], (None, ""), strict=True):
            ParticipationRolePermission.objects.create(
                role=role, permission=PPerm.included_in_grade_statistics,
                argument=argument)

        cls.role_only = factories.ParticipationFactory(
            course=cls.course, roles=[cls.roles[0]])
        cls.individual_only = factories.ParticipationFactory(
            course=cls.course, roles=[cls.roles[2]])
        cls.no_roles = factories.ParticipationFactory(course=cls.course)
        cls.no_roles.roles.clear()
        cls.overlapping = factories.ParticipationFactory(
            course=cls.course, roles=cls.roles)
        for participation, argument in (
                (cls.individual_only, None), (cls.no_roles, ""),
                (cls.overlapping, None), (cls.overlapping, "")):
            ParticipationPermission.objects.create(
                participation=participation,
                permission=PPerm.included_in_grade_statistics, argument=argument)

        cls.excluded = factories.ParticipationFactory(
            course=cls.course, roles=[cls.roles[2]])
        cls.dropped = factories.ParticipationFactory(
            course=cls.course, roles=[cls.roles[0]],
            status=ParticipationStatus.dropped)
        cls.other_course = factories.CourseFactory(identifier="other-course")
        cls.other_participation = factories.ParticipationFactory(
            course=cls.other_course)
        ParticipationPermission.objects.create(
            participation=cls.other_participation,
            permission=PPerm.included_in_grade_statistics)

    def test_only_literal_zero_disables_filter(self):
        factory = RequestFactory()
        for value in (*FILTER_VALUES, "", "false", "00", "unexpected"):
            with self.subTest(value=value):
                request = factory.get("/", filter_query(value))
                self.assertEqual(stats_only_participants(request), value != "0")

    def test_role_and_individual_permissions_are_a_union_without_duplicates(self):
        self.assertCountEqual(
            get_gradebook_participations(self.course),
            [self.role_only, self.individual_only, self.no_roles,
             self.overlapping, self.dropped])

    def test_unfiltered_participations_still_belong_to_course(self):
        self.assertCountEqual(
            get_gradebook_participations(self.course, stats_only=False),
            [self.role_only, self.individual_only, self.no_roles,
             self.overlapping, self.excluded, self.dropped])

    def test_permission_arguments_do_not_grant_argumentless_permission(self):
        for permission_model, owner in (
                (ParticipationRolePermission, {"role": self.roles[2]}),
                (ParticipationPermission, {"participation": self.excluded})):
            with self.subTest(permission_model=permission_model.__name__):
                permission = permission_model.objects.create(
                    **owner, permission=PPerm.included_in_grade_statistics,
                    argument="not-an-argumentless-permission")
                self.assertNotIn(
                    self.excluded, get_gradebook_participations(self.course))
                permission.delete()

    def test_grade_table_defaults_to_filtered_active_participations(self):
        for value in (None, True, False):
            with self.subTest(stats_only=value):
                args = () if value is None else (value,)
                participations, _opportunities, rows = get_grade_table(
                    self.course, *args)
                expected = [self.role_only, self.individual_only,
                            self.no_roles, self.overlapping]
                if value is False:
                    expected.append(self.excluded)
                self.assertEqual(participations, sorted(expected, key=lambda p: p.pk))
                self.assertEqual(len(rows), len(expected))


class ParticipantFilterViewTests(SingleCoursePageTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Exercise individual permission inclusion for a non-student role.
        ParticipationPermission.objects.create(
            participation=cls.ta_participation,
            permission=PPerm.included_in_grade_statistics)
        cls.sessions = {}
        client = Client()
        for participation in (cls.instructor_participation,
                              cls.student_participation, cls.ta_participation):
            client.force_login(participation.user)
            cls.start_flow(client, cls.flow_id)
            cls.end_flow(client)
            cls.sessions[participation.pk] = FlowSession.objects.get(
                pk=cls.default_flow_params["flow_session_id"])
        cls.opportunity = GradingOpportunity.objects.get(course=cls.course)
        cls.dropped = factories.ParticipationFactory(
            course=cls.course, roles=list(cls.student_participation.roles.all()),
            status=ParticipationStatus.dropped)
        # Make username ordering differ from both ID and real-name ordering.
        for participation, username, last_name in (
                (cls.instructor_participation, "z-instructor", "A"),
                (cls.student_participation, "c-student", "B"),
                (cls.ta_participation, "a-ta", "C"),
                (cls.dropped, "b-dropped", "D")):
            user = participation.user
            user.username = username
            user.last_name = last_name
            user.save()

    def setUp(self):
        super().setUp()
        self.client.force_login(self.instructor_participation.user)

    def list_urls(self):
        return [
            reverse("relate-view_participant_list", args=[self.course.identifier]),
            reverse("relate-view_gradebook", args=[self.course.identifier]),
            reverse("relate-view_grades_by_opportunity",
                    args=[self.course.identifier, self.opportunity.pk]),
        ]

    def expected_participations(
            self, value: str | None, *, include_dropped: bool = False):
        expected = [self.student_participation, self.ta_participation]
        if value == "0":
            expected.append(self.instructor_participation)
        if include_dropped:
            expected.append(self.dropped)
        return expected

    def assert_link(
            self, response: HttpResponse, path: str, query: dict[str, list[str]]):
        links = LinkParser(response.content).links
        self.assertTrue(any(
            urlsplit(link).path == path
            and parse_qs(urlsplit(link).query) == query
            for link in links), (path, query))

    def test_list_views_default_and_explicit_filter(self):
        for index, url in enumerate(self.list_urls()):
            for value in FILTER_VALUES:
                with self.subTest(url=url, value=value):
                    response = self.client.get(url, filter_query(value))
                    self.assertEqual(response.status_code, 200)
                    expected = self.expected_participations(
                        value, include_dropped=index == 0)
                    if index == 2:
                        actual = [p for p, _info in response.context["grade_table"]]
                        self.assertEqual(
                            response.context["total_sessions"], len(expected))
                        self.assertEqual(
                            response.context["finished_sessions"], len(expected))
                    else:
                        actual = response.context["participations"]
                    self.assertCountEqual(actual, expected)
                    if index == 1:
                        self.assertCountEqual(
                            [p for p, _row in response.context["grade_table"]],
                            expected)

    def test_list_views_preserve_username_order(self):
        for index, url in enumerate(self.list_urls()):
            for value in FILTER_VALUES:
                with self.subTest(url=url, value=value):
                    response = self.client.get(url, filter_query(value))
                    self.assertEqual(response.status_code, 200)
                    expected = sorted(self.expected_participations(
                        value, include_dropped=index == 0),
                        key=lambda p: p.user.username)
                    if index == 0:
                        actual = response.context["participations"]
                    else:
                        actual = [p for p, _info in response.context["grade_table"]]
                    self.assertEqual(actual, expected)
                    # DataTables must not replace server ordering on initialization.
                    self.assertContains(response, '"order": []')
                    links = [urlsplit(link).path
                             for link in LinkParser(response.content).links]
                    participant_paths = [reverse(
                        "relate-view_single_grade" if index == 2
                        else "relate-view_participant_grades",
                        args=[self.course.identifier, p.pk, self.opportunity.pk]
                        if index == 2 else [self.course.identifier, p.pk])
                        for p in expected]
                    # Opportunity rows also link to the same participant's overall
                    # grade; compare the first occurrence for each participant.
                    self.assertEqual(
                        sorted(participant_paths, key=links.index), participant_paths)

    def test_csv_default_and_explicit_filter(self):
        url = reverse("relate-export_gradebook_csv", args=[self.course.identifier])
        for value in FILTER_VALUES:
            with self.subTest(value=value):
                response = self.client.get(url, filter_query(value))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response["Content-Disposition"],
                    f'attachment; filename="grades-{self.course.identifier}.csv"')
                rows = list(csv.reader(StringIO(response.content.decode())))
                self.assertEqual(rows[0][:3], ["user_name", "last_name", "first_name"])
                self.assertEqual(rows[0][3:], [self.opportunity.identifier])
                self.assertCountEqual(
                    [row[0] for row in rows[1:]],
                    [p.user.username for p in self.expected_participations(value)])

    def test_toggle_preserves_other_query_parameters(self):
        for url in self.list_urls():
            for value in FILTER_VALUES:
                with self.subTest(url=url, value=value):
                    query = {"view_page_grades": "1", "search": "a & b",
                             "tag": ["first", "second"], **filter_query(value)}
                    response = self.client.get(url, query)
                    self.assertEqual(response.status_code, 200)
                    self.assertTemplateUsed(
                        response, "course/gradebook-participant-toggle.html")
                    self.assert_link(response, "", {
                        "view_page_grades": ["1"], "search": ["a & b"],
                        "tag": ["first", "second"],
                        FILTER: ["1" if value == "0" else "0"],
                    })

    def test_fixed_participant_views_have_no_filter_toggle(self):
        urls = [
            reverse("relate-view_participant_grades", args=[
                self.course.identifier, self.instructor_participation.pk]),
            reverse("relate-view_single_grade", args=[
                self.course.identifier, self.instructor_participation.pk,
                self.opportunity.pk]),
        ]
        for url in urls:
            for value in FILTER_VALUES:
                with self.subTest(url=url, value=value):
                    response = self.client.get(url, filter_query(value))
                    self.assertEqual(response.status_code, 200)
                    self.assertTemplateNotUsed(
                        response, "course/gradebook-participant-toggle.html")
                    self.assert_link(response, self.list_urls()[1], {})

    def test_menu_uses_default_filter_and_content_links_preserve_filter(self):
        opportunity_list_url = reverse(
            "relate-view_grading_opportunity_list", args=[self.course.identifier])
        csv_url = reverse("relate-export_gradebook_csv", args=[self.course.identifier])
        participant_url = reverse("relate-view_participant_grades", args=[
            self.course.identifier, self.student_participation.pk])
        single_grade_url = reverse("relate-view_single_grade", args=[
            self.course.identifier, self.student_participation.pk, self.opportunity.pk])
        for url in [*self.list_urls(), opportunity_list_url]:
            for value in FILTER_VALUES:
                with self.subTest(url=url, value=value):
                    response = self.client.get(url, filter_query(value))
                    self.assertEqual(response.status_code, 200)
                    query = {FILTER: [value or "1"]}
                    targets = [*self.list_urls()[:2], opportunity_list_url, csv_url]
                    for target in targets:
                        self.assert_link(response, target, {})
                    if url in (self.list_urls()[1], opportunity_list_url):
                        self.assert_link(response, self.list_urls()[2], query)
                    if url in self.list_urls()[:2]:
                        self.assert_link(response, participant_url, query)
                    if url in self.list_urls()[1:]:
                        self.assert_link(response, single_grade_url, query)

    def test_page_grade_view_filters_participants_and_propagates_filter(self):
        url = self.list_urls()[2]
        for value in FILTER_VALUES:
            with self.subTest(value=value):
                response = self.client.get(
                    url, {"view_page_grades": "1", **filter_query(value)})
                self.assertEqual(response.status_code, 200)
                self.assertCountEqual(
                    [p for p, _info in response.context["grade_table"]],
                    self.expected_participations(value))
                session = self.sessions[self.student_participation.pk]
                self.assert_link(response, self.get_page_grading_url_by_ordinal(
                    flow_session_id=session.pk, page_ordinal=0),
                    {FILTER: [value or "1"]})

    def test_next_previous_sessions_follow_participant_filter(self):
        for value in FILTER_VALUES:
            expected = sorted(self.expected_participations(value),
                              key=lambda p: p.user.username)
            sessions = [self.sessions[p.pk] for p in expected]
            for index, session in enumerate(sessions):
                with self.subTest(value=value, session=session.pk):
                    url = self.get_page_grading_url_by_ordinal(
                        flow_session_id=session.pk, page_ordinal=0)
                    response = self.client.get(url, filter_query(value))
                    self.assertEqual(response.status_code, 200)
                    previous = sessions[index-1].pk if index else None
                    following = (
                        sessions[index+1].pk if index+1 < len(sessions) else None)
                    self.assertEqual(response.context["prev_flow_session_id"], previous)
                    self.assertEqual(
                        response.context["next_flow_session_id"], following)
                    for target in (previous, following):
                        if target is not None:
                            self.assert_link(
                                response, self.get_page_grading_url_by_ordinal(
                                    flow_session_id=target, page_ordinal=0),
                                {FILTER: [value or "1"]})
