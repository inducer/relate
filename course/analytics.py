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


import six
from django.utils.translation import ugettext as _, pgettext
from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.urls import reverse
from django.core.exceptions import ObjectDoesNotExist
from django import http
from django.contrib import messages

from course.utils import course_view, render_course_page, PageInstanceCache
from course.models import (
        FlowSession,
        FlowPageVisit,
        flow_permission)

from course.constants import (
        participation_permission as pperm,
        )

from course.content import get_flow_desc


# {{{ flow list

@login_required
@course_view
def flow_list(pctx):
    if not pctx.has_permission(pperm.view_analytics):
        raise PermissionDenied(_("may not view analytics"))

    cursor = connection.cursor()

    cursor.execute("select distinct flow_id from course_flowsession "
            "where course_id=%s order by flow_id",
            [pctx.course.id])
    flow_ids = [row[0] for row in cursor.fetchall()]

    return render_course_page(pctx, "course/analytics-flows.html", {
        "flow_ids": flow_ids,
        })

# }}}


# {{{ histogram tool

class BinInfo(object):
    def __init__(self, title, raw_weight, percentage, url=None):
        self.title = title
        self.raw_weight = raw_weight
        self.percentage = percentage
        self.url = url


class Histogram(object):
    def __init__(self, num_bin_count=10, num_bin_starts=None,
            num_min_value=None, num_max_value=None,
            num_enforce_bounds=False, num_log_bins=False,
            num_bin_title_formatter=str):
        self.string_weights = {}
        self.num_values = []
        self.num_bin_starts = num_bin_starts
        self.num_min_value = num_min_value
        self.num_max_value = num_max_value
        self.num_bin_count = num_bin_count
        self.num_log_bins = num_log_bins
        self.num_bin_title_formatter = num_bin_title_formatter

    def add_data_point(self, value, weight=1):
        if isinstance(value, six.string_types):
            self.string_weights[value] = \
                    self.string_weights.get(value, 0) + weight
        elif value is None:
            self.add_data_point(
                "".join([
                        "(",
                        pgettext("No data", "None"),
                        ")"]),
                weight)
        else:
            if (self.num_max_value is not None
                    and value > self.num_max_value):
                self.add_data_point(
                    "".join([
                            "(",
                            pgettext("Value of grade", "value greater than max"),
                            ")"]),
                    weight)
            elif (self.num_min_value is not None
                    and value < self.num_min_value):
                self.add_data_point(
                    "".join([
                            "(",
                            pgettext("Value of grade", "value smaller than min"),
                            ")"]),
                    weight)
            else:
                self.num_values.append((value, weight))

    def total_weight(self):
        return (
                sum(weight for val, weight in self.num_values)
                + sum(six.itervalues(self.string_weights)))

    def get_bin_info_list(self):
        min_value = self.num_min_value
        max_value = self.num_max_value

        if self.num_bin_starts is not None:
            num_bin_starts = self.num_bin_starts
        else:
            if min_value is None:
                if self.num_values:
                    min_value, _ = min(self.num_values)
                else:
                    min_value = 1
            if max_value is None:
                if self.num_values:
                    max_value, _ = max(self.num_values)
                else:
                    max_value = 1

            if self.num_log_bins:
                min_value = max(min_value, 1e-15)
                max_value = max(max_value, 1.01*min_value)

                from math import log, exp
                bin_width = (log(max_value) - log(min_value))/self.num_bin_count
                num_bin_starts = [
                        exp(log(min_value)+bin_width*i)
                        for i in range(self.num_bin_count)]
                # Rounding error means exp(log(min_value)) may be greater
                # than min_value, so set start of first bin to min_value
                num_bin_starts[0] = min_value
            else:
                bin_width = (max_value - min_value)/self.num_bin_count
                num_bin_starts = [
                        min_value+bin_width*i
                        for i in range(self.num_bin_count)]

        bins = [0 for i in range(len(num_bin_starts))]

        temp_string_weights = self.string_weights.copy()

        oob = pgettext("Value in histogram", "<out of bounds>")

        from bisect import bisect
        for value, weight in self.num_values:
            if ((max_value is not None
                    and value > max_value)
                    or value < num_bin_starts[0]):
                temp_string_weights[oob] = \
                        temp_string_weights.get(oob, 0) + weight
            else:
                bin_nr = bisect(num_bin_starts, value)-1
                bins[bin_nr] += weight

        total_weight = self.total_weight()

        num_bin_info = [
                BinInfo(
                    title=self.num_bin_title_formatter(start),
                    raw_weight=weight,
                    percentage=(
                        100*weight/total_weight
                        if total_weight
                        else None))
                for start, weight in zip(num_bin_starts, bins)]

        str_bin_info = [
                BinInfo(
                    title=key,
                    raw_weight=temp_string_weights[key],
                    percentage=100*temp_string_weights[key]/total_weight)
                for key in sorted(six.iterkeys(temp_string_weights))]

        return num_bin_info + str_bin_info

    def html(self):
        bin_info_list = self.get_bin_info_list()
        max_len = max(len(bin.title) for bin in bin_info_list)

        if max_len < 20:
            from django.template.loader import render_to_string
            return render_to_string("course/histogram-wide.html", {
                "bin_info_list": bin_info_list,
                })
        else:
            from django.template.loader import render_to_string
            return render_to_string("course/histogram.html", {
                "bin_info_list": bin_info_list,
                })

