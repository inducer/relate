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
import sys
import unittest
from typing import TYPE_CHECKING, Literal

import pytest
from django import forms
from django.test import TestCase
from pydantic import BaseModel, ValidationError as PdValidationError

from course.page.text import (
    CaseSensitivePlainMatcher,
    FloatMatcher,
    Matcher,
    PlainMatcher,
    RegexMatcher,
    SymbolicExpressionMatcher,
    TextAnswerForm,
    TextValidatorBase,
    WidgetDesc,
    float_or_sympy_evalf,
    multiple_to_single_spaces,
)
from tests.constants import PAGE_ERRORS
from tests.test_sandbox import SingleCoursePageSandboxTestBaseMixin
from tests.utils import mock


if TYPE_CHECKING:
    from collections.abc import Mapping


TEXT_QUESTION_WITH_ANSWER_EXPLANATION_MARKDOWN = r"""
type: TextQuestion
id: eigvec
title: Eigenvectors
prompt: |

    # What's an eigenvector?

    Yadda ___________________ yadda.

answers:

- <plain>matrix
- <case_sens_plain>Eigenmatrix
- <regex>(?:linear\s+)?\s*map
- type: regex
  value: '(?:operator\s+)?\s*map'
  flags: []

answer_explanation: |

    [reference](explanation)

"""

TEXT_QUESTION_WITH_UNKNOWN_WIDGET_MARKDOWN = r"""
type: TextQuestion
id: eigvec
title: Eigenvectors
widget: unknown
prompt: |

    # What's an eigenvector?

    Yadda ___________________ yadda.

answers:

- <plain>matrix
- <case_sens_plain>Eigenmatrix
- <regex>(?:linear\s+)?\s*map
- type: regex
  value: '(?:operator\s+)?\s*map'
  flags: []

"""

TEXT_QUESTION_WITH_NO_CORRECT_ANSWER_MARKDOWN = """
type: TextQuestion
id: eigvec
title: Eigenvectors
widget: unknown
prompt: |

    # What's an eigenvector?

    Yadda ___________________ yadda.

answers: []

"""

TEXT_QUESTION_WITH_NONE_STRINGIFIABLE_ANSWER_MARKDOWN = r"""
type: TextQuestion
id: eigvec
title: Eigenvectors
prompt: |

    # What's an eigenvector?

    Yadda ___________________ yadda.

answers:

- <regex>(?:linear\s+)?\s*map

"""

SURVEY_TEXT_QUESTION_WITH_ANSWER_COMMENT = """
type: SurveyTextQuestion
id: fear
widget: textarea
prompt: |

    # Psychology Survey

    What's your biggest fear?

answer_comment:  |

    [reference](types.fear.com)

"""


class TextAnswerFormTest(unittest.TestCase):
    def test_unknown_widget_type(self):
        with pytest.raises(PdValidationError):
            assert TextAnswerForm.get_text_widget(
                                WidgetDesc.model_validate("unknown"))

    def test_validation_error(self):
        class SomeValidator1(TextValidatorBase):
            type: Literal["SomeValidator1"] = "SomeValidator1"

            def validate_text(self, s):
                raise forms.ValidationError("foo")

        class SomeValidator2(TextValidatorBase):
            type: Literal["SomeValidator2"] = "SomeValidator2"

            def validate_text(self, s):
                raise forms.ValidationError("bar")

        form = TextAnswerForm(
            widget_type=WidgetDesc(),
            read_only=False, interaction_mode="default",
            validators=[SomeValidator1(), SomeValidator2()],
            data={"answer": "some answer"},
            initial_text=None)

        self.assertFalse(form.is_valid())
        self.assertIn("bar", form.errors["__all__"])


class MultipleToSingleSpacesTest(unittest.TestCase):
    # test multiple_to_single_spaces
    def test_multiple_to_single_spaces(self):
        assert multiple_to_single_spaces(" abcd    ef") == "abcd ef"
        assert multiple_to_single_spaces(" abcd e  f") == "abcd e f"


