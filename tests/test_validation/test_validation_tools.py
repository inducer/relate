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

import unittest

from course import validation
from course.validation import ValidationError
from course.content import dict_to_struct

from tests.utils import mock, suppress_stdout_decorator

location = "some_where"
vctx = mock.MagicMock()


class ValidationMixin(object):
    def setUp(self):
        self.addCleanup(vctx.reset_mock)


class ValidateIdentifierTest(ValidationMixin, unittest.TestCase):
    # test validation.validate_identifier

    def test_success(self):
        identifier = "identifier"
        validation.validate_identifier(
            vctx, location, identifier, warning_only=True)

        validation.validate_identifier(vctx, location, identifier)
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_id_re_not_matched(self):
        identifier = "test identifier"
        expected_error_msg = "invalid identifier '%s'" % identifier
        validation.validate_identifier(
            vctx, location, identifier, warning_only=True)
        self.assertEqual(vctx.add_warning.call_count, 1)
        self.assertIn(expected_error_msg, vctx.add_warning.call_args[0])
        with self.assertRaises(ValidationError) as cm:
            validation.validate_identifier(vctx, location, identifier)
        self.assertIn(expected_error_msg, str(cm.exception))


class ValidateRoleTest(ValidationMixin, unittest.TestCase):
    # test validation.validate_role

    def test_vctx_no_course(self):
        vctx.course = None
        validation.validate_role(vctx, location, "some_role")
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_role_not_found(self):
        vctx.course = mock.MagicMock()
        expected_error_msg = "invalid role 'some_role'"
        with mock.patch("course.models.ParticipationRole.objects.filter"
                        ) as mock_p_role_filter:
            mock_p_role_filter.return_value.values_list.return_value = [
                "role1", "role2"]
            with self.assertRaises(ValidationError) as cm:
                validation.validate_role(vctx, location, "some_role")
            self.assertIn(expected_error_msg, str(cm.exception))

    def test_success(self):
        vctx.course = mock.MagicMock()
        with mock.patch("course.models.ParticipationRole.objects.filter"
                        ) as mock_p_role_filter:
            mock_p_role_filter.return_value.values_list.return_value = [
                "role1", "role2"]
            validation.validate_role(vctx, location, "role1")


class ValidateFacilityTest(ValidationMixin, unittest.TestCase):
    # test validate_facility

    def test_validate_facility_no_facility(self):
        with mock.patch("course.utils.get_facilities_config") as mock_get_f:
            mock_get_f.return_value = None
            validation.validate_facility(vctx, location, "some_facility")

    def test_validate_facility_not_found(self):
        with mock.patch("course.utils.get_facilities_config") as mock_get_f:
            mock_get_f.return_value = ["f1", "f2"]
            expected_error_msg = (
                "Name of facility not recognized: 'some_facility'. "
                "Known facility names: 'f1, f2'")
            validation.validate_facility(vctx, location, "some_facility")
            self.assertIn(expected_error_msg, vctx.add_warning.call_args[0])

    def test_success(self):
        with mock.patch("course.utils.get_facilities_config") as mock_get_f:
            mock_get_f.return_value = ["f1", "f2"]
            validation.validate_facility(vctx, location, "f1")
            self.assertEqual(vctx.add_warning.call_count, 0)


class ValidateParticipationtagTest(ValidationMixin, unittest.TestCase):
    # test validate_participationtag
    # Todo: test memoize_in

    def test_vctx_no_course(self):
        vctx.course = None
        validation.validate_participationtag(vctx, location, "my_tag")
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_tag_not_found(self):
        vctx.course = mock.MagicMock()
        vctx.available_participation_tags = {}

        from functools import wraps

        def mock_decorator(*args, **kwargs):
            def decorator(f):
                @wraps(f)
                def decorated_function(*args, **kwargs):
                    return f(*args, **kwargs)

                return decorated_function

            return decorator

        with mock.patch(
                "course.models.ParticipationTag.objects.filter"
        ) as mock_p_tag_filter, mock.patch("pytools.memoize_in", mock_decorator):
            mock_p_tag_filter.return_value.values_list.return_value = [
                "tag1", "tag2"]
            validation.validate_participationtag(vctx, location, "my_tag")
            expected_error_msg = (
                "Name of participation tag not recognized: 'my_tag'. "
                "Known participation tag names: 'tag1, tag2'")
            self.assertIn(expected_error_msg, vctx.add_warning.call_args[0])

    def test_success(self):
        vctx.course = mock.MagicMock()
        vctx.available_participation_tags = {}

        from functools import wraps

        def mock_decorator(*args, **kwargs):
            def decorator(f):
                @wraps(f)
                def decorated_function(*args, **kwargs):
                    return f(*args, **kwargs)

                return decorated_function

            return decorator

        with mock.patch(
                "course.models.ParticipationTag.objects.filter"
        ) as mock_p_tag_filter, mock.patch("pytools.memoize_in", mock_decorator):
            mock_p_tag_filter.return_value.values_list.return_value = [
                "tag1", "tag2"]

            validation.validate_participationtag(vctx, location, "tag1")
            self.assertEqual(vctx.add_warning.call_count, 0)


