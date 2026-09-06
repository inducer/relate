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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from course.models import FlowPageVisitGrade, update_bulk_feedback
from course.repo import serialize_revision
from relate.utils import retry_transaction_decorator


if TYPE_CHECKING:
    from course.models import FlowPageVisit
    from course.page.base import AnswerData, GradeData, PageBase, PageContext, PageData


@dataclass(frozen=True)
class EvaluatedGrade:
    max_points: float
    correctness: float | None
    feedback: Any
    bulk_feedback: Any


def evaluate_grade(
        visit: FlowPageVisit,
        page: PageBase,
        page_context: PageContext,
        grade_data: GradeData,
        ) -> EvaluatedGrade:
    """Evaluate a page without opening a transaction."""
    from course.utils import LanguageOverride

    page_data = cast("PageData", visit.page_data.data)
    answer_data = cast("AnswerData", visit.answer)
    with LanguageOverride(page_context.course):
        feedback = page.grade(
                page_context, page_data, answer_data, grade_data)

    feedback_json = None
    bulk_feedback_json = None
    if feedback is not None:
        feedback_json, bulk_feedback_json = feedback.as_json()
    return EvaluatedGrade(
            max_points=page.max_points(page_data),
            correctness=feedback.correctness if feedback is not None else None,
            feedback=feedback_json,
            bulk_feedback=bulk_feedback_json)


@retry_transaction_decorator()
def persist_evaluated_grade(
        visit: FlowPageVisit,
        page_context: PageContext,
        grade_data: GradeData,
        evaluated: EvaluatedGrade,
        *,
        grader_id: int | None = None,
        ai_generated_by: str | None = None,
        ) -> FlowPageVisitGrade:
    """Atomically store an already evaluated grade, retrying only storage."""
    grade = FlowPageVisitGrade(
            visit=visit,
            grader_id=grader_id,
            ai_generated_by=ai_generated_by,
            graded_at_git_commit_sha=serialize_revision(page_context.commit_sha),
            grade_data=grade_data,
            max_points=evaluated.max_points,
            correctness=evaluated.correctness,
            feedback=evaluated.feedback)
    grade.save()
    update_bulk_feedback(visit.page_data, grade, evaluated.bulk_feedback)
    return grade


def persist_grade(
        visit: FlowPageVisit,
        page: PageBase,
        page_context: PageContext,
        grade_data: GradeData,
        *,
        grader_id: int | None = None,
        ai_generated_by: str | None = None,
        ) -> FlowPageVisitGrade:
    """Evaluate once, then atomically store a grade without recomputing its session.

    Evaluation precedes the storage transaction, but still runs in any transaction
    opened by the caller.
    """
    evaluated = evaluate_grade(visit, page, page_context, grade_data)
    return persist_evaluated_grade(
            visit, page_context, grade_data, evaluated,
            grader_id=grader_id, ai_generated_by=ai_generated_by)
