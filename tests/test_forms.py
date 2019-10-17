from __future__ import division

__copyright__ = "Copyright (C) 2019 Isuru Fernando"

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

from django.test import TestCase

from course.forms import process_form_fields
from course.validation import ValidationError
from relate.utils import dict_to_struct


class CreateFormTest(TestCase):

    required_fields = [
        dict_to_struct({"id": "template_in", "type": "Text", "value": "spam"}),
        dict_to_struct({"id": "template_out", "type": "Text", "value": "spam"}),
    ]

    def test_fields_label(self):
        fields = [
            dict_to_struct({"id": "template_in", "type": "Text"}),
            dict_to_struct({"id": "template_out", "type": "Text", "label": "label"}),
        ]
        process_form_fields(fields, {})
        self.assertEqual(fields[0].label, "template_in")
        self.assertEqual(fields[1].label, "label")

    def test_fields_value(self):
        fields = [
            dict_to_struct({"id": "template_in", "type": "Text", "value": "spam"}),
            dict_to_struct({"id": "template_out", "type": "Choice",
                            "choices": ["choice1", "~DEFAULT~ choice2"]}),
        ]
        process_form_fields(fields, {})
        self.assertEqual(fields[0].value, "spam")
        self.assertEqual(fields[1].value, "choice2")
        self.assertEqual(fields[1].choices, ["choice1", "choice2"])

    def test_fields_assign_data(self):
        fields = [
            dict_to_struct({"id": "template_in", "type": "Text", "value": "spam"}),
            dict_to_struct({"id": "template_out", "type": "Choice",
                            "choices": ["choice1", "~DEFAULT~ choice2"]}),
            dict_to_struct({"id": "field0", "type": "Integer", "value": 2}),
            dict_to_struct({"id": "field1", "type": "Float", "value": 2.5}),
        ]
        process_form_fields(fields, {"template_in": "eggs",
                                     "template_out": "choice1",
                                     "field0": "1",
                                     "field1": "1.5",
                                     })
        self.assertEqual(fields[0].value, "eggs")
        self.assertEqual(fields[1].value, "choice1")
        self.assertEqual(fields[2].value, 1)
        self.assertEqual(fields[3].value, 1.5)

    def test_invalid_data(self):
        fields = [
            dict_to_struct({"id": "template_in", "type": "Text", "value": "spam"}),
            dict_to_struct({"id": "template_out", "type": "Text", "value": "spam"}),
            dict_to_struct({"id": "field0", "type": "Integer", "value": 2}),
        ]

        expected_error_msg = (
            "form field 'field0' value 'a' is not a 'Integer'.")
        with self.assertRaises(ValidationError) as cm:
            process_form_fields(fields, {"template_in": "eggs",
                                         "template_out": "choice1",
                                         "field0": "a",
                                         })
        self.assertIn(expected_error_msg, str(cm.exception))
