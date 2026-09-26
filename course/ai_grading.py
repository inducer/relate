from __future__ import annotations


__copyright__ = "Copyright (C) 2026 Andreas Kloeckner"

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
from typing import TYPE_CHECKING, Any

from django.utils.timezone import now
from django.utils.translation import gettext as _
from pydantic import BaseModel, Field, ValidationError

from course.constants import MAX_EXTRA_CREDIT_FACTOR
from course.models import FlowPageVisitGrade, update_bulk_feedback
from course.repo import serialize_revision


if TYPE_CHECKING:
    from collections.abc import Sequence

    from openai import OpenAI
    from openai.types.chat import ChatCompletionMessageParam

    from course.models import Course, FlowPageVisit
    from course.page.base import (
        AnswerData,
        PageBaseWithHumanTextFeedback,
        PageContext,
        PageData,
    )
    from course.repo import RevisionID_ish


class AIGradingError(RuntimeError):
    """Raised when the AI grading endpoint is misconfigured or returns
    a response that cannot be used to draft a grade.
    """


DEFAULT_AI_GRADING_PROMPT = _(
    "You are an experienced, fair, and detail-oriented teaching assistant "
    "grading a student's answer to a course assignment question. Carefully "
    "compare the student's answer against the rubric provided below, and "
    "write feedback in RELATE-flavored Markdown (roughly GitHub-flavored "
    "Markdown) explaining what was correct, what was missing or incorrect, "
    "and how the grade was determined. Be specific and refer to the rubric. "
    "If prior graded examples for this question are given, use them to "
    "calibrate the standard and style of your grading, so that your "
    "grading is consistent with what has already been done for other "
    "students.")


class AIGradeResult(BaseModel):
    grade_percent: float = Field(ge=0, le=100*MAX_EXTRA_CREDIT_FACTOR)
    feedback_text: str


@dataclass(frozen=True)
class CalibrationExample:
    answer_text: str
    grade_percent: float
    feedback_text: str


def get_openai_client(course: Course) -> OpenAI:
    if not (course.ai_grading_api_base_url
            and course.ai_grading_api_key
            and course.ai_grading_model):
        raise AIGradingError(
                _("AI grading is not configured for this course. Please "
                    "set 'AI grading API base URL', 'AI grading API key', "
                    "and 'AI grading model' on the course's 'Edit Course' "
                    "page."))

    import openai
    return openai.OpenAI(
            base_url=course.ai_grading_api_base_url,
            api_key=course.ai_grading_api_key)


def gather_calibration_examples(
        course: Course,
        flow_id: str,
        group_id: str,
        page_id: str,
        page: PageBaseWithHumanTextFeedback,
        page_context: PageContext,
        limit: int = 5,
        ) -> list[CalibrationExample]:
    """Collect a sample of already human-graded submissions of the same
    question, to give the AI grading assistant as few-shot calibration
    examples.
    """

    grades = (FlowPageVisitGrade.objects
            .filter(
                visit__flow_session__course=course,
                visit__flow_session__flow_id=flow_id,
                visit__page_data__group_id=group_id,
                visit__page_data__page_id=page_id,
                ai_generated_by__isnull=True)
            .select_related("visit", "visit__page_data")
            .order_by("-grade_time")[:4*limit])

    examples: list[CalibrationExample] = []
    for grade in grades:
        grade_data: dict[str, Any] | None = grade.grade_data
        if not grade_data or not grade_data.get("released"):
            continue

        feedback_text: str | None = grade_data.get("feedback_text")
        grade_percent: float | None = grade_data.get("grade_percent")
        if not feedback_text or grade_percent is None:
            continue

        visit_page_data: PageData = grade.visit.page_data.data
        visit_answer: AnswerData = grade.visit.answer
        answer_text = page.normalized_answer(
                page_context, visit_page_data, visit_answer)
        if not answer_text:
            continue

        examples.append(CalibrationExample(
            answer_text=answer_text,
            grade_percent=grade_percent,
            feedback_text=feedback_text))

        if len(examples) >= limit:
            break

    return examples