# }}}


def is_flow_multiple_submit(flow_desc):
    if not hasattr(flow_desc, "rules"):
        return False

    for rule in flow_desc.rules.access:
        if flow_permission.change_answer in rule.permissions:
            return True

    return False


def is_page_multiple_submit(flow_desc, page_desc):
    result = is_flow_multiple_submit(flow_desc)

    page_rules = getattr(page_desc, "access_rules", None)
    if page_rules is None:
        return result

    add_permissions = getattr(page_rules, "add_permissions", None)
    remove_permissions = getattr(page_rules, "remove_permissions", None)

    if result:
        if remove_permissions is not None:
            if flow_permission.change_answer in remove_permissions:
                result = False

    else:
        if add_permissions is not None:
            if flow_permission.change_answer in add_permissions:
                result = True

    return result


# {{{ flow analytics

def make_grade_histogram(pctx, flow_id):
    qset = FlowSession.objects.filter(
            course=pctx.course,
            flow_id=flow_id,
            participation__roles__permissions__permission=(
                pperm.included_in_grade_statistics))

    hist = Histogram(
        num_min_value=0,
        num_max_value=100)
    for session in qset:
        if session.in_progress:
            hist.add_data_point(
                    "".join(["<",
                        pgettext("Status of session", "in progress"),
                        ">"]))
        else:
            hist.add_data_point(session.points_percentage())

    return hist


class PageAnswerStats(object):
    def __init__(self, group_id, page_id, title, average_correctness,
            average_emptiness, answer_count, total_count, url=None):
        self.group_id = group_id
        self.page_id = page_id
        self.title = title
        self.average_correctness_percent = 99.99*average_correctness
        self.average_emptiness_percent = 99.99*average_emptiness
        self.average_wrongness_percent = 99.99*(
                1-average_correctness-average_emptiness)
        self.answer_count = answer_count
        self.total_count = total_count
        self.url = url


def safe_div(num, denom):
    if denom == 0:
        return 0
    return num/denom


