from __future__ import division

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
from django.test import TestCase
from django import forms
import unittest

from relate.utils import dict_to_struct

from course.validation import ValidationError

from course.page.text import (
    TextAnswerForm, get_validator_class, parse_validator, multiple_to_single_spaces,
    CaseSensitivePlainMatcher, PlainMatcher, RegexMatcher,
    CaseSensitiveRegexMatcher, SymbolicExpressionMatcher, float_or_sympy_evalf,
    FloatMatcher, get_matcher_class, parse_matcher_string, parse_matcher,
)

from tests.test_sandbox import (
    SingleCoursePageSandboxTestBaseMixin
)
from tests.constants import PAGE_ERRORS
from tests.utils import mock

TEXT_QUESTION_WITH_ANSWER_EXPLANATION_MARKDOWN = r"""
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
- <case_sens_regex>(?:operator\s+)?\s*map

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
- <case_sens_regex>(?:operator\s+)?\s*map


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
widget: unknown
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
        self.assertEqual(TextAnswerForm.get_text_widget("unkown"), (None, None))

    def test_validation_error(self):
        class SomeValidator1(object):
            def validate(self, s):
                raise forms.ValidationError("foo")

        class SomeValidator2(object):
            def validate(self, s):
                raise forms.ValidationError("bar")

        form = TextAnswerForm(
            read_only=False, interaction_mode="default",
            validators=[SomeValidator1(), SomeValidator2()],
            data={"answer": "some answer"})

        self.assertFalse(form.is_valid())
        self.assertIn("bar", form.errors['__all__'])


class GetValidatorClassTest(unittest.TestCase):
    # test get_validator_class
    def test_get_validator_class_unknown(self):
        unknown_type = "unknown"
        with self.assertRaises(ValidationError) as cm:
            get_validator_class("", unknown_type)
        self.assertIn("unknown validator type'unknown'", str(cm.exception))


class ParseValidatorTest(unittest.TestCase):
    # test parse_validator
    def test_parse_validator_not_struct(self):
        with self.assertRaises(ValidationError) as cm:
            parse_validator(None, "", "abcd")
        self.assertIn("must be struct", str(cm.exception))

    def test_parse_validator_no_type(self):
        with self.assertRaises(ValidationError) as cm:
            parse_validator(None, "", dict_to_struct({"id": "abcd"}))
        self.assertIn("matcher must supply 'type'", str(cm.exception))


class MultipleToSingleSpacesTest(unittest.TestCase):
    # test multiple_to_single_spaces
    def test_multiple_to_single_spaces(self):
        self.assertEqual(multiple_to_single_spaces(" abcd    ef"), "abcd ef")
        self.assertEqual(multiple_to_single_spaces(" abcd e  f"), "abcd e f")


class MatcherTest(unittest.TestCase):
    def test_case_sensitive_plain_matcher(self):
        # test CaseSensitivePlainMatcher
        pattern = "abcd e   f"
        matcher = CaseSensitivePlainMatcher(None, "", pattern)
        self.assertEqual(matcher.grade("abcdef"), 0)
        self.assertEqual(matcher.grade("abcd  e f  "), 1)
        self.assertEqual(matcher.correct_answer_text(), pattern)

    def test_case_plain_matcher(self):
        # test PlainMatcher
        pattern = "abcD e   f"
        matcher = PlainMatcher(None, "", pattern)
        self.assertEqual(matcher.grade("abcdEf"), 0)
        self.assertEqual(matcher.grade("ABCD  e f  "), 1)
        self.assertEqual(matcher.correct_answer_text(), pattern)

    def test_regex_matcher(self):
        # test RegexMatcher
        failed_pattern = "[\n"
        expected_error_msg = (
            "regex '[\n' did not compile: error: "
            "unterminated character set at position 0 (line 1, column 1)")
        with self.assertRaises(ValidationError) as cm:
            RegexMatcher(None, "", failed_pattern)
        self.assertIn(expected_error_msg, str(cm.exception))

        pattern = r"(?:linear\s+)?\s*map"
        matcher = RegexMatcher(None, "", pattern)
        self.assertEqual(matcher.grade("Linear map"), 1)
        self.assertEqual(matcher.grade("linear    MAP  "), 1)
        self.assertEqual(matcher.grade("linear "), 0)
        self.assertEqual(matcher.correct_answer_text(), None)

    def test_case_sensitive_regex_matcher(self):
        # test CaseSensitiveRegexMatcher
        failed_pattern = "[\n"
        expected_error_msg = (
            "regex '[\n' did not compile: error: "
            "unterminated character set at position 0 (line 1, column 1)")
        with self.assertRaises(ValidationError) as cm:
            CaseSensitiveRegexMatcher(None, "", failed_pattern)
        self.assertIn(expected_error_msg, str(cm.exception))

        pattern = r"(?:linear\s+)?\s*map"
        matcher = CaseSensitiveRegexMatcher(None, "", pattern)
        self.assertEqual(matcher.grade("linear map"), 1)
        self.assertEqual(matcher.grade("Linear map"), 0)
        self.assertEqual(matcher.grade("linear    MAP  "), 0)
        self.assertEqual(matcher.grade("linear "), 0)
        self.assertEqual(matcher.correct_answer_text(), None)


class SymbolicExpressionMatcherTest(unittest.TestCase):
    def test_symbolic_expression_matcher_pymbolic_import_error(self):
        with mock.patch.dict(sys.modules, {'pymbolic': None}):
            expected_warning = (
                "some_where: unable to check symbolic "
                "expression")
            mock_vctx = mock.MagicMock()
            SymbolicExpressionMatcher(mock_vctx, "some_where", "abcd")
            self.assertEqual(mock_vctx.add_warning.call_count, 1)
            self.assertIn(expected_warning, mock_vctx.add_warning.call_args[0][1])

            # no validation context
            SymbolicExpressionMatcher(None, "", "abcd")

    def test_symbolic_expression_matcher_validation_error(self):
        with mock.patch("pymbolic.parse") as mock_pymbolic_parse:
            expected_error_msg = "some error"
            mock_pymbolic_parse.side_effect = ValueError(expected_error_msg)
            with self.assertRaises(ValidationError) as cm:
                SymbolicExpressionMatcher(None, "", "abcd")
            self.assertIn(expected_error_msg, str(cm.exception))

    def test_symbolic_expression_matcher_validate(self):
        pattern = "1/A"
        matcher = SymbolicExpressionMatcher(None, "", pattern)
        matcher.validate("A^(-1)")
        with self.assertRaises(forms.ValidationError) as cm:
            matcher.validate("A^^(-1)")
        self.assertIn("ParseError: terminal expected, bitwisexor found "
                      "instead at index 2: ...^(-1)...']",
                      str(cm.exception))
        self.assertEqual(matcher.correct_answer_text(), pattern)

    def test_symbolic_expression_matcher_grade(self):
        matcher = SymbolicExpressionMatcher(None, "", "1/A")
        self.assertEqual(matcher.grade("A**(-1)"), 1)
        # case sensitive
        self.assertEqual(matcher.grade("a**(-1)"), 0)

        self.assertEqual(matcher.grade("A**(-2)"), 0)

        # parse_sympy error
        self.assertEqual(matcher.grade("A^^(-2)"), 0)

        # simplify error
        with mock.patch("sympy.simplify") as mock_simplify:
            mock_simplify.side_effect = ValueError("my simplify error")
            self.assertEqual(matcher.grade("abcd"), 0)


class FloatOrSympyEvalfTest(unittest.TestCase):
    # test float_or_sympy_evalf
    def test_float_or_sympy_evalf(self):

        # long int
        long_int = sys.maxsize + 1
        self.assertEqual(float_or_sympy_evalf(long_int), long_int)

        self.assertEqual(float_or_sympy_evalf(1), 1)
        self.assertEqual(float_or_sympy_evalf(-1), -1)
        self.assertEqual(float_or_sympy_evalf(0), 0)
        self.assertEqual(float_or_sympy_evalf(-0.2), -0.2)
        self.assertEqual(float_or_sympy_evalf(-0.333), -0.333)
        self.assertEqual(float_or_sympy_evalf("inf"), float("inf"))

    def test_float_or_sympy_evalf_value_empty(self):
        self.assertEqual(float_or_sympy_evalf(""), "")

    def test_float_or_sympy_evalf_value_error(self):
        expected_error_msg = "can't convert expression to float"
        with self.assertRaises(TypeError) as cm:
            float_or_sympy_evalf("abcd")
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_float_or_sympy_evalf_instance_error(self):
        expected_error_msg = ("expected string, int or float for floating "
                              "point literal")
        with self.assertRaises(TypeError) as cm:
            float_or_sympy_evalf([0.5])
        self.assertIn(expected_error_msg, str(cm.exception))


class FloatMatcherTest(unittest.TestCase):
    def test_float_matcher_struct_validation_error(self):
        # make sure validate_struct is called
        expected_error_msg = "not a key-value map"
        with self.assertRaises(ValidationError) as cm:
            FloatMatcher(None, "", "abcd")
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_float_matcher_value_error(self):
        expected_error_msg = "'value' does not provide a valid float literal"
        with self.assertRaises(ValidationError) as cm:
            FloatMatcher(None, "",
                         dict_to_struct({"type": "float", "value": "abcd"}))
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_float_matcher_rtol_error(self):
        expected_error_msg = "'rtol' does not provide a valid float literal"
        with self.assertRaises(ValidationError) as cm:
            FloatMatcher(None, "",
                         dict_to_struct(
                             {"type": "float",
                              "value": "1",
                              "rtol": "abcd"}))
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_float_matcher_value_zero_rtol_zero_error(self):
        expected_error_msg = "'rtol' not allowed when 'value' is zero"
        with self.assertRaises(ValidationError) as cm:
            FloatMatcher(None, "",
                         dict_to_struct(
                             {"type": "float",
                              "value": "0",
                              "rtol": "0"}))
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_float_matcher_atol_error(self):
        expected_error_msg = "'atol' does not provide a valid float literal"
        with self.assertRaises(ValidationError) as cm:
            FloatMatcher(None, "",
                         dict_to_struct(
                             {"type": "float",
                              "value": "1",
                              "atol": "abcd"}))
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_float_matcher_value_zero_atol_not_present_warning(self):
        mock_vctx = mock.MagicMock()
        expected_warning = ("Float match for 'value' zero should have "
                            "atol--otherwise it will match any number")
        FloatMatcher(mock_vctx, "some where",
                     dict_to_struct(
                         {"type": "float",
                          "value": "0"}))

        self.assertIn(expected_warning, mock_vctx.add_warning.call_args[0])

    def test_float_matcher_neither_atol_nor_rtol_present_warning(self):
        mock_vctx = mock.MagicMock()
        expected_warning = ("Float match should have either rtol or atol--"
                            "otherwise it will match any number")
        FloatMatcher(mock_vctx, "some where",
                     dict_to_struct(
                         {"type": "float",
                          "value": "1"}))
        self.assertIn(expected_warning, mock_vctx.add_warning.call_args[0])

    def test_float_matcher_validate(self):
        matcher = FloatMatcher(None, "",
                               dict_to_struct(
                                   {"type": "float",
                                    "value": "1",
                                    "atol": 0.01
                                    }))
        matcher.validate(1.1)

        expected_error_msg = "TypeError: can\'t convert expression to float"
        with self.assertRaises(forms.ValidationError) as cm:
            matcher.validate("abcd")
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_float_matcher_grade_atol(self):
        matcher = FloatMatcher(None, "",
                               dict_to_struct(
                                   {"type": "float",
                                    "value": "1",
                                    "atol": 0.01
                                    }))
        self.assertEqual(matcher.grade(""), 0)
        self.assertEqual(matcher.grade(0), 0)
        self.assertEqual(matcher.grade("abcd"), 0)

        self.assertEqual(matcher.grade(1), 1)
        self.assertEqual(matcher.grade(1.005), 1)
        self.assertEqual(matcher.grade(1.02), 0)

        self.assertEqual(matcher.grade(float("nan")), 0)
        self.assertEqual(matcher.grade(float("inf")), 0)

    def test_float_matcher_grade_rtol(self):
        matcher = FloatMatcher(None, "",
                               dict_to_struct(
                                   {"type": "float",
                                    "value": "100.1",
                                    "rtol": 0.01
                                    }))
        self.assertEqual(matcher.grade(""), 0)
        self.assertEqual(matcher.grade(0), 0)
        self.assertEqual(matcher.grade("abcd"), 0)

        self.assertEqual(matcher.grade(100), 1)
        self.assertEqual(matcher.grade(100.9), 1)
        self.assertEqual(matcher.grade(101.11), 0)
        self.assertEqual(matcher.correct_answer_text(), str(100.1))

        self.assertEqual(matcher.grade(float("nan")), 0)
        self.assertEqual(matcher.grade(float("inf")), 0)

    def test_float_matcher_grade_nan(self):
        matcher = FloatMatcher(None, "",
                               dict_to_struct(
                                   {"type": "float",
                                    "value": "nan",
                                    "rtol": 0.01
                                    }))

        self.assertEqual(matcher.grade(float("nan")), 1)
        self.assertEqual(matcher.grade(float("inf")), 0)
        self.assertEqual(matcher.grade(float("20.5")), 0)

    def test_float_matcher_grade_inf(self):
        matcher = FloatMatcher(None, "",
                               dict_to_struct(
                                   {"type": "float",
                                    "value": "inf",
                                    "rtol": 0.01
                                    }))

        self.assertEqual(matcher.grade(float("nan")), 0)
        self.assertEqual(matcher.grade(float("inf")), 1)
        self.assertEqual(matcher.grade(float("20.5")), 0)

    def test_float_matcher_grade_neither_rtol_nor_atol(self):
        matcher = FloatMatcher(None, "",
                               dict_to_struct(
                                   {"type": "float",
                                    "value": "20.1",
                                    }))
        self.assertEqual(matcher.grade(""), 0)
        self.assertEqual(matcher.grade("abcd"), 0)

        self.assertEqual(matcher.grade(20000), 1)
        self.assertEqual(matcher.grade(-2), 1)


class GetMatcherClassTest(unittest.TestCase):
    # test get_matcher_class
    def test_get_matcher_class(self):
        self.assertEqual(
            get_matcher_class("", matcher_type="plain",
                              pattern_type="string"),
            PlainMatcher)

    def test_get_matcher_class_validation_error(self):
        expected_error_msg = (
            "some where: PlainMatcher only accepts 'string' patterns")
        with self.assertRaises(ValidationError) as cm:
            get_matcher_class("some where", matcher_type="plain",
                              pattern_type="struct")
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_get_matcher_class_unknown_matcher_type_error(self):
        expected_error_msg = (
            "some where: unknown match type 'unknown'")
        with self.assertRaises(ValidationError) as cm:
            get_matcher_class("some where", matcher_type="unknown",
                              pattern_type="struct")
        self.assertIn(expected_error_msg, str(cm.exception))


class ParseMatcherStringTest(unittest.TestCase):
    def test_parse_matcher_string(self):
        s = "<plain>half"
        result = parse_matcher_string(None, "", s)
        self.assertTrue(isinstance(result, PlainMatcher))
        self.assertEqual(result.correct_answer_text(), "half")

    def test_parse_matcher_string_no_match(self):
        s = "<plain:half"
        with self.assertRaises(ValidationError) as cm:
            parse_matcher_string(None, "some where", s)
        self.assertIn("some where: does not specify match type",
                      str(cm.exception))

    def test_parse_matcher_string_deprecated(self):
        s = "plain:half"
        with mock.patch("course.validation.ValidationContext.add_warning",
                        autospec=True) as mock_vctx_add_warning:
            mock_vctx_add_warning.return_value = None
            result = parse_matcher_string(None, "", s)
            self.assertEqual(mock_vctx_add_warning.call_count, 0)
            self.assertTrue(isinstance(result, PlainMatcher))
            self.assertEqual(result.correct_answer_text(), "half")

        mock_vctx = mock.MagicMock()
        expected_warning = "uses deprecated 'matcher:answer' style"

        result = parse_matcher_string(mock_vctx, "some_where", s)
        self.assertIn(expected_warning, mock_vctx.add_warning.call_args[0])
        self.assertTrue(isinstance(result, PlainMatcher))
        self.assertEqual(result.correct_answer_text(), "half")


class ParseMatcherTest(unittest.TestCase):
    # test parse_matcher
    def test_parse_matcher_instance_is_string(self):
        s = "<plain>half"
        result = parse_matcher(None, "", s)
        self.assertTrue(isinstance(result, PlainMatcher))
        self.assertEqual(result.correct_answer_text(), "half")

    def test_parse_matcher_instance_is_struct(self):
        s = dict_to_struct(
            {"type": "float",
             "value": "20.1",
             })
        result = parse_matcher(None, "", s)
        self.assertTrue(isinstance(result, FloatMatcher))
        self.assertEqual(result.correct_answer_text(), "20.1")

    def test_parse_matcher_instance_is_struct_no_type_error(self):
        s = dict_to_struct(
            {"value": "20.1"})
        with self.assertRaises(ValidationError) as cm:
            parse_matcher(None, "some where", s)
        self.assertIn("some where: matcher must supply 'type'",
                      str(cm.exception))

    def test_parse_matcher_instance_not_supported(self):
        s = {"type": "float",
             "value": "20.1"}
        with self.assertRaises(ValidationError) as cm:
            parse_matcher(None, "some where", s)
        self.assertIn("some where: must be struct or string", str(cm.exception))


class TextQuestionTest(SingleCoursePageSandboxTestBaseMixin, TestCase):

    # {{{ test TextQuestionBase

    def test_text_question_base_validation(self):
        with mock.patch("course.page.text.TextAnswerForm.get_text_widget"
                        ) as mock_get_text_widget:
            mock_get_text_widget.return_value = None
            resp = self.get_page_sandbox_preview_response(
                TEXT_QUESTION_WITH_UNKNOWN_WIDGET_MARKDOWN)
            self.assertEqual(resp.status_code, 200)
            self.assertSandboxNotHasValidPage(resp)
            self.assertResponseContextContains(
                resp, PAGE_ERRORS, "unrecognized widget type'unknown'")
    # }}}

    # {{{ test TextQuestion

    def test_text_question_validation_no_answer(self):
        markdown = TEXT_QUESTION_WITH_NO_CORRECT_ANSWER_MARKDOWN
        expected_error_msg = "at least one answer must be provided"
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS, expected_error_msg)

    def test_text_question_validation_no_stringifiable_correct_answer(self):
        markdown = TEXT_QUESTION_WITH_NONE_STRINGIFIABLE_ANSWER_MARKDOWN
        expected_error_msg = (
            "no matcher is able to provide a plain-text correct answer")
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS, expected_error_msg)

    def test_text_question_with_answer_explanation(self):
        markdown = TEXT_QUESTION_WITH_ANSWER_EXPLANATION_MARKDOWN
        expected_html = '<p><a href="explanation">reference</a></p>'
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertResponseContextContains(resp, "correct_answer", expected_html)

    # }}}

    # {{{ test SurveyTextQuestion

    def test_correct_answer(self):
        markdown = SURVEY_TEXT_QUESTION_WITH_ANSWER_COMMENT
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxHasValidPage(resp)
        expected_html = '<p><a href="types.fear.com">reference</a></p>'
        self.assertResponseContextContains(resp, "correct_answer", expected_html)

    # }}}

# vim: fdm=marker