def build_messages(
        page: PageBaseWithHumanTextFeedback,
        page_context: PageContext,
        page_data: PageData,
        answer_data: AnswerData,
        point_value: float | None,
        grading_prompt: str | None,
        calibration_examples: Sequence[CalibrationExample],
        ) -> list[ChatCompletionMessageParam]:
    system_prompt = (grading_prompt or str(DEFAULT_AI_GRADING_PROMPT)) + "\n\n" + str(_(
        'Respond with a single JSON object with exactly two keys: '
        '"grade_percent" (a number from 0 to 100, the percentage of credit '
        'earned) and "feedback_text" (a string containing feedback for the '
        "student, written in RELATE-flavored Markdown). Do not include any "
        "other text outside of the JSON object."))

    parts = [f"# Rubric\n\n{page.rubric}"]

    if point_value is not None:
        parts.append(
            str(_("# Point value\n\nThis question is worth %.1f points."))
            % point_value)

    correct_answer = getattr(page, "correct_answer", None)
    if correct_answer:
        parts.append(f"# Reference/correct answer\n\n{correct_answer}")

    if calibration_examples:
        example_parts = [
                f"## Example {i+1}\n\n"
                f"Student answer:\n\n{ex.answer_text}\n\n"
                f"Grade given: {ex.grade_percent:.1f}%\n\n"
                f"Feedback given:\n\n{ex.feedback_text}"
                for i, ex in enumerate(calibration_examples)]
        parts.append(
                "# Previously graded examples for this question\n\n"
                "Use these to calibrate your grading standard and style.\n\n"
                + "\n\n".join(example_parts))

    student_answer_text = page.normalized_answer(
            page_context, page_data, answer_data)
    parts.append(
            "# Student answer to grade\n\n"
            + (student_answer_text or "(no answer provided)"))

    return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n\n".join(parts)},
            ]


def run_ai_grading_for_visit(
        course: Course,
        page: PageBaseWithHumanTextFeedback,
        page_context: PageContext,
        page_data: PageData,
        answer_data: AnswerData,
        point_value: float | None,
        grading_prompt: str | None,
        calibration_examples: Sequence[CalibrationExample],
        ) -> AIGradeResult:
    client = get_openai_client(course)

    model = course.ai_grading_model
    assert model

    messages = build_messages(
            page, page_context, page_data, answer_data, point_value,
            grading_prompt, calibration_examples)

    try:
        response = client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=messages)
    except Exception as exc:
        raise AIGradingError(
                _("AI grading request failed: %s") % exc) from exc

    content = response.choices[0].message.content
    if not content:
        raise AIGradingError(
                _("AI grading endpoint returned an empty response."))

    try:
        return AIGradeResult.model_validate_json(content)
    except ValidationError as exc:
        raise AIGradingError(
                _("AI grading endpoint returned a malformed response: %s")
                % exc) from exc


def create_ai_grade(
        visit: FlowPageVisit,
        page: PageBaseWithHumanTextFeedback,
        page_context: PageContext,
        course_commit_sha: RevisionID_ish,
        ai_result: AIGradeResult,
        ) -> FlowPageVisitGrade:
    """Save *ai_result* as a new, unreleased :class:`FlowPageVisitGrade`
    for *visit*.
    """

    grade_data: dict[str, Any] = {
            "released": False,
            "grade_percent": ai_result.grade_percent,
            "feedback_text": ai_result.feedback_text,
            "notes": str(_(
                "Drafted by an AI grading assistant on %(time)s. "
                "Review before releasing.")) % {
                    "time": now().isoformat(timespec="minutes")},
            }

    page_data = visit.page_data
    visit_page_data: PageData = page_data.data
    visit_answer: AnswerData = visit.answer

    feedback = page.grade(
            page_context, visit_page_data, visit_answer, grade_data)

    feedback_json: dict[str, Any] | None = None
    bulk_feedback_json: dict[str, Any] | None = None
    if feedback is not None:
        feedback_json, bulk_feedback_json = feedback.as_json()

    grade = FlowPageVisitGrade(
            visit=visit,
            grader=None,
            ai_generated_by=page_context.course.ai_grading_model,
            graded_at_git_commit_sha=serialize_revision(course_commit_sha),
            grade_data=grade_data,
            max_points=page.max_points(visit_page_data),
            correctness=feedback.correctness if feedback is not None else None,
            feedback=feedback_json)
    grade.save()

    update_bulk_feedback(page_data, grade, bulk_feedback_json)

    return grade
