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

from typing import Any
from unittest import mock

import pytest
from django.db import OperationalError, connection
from django.utils.timezone import now

from course.grade_storage import persist_grade
from course.grading import _save_grade
from course.models import (
    FlowPageBulkFeedback,
    FlowPageData,
    FlowPageVisitGrade,
    update_bulk_feedback,
)
from course.page import PageContext
from course.page.base import AnswerFeedback, PageBase
from course.utils import FlowPageContext
from tests import factories


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("failure", [None, OperationalError, ValueError])
@pytest.mark.parametrize("human_grade", [False, True])
def test_persist_grade_transaction_scope_and_retries(
        failure: type[Exception] | None, human_grade: bool) -> None:
    visit = factories.FlowPageVisitFactory(is_submitted_answer=True, answer="answer")
    page_context = PageContext(
            course=visit.flow_session.course, repo=None,
            commit_sha=b"some_sha", flow_session=visit.flow_session)
    page = mock.Mock(spec=PageBase)

    def evaluate(*_args: object) -> AnswerFeedback:
        assert not connection.in_atomic_block
        return AnswerFeedback(correctness=0.75, feedback="Good effort")

    page.grade.side_effect = evaluate
    page.max_points.return_value = 10
    attempts = 0

    def store_feedback(
            page_data: FlowPageData, grade: FlowPageVisitGrade,
            feedback: Any) -> None:
        nonlocal attempts
        attempts += 1
        assert connection.in_atomic_block
        assert FlowPageVisitGrade.objects.filter(pk=grade.pk).exists()
        update_bulk_feedback(page_data, grade, feedback)
        if not human_grade and failure is not None and attempts == 1:
            raise failure("Storage failed")

    def recompute_session(*_args: object) -> None:
        assert connection.in_atomic_block
        assert visit.grades.count() == 1
        if failure is not None and attempts == 1:
            raise failure("Storage failed")

    def save() -> FlowPageVisitGrade:
        if human_grade:
            fpctx = mock.Mock(spec=FlowPageContext)
            fpctx.page = page
            fpctx.page_context = page_context
            fpctx.prev_answer_visit = visit
            fpctx.flow_desc = mock.Mock()
            return _save_grade(fpctx, visit.flow_session, None, visit.user_id, now())
        return persist_grade(visit, page, page_context, None)

    with mock.patch("course.grade_storage.update_bulk_feedback",
                    side_effect=store_feedback), \
            mock.patch("time.sleep"), \
            mock.patch("course.grading.get_session_grading_mode"), \
            mock.patch("course.flow.grade_flow_session",
                       side_effect=recompute_session):
        if failure is ValueError:
            with pytest.raises(ValueError, match="Storage failed"):
                save()
            assert not visit.grades.exists()
            assert not FlowPageBulkFeedback.objects.filter(
                    page_data=visit.page_data).exists()
        else:
            grade = save()
            grade.refresh_from_db()
            assert grade.correctness == pytest.approx(0.75)
            assert grade.max_points == 10
            assert visit.grades.count() == 1
            assert FlowPageBulkFeedback.objects.get(
                    page_data=visit.page_data).grade == grade

    page.grade.assert_called_once_with(
            page_context, visit.page_data.data, visit.answer, None)
    page.max_points.assert_called_once_with(visit.page_data.data)
    assert attempts == (2 if failure is OperationalError else 1)
