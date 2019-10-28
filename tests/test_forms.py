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
import django.forms as forms

from course.forms import process_form_fields, CreateForm
from course.validation import ValidationError
from course.constants import participation_permission as pperm
from relate.utils import dict_to_struct
from tests import factories
from course.models import ParticipationRolePermission, ParticipationRole

from tests.base_test_mixins import SingleCourseTestMixin, MockAddMessageMixing


class CreateFormTest(TestCase):

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

    def test_reset(self):
        fields = [
            dict_to_struct({"id": "template_in", "type": "Text", "value": "spam"}),
            dict_to_struct({"id": "template_out", "type": "Text", "value": "eggs"}),
        ]
        process_form_fields(fields, {"reset": True, "template_in": "eggs"})
        self.assertEqual(fields[0].value, "spam")
        self.assertEqual(fields[1].value, "eggs")

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
        _ = CreateForm(fields)
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

    def test_create_form(self):
        fields = [
            dict_to_struct({"id": "template_in", "type": "Text", "value": "spam"}),
            dict_to_struct({"id": "template_out", "type": "Text",
                            "value": "out.yml"}),
            dict_to_struct({"id": "field0", "type": "Integer", "value": 2}),
            dict_to_struct({"id": "field1", "type": "Float", "value": 2.5}),
            dict_to_struct({"id": "field2", "type": "Choice",
                            "choices": ["choice1", "~DEFAULT~ choice2"]}),
            dict_to_struct({"id": "field3", "type": "Hidden", "value": 2}),
        ]
        process_form_fields(fields, {})
        form = CreateForm(fields)
        for field, ftype in [("field0", forms.IntegerField),
                             ("field1", forms.FloatField),
                             ("field2", forms.ChoiceField),
                             ("template_in", forms.CharField),
                             ("template_out", forms.CharField)]:
            self.assertIn(field, form.fields)
            self.assertIsInstance(form.fields[field], ftype)

        self.assertNotIn("field3", form.fields)
        # Check that template_out has id appended
        self.assertEqual(form.template_out, "out_{}.yml".format(form.id))
        self.assertIn(form.id, form.get_jinja_text()[0])


class FormsBase(SingleCourseTestMixin, MockAddMessageMixing, TestCase):

    initial_commit_sha = "f3e9d31a61714e759a6ea12b900b173accb753f5"
    form_title = b"Create an instant flow with one multiple choice question"

    def get_user_with_no_forms(self):
        # This user has no form with access, but has access to viewing the
        # forms list.
        limited_instructor = factories.UserFactory()
        limited_instructor_role = factories.ParticipationRoleFactory(
            course=self.course,
            identifier="limited_instructor"
        )
        participation = factories.ParticipationFactory(
            course=self.course,
            user=limited_instructor)
        participation.roles.set([limited_instructor_role])
        ParticipationRolePermission(role=limited_instructor_role,
                                    permission=pperm.use_forms).save()
        return limited_instructor


class ViewAllFormsTest(FormsBase):

    def test_student_no_form_access(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(self.get_view_all_forms_url())
            self.assertEqual(resp.status_code, 403)

    def test_use_forms_permission(self):
        with self.temporarily_switch_to_user(self.get_user_with_no_forms()):
            resp = self.c.get(self.get_view_all_forms_url())
            self.assertEqual(resp.status_code, 200)
            self.assertIn(self.form_title, resp.content)


class ViewFormTest(FormsBase):

    def test_student_no_form_access(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(self.get_view_form_url(form_id="instant"))
            self.assertEqual(resp.status_code, 403)

    def test_user_with_no_forms(self):
        with self.temporarily_switch_to_user(self.get_user_with_no_forms()):
            resp = self.c.get(self.get_view_form_url(form_id="instant"))
            self.assertEqual(resp.status_code, 403)

    def get_instructor_with_perm(self):
        role = ParticipationRole.objects.filter(
            identifier="instructor",
        ).first()
        ParticipationRolePermission(role=role,
                                    permission=pperm.use_forms).save()
        return self.instructor_participation.user

    def test_instructor_form_access(self):
        with self.temporarily_switch_to_user(self.get_instructor_with_perm()):
            resp = self.c.get(self.get_view_form_url(form_id="instant"))
            self.assertEqual(resp.status_code, 200)

    def test_form_reset(self):
        with self.temporarily_switch_to_user(self.get_instructor_with_perm()):
            from time import time
            new_duration = int(time())
            data = {"reset": "", "duration": new_duration}
            resp = self.c.post(self.get_view_form_url(form_id="instant"), data=data)
            self.assertEqual(resp.status_code, 200)
            self.assertNotIn(str(new_duration), resp.content.decode("utf-8"))