required_attrs = [("ra1", int), ("ra2", str)]
allowed_attrs = [("aa1", float), ("aa2", bool), "aa3", ("aa4", "markup")]
rule1 = dict_to_struct({"ra1": 1, "ra2": "abcd"})
rule2 = dict_to_struct({"ra2": "abcd"})
rule3 = dict_to_struct(
    {"ra1": 1, "ra2": "abcd",
     "unknown1": "some_value", "unknown2": "some_value2"})
rule4 = dict_to_struct(
    {"ra1": 0.5, "ra2": "abcd"})
rule5 = dict_to_struct({"ra1": 1, "ra2": "abcd", "aa4": "[href](abcd)"})


class ValidateStructTest(ValidationMixin, unittest.TestCase):
    # test validation.validate_struct

    def test_target_not_struct(self):
        with self.assertRaises(ValidationError) as cm:
            validation.validate_struct(
                vctx, location, "some string", required_attrs, allowed_attrs)

        expected_error_msg = "not a key-value map"
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_success(self):
        with mock.patch("course.validation.validate_markup") as mock_val_markup:
            validation.validate_struct(
                vctx, location, rule1, required_attrs, allowed_attrs)
            self.assertEqual(mock_val_markup.call_count, 0)

            validation.validate_struct(
                vctx, location, rule5, required_attrs, allowed_attrs)
            self.assertEqual(mock_val_markup.call_count, 1)

    def test_required_missing(self):
        with self.assertRaises(ValidationError) as cm:
            validation.validate_struct(
                vctx, location, rule2, required_attrs, allowed_attrs)

        expected_error_msg = "attribute 'ra1' missing"
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_extraneous(self):
        with self.assertRaises(ValidationError) as cm:
            validation.validate_struct(
                vctx, location, rule3, required_attrs, allowed_attrs)

        expected_error_msg1 = "extraneous attribute(s) 'unknown1,unknown2'"
        expected_error_msg2 = "extraneous attribute(s) 'unknown2,unknown1'"
        self.assertTrue(
            expected_error_msg1 in str(cm.exception)
            or expected_error_msg2 in str(cm.exception))

    def test_instance_wrong(self):
        with self.assertRaises(ValidationError) as cm:
            validation.validate_struct(
                vctx, location, rule4, required_attrs, allowed_attrs)

        expected_error_msg = (
            "attribute 'ra1' has wrong type: got 'float', expected ")

        self.assertIn(expected_error_msg, str(cm.exception))


class ValidateMarkupTest(ValidationMixin, unittest.TestCase):
    # test validation.validate_markup

    def test_success(self):
        with mock.patch("course.content.markup_to_html") as mock_mth:
            mock_mth.return_value = None
            validation.validate_markup(vctx, location, "some string")

    @suppress_stdout_decorator(suppress_stderr=True)
    def test_markup_to_html_failure(self):
        with mock.patch("course.content.markup_to_html") as mock_mth:
            mock_mth.side_effect = RuntimeError("my error")
            with self.assertRaises(ValidationError) as cm:
                validation.validate_markup(
                    vctx, location, "some problematic string")

            expected_error_msg = ("RuntimeError: my error")
            self.assertIn(expected_error_msg, str(cm.exception))


chunk_rule2_dict = {
    "weight": 1,
    "if_after": "some_date1",
    "if_before": "some_date2",
    "if_in_facility": "some_facility",
    "if_has_role": ["r1", "r2"],
    "if_has_participation_tags_any": ["tag1", "tag2"],
    "if_has_participation_tags_all": ["tag3", "tag4"],
}
chunk_rule3 = dict_to_struct({
    "weight": 1,
    "if_after": "some_date1",
    "if_before": "some_date2",
    "if_in_facility": "some_facility",
    "if_has_role": ["r1", "r2"],
    "if_has_participation_tags_any": ["tag1", "tag2"],
    "if_has_participation_tags_all": ["tag3", "tag4"],
})


