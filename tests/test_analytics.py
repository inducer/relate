from __future__ import annotations


__copyright__ = "Copyright (C) 2018 Dong Zhuang"

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
import re
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
from django.core.exceptions import ObjectDoesNotExist
from django.template.loader import render_to_string
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils.translation import override

from course import analytics
from course.models import FlowSession
from tests import factories
from tests.base_test_mixins import (
    CoursesTestMixinBase,
    HackRepoMixin,
    MockAddMessageMixing,
    SingleCourseQuizPageTestMixin,
    SingleCourseTestMixin,
)
from tests.utils import mock


def _dummy_histogram(*args):
    from course.analytics import Histogram
    hist = Histogram()
    hist.add_data_point(1)
    hist.add_data_point(2)
    return hist


@pytest.mark.slow
class FlowListTest(SingleCourseTestMixin, TestCase):
    """test analytics.flow_list"""
    def get_flow_list_url(self, course_identifier=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        kwargs = {"course_identifier": course_identifier}
        return reverse("relate-flow_list", kwargs=kwargs)

    def get_flow_list_view(self, course_identifier=None,
                           force_login_instructor=True):
        course_identifier = course_identifier or self.get_default_course_identifier()
        if not force_login_instructor:
            user = self.get_logged_in_user()
        else:
            user = self.instructor_participation.user

        with self.temporarily_switch_to_user(user):
            return self.client.get(
                self.get_flow_list_url(course_identifier))

    def test_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_flow_list_view(force_login_instructor=False)
            self.assertEqual(resp.status_code, 302)

    def test_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_flow_list_view(force_login_instructor=False)
            self.assertEqual(resp.status_code, 403)

    def test_result(self):
        flow_ids = ["c", "b", "a"]

        for flow_id in flow_ids:
            factories.FlowSessionFactory.create_batch(
                size=2,
                participation=self.student_participation,
                flow_id=flow_id)

        another_course = factories.CourseFactory(identifier="another-course")
        another_participation = factories.ParticipationFactory(course=another_course)

        # This make sure other courses' flow_id won't be included
        factories.FlowSessionFactory(participation=another_participation,
                                     flow_id="d")

        resp = self.get_flow_list_view()
        self.assertEqual(resp.status_code, 200)

        self.assertResponseContextEqual(resp, "flow_ids", sorted(flow_ids))


class HistogramTest(CoursesTestMixinBase, TestCase):
    """test analytics.Histogram (for cases not covered by other tests)"""
    def test_add_data_point_num_max_value(self):
        """self.num_max_value is not None and value > self.num_max_value"""
        his = analytics.Histogram(num_max_value=100)
        his.add_data_point(value=110, weight=1.1)
        self.assertEqual(his.string_weights["(value greater than max)"], 1.1)

    def test_add_data_point_num_min_value(self):
        """self.num_min_value is not None and value < self.num_min_value"""
        his = analytics.Histogram(num_min_value=60)
        his.add_data_point(value=50, weight=1.2)
        self.assertEqual(his.string_weights["(value smaller than min)"], 1.2)

    def test_get_bin_info_list_num_bin_starts_is_not_none(self):
        # just make sure it works
        his = analytics.Histogram(num_bin_starts=[2])
        his.get_bin_info_list()

    def test_get_bin_info_nothing_configured(self):
        # just make sure it works
        his = analytics.Histogram()
        his.get_bin_info_list()
        his.html()
        self.assertTemplateUsed("course/histogram-wide.html")

    def test_non_wide_html_template_render(self):
        his = analytics.Histogram()
        faked_get_bin_info_list = [analytics.BinInfo(
            title="foo"*30, raw_weight="bar", percentage=100)]
        with mock.patch(
                "course.analytics.Histogram.get_bin_info_list"
        ) as mock_get_bin_info_list:
            mock_get_bin_info_list.return_value = faked_get_bin_info_list

            his.html()
            self.assertTemplateUsed("course/histogram.html")


class PageAnswerStatsTest(CoursesTestMixinBase, TestCase):
    """Test JSON serialization on analytics.PageAnswerStats.statistics."""

    def _make_stats(self, quartile_correctness_list):
        return analytics.PageAnswerStats(
            group_id="grp",
            page_id="pg",
            title="Test",
            url=None,
            statistics=analytics.PageAnswerStatistics(
                average_correctness=0.5,
                average_credited_fraction=0.5,
                average_emptiness=0.1,
                average_wrongness=0.4,
                answer_count=5,
                total_count=6,
                graded_count=5,
                quartile_correctness_list=quartile_correctness_list,
            ),
        )

    def test_quartile_correctness_json_values(self):
        stats = self._make_stats([0.25, 0.5, 0.75, 1.0])
        parsed = json.loads(stats.statistics.quartile_correctness_json)
        self.assertEqual(parsed, [0.25, 0.5, 0.75, 1.0])

    def test_quartile_correctness_json_with_none(self):
        stats = self._make_stats([None, 0.5, None, 1.0])
        parsed = json.loads(stats.statistics.quartile_correctness_json)
        self.assertIsNone(parsed[0])
        self.assertEqual(parsed[1], 0.5)
        self.assertIsNone(parsed[2])
        self.assertEqual(parsed[3], 1.0)

    def test_quartile_correctness_json_all_none(self):
        stats = self._make_stats([None, None, None, None])
        parsed = json.loads(stats.statistics.quartile_correctness_json)
        self.assertEqual(parsed, [None, None, None, None])


@pytest.mark.parametrize("has_answer", [False, True], ids=["unanswered", "answered"])
@pytest.mark.parametrize("correctness", [0.0, 0.25, 1.0, 1.5, None])
def test_compute_page_answer_statistics_single_visit(
        has_answer: bool, correctness: float | None) -> None:
    visit = analytics.PageAnswerVisitData(
        has_answer=has_answer, correctness=correctness)
    assert visit.quartile is None

    stats = analytics.compute_page_answer_statistics([visit])

    assert isinstance(stats, analytics.PageAnswerStatistics)
    assert stats.total_count == 1
    assert stats.answer_count == int(has_answer)
    assert stats.graded_count == int(correctness is not None)
    assert stats.average_correctness == pytest.approx(
        correctness if correctness is not None else 0.0)
    credited = min(correctness, 1.0) if correctness is not None else 0.0
    uncredited = 1.0 - credited if correctness is not None else 0.0
    assert stats.average_credited_fraction == pytest.approx(credited)
    assert stats.average_emptiness == pytest.approx(
        0.0 if has_answer else uncredited)
    assert stats.average_wrongness == pytest.approx(
        uncredited if has_answer else 0.0)
    assert stats.quartile_correctness_list == [None, None, None, None]


@pytest.mark.parametrize("field,value", [
    ("has_answer", False),
    ("correctness", None),
    ("quartile", 3),
])
def test_page_answer_visit_data_is_frozen(
        field: str, value: bool | float | None) -> None:
    visit = analytics.PageAnswerVisitData(
        has_answer=True, correctness=0.5, quartile=0)
    with pytest.raises(FrozenInstanceError):
        setattr(visit, field, value)


@pytest.mark.parametrize((
    "visit_data,expected_score,expected_credit,expected_empty,expected_wrong,"
    "answer_count,graded_count"
), [
    pytest.param([], 0.0, 0.0, 0.0, 0.0, 0, 0, id="no-visits"),
    pytest.param(
        [(False, None), (True, None)],
        0.0, 0.0, 0.0, 0.0, 1, 0, id="no-graded-visits"),
    pytest.param(
        [(False, 0.0), (False, 0.5), (True, 0.0), (True, 0.5),
         (True, 1.0), (False, 1.5)],
        3.5 / 6, 0.5, 0.25, 0.25, 3, 6, id="mixed-population"),
    pytest.param(
        [(False, 0.5), (True, 0.0), (True, None), (False, None)],
        0.25, 0.25, 0.25, 0.5, 2, 2, id="unknowns-excluded-from-denominator"),
    pytest.param(
        [(False, 0.0), (True, 2.0)],
        1.0, 0.5, 0.5, 0.0, 1, 2, id="clip-before-average-answered-bonus"),
    pytest.param(
        [(True, 0.0), (False, 2.0)],
        1.0, 0.5, 0.0, 0.5, 1, 2, id="clip-before-average-unanswered-bonus"),
    pytest.param(
        [(False, 1.5), (True, 2.0)],
        1.75, 1.0, 0.0, 0.0, 1, 2, id="all-extra-credit"),
])
@pytest.mark.parametrize("as_iterator", [False, True], ids=["list", "iterator"])
def test_compute_page_answer_statistics_population(
        visit_data: list[tuple[bool, float | None]],
        expected_score: float, expected_credit: float, expected_empty: float,
        expected_wrong: float, answer_count: int, graded_count: int,
        as_iterator: bool) -> None:
    visits = [
        analytics.PageAnswerVisitData(has_answer=answered, correctness=score)
        for answered, score in visit_data
    ]
    stats = analytics.compute_page_answer_statistics(
        iter(visits) if as_iterator else visits)

    assert stats.total_count == len(visit_data)
    assert stats.answer_count == answer_count
    assert stats.graded_count == graded_count
    assert stats.average_correctness == pytest.approx(expected_score)
    assert stats.average_credited_fraction == pytest.approx(expected_credit)
    assert stats.average_emptiness == pytest.approx(expected_empty)
    assert stats.average_wrongness == pytest.approx(expected_wrong)
    assert stats.quartile_correctness_list == [None, None, None, None]
    assert (stats.average_credited_fraction + stats.average_emptiness
            + stats.average_wrongness) == pytest.approx(1.0 if graded_count else 0.0)

    assert stats.average_credited_fraction_ui == pytest.approx(expected_credit * 99.99)
    assert stats.average_credited_fraction_percent == pytest.approx(
        expected_credit * 100)
    assert stats.average_score_percent == pytest.approx(expected_score * 100)
    assert stats.average_emptiness_ui == pytest.approx(expected_empty * 99.99)
    assert stats.average_emptiness_percent == pytest.approx(expected_empty * 100)
    assert stats.average_wrongness_ui == pytest.approx(expected_wrong * 99.99)
    assert stats.average_wrongness_percent == pytest.approx(expected_wrong * 100)
    for fraction in ("credited_fraction", "emptiness", "wrongness"):
        assert 0.0 <= getattr(stats, f"average_{fraction}_ui") <= 99.99
        assert 0.0 <= getattr(stats, f"average_{fraction}_percent") <= 100.0


@pytest.mark.parametrize("visit_data,expected_quartiles,expected_score", [
    pytest.param([], [None, None, None, None], 0.0, id="empty"),
    pytest.param(
        [(True, None, 0), (False, None, 3)],
        [None, None, None, None], 0.0, id="unknown-only"),
    pytest.param(
        [(True, 0.25, 0), (False, 0.5, 1),
         (True, 1.0, 2), (False, 1.5, 3)],
        [0.25, 0.5, 1.0, 1.5], 3.25 / 4, id="all-quartiles-uncapped"),
    pytest.param(
        [(True, 0.5, 0), (False, 2.0, 0), (True, None, 0),
         (False, None, 1), (True, 0.0, 2), (False, 1.5, None),
         (True, None, None)],
        [1.25, None, 0.0, None], 1.0,
        id="average-within-quartile-ignore-unknown-and-unassigned"),
])
def test_compute_page_answer_statistics_quartiles(
        visit_data: list[tuple[bool, float | None, int | None]],
        expected_quartiles: list[float | None], expected_score: float) -> None:
    stats = analytics.compute_page_answer_statistics(
        analytics.PageAnswerVisitData(
            has_answer=answered, correctness=score, quartile=quartile)
        for answered, score, quartile in visit_data
    )

    assert len(stats.quartile_correctness_list) == 4
    for actual, expected in zip(
            stats.quartile_correctness_list, expected_quartiles, strict=True):
        if expected is None:
            assert actual is None
        else:
            assert actual == pytest.approx(expected)
    assert json.loads(stats.quartile_correctness_json) == expected_quartiles
    assert stats.average_correctness == pytest.approx(expected_score)
    assert stats.total_count == len(visit_data)
    assert stats.answer_count == sum(answered for answered, _, _ in visit_data)
    assert stats.graded_count == sum(score is not None for _, score, _ in visit_data)


def _render_page_answer_statistics(
        visit_data: list[tuple[bool, float | None]]) -> str:
    stats = analytics.PageAnswerStats(
        group_id="grp",
        page_id="pg",
        title="Test question",
        url=None,
        statistics=analytics.compute_page_answer_statistics(
            analytics.PageAnswerVisitData(has_answer=answered, correctness=score)
            for answered, score in visit_data
        ),
    )
    histogram = SimpleNamespace(total_weight=0, html=mock.Mock(return_value=""))
    # Isolate the analytics content from navigation and request-dependent context.
    with override_settings(TEMPLATES=[{
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "OPTIONS": {
            "loaders": [
                ("django.template.loaders.locmem.Loader", {
                    "course/course-base-with-markup.html":
                        "{% block content %}{% endblock %}",
                }),
                "django.template.loaders.app_directories.Loader",
            ],
        },
    }]), override("en"):
        return render_to_string("course/analytics-flow.html", {
            "flow_identifier": "test-flow",
            "page_answer_stats_list": [stats],
            "grade_histogram": histogram,
            "time_histogram": histogram,
            "participant_count": None,
        })


@pytest.mark.parametrize("visit_data,answer_count,total_count", [
    pytest.param([], 0, 0, id="no-visits"),
    pytest.param([(False, None)], 0, 1, id="ungraded-empty"),
    pytest.param([(True, None), (False, None)], 1, 2, id="ungraded-mixed"),
])
def test_page_answer_statistics_template_no_known_grades(
        visit_data: list[tuple[bool, float | None]],
        answer_count: int, total_count: int) -> None:
    html = _render_page_answer_statistics(visit_data)

    assert "Credit breakdown unavailable: no known grades." in html
    assert "Average score:" not in html
    assert 'role="progressbar"' not in html
    assert f"({answer_count} non-empty response" in html
    assert f"{total_count} response" in html
    assert 'data-points="[null, null, null, null]"' in html


@pytest.mark.parametrize((
    "visit_data,expected_score,expected_credit,expected_empty,expected_wrong"
), [
    pytest.param(
        [(False, 0.25)], 25.0, 25.0, 75.0, 0.0, id="credited-empty"),
    pytest.param(
        [(False, 1.5)], 150.0, 100.0, 0.0, 0.0, id="extra-credit-empty"),
    pytest.param(
        [(True, 1.5)], 150.0, 100.0, 0.0, 0.0, id="extra-credit-answered"),
    pytest.param(
        [(False, 0.5), (True, 1.5), (True, None)],
        100.0, 75.0, 25.0, 0.0, id="mixed-with-ungraded"),
    pytest.param(
        [(True, 0.25)], 25.0, 25.0, 0.0, 75.0, id="answered-uncredited"),
])
def test_page_answer_statistics_template_credit_display(
        visit_data: list[tuple[bool, float | None]],
        expected_score: float, expected_credit: float,
        expected_empty: float, expected_wrong: float) -> None:
    html = _render_page_answer_statistics(visit_data)

    assert "Credit breakdown unavailable" not in html
    assert f"Average score: {expected_score:.1f}%" in html
    bars = re.findall(
        r'aria-label="([^"]+)"[^>]*aria-valuenow="([^"]+)"'
        r'[^>]*style="width: ([^%]+)%"', html)
    assert len(bars) == 3
    for (label, percentage, width), (expected_label, expected_percent) in zip(
            bars, [
                ("Credit earned", expected_credit),
                ("Answered, uncredited", expected_wrong),
                ("Unanswered, uncredited", expected_empty),
            ], strict=True):
        assert label == expected_label
        assert float(percentage) == pytest.approx(expected_percent)
        assert float(width) == pytest.approx(expected_percent * 0.9999)
        assert 0.0 <= float(percentage) <= 100.0
        assert 0.0 <= float(width) <= 99.99
        assert f"{expected_percent:.1f}%</span>" in html


@pytest.mark.slow
class ComputeSessionQuartileMapTest(SingleCourseTestMixin, TestCase):
    """Test analytics.compute_session_quartile_map."""

    FLOW_ID = "test-quartile-flow"

    def _make_pctx(self):
        pctx = mock.MagicMock()
        pctx.course = self.course
        return pctx

    def _make_session(self, participation, points, max_points,
                      in_progress=False):
        return factories.FlowSessionFactory(
            participation=participation,
            flow_id=self.FLOW_ID,
            points=points,
            max_points=max_points,
            in_progress=in_progress,
        )

    def test_no_sessions_returns_empty_map(self):
        pctx = self._make_pctx()
        result = analytics.compute_session_quartile_map(pctx, self.FLOW_ID)
        self.assertEqual(result, {})

    def test_sessions_without_points_excluded(self):
        pctx = self._make_pctx()
        self._make_session(self.student_participation, None, 10)
        result = analytics.compute_session_quartile_map(pctx, self.FLOW_ID)
        self.assertEqual(result, {})

    def test_in_progress_sessions_excluded(self):
        pctx = self._make_pctx()
        self._make_session(
            self.student_participation, 80, 100, in_progress=True)
        result = analytics.compute_session_quartile_map(pctx, self.FLOW_ID)
        self.assertEqual(result, {})

    def test_single_session_assigned_to_first_quartile(self):
        pctx = self._make_pctx()
        session = self._make_session(self.student_participation, 7, 10)
        result = analytics.compute_session_quartile_map(pctx, self.FLOW_ID)
        # n=1: i=0 → int(0*4/1)=0
        self.assertEqual(result, {session.id: 0})

    def test_four_sessions_one_per_quartile(self):
        pctx = self._make_pctx()
        participations = [
            factories.ParticipationFactory(course=self.course)
            for _ in range(4)
        ]
        sessions = [
            self._make_session(p, score, 100)
            for p, score in zip(
                participations, [25, 50, 75, 100], strict=True)
        ]
        result = analytics.compute_session_quartile_map(pctx, self.FLOW_ID)
        self.assertEqual(result[sessions[0].id], 0)  # 25% -> Q1
        self.assertEqual(result[sessions[1].id], 1)  # 50% -> Q2
        self.assertEqual(result[sessions[2].id], 2)  # 75% -> Q3
        self.assertEqual(result[sessions[3].id], 3)  # 100% -> Q4

    def test_two_sessions_small_n(self):
        pctx = self._make_pctx()
        p1 = factories.ParticipationFactory(course=self.course)
        p2 = factories.ParticipationFactory(course=self.course)
        s_low = self._make_session(p1, 30, 100)
        s_high = self._make_session(p2, 80, 100)
        result = analytics.compute_session_quartile_map(pctx, self.FLOW_ID)
        # n=2: i=0 → int(0*4/2)=0; i=1 → int(1*4/2)=2
        self.assertEqual(result[s_low.id], 0)
        self.assertEqual(result[s_high.id], 2)

    def test_three_sessions_small_n(self):
        pctx = self._make_pctx()
        participations = [
            factories.ParticipationFactory(course=self.course)
            for _ in range(3)
        ]
        sessions = [
            self._make_session(p, score, 100)
            for p, score in zip(
                participations, [10, 50, 90], strict=True)
        ]
        result = analytics.compute_session_quartile_map(pctx, self.FLOW_ID)
        # n=3: i=0→0, i=1→int(4/3)=1, i=2→int(8/3)=2
        self.assertEqual(result[sessions[0].id], 0)
        self.assertEqual(result[sessions[1].id], 1)
        self.assertEqual(result[sessions[2].id], 2)

    def test_sorted_by_score(self):
        """Sessions are ranked by score, not by insertion order."""
        pctx = self._make_pctx()
        p1 = factories.ParticipationFactory(course=self.course)
        p2 = factories.ParticipationFactory(course=self.course)
        p3 = factories.ParticipationFactory(course=self.course)
        p4 = factories.ParticipationFactory(course=self.course)
        # Create sessions in non-sorted order
        s90 = self._make_session(p1, 90, 100)
        s10 = self._make_session(p2, 10, 100)
        s50 = self._make_session(p3, 50, 100)
        s70 = self._make_session(p4, 70, 100)
        result = analytics.compute_session_quartile_map(pctx, self.FLOW_ID)
        # Sorted order: 10→Q1, 50→Q2, 70→Q3, 90→Q4
        self.assertEqual(result[s10.id], 0)
        self.assertEqual(result[s50.id], 1)
        self.assertEqual(result[s70.id], 2)
        self.assertEqual(result[s90.id], 3)


@pytest.mark.slow
class PageAnalyticsTest(SingleCourseTestMixin, TestCase):
    """test analytics.page_analytics, (for cases not covered by other tests)"""
    def test_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_flow_page_analytics(
                flow_id="blabla", group_id="foo", page_id="bar",
                force_login_instructor=False)
            self.assertEqual(resp.status_code, 302)

    def test_no_pperm(self):
        # student user is logged in
        resp = self.get_flow_page_analytics(
            flow_id="blabla", group_id="foo", page_id="bar",
            force_login_instructor=False)
        self.assertEqual(resp.status_code, 403)


@pytest.mark.slow
class FlowAnalyticsTest(SingleCourseQuizPageTestMixin, HackRepoMixin,
                        MockAddMessageMixing, TestCase):
    """analytics.flow_analytics"""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.course.active_git_commit_sha = "my_fake_commit_sha_for_flow_analytics"
        cls.course.save()

        client = Client()
        client.force_login(cls.student_participation.user)
        cls.start_flow(client, cls.flow_id)
        fs = FlowSession.objects.last()
        for page_ordinal in range(fs.page_count):
            cls.submit_page_answer_by_ordinal_and_test(
                    client,
                    page_ordinal=page_ordinal, do_grading=False,
                    do_human_grade=False)
        cls.end_flow(client)

        # start another in-progress session with answers
        cls.start_flow(client, cls.flow_id)
        fs = FlowSession.objects.last()
        for page_ordinal in range(fs.page_count):
            cls.submit_page_answer_by_ordinal_and_test(
                    client,
                    page_ordinal=page_ordinal, do_grading=False,
                    do_human_grade=False)

        # start another ended session with out answers
        cls.start_flow(client, cls.flow_id)
        cls.end_flow(client)

        # create another participation and with a flow session
        another_partcpt = factories.ParticipationFactory(course=cls.course)
        with cls.temporarily_switch_to_user(client, another_partcpt.user):
            cls.start_flow(client, cls.flow_id)
            cls.end_flow(client)

    def test_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_flow_analytics_view(
                flow_id="blabla", force_login_instructor=False)
            self.assertEqual(resp.status_code, 302)

    def test_no_pperm(self):
        # student user is logged in
        resp = self.get_flow_analytics_view(
            flow_id="blabla", force_login_instructor=False)
        self.assertEqual(resp.status_code, 403)

    def test_success(self):
        resp = self.get_flow_analytics_view(flow_id=self.flow_id)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "flow_identifier", self.flow_id)

        resp = self.get_flow_analytics_view(flow_id=self.flow_id,
                                            restrict_to_first_attempt=1)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "flow_identifier", self.flow_id)

    def test_credit_on_unanswered_visit(self) -> None:
        from course.models import FlowPageVisit, FlowPageVisitGrade

        visit = FlowPageVisit.objects.filter(
            flow_session__course=self.course,
            flow_session__participation=self.student_participation,
            flow_session__flow_id=self.flow_id,
            is_synthetic=True,
            is_submitted_answer=True,
        ).select_related("page_data").first()
        assert visit is not None
        assert visit.answer is None
        previous_grade = visit.get_most_recent_grade()
        assert previous_grade is not None
        FlowPageVisitGrade.objects.create(
            visit=visit,
            max_points=previous_grade.max_points,
            correctness=0.5,
            grader=self.instructor_participation.user,
            graded_at_git_commit_sha=self.course.active_git_commit_sha,
        )

        with mock.patch(
                "course.analytics.compute_page_answer_statistics",
                wraps=analytics.compute_page_answer_statistics,
                ) as compute_stats:
            resp = self.get_flow_analytics_view(flow_id=self.flow_id)
        self.assertEqual(resp.status_code, 200)
        # Verify the access layer passes the latest grade and missing-answer
        # status through to the pure computation, not an older zero grade.
        assert any(
            not data.has_answer and data.correctness == pytest.approx(0.5)
            for call in compute_stats.call_args_list
            for data in call.args[0])

    def test_success_check_func_call(self):
        with mock.patch(
            "course.analytics.make_grade_histogram",
            return_value=_dummy_histogram()
        ) as mock_make_g_his, mock.patch(
            "course.analytics.make_page_answer_stats_list"
        ) as mock_make_stats_list, mock.patch(
            "course.analytics.make_time_histogram",
            return_value=_dummy_histogram()
        ) as mock_make_t_his, mock.patch(
            "course.analytics.count_participants",
            return_value=2,
        ) as mock_count_particpt:
            resp = self.get_flow_analytics_view(flow_id=self.flow_id)
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(
                resp, "flow_identifier", self.flow_id)
            self.assertResponseContextEqual(resp, "participant_count", 2)
            self.assertResponseContextEqual(resp, "restrict_to_first_attempt", 0)

            self.assertEqual(mock_make_g_his.call_count, 1)
            self.assertEqual(mock_make_stats_list.call_count, 1)
            self.assertEqual(mock_make_t_his.call_count, 1)
            self.assertEqual(mock_count_particpt.call_count, 1)

    def test_success_test_restrict_to_first_attempt(self):
        with mock.patch(
            "course.analytics.make_grade_histogram",
            return_value=_dummy_histogram()
        ) as mock_make_g_his, mock.patch(
            "course.analytics.make_page_answer_stats_list"
        ) as mock_make_stats_list, mock.patch(
            "course.analytics.make_time_histogram",
            return_value=_dummy_histogram(),
        ) as mock_make_t_his, mock.patch(
            "course.analytics.count_participants",
            return_value=2,
        ) as mock_count_particpt:
            resp = self.get_flow_analytics_view(flow_id=self.flow_id,
                                                restrict_to_first_attempt=1)
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(
                resp, "flow_identifier", self.flow_id)
            self.assertResponseContextEqual(resp, "participant_count", 2)

            # make_page_answer_stats_list is called
            # using restrict_to_first_attempt = 1
            self.assertIn(1, mock_make_stats_list.call_args[0])
            self.assertResponseContextEqual(resp, "restrict_to_first_attempt", 1)

            self.assertEqual(mock_make_g_his.call_count, 1)
            self.assertEqual(mock_make_stats_list.call_count, 1)
            self.assertEqual(mock_make_t_his.call_count, 1)
            self.assertEqual(mock_count_particpt.call_count, 1)

    def test_success_test_restrict_to_first_attempt_invalid(self):
        with mock.patch(
            "course.analytics.make_grade_histogram",
            return_value=_dummy_histogram()
        ) as mock_make_g_his, mock.patch(
            "course.analytics.make_page_answer_stats_list"
        ) as mock_make_stats_list, mock.patch(
            "course.analytics.make_time_histogram",
            return_value=_dummy_histogram()
        ) as mock_make_t_his, mock.patch(
            "course.analytics.count_participants",
            return_value=2,
        ) as mock_count_particpt:
            resp = self.get_flow_analytics_view(flow_id=self.flow_id,
                                                restrict_to_first_attempt="foo")
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(
                resp, "flow_identifier", self.flow_id)

            # make_page_answer_stats_list is called
            # using restrict_to_first_attempt = 0
            self.assertIn(0, mock_make_stats_list.call_args[0])
            self.assertResponseContextEqual(resp, "restrict_to_first_attempt", 0)

            self.assertEqual(mock_make_g_his.call_count, 1)
            self.assertEqual(mock_make_stats_list.call_count, 1)
            self.assertEqual(mock_make_t_his.call_count, 1)
            self.assertEqual(mock_count_particpt.call_count, 1)

    def test_flow_id_does_not_exist(self):
        with mock.patch(
            "course.analytics.make_page_answer_stats_list"
        ) as mock_make_stats_list:
            mock_make_stats_list.side_effect = ObjectDoesNotExist()
            resp = self.get_flow_analytics_view(flow_id=self.flow_id)
            self.assertEqual(resp.status_code, 404)
            self.assertAddMessageCalledWith(
                f"Flow '{self.flow_id}' was not found in the repository, but it exists in "  # ruff:ignore[line-too-long]
                    "the database--maybe it was deleted?")

# vim: fdm=marker
