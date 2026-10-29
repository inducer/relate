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

from typing import TYPE_CHECKING, Any, Literal

from django.utils.timezone import now
from django.utils.translation import gettext as _
from pydantic import BaseModel, Field

from course.constants import MAX_EXTRA_CREDIT_FACTOR
from course.grading import parse_points_specs, sum_points_specs
from course.models import FlowPageVisitGrade, update_bulk_feedback
from course.repo import serialize_revision


if TYPE_CHECKING:
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


DEFAULT_AI_GRADING_PROMPT = """
You are an experienced, fair, and detail-oriented teaching assistant
grading a student's answer to a course assignment question. Carefully
compare the student's answer against the rubric provided below, and
write feedback in RELATE-flavored Markdown (roughly GitHub-flavored
Markdown) explaining what was correct, what was missing or incorrect,
and how the grade was determined. Be specific and refer to the rubric.
If prior graded examples for this question are given, use them to
calibrate the standard and style of your grading, so that your
grading is consistent with what has already been done for other
students.
"""

SYSTEM_PROMPT = """
Respond with a single JSON object with exactly two keys:
"grade_percent" (a number from 0 to 100, the percentage of credit
earned, or the string "COMPUTED" as described below) and
"feedback_text" (a string containing feedback for the student,
written in RELATE-flavored Markdown). Do not include any other
text outside of the JSON object.\n\n
RELATE supports automatic point calculation using [pts:...] markers.
If the rubric contains these markers, you must use them: return an
updated version of the rubric as feedback_text, with every marker's
earned points filled in. Preserve the rubric's structure, all markers,
their denominators, and optional #identifiers. For example,
[pts:/2 #reasoning] becomes [pts:1/2 #reasoning] when one of two
points is earned. Markers without denominators (such as [pts:-1.5])
also contribute to the earned point total, including negative
contributions. If any rubric marker has a denominator, you must
return grade_percent: "COMPUTED"; RELATE will calculate the percentage
as 100 times the sum of all earned points divided by the sum of all
explicit denominators in feedback_text. Do not calculate or return a
numeric percentage yourself in that case. If no denominator is
present, return a numeric grade_percent. Explain deductions where
needed, but awarding full points suffices as feedback for correct
work; do not add laudatory verbiage.

Respond in the language used by the provided prompt, which indicates
the language in which the course is being offered.
"""


class _AIGradeResponse(BaseModel):
    grade_percent: float | Literal["COMPUTED"]
    feedback_text: str


class AIGradeResult(BaseModel):
    grade_percent: float = Field(ge=0, le=100*MAX_EXTRA_CREDIT_FACTOR)
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


def build_messages(
        page: PageBaseWithHumanTextFeedback,
        page_context: PageContext,
        page_data: PageData,
        answer_data: AnswerData,
        point_value: float | None,
        grading_prompt: str | None,
        ) -> list[ChatCompletionMessageParam]:
    system_prompt = (
        (grading_prompt or str(DEFAULT_AI_GRADING_PROMPT))
        + "\n\n"
        + str(SYSTEM_PROMPT))

    parts = [f"# Rubric\n\n{page.rubric}"]

    if point_value is not None:
        parts.append(
            str(_("# Point value\n\nThis question is worth %.1f points."))
            % point_value)

    correct_answer = getattr(page, "correct_answer", None)
    if correct_answer:
        parts.append(f"# Reference/correct answer\n\n{correct_answer}")

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
        ) -> AIGradeResult:
    client = get_openai_client(course)

    model = course.ai_grading_model
    assert model

    messages = build_messages(
            page, page_context, page_data, answer_data, point_value,
            grading_prompt)

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
        result = _AIGradeResponse.model_validate_json(content)
        rubric_specs = parse_points_specs(page.rubric or "")
        if (any(spec["maxPoints"] is not None for spec in rubric_specs)
                and result.grade_percent != "COMPUTED"):
            raise ValueError(
                    "Rubrics with point denominators require "
                    'grade_percent: "COMPUTED".')

        if result.grade_percent == "COMPUTED":
            totals = sum_points_specs(parse_points_specs(result.feedback_text))
            if totals["points"] is None or totals["maxPoints"] is None:
                raise ValueError(
                        "Computed grades require earned points and denominators "
                        "in the feedback rubric.")
            grade_percent = 100 * totals["points"] / totals["maxPoints"]
        else:
            grade_percent = result.grade_percent

        return AIGradeResult(
                grade_percent=grade_percent, feedback_text=result.feedback_text)
    except ValueError as exc:
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