class ValidateChunkRuleTest(ValidationMixin, unittest.TestCase):
    # test validation.validate_chunk_rule

    chunk_rule_dict_base = {"weight": 1}

    def get_updated_rule(self, **kwargs):
        rule = self.chunk_rule_dict_base.copy()
        rule.update(kwargs)
        return dict_to_struct(rule)

    def test_base_success(self):
        with mock.patch("course.validation.validate_struct") as mock_val_func:
            validation.validate_chunk_rule(
                vctx, location, self.get_updated_rule())
            self.assertEqual(mock_val_func.call_count, 1)

    def test_encounter_datespec_call(self):
        validation.validate_chunk_rule(
            vctx, location,
            self.get_updated_rule(if_after="some_date1"))
        self.assertEqual(vctx.encounter_datespec.call_count, 1)

        vctx.reset_mock()

        validation.validate_chunk_rule(
            vctx, location,
            self.get_updated_rule(if_before="some_date1"))
        self.assertEqual(vctx.encounter_datespec.call_count, 1)

    def test_if_has_role(self):
        with mock.patch("course.validation.validate_role") as mock_val_func:
            validation.validate_chunk_rule(
                vctx, location,
                self.get_updated_rule(if_has_role=["r1", "r2"]))
            self.assertEqual(mock_val_func.call_count, 2)

    def test_if_has_participation_tags_any(self):
        with mock.patch("course.validation.validate_participationtag"
                        ) as mock_val_func:
            validation.validate_chunk_rule(
                vctx, location,
                self.get_updated_rule(
                    if_has_participation_tags_any=["tag1", "tag2", "tag3"]))
            self.assertEqual(mock_val_func.call_count, 3)

    def test_if_has_participation_tags_all(self):
        with mock.patch("course.validation.validate_participationtag"
                        ) as mock_val_func:
            validation.validate_chunk_rule(
                vctx, location,
                self.get_updated_rule(
                    if_has_participation_tags_all=["tag1", "tag2"]))
            self.assertEqual(mock_val_func.call_count, 2)

    def test_if_in_facility(self):
        with mock.patch("course.validation.validate_facility"
                        ) as mock_val_func:
            validation.validate_chunk_rule(
                vctx, location,
                self.get_updated_rule(
                    if_in_facility="some_facility"))
            self.assertEqual(mock_val_func.call_count, 1)

    def test_deprecated_time_attribute(self):
        expected_error_msg = ("Uses deprecated 'start' attribute--"
                              "use 'if_after' instead")
        validation.validate_chunk_rule(
            vctx, location,
            self.get_updated_rule(start="some_time"))
        self.assertIn(expected_error_msg, vctx.add_warning.call_args[0])

        vctx.reset_mock()

        expected_error_msg = ("Uses deprecated 'end' attribute--"
                              "use 'if_before' instead")
        validation.validate_chunk_rule(
            vctx, location,
            self.get_updated_rule(end="some_time"))
        self.assertIn(expected_error_msg, vctx.add_warning.call_args[0])

    def test_deprecated_roles(self):
        expected_error_msg = ("Uses deprecated 'roles' attribute--"
                              "use 'if_has_role' instead")

        with mock.patch("course.validation.validate_role") as mock_val_func:
            validation.validate_chunk_rule(
                vctx, location,
                self.get_updated_rule(
                    roles=["r1", "r2", "r3"]))
            self.assertEqual(mock_val_func.call_count, 3)
            self.assertIn(expected_error_msg, vctx.add_warning.call_args[0])


class ValidatePageChunkTest(ValidationMixin, unittest.TestCase):
    def get_updated_rule(self, **kwargs):
        rule = {"id": "my_id", "content": "some content"}
        rule.update(kwargs)
        return dict_to_struct(rule)

    def test_success(self):
        with mock.patch("course.validation.validate_struct"
                        ) as mock_vs, mock.patch(
            "course.content.extract_title_from_markup"
        ) as mock_etfm, mock.patch(
            "course.validation.validate_chunk_rule"
        ) as mock_vcr, mock.patch(
            "course.validation.validate_markup"
        ) as mock_vm:
            validation.validate_page_chunk(
                vctx, location,
                self.get_updated_rule(
                    title="The title"))
            self.assertEqual(mock_vs.call_count, 1)
            self.assertEqual(mock_etfm.call_count, 0)
            self.assertEqual(mock_vcr.call_count, 0)
            self.assertEqual(mock_vm.call_count, 1)

    def test_not_title(self):
        with mock.patch("course.validation.validate_struct"
                        ) as mock_vs, mock.patch(
            "course.content.extract_title_from_markup"
        ) as mock_etfm, mock.patch(
            "course.validation.validate_chunk_rule"
        ) as mock_vcr, mock.patch(
            "course.validation.validate_markup"
        ) as mock_vm:
            mock_etfm.return_value = None

            with self.assertRaises(ValidationError) as cm:
                validation.validate_page_chunk(
                    vctx, location,
                    self.get_updated_rule())

            expected_error_msg = "no title present"
            self.assertIn(expected_error_msg, str(cm.exception))

            self.assertEqual(mock_vs.call_count, 1)
            self.assertEqual(mock_etfm.call_count, 1)

            self.assertEqual(mock_vcr.call_count, 0)
            self.assertEqual(mock_vm.call_count, 0)

    def test_chunk_has_rule(self):
        with mock.patch("course.validation.validate_struct"
                        ) as mock_vs, mock.patch(
            "course.content.extract_title_from_markup"
        ) as mock_etfm, mock.patch(
            "course.validation.validate_chunk_rule"
        ) as mock_vcr, mock.patch(
            "course.validation.validate_markup"
        ) as mock_vm:
            mock_etfm.return_value = "Some title"

            validation.validate_page_chunk(
                vctx, location,
                self.get_updated_rule(rules=["r1", "r2", "r3"]))

            self.assertEqual(mock_vs.call_count, 1)
            self.assertEqual(mock_etfm.call_count, 1)

            self.assertEqual(mock_vcr.call_count, 3)
            self.assertEqual(mock_vm.call_count, 1)