class MatcherTest(unittest.TestCase):
    def test_case_sensitive_plain_matcher(self):
        # test CaseSensitivePlainMatcher
        pattern = "abcd e   f"
        matcher = CaseSensitivePlainMatcher.model_validate(
                {"type": "case_sens_plain", "value": pattern})
        assert matcher.grade("abcdef").correctness == 0
        assert matcher.grade("abcd  e f  ").correctness == 1
        assert matcher.correct_answer_text() == pattern

    def test_case_plain_matcher(self):
        # test PlainMatcher
        pattern = "abcD e   f"
        matcher = PlainMatcher.model_validate({"type": "plain", "value": pattern})
        assert matcher.grade("abcdEf").correctness == 0
        assert matcher.grade("ABCD  e f  ").correctness == 1
        assert matcher.correct_answer_text() == pattern

    def test_regex_matcher(self):
        # test RegexMatcher
        failed_pattern = "[\n"
        expected_error_msg = (
            "unterminated character set at position 0 (line 1, column 1)")
        with self.assertRaises(PdValidationError) as cm:
            RegexMatcher.model_validate(
                    {"type": "regex", "value": failed_pattern})
        self.assertIn(expected_error_msg, str(cm.exception))

        pattern = r"(?:linear\s+)?\s*map"
        matcher = RegexMatcher.model_validate({"value": pattern})
        assert matcher.grade("Linear map").correctness == 1
        assert matcher.grade("linear    MAP  ").correctness == 1
        assert matcher.grade("linear ").correctness == 0
        assert matcher.correct_answer_text() is None

    def test_case_sensitive_regex_matcher(self):
        pattern = r"(?:linear\s+)?\s*map"
        matcher = RegexMatcher.model_validate(
                                    {"value": pattern, "flags": []})
        assert matcher.grade("linear map").correctness == 1
        assert matcher.grade("Linear map").correctness == 0
        assert matcher.grade("linear    MAP  ").correctness == 0
        assert matcher.grade("linear ").correctness == 0
        assert matcher.correct_answer_text() is None


class SymbolicExpressionMatcherTest(unittest.TestCase):
    def test_symbolic_expression_matcher_validate(self):
        pattern = "1/A"
        matcher = SymbolicExpressionMatcher.model_validate(
                {"type": "sym_expr", "value": pattern})
        matcher.validate_text("A**(-1)")
        with self.assertRaises(forms.ValidationError) as cm:
            matcher.validate_text("A^^(-1)")
        self.assertIn("ParseError: terminal expected, bitwisexor found "
                      "instead at index 2: ...^(-1)...']",
                      str(cm.exception))
        assert matcher.correct_answer_text() == pattern

    def test_symbolic_expression_matcher_grade(self):
        matcher = SymbolicExpressionMatcher.model_validate(
                {"type": "sym_expr", "value": "1/A"})
        assert matcher.grade("A**(-1)").correctness == 1
        # case sensitive
        assert matcher.grade("a**(-1)").correctness == 0

        assert matcher.grade("A**(-2)").correctness == 0

        # parse_sympy error
        assert matcher.grade("A^^(-2)").correctness == 0

        # simplify error
        with mock.patch("sympy.simplify") as mock_simplify:
            mock_simplify.side_effect = ValueError("my simplify error")
            assert matcher.grade("abcd").correctness == 0


class FloatOrSympyEvalfTest(unittest.TestCase):
    # test float_or_sympy_evalf
    def test_float_or_sympy_evalf(self):

        # long int
        long_int = sys.maxsize + 1
        assert float_or_sympy_evalf(long_int) == long_int

        assert float_or_sympy_evalf(1) == 1
        assert float_or_sympy_evalf(-1) == -1
        assert float_or_sympy_evalf(0) == 0
        assert float_or_sympy_evalf(-0.2) == -0.2
        assert float_or_sympy_evalf(-0.333) == -0.333
        assert float_or_sympy_evalf("inf") == float("inf")

    def test_float_or_sympy_evalf_value_empty(self):
        with self.assertRaises(ValueError):
            float_or_sympy_evalf("")

    def test_float_or_sympy_evalf_value_error(self):
        expected_error_msg = "Cannot convert expression to float"
        with self.assertRaises(TypeError) as cm:
            float_or_sympy_evalf("abcd")
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_float_or_sympy_evalf_instance_error(self):
        expected_error_msg = ("expected string, int or float for floating "
                              "point literal")
        with self.assertRaises(TypeError) as cm:
            float_or_sympy_evalf([0.5])
        self.assertIn(expected_error_msg, str(cm.exception))