def make_page_answer_stats_list(pctx, flow_id, restrict_to_first_attempt):
    flow_desc = get_flow_desc(pctx.repo, pctx.course, flow_id,
            pctx.course_commit_sha)

    page_cache = PageInstanceCache(pctx.repo, pctx.course, flow_id)

    page_info_list = []
    for group_desc in flow_desc.groups:
        for page_desc in group_desc.pages:
            points = 0
            graded_count = 0
            empty_count = 0

            answer_count = 0
            total_count = 0

            visits = (FlowPageVisit.objects
                    .filter(
                        flow_session__course=pctx.course,
                        flow_session__flow_id=flow_id,
                        flow_session__participation__roles__permissions__permission=(
                            pperm.included_in_grade_statistics),
                        page_data__group_id=group_desc.id,
                        page_data__page_id=page_desc.id,
                        is_submitted_answer=True,
                        ))

            if connection.features.can_distinct_on_fields:
                if restrict_to_first_attempt:
                    visits = (visits
                            .distinct("flow_session__participation__id")
                            .order_by("flow_session__participation__id",
                                "visit_time"))
                elif is_page_multiple_submit(flow_desc, page_desc):
                    visits = (visits
                            .distinct("page_data__id")
                            .order_by("page_data__id", "-visit_time"))

            visits = (visits
                    .select_related("flow_session")
                    .select_related("page_data"))

            answer_expected = False

            title = None
            for visit in visits:
                page = page_cache.get_page(group_desc.id, page_desc.id,
                        pctx.course_commit_sha)

                answer_expected = answer_expected or page.expects_answer()

                from course.page import PageContext
                grading_page_context = PageContext(
                        course=pctx.course,
                        repo=pctx.repo,
                        commit_sha=pctx.course_commit_sha,
                        flow_session=visit.flow_session)

                title = page.title(grading_page_context, visit.page_data.data)

                answer_feedback = visit.get_most_recent_feedback()

                if visit.answer is not None:
                    answer_count += 1
                else:
                    empty_count += 1

                total_count += 1

                if (answer_feedback is not None
                        and answer_feedback.correctness is not None):
                    if visit.answer is None:
                        assert answer_feedback.correctness == 0
                    else:
                        points += answer_feedback.correctness

                    graded_count += 1

            if not answer_expected:
                continue

            page_info_list.append(
                    PageAnswerStats(
                        group_id=group_desc.id,
                        page_id=page_desc.id,
                        title=title,
                        average_correctness=safe_div(points, graded_count),
                        average_emptiness=safe_div(
                            empty_count, graded_count),
                        answer_count=answer_count,
                        total_count=total_count,
                        url=reverse(
                            "relate-page_analytics",
                            args=(
                                pctx.course_identifier,
                                flow_id,
                                group_desc.id,
                                page_desc.id,
                                ))))

    return page_info_list


def make_time_histogram(pctx, flow_id):
    qset = FlowSession.objects.filter(
            course=pctx.course,
            flow_id=flow_id)

    from relate.utils import string_concat
    hist = Histogram(
            num_log_bins=True,
            num_bin_title_formatter=(
                lambda minutes: string_concat(
                    "$>$ %.1f ",
                    pgettext("Minute (time unit)", "min"))
                % minutes))
    for session in qset:
        if session.in_progress:
            hist.add_data_point(
                    "".join(["<",
                        pgettext("Status of session", "in progress"),
                        ">"]))
        else:
            delta = session.completion_time - session.start_time
            minutes = delta.total_seconds() / 60
            hist.add_data_point(minutes)

    return hist


def count_participants(pctx, flow_id):
    if not connection.features.can_distinct_on_fields:
        return None

    qset = (FlowSession.objects
            .filter(
                course=pctx.course,
                flow_id=flow_id)
            .order_by("participation__id")
            .distinct("participation__id"))
    return qset.count()


@login_required
@course_view
def flow_analytics(pctx, flow_id):
    if not pctx.has_permission(pperm.view_analytics):
        raise PermissionDenied(_("may not view analytics"))

    restrict_to_first_attempt = int(
            bool(pctx.request.GET.get("restrict_to_first_attempt") == "1"))

    try:
        stats_list = make_page_answer_stats_list(pctx, flow_id,
                restrict_to_first_attempt)
    except ObjectDoesNotExist:
        messages.add_message(pctx.request, messages.ERROR,
                _("Flow '%s' was not found in the repository, but it exists in "
                    "the database--maybe it was deleted?")
                % flow_id)
        raise http.Http404()

    return render_course_page(pctx, "course/analytics-flow.html", {
        "flow_identifier": flow_id,
        "grade_histogram": make_grade_histogram(pctx, flow_id),
        "page_answer_stats_list": stats_list,
        "time_histogram": make_time_histogram(pctx, flow_id),
        "participant_count": count_participants(pctx, flow_id),
        "restrict_to_first_attempt": restrict_to_first_attempt,
        })

