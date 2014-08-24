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


from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connection

from course.utils import course_view, render_course_page
from course.models import (
        FlowSession,
        FlowPageVisit,
        participation_role)

from course.content import (
        get_flow_desc, get_flow_page_desc,
        instantiate_flow_page)


# {{{ flow list

@login_required
@course_view
def flow_list(pctx):
    if pctx.role != participation_role.instructor:
        raise PermissionDenied("must be instructor to view analytics")

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
            num_enforce_bounds=False):
        self.string_weights = {}
        self.num_values = []
        self.num_bin_starts = num_bin_starts
        self.num_min_value = num_min_value
        self.num_max_value = num_max_value
        self.num_bin_count = num_bin_count

    def add_data_point(self, value, weight=1):
        if isinstance(value, basestring):
            self.string_weights[value] = \
                    self.string_weights.get(value, 0) + weight
        else:
            if (self.num_max_value is not None
                    and value > self.num_max_value):
                self.add_data_point("(value greater than max)", weight)
            elif (self.num_min_value is not None
                    and value < self.num_min_value):
                self.add_data_point("(value smaller than min)", weight)
            else:
                self.num_values.append((value, weight))

    def total_weight(self):
        return (
                sum(weight for val, weight in self.num_values)
                + sum(self.string_weights.itervalues()))

    def get_bin_info_list(self):
        min_value = self.num_min_value
        max_value = self.num_max_value

        if self.num_bin_starts is not None:
            num_bin_starts = self.num_bin_starts
        else:
            if min_value is None:
                min_value, _ = min(self.num_values)
            if max_value is None:
                max_value, _ = max(self.num_values)

            bin_width = (max_value - min_value)/self.num_bin_count
            num_bin_starts = [
                    min_value+bin_width*i
                    for i in range(self.num_bin_count)]

        bins = [0 for i in range(len(num_bin_starts))]

        from bisect import bisect
        for value, weight in self.num_values:
            if (max_value is not None
                    and value > max_value
                    or value < num_bin_starts[0]):
                # ignore out-of-bounds value
                assert False
            else:
                bin_nr = bisect(num_bin_starts, value)-1
                bins[bin_nr] += weight

        total_weight = self.total_weight()
        num_bin_info = [
                BinInfo(
                    title=str(start),
                    raw_weight=weight,
                    percentage=100*weight/total_weight)
                for start, weight in zip(num_bin_starts, bins)]

        str_bin_info = [
                BinInfo(
                    title=key,
                    raw_weight=self.string_weights[key],
                    percentage=100*self.string_weights[key]/total_weight)
                for key in sorted(self.string_weights.iterkeys())]

        return num_bin_info + str_bin_info

    def html(self):
        bin_info_list = self.get_bin_info_list()
        max_len = max(len(bin.title) for bin in bin_info_list)

        if max_len < 20:
            from django.template.loader import render_to_string
            return render_to_string("course/histogram-wide.html", {
                "bin_info_list": self.get_bin_info_list(),
                })
        else:
            from django.template.loader import render_to_string
            return render_to_string("course/histogram.html", {
                "bin_info_list": self.get_bin_info_list(),
                })

# }}}


# {{{ flow analytics

def make_grade_histogram(pctx, flow_identifier):
    qset = FlowSession.objects.filter(
            course=pctx.course,
            flow_id=flow_identifier)

    hist = Histogram(
        num_min_value=0,
        num_max_value=100)
    for session in qset:
        if session.in_progress:
            hist.add_data_point("<in progress>")
        else:
            hist.add_data_point(session.points_percentage())

    return hist


class PageAnswerStats(object):
    def __init__(self, group_id, page_id, title, average_correctness,
            answer_count, url=None):
        self.group_id = group_id
        self.page_id = page_id
        self.title = title
        self.average_correctness_percent = 100*average_correctness
        self.answer_count = answer_count
        self.url = url


def make_page_answer_stats_list(pctx, flow_identifier):
    flow_desc = get_flow_desc(pctx.repo, pctx.course, flow_identifier,
            pctx.course_commit_sha)

    page_cache = {}

    def get_page(group_id, page_id, commit_sha):
        key = (group_id, page_id, commit_sha)
        try:
            return page_cache[key]
        except KeyError:
            page_desc = get_flow_page_desc(
                    flow_identifier,
                    get_flow_desc(pctx.repo, pctx.course, flow_identifier,
                        commit_sha),
                    group_id, page_id)

            page = instantiate_flow_page(
                    location="flow '%s', group, '%s', page '%s'"
                    % (flow_identifier, group_desc.id, page_desc.id),
                    repo=pctx.repo, page_desc=page_desc,
                    commit_sha=commit_sha)
            page_cache[key] = page
            return page

    from course.content import get_flow_commit_sha

    page_info_list = []
    for group_desc in flow_desc.groups:
        for page_desc in group_desc.pages:
            points = 0
            count = 0

            visits = (FlowPageVisit.objects
                    .filter(
                        flow_session__flow_id=flow_identifier,
                        page_data__group_id=group_desc.id,
                        page_data__page_id=page_desc.id,
                        is_graded_answer=True,
                        )
                    .prefetch_related("flow_session")
                    .prefetch_related("page_data"))

            title = None
            for visit in visits:
                flow_commit_sha = get_flow_commit_sha(
                        pctx.course, pctx.participation, flow_desc,
                        visit.flow_session)
                page = get_page(group_desc.id, page_desc.id, flow_commit_sha)

                from course.page import PageContext
                grading_page_context = PageContext(
                        course=pctx.course,
                        repo=pctx.repo,
                        commit_sha=flow_commit_sha)

                title = page.title(grading_page_context, visit.page_data.data)

                answer_feedback = page.grade(
                        grading_page_context, visit.page_data.data,
                        visit.answer, grade_data=None)

                count += 1
                points += answer_feedback.correctness

            page_info_list.append(
                    PageAnswerStats(
                        group_id=group_desc.id,
                        page_id=page_desc.id,
                        title=title,
                        average_correctness=points/count,
                        answer_count=count))

    return page_info_list


@login_required
@course_view
def flow_analytics(pctx, flow_identifier):
    if pctx.role != participation_role.instructor:
        raise PermissionDenied("must be instructor to view analytics")

    return render_course_page(pctx, "course/analytics-flow.html", {
        "flow_identifier": flow_identifier,
        "grade_histogram": make_grade_histogram(pctx, flow_identifier),
        "page_answer_stats_list": make_page_answer_stats_list(pctx, flow_identifier),
        })

# }}}

# vim: foldmethod=marker