class MatcherTestContainer(BaseModel):
    desc: Matcher


def parse_matcher(s: str | Mapping[str, str | int]):
    return MatcherTestContainer.model_validate({"desc": s}).desc


class ParseMatcherStringTest(unittest.TestCase):
    def test_parse_matcher_string(self):
        s = "<plain>half"
        result = parse_matcher(s)
        self.assertTrue(isinstance(result, PlainMatcher))
        assert result.correct_answer_text() == "half"

    def test_parse_matcher_string_no_match(self):
        s = "<plain:half"
        with self.assertRaises(ValueError) as cm:
            parse_matcher(s)
        self.assertIn("Input should be a valid dictionary",
                      str(cm.exception))


class ParseMatcherTest(unittest.TestCase):
    # test parse_matcher
    def test_parse_matcher_instance_is_string(self):
        s = "<plain>half"
        result = parse_matcher(s)
        self.assertTrue(isinstance(result, PlainMatcher))
        assert result.correct_answer_text() == "half"

    def test_parse_matcher_instance_is_struct(self):
        s = {"type": "float",
             "value": "20.1",
             "atol": 0.1,
             }
        result = parse_matcher(s)
        self.assertTrue(isinstance(result, FloatMatcher))
        assert result.correct_answer_text() == "20.1"

    def test_parse_matcher_instance_is_struct_no_type_error(self):
        s = {"value": "20.1"}
        with self.assertRaises(PdValidationError) as cm:
            parse_matcher(s)
        self.assertIn("Unable to extract tag using discriminator 'type'",
                      str(cm.exception))


class TextQuestionTest(SingleCoursePageSandboxTestBaseMixin, TestCase):

    # {{{ test TextQuestionBase

    def test_text_question_base_validation(self):
        with mock.patch("course.page.text.TextAnswerForm.get_text_widget"
                        ) as mock_get_text_widget:
            mock_get_text_widget.return_value = None
            resp = self.get_page_sandbox_preview_response(
                TEXT_QUESTION_WITH_UNKNOWN_WIDGET_MARKDOWN)
            assert resp.status_code == 200
            self.assertSandboxNotHasValidPage(resp)
            self.assertResponseContextContains(
                resp, PAGE_ERRORS, "'unknown' is not a valid WidgetType")
    # }}}

    # {{{ test TextQuestion

    def test_text_question_validation_no_answer(self):
        markdown = TEXT_QUESTION_WITH_NO_CORRECT_ANSWER_MARKDOWN
        expected_error_msg = "TextQuestion.answers\n  Value error, may not be empty"
        resp = self.get_page_sandbox_preview_response(markdown)
        assert resp.status_code == 200
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS, expected_error_msg)

    def test_text_question_validation_no_stringifiable_correct_answer(self):
        markdown = TEXT_QUESTION_WITH_NONE_STRINGIFIABLE_ANSWER_MARKDOWN
        expected_error_msg = (
            "no matcher is able to provide a plain-text correct answer")
        resp = self.get_page_sandbox_preview_response(markdown)
        assert resp.status_code == 200
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS, expected_error_msg)

    def test_text_question_with_answer_explanation(self):
        markdown = TEXT_QUESTION_WITH_ANSWER_EXPLANATION_MARKDOWN
        expected_html = '<p><a href="explanation">reference</a></p>'
        resp = self.get_page_sandbox_preview_response(markdown)
        assert resp.status_code == 200
        self.assertSandboxHasValidPage(resp)
        self.assertResponseContextContains(resp, "correct_answer", expected_html)

    # }}}

    # {{{ test SurveyTextQuestion

    def test_correct_answer(self):
        markdown = SURVEY_TEXT_QUESTION_WITH_ANSWER_COMMENT
        resp = self.get_page_sandbox_preview_response(markdown)
        assert resp.status_code == 200
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxHasValidPage(resp)
        expected_html = '<p><a href="types.fear.com">reference</a></p>'
        self.assertResponseContextContains(resp, "correct_answer", expected_html)

    # }}}

# vim: fdm=marker