# }}}


# {{{ page analytics

class AnswerStats(object):
    def __init__(self, normalized_answer, correctness, count,
            percentage):
        self.normalized_answer = normalized_answer
        self.correctness = correctness
        self.count = count
        self.percentage = percentage


@login_required
@course_view
def page_analytics(pctx, flow_id, group_id, page_id):
    if not pctx.has_permission(pperm.view_analytics):
        raise PermissionDenied(_("may not view analytics"))

    flow_desc = get_flow_desc(pctx.repo, pctx.course, flow_id,
            pctx.course_commit_sha)

    restrict_to_first_attempt = int(
            bool(pctx.request.GET.get("restrict_to_first_attempt") == "1"))

    page_cache = PageInstanceCache(pctx.repo, pctx.course, flow_id)

    visits = (FlowPageVisit.objects
            .filter(
                flow_session__course=pctx.course,
                flow_session__flow_id=flow_id,
                flow_session__participation__roles__permissions__permission=(
                    pperm.included_in_grade_statistics),
                page_data__group_id=group_id,
                page_data__page_id=page_id,
                is_submitted_answer=True,
                ))

    if connection.features.can_distinct_on_fields:

        is_multiple_submit = is_flow_multiple_submit(flow_desc)

        if restrict_to_first_attempt:
            visits = (visits
                    .distinct("flow_session__participation__id")
                    .order_by("flow_session__participation__id", "visit_time"))
        elif is_multiple_submit:
            visits = (visits
                    .distinct("page_data__id")
                    .order_by("page_data__id", "-visit_time"))

    visits = (visits
            .select_related("flow_session")
            .select_related("page_data"))

    normalized_answer_and_correctness_to_count = {}

    title = None
    body = None
    total_count = 0
    graded_count = 0

    for visit in visits:
        page = page_cache.get_page(group_id, page_id, pctx.course_commit_sha)

        from course.page import PageContext
        grading_page_context = PageContext(
                course=pctx.course,
                repo=pctx.repo,
                commit_sha=pctx.course_commit_sha,
                flow_session=visit.flow_session)

        title = page.title(grading_page_context, visit.page_data.data)
        body = page.analytic_view_body(grading_page_context, visit.page_data.data)
        normalized_answer = page.normalized_answer(
                grading_page_context, visit.page_data.data, visit.answer)

        answer_feedback = visit.get_most_recent_feedback()

        if answer_feedback is not None:
            key = (normalized_answer, answer_feedback.correctness)
            normalized_answer_and_correctness_to_count[key] = \
                    normalized_answer_and_correctness_to_count.get(key, 0) + 1
            graded_count += 1
        else:
            key = (normalized_answer, None)
            normalized_answer_and_correctness_to_count[key] = \
                    normalized_answer_and_correctness_to_count.get(key, 0) + 1

        total_count += 1

    answer_stats = []
    for (normalized_answer, correctness), count in \
            six.iteritems(normalized_answer_and_correctness_to_count):
        answer_stats.append(
                AnswerStats(
                    normalized_answer=normalized_answer,
                    correctness=correctness,
                    count=count,
                    percentage=safe_div(100 * count, total_count)))

    answer_stats = sorted(
            answer_stats,
            key=lambda astats: astats.percentage,
            reverse=True)

    return render_course_page(pctx, "course/analytics-page.html", {
        "flow_identifier": flow_id,
        "group_id": group_id,
        "page_id": page_id,
        "title": title,
        "body": body,
        "answer_stats_list": answer_stats,
        "restrict_to_first_attempt": restrict_to_first_attempt,
        })

# }}}

# vim: foldmethod=marker
