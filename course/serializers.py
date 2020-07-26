# -*- coding: utf-8 -*-

from __future__ import division

__copyright__ = "Copyright (C) 2020 Dong Zhuang"

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


from rest_framework import serializers
from course.models import (
    FlowSession, FlowPageVisit, FlowPageData, FlowPageVisitGrade)


class FlowSessionSerializer(serializers.ModelSerializer):

    class Meta:
        model = FlowSession

        fields = ("id",
                  "username",
                  "institutional_id",
                  "active_git_commit_sha",
                  "flow_id",
                  "start_time",
                  "completion_time",
                  "last_activity",
                  "page_count",
                  "in_progress",
                  "access_rules_tag",
                  "expiration_mode",
                  "points",
                  "max_points",
                  "result_comment",
                  "points_percentage",
                  )

    username = serializers.CharField(
        source="participation.user.username", read_only=True)

    institutional_id = serializers.CharField(
        source="participation.user.institutional_id", read_only=True)

    last_activity = serializers.SerializerMethodField()

    points_percentage = serializers.SerializerMethodField()

    def get_last_activity(self, obj):
        return obj.last_activity()

    def get_points_percentage(self, obj):
        return obj.points_percentage()


class FlowPageDateSerializer(serializers.ModelSerializer):

    class Meta:
        model = FlowPageData

        fields = ("page_ordinal",
                  "page_type",
                  "group_id",
                  "page_id",
                  "data",
                  "title",
                  "bookmarked"
                  )


class FlowPageVisitSerializer(serializers.ModelSerializer):

    class Meta:
        model = FlowPageVisit

        fields = ("flow_session",
                  "page_data",
                  "visit_time",
                  "remote_address",
                  "user",
                  "impersonated_by",
                  "is_synthetic",
                  "answer",
                  "is_submitted_answer",
                  )

    user = serializers.CharField(source="visitor.username", read_only=True)
    impersonated_by = serializers.CharField(
        source="impersonated_by.user.username", read_only=True)


class FlowPageVisitGradeSerializer(serializers.ModelSerializer):

    class Meta:
        model = FlowPageVisitGrade

        fields = (
            "visit",
            "grader",
            "grade_time",
            "graded_at_git_commit_sha",
            "grade_data",
            "max_points",
            "correctness",
            "feedback",
            "percentage",
        )

    grader = serializers.CharField(
        source="grader.username", read_only=True)

    percentage = serializers.SerializerMethodField()

    def get_percentage(self, obj):
        if obj.correctness is not None:
            return 100 * obj.correctness
        else:
            return None
