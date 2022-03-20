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
import stat
import hashlib
from dulwich.repo import Tree
from django.test import TestCase

from course import validation
from course.validation import ValidationError
from course.content import dict_to_struct
from course.constants import (
    flow_permission, grade_aggregation_strategy, ATTRIBUTES_FILENAME)

from tests.utils import mock, suppress_stdout_decorator
from tests.base_test_mixins import CoursesTestMixinBase
from tests import factories


location = "some_where"
vctx = mock.MagicMock()
vctx.repo = mock.MagicMock()


class ValidationTestMixin:
    def setUp(self):
        super().setUp()
        self.addCleanup(vctx.reset_mock)


class ValidateIdentifierTest(ValidationTestMixin, unittest.TestCase):
    # test validation.validate_identifier

    def test_success(self):
        identifier = "identifier"
        validation.validate_identifier(
            vctx, location, identifier, warning_only=True)

        validation.validate_identifier(vctx, location, identifier)
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_id_re_not_matched(self):
        identifier = "test identifier"
        expected_warn_msg = expected_error_msg = (
            "invalid identifier '%s'" % identifier)
        validation.validate_identifier(
            vctx, location, identifier, warning_only=True)
        self.assertEqual(vctx.add_warning.call_count, 1)
        self.assertIn(expected_warn_msg, vctx.add_warning.call_args[0])
        with self.assertRaises(ValidationError) as cm:
            validation.validate_identifier(vctx, location, identifier)
        self.assertIn(expected_error_msg, str(cm.exception))


class ValidateRoleTest(ValidationTestMixin, CoursesTestMixinBase, TestCase):
    # test validation.validate_role

    def setUp(self):
        super().setUp()
        course = factories.CourseFactory()
        vctx.course = course
        factories.ParticipationRoleFactory(course=course, identifier="role1")
        factories.ParticipationRoleFactory(course=course, identifier="role2")

    def test_vctx_no_course(self):
        vctx.course = None
        validation.validate_role(vctx, location, "some_role")
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_success(self):
        validation.validate_role(vctx, location, "role1")

    def test_role_not_found(self):
        expected_error_msg = "invalid role 'some_role'"
        with self.assertRaises(ValidationError) as cm:
            validation.validate_role(vctx, location, "some_role")
        self.assertIn(expected_error_msg, str(cm.exception))


class ValidateFacilityTest(ValidationTestMixin, unittest.TestCase):
    # test validate_facility

    def test_validate_facility_no_facility(self):
        with mock.patch("course.utils.get_facilities_config") as mock_get_f:
            mock_get_f.return_value = None
            validation.validate_facility(vctx, location, "some_facility")

    def test_validate_facility_not_found(self):
        with mock.patch("course.utils.get_facilities_config") as mock_get_f:
            mock_get_f.return_value = ["f1", "f2"]
            expected_warn_msg = (
                "Name of facility not recognized: 'some_facility'. "
                "Known facility names: 'f1, f2'")
            validation.validate_facility(vctx, location, "some_facility")
            self.assertIn(expected_warn_msg, vctx.add_warning.call_args[0])

    def test_success(self):
        with mock.patch("course.utils.get_facilities_config") as mock_get_f:
            mock_get_f.return_value = ["f1", "f2"]
            validation.validate_facility(vctx, location, "f1")
            self.assertEqual(vctx.add_warning.call_count, 0)


class ValidateParticipationtagTest(CoursesTestMixinBase, TestCase):
    # test validate_participationtag

    def setUp(self):
        # we don't use mock vctx, because there is a memoize_in decorator
        # which won't function when the vctx itself is mocked.
        super().setUp()
        course = factories.CourseFactory()

        repo = mock.MagicMock()
        self.vctx = validation.ValidationContext(repo, "some_sha", course)

        factories.ParticipationTagFactory(course=course, name="tag1")
        factories.ParticipationTagFactory(course=course, name="tag2")

    def test_vctx_no_course(self):
        self.vctx.course = None
        with mock.patch(
                "course.validation.ValidationContext.add_warning") as mock_add_warn:
            validation.validate_participationtag(self.vctx, location, "my_tag")
            self.assertEqual(mock_add_warn.call_count, 0)

    def test_tag_not_found(self):
        with mock.patch(
                "course.validation.ValidationContext.add_warning") as mock_add_warn:
            validation.validate_participationtag(self.vctx, location, "my_tag")
            expected_warn_msg = (
                "Name of participation tag not recognized: 'my_tag'. "
                "Known participation tag names: 'tag1, tag2'")
            self.assertIn(expected_warn_msg, mock_add_warn.call_args[0])

    def test_success_and_memoized(self):
        with mock.patch(
                "course.validation.ValidationContext.add_warning") as mock_add_warn:
            validation.validate_participationtag(self.vctx, location, "tag1")
            self.assertEqual(mock_add_warn.call_count, 0)

        with mock.patch(
                "course.models.ParticipationTag.objects.filter"
        ) as mock_ptag_filter_func:
            validation.validate_participationtag(self.vctx, location, "tag2")
            self.assertEqual(mock_ptag_filter_func.call_count, 0)


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


class ValidateStructTest(ValidationTestMixin, unittest.TestCase):
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


class ValidateMarkupTest(ValidationTestMixin, unittest.TestCase):
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


class ValidateChunkRuleTest(ValidationTestMixin, unittest.TestCase):
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
        expected_warn_msg = ("Uses deprecated 'start' attribute--"
                             "use 'if_after' instead")
        validation.validate_chunk_rule(
            vctx, location,
            self.get_updated_rule(start="some_time"))
        self.assertIn(expected_warn_msg, vctx.add_warning.call_args[0])

        vctx.reset_mock()

        expected_warn_msg = ("Uses deprecated 'end' attribute--"
                             "use 'if_before' instead")
        validation.validate_chunk_rule(
            vctx, location,
            self.get_updated_rule(end="some_time"))
        self.assertIn(expected_warn_msg, vctx.add_warning.call_args[0])

    def test_deprecated_roles(self):
        expected_warn_msg = ("Uses deprecated 'roles' attribute--"
                             "use 'if_has_role' instead")

        with mock.patch("course.validation.validate_role") as mock_val_func:
            validation.validate_chunk_rule(
                vctx, location,
                self.get_updated_rule(
                    roles=["r1", "r2", "r3"]))
            self.assertEqual(mock_val_func.call_count, 3)
            self.assertIn(expected_warn_msg, vctx.add_warning.call_args[0])


class ValidatePageChunkTest(ValidationTestMixin, unittest.TestCase):
    def get_updated_chunk(self, **kwargs):
        chunk = {"id": "my_id", "content": "some content"}
        chunk.update(kwargs)
        return dict_to_struct(chunk)

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
                self.get_updated_chunk(
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
                    self.get_updated_chunk())

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
                self.get_updated_chunk(rules=["r1", "r2", "r3"]))

            self.assertEqual(mock_vs.call_count, 1)
            self.assertEqual(mock_etfm.call_count, 1)

            self.assertEqual(mock_vcr.call_count, 3)
            self.assertEqual(mock_vm.call_count, 1)


class ValidateStaticpageDesc(ValidationTestMixin, unittest.TestCase):
    # test validation.validate_staticpage_desc

    def get_updated_page_desc(self, **kwargs):
        page_desc = {}
        page_desc.update(kwargs)
        return dict_to_struct(page_desc)

    def test_success_with_content(self):
        with mock.patch("course.validation.validate_struct"
                        ) as mock_vs, mock.patch(
            "course.validation.validate_page_chunk"
        ) as mock_vpc:
            validation.validate_staticpage_desc(
                vctx, location,
                self.get_updated_page_desc(content="blabla"))

            self.assertEqual(mock_vs.call_count, 1)
            self.assertEqual(mock_vpc.call_count, 1)

    def test_success_with_chunks(self):
        with mock.patch("course.validation.validate_struct"
                        ) as mock_vs, mock.patch(
            "course.content.normalize_page_desc"
        ) as mock_npd, mock.patch(
            "course.validation.validate_page_chunk"
        ) as mock_vpc:
            validation.validate_staticpage_desc(
                vctx, location,
                self.get_updated_page_desc(
                    chunks=(
                        dict_to_struct(
                            {"id": "my_id", "content": "some content"}),
                        dict_to_struct(
                            {"id": "my_id2", "content": "some content2"}),
                        dict_to_struct(
                            {"id": "my_id3", "content": "some content2"}),
                    )
                ))

            self.assertEqual(mock_vs.call_count, 1)
            self.assertEqual(mock_npd.call_count, 0)
            self.assertEqual(mock_vpc.call_count, 3)

    def test_neither_chunks_nor_content(self):
        with mock.patch("course.validation.validate_struct"
                        ) as mock_vs, mock.patch(
            "course.content.normalize_page_desc"
        ) as mock_npd, mock.patch(
            "course.validation.validate_page_chunk"
        ) as mock_vpc:
            with self.assertRaises(ValidationError) as cm:
                validation.validate_staticpage_desc(
                    vctx, location,
                    self.get_updated_page_desc())

            expected_error_msg = "must have either 'chunks' or 'content'"
            self.assertIn(expected_error_msg, str(cm.exception))

            self.assertEqual(mock_vs.call_count, 1)
            self.assertEqual(mock_npd.call_count, 0)
            self.assertEqual(mock_vpc.call_count, 0)

    def test_both_chunks_and_content(self):
        with mock.patch("course.validation.validate_struct"
                        ) as mock_vs, mock.patch(
            "course.content.normalize_page_desc"
        ) as mock_npd, mock.patch(
            "course.validation.validate_page_chunk"
        ) as mock_vpc:
            with self.assertRaises(ValidationError) as cm:
                validation.validate_staticpage_desc(
                    vctx, location,
                    self.get_updated_page_desc(chunks="blabla", content="blabal2"))

            expected_error_msg = "must have either 'chunks' or 'content'"
            self.assertIn(expected_error_msg, str(cm.exception))

            self.assertEqual(mock_vs.call_count, 1)
            self.assertEqual(mock_npd.call_count, 0)
            self.assertEqual(mock_vpc.call_count, 0)

    def test_success_with_chunks_id_not_unique(self):
        with mock.patch("course.validation.validate_struct"
                        ) as mock_vs, mock.patch(
            "course.content.normalize_page_desc"
        ) as mock_npd, mock.patch(
            "course.validation.validate_page_chunk"
        ) as mock_vpc:
            with self.assertRaises(ValidationError) as cm:
                validation.validate_staticpage_desc(
                    vctx, location,
                    self.get_updated_page_desc(
                        chunks=(
                            dict_to_struct(
                                {"id": "my_id", "content": "some content"}),
                            dict_to_struct(
                                {"id": "my_id2", "content": "some content2"}),
                            dict_to_struct(
                                {"id": "my_id2", "content": "some content2"}),
                        )
                    ))

            expected_error_msg = "chunk id 'my_id2' not unique"
            self.assertIn(expected_error_msg, str(cm.exception))

            self.assertEqual(mock_vs.call_count, 1)
            self.assertEqual(mock_vpc.call_count, 3)
            self.assertEqual(mock_npd.call_count, 0)


class FakeCustomRepoPageType1:
    def __init__(self, vctx, location, page_desc):
        return


class FakePageType1:
    def __init__(self, vctx, location, page_desc):
        raise ValidationError("This is a faked validation error")


class FakePageType2:
    def __init__(self, vctx, location, page_desc):
        raise RuntimeError("This is a faked RuntimeError")


class ValidateFlowPageTest(ValidationTestMixin, unittest.TestCase):
    # test validation.validate_flow_page

    def get_updated_page_desc(self, **kwargs):
        page_desc = {"id": "my_page_id"}
        page_desc.update(kwargs)
        return dict_to_struct(page_desc)

    def test_no_id(self):
        with self.assertRaises(ValidationError) as cm:
            validation.validate_flow_page(vctx, location, dict_to_struct({}))
        expected_error_msg = "flow page has no ID"
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_flow_page_fail_validation(self):
        with mock.patch("course.validation.validate_identifier"
                        ) as mock_vi, mock.patch(
            "course.content.get_flow_page_class"
        ) as mock_gfpc:
            mock_vi.return_value = None
            mock_gfpc.return_value = FakePageType1

            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_page(
                    vctx, location,
                    self.get_updated_page_desc(type="PageType1"))

            expected_error_msg = (
                "This is a faked validation error")
            self.assertIn(expected_error_msg, str(cm.exception))

    def test_flow_page_instantiate_error(self):
        with mock.patch("course.validation.validate_identifier"
                        ) as mock_vi, mock.patch(
            "course.content.get_flow_page_class"
        ) as mock_gfpc:
            mock_vi.return_value = None
            mock_gfpc.return_value = FakePageType2

            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_page(
                    vctx, location,
                    self.get_updated_page_desc(type="PageType2"))

            expected_error_msg = (
                "could not instantiate flow page: RuntimeError: This is a "
                "faked RuntimeError")
            self.assertIn(expected_error_msg, str(cm.exception))


class ValidateFlowGroupTest(ValidationTestMixin, unittest.TestCase):
    # test validation.validate_flow_group

    def get_updated_group(self, **kwargs):
        group_desc = {"id": "my_page_id",
                      "pages": [
                          dict_to_struct({"id": "page1"}),
                          dict_to_struct({"id": "page2"}),
                      ]}
        group_desc.update(kwargs)
        return dict_to_struct(group_desc)

    def test_success(self):
        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_flow_page"
        ) as mock_vfp, mock.patch(
            "course.validation.validate_identifier"
        ) as mock_vi:
            mock_vs.return_value = None
            mock_vfp.return_value = None
            mock_vi.return_value = None

            validation.validate_flow_group(
                vctx, location,
                self.get_updated_group()
            )

            self.assertEqual(mock_vs.call_count, 1)
            self.assertEqual(mock_vfp.call_count, 2)
            self.assertEqual(mock_vi.call_count, 1)

            self.assertIn("my_page_id", mock_vi.call_args[0])

    def test_empty_group(self):
        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_flow_page"
        ) as mock_vfp, mock.patch(
            "course.validation.validate_identifier"
        ) as mock_vi:
            mock_vs.return_value = None
            mock_vfp.return_value = None
            mock_vi.return_value = None

            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_group(
                    vctx, location,
                    self.get_updated_group(pages=[])
                )

            expected_error_msg = (
                "group 'my_page_id': group is empty")
            self.assertIn(expected_error_msg, str(cm.exception))

            self.assertEqual(mock_vs.call_count, 1)
            self.assertEqual(mock_vfp.call_count, 0)

    def test_empty_non_positive_max_page_count(self):
        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_flow_page"
        ) as mock_vfp, mock.patch(
            "course.validation.validate_identifier"
        ) as mock_vi:
            mock_vs.return_value = None
            mock_vfp.return_value = None
            mock_vi.return_value = None

            expected_error_msg = (
                "group 'my_page_id': max_page_count is not positive")

            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_group(
                    vctx, location,
                    self.get_updated_group(max_page_count=0)
                )
            self.assertIn(expected_error_msg, str(cm.exception))

            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_group(
                    vctx, location,
                    self.get_updated_group(max_page_count=-2)
                )
            self.assertIn(expected_error_msg, str(cm.exception))

    def test_pages_in_group_id_not_unique(self):
        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_flow_page"
        ) as mock_vfp, mock.patch(
            "course.validation.validate_identifier"
        ) as mock_vi:
            mock_vs.return_value = None
            mock_vfp.return_value = None
            mock_vi.return_value = None

            expected_error_msg = ("page id 'page2' not unique")

            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_group(
                    vctx, location,
                    self.get_updated_group(pages=[
                        dict_to_struct({"id": "page1"}),
                        dict_to_struct({"id": "page2"}),
                        dict_to_struct({"id": "page2"}),
                    ])
                )
            self.assertIn(expected_error_msg, str(cm.exception))

    def test_max_page_count_with_shuffle_not_given(self):
        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_flow_page"
        ) as mock_vfp, mock.patch(
            "course.validation.validate_identifier"
        ) as mock_vi:
            mock_vs.return_value = None
            mock_vfp.return_value = None
            mock_vi.return_value = None

            validation.validate_flow_group(
                vctx, location,
                self.get_updated_group(max_page_count=1, shuffle=True)
            )
            self.assertEqual(vctx.add_warning.call_count, 0)

            expected_warn_msg = (
                "shuffle attribute will be required for groups with"
                "max_page_count in a future version. set "
                "'shuffle: False' to match current behavior.")

            validation.validate_flow_group(
                vctx, location,
                self.get_updated_group(max_page_count=1)
            )
            self.assertIn(expected_warn_msg, vctx.add_warning.call_args[0])
            vctx.add_warning.reset_mock()


class ValidateSessionStartRuleTest(ValidationTestMixin, unittest.TestCase):
    # test validation.validate_session_start_rule

    def get_updated_nrule(self, no_may_start_new_session=False,
                          no_may_list_existing_sessions=False, **kwargs):
        rule = {}
        if not no_may_start_new_session:
            rule["may_start_new_session"] = True
        if not no_may_list_existing_sessions:
            rule["may_list_existing_sessions"] = True
        rule.update(kwargs)
        return dict_to_struct(rule)

    def get_updated_tags(self, extra=None):
        tags = []

        if extra is not None:
            assert isinstance(extra, list)
        else:
            extra = []

        tags.extend(extra)
        return tags

    def test_success(self):
        validation.validate_session_start_rule(
            vctx, location, self.get_updated_nrule(), self.get_updated_tags())

        validation.validate_session_start_rule(
            vctx, location, self.get_updated_nrule(
                may_start_new_session=False), self.get_updated_tags())
        validation.validate_session_start_rule(
            vctx, location, self.get_updated_nrule(
                may_start_new_session=True), self.get_updated_tags())

        validation.validate_session_start_rule(
            vctx, location, self.get_updated_nrule(
                may_list_existing_sessions=False), self.get_updated_tags())
        validation.validate_session_start_rule(
            vctx, location, self.get_updated_nrule(
                may_list_existing_sessions=True), self.get_updated_tags())

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_success_may_start_new_session_not_present(self):
        validation.validate_session_start_rule(
            vctx, location,
            self.get_updated_nrule(no_may_start_new_session=True),
            self.get_updated_tags())

        expected_warn_msg = (
            "attribute 'may_start_new_session' is not present")
        self.assertIn(expected_warn_msg, vctx.add_warning.call_args[0])

    def test_success_may_list_existing_sessions_not_present(self):
        validation.validate_session_start_rule(
            vctx, location,
            self.get_updated_nrule(no_may_list_existing_sessions=True),
            self.get_updated_tags())

        expected_warn_msg = (
            "attribute 'may_list_existing_sessions' is not present")
        self.assertIn(expected_warn_msg, vctx.add_warning.call_args[0])

    def test_if_after(self):
        datespec = "some_time1"
        kwargs = {
            "if_after": datespec
        }
        validation.validate_session_start_rule(
            vctx, location,
            self.get_updated_nrule(**kwargs),
            self.get_updated_tags())

        self.assertEqual(vctx.encounter_datespec.call_count, 1)
        self.assertIn(datespec, vctx.encounter_datespec.call_args[0])

    def test_if_before(self):
        datespec = "some_time2"
        kwargs = {
            "if_before": datespec
        }
        validation.validate_session_start_rule(
            vctx, location,
            self.get_updated_nrule(**kwargs),
            self.get_updated_tags())

        self.assertEqual(vctx.encounter_datespec.call_count, 1)
        self.assertIn(datespec, vctx.encounter_datespec.call_args[0])

    def test_if_has_role(self):
        roles = ["r1", "r2", "r3"]
        kwargs = {
            "if_has_role": roles
        }
        with mock.patch("course.validation.validate_role") as mock_val_func:
            validation.validate_session_start_rule(
                vctx, location,
                self.get_updated_nrule(**kwargs),
                self.get_updated_tags())
        self.assertEqual(mock_val_func.call_count, 3)

    def test_if_has_participation_tags(self):
        ptags = ["t1", "t2", "t3"]
        kwargs1 = {
            "if_has_participation_tags_any": ptags
        }
        kwargs2 = {
            "if_has_participation_tags_all": ptags
        }
        with mock.patch(
                "course.validation.validate_participationtag") as mock_val_func:
            validation.validate_session_start_rule(
                vctx, location,
                self.get_updated_nrule(**kwargs1),
                self.get_updated_tags())
            self.assertEqual(mock_val_func.call_count, 3)
            mock_val_func.reset_mock()

            validation.validate_session_start_rule(
                vctx, location,
                self.get_updated_nrule(**kwargs2),
                self.get_updated_tags())
            self.assertEqual(mock_val_func.call_count, 3)

    def test_if_in_facility(self):
        faclity = "f1"
        kwargs = {
            "if_in_facility": faclity
        }

        with mock.patch(
                "course.validation.validate_facility") as mock_val_func:
            validation.validate_session_start_rule(
                vctx, location,
                self.get_updated_nrule(**kwargs),
                self.get_updated_tags())
            self.assertEqual(mock_val_func.call_count, 1)
            self.assertIn(faclity, mock_val_func.call_args[0])

    def test_if_has_session_tagged(self):
        s_tag = None
        kwargs = {
            "if_has_session_tagged": s_tag
        }

        with mock.patch(
                "course.validation.validate_identifier") as mock_val_func:
            validation.validate_session_start_rule(
                vctx, location,
                self.get_updated_nrule(**kwargs),
                self.get_updated_tags())
            self.assertEqual(mock_val_func.call_count, 0)

        s_tag = "s_tag1"
        kwargs = {
            "if_has_session_tagged": s_tag
        }
        with mock.patch(
                "course.validation.validate_identifier") as mock_val_func:
            validation.validate_session_start_rule(
                vctx, location,
                self.get_updated_nrule(**kwargs),
                self.get_updated_tags())
            self.assertEqual(mock_val_func.call_count, 1)
            self.assertIn(s_tag, mock_val_func.call_args[0])

    def test_deprecated_lock_down_as_exam_session(self):

        expected_warn_msg = (
            "Attribute 'lock_down_as_exam_session' is deprecated "
            "and non-functional. Use the access permission flag "
            "'lock_down_as_exam_session' instead.")

        kwargs = {
            "lock_down_as_exam_session": True
        }

        validation.validate_session_start_rule(
            vctx, location,
            self.get_updated_nrule(**kwargs),
            self.get_updated_tags())

        self.assertIn(expected_warn_msg, vctx.add_warning.call_args[0])

        kwargs = {
            "lock_down_as_exam_session": False
        }

        validation.validate_session_start_rule(
            vctx, location,
            self.get_updated_nrule(**kwargs),
            self.get_updated_tags())

        self.assertIn(expected_warn_msg, vctx.add_warning.call_args[0])

    def test_tag_session_none(self):
        tag_session = None
        kwargs = {
            "tag_session": tag_session
        }

        with mock.patch(
                "course.validation.validate_identifier") as mock_val_func:
            validation.validate_session_start_rule(
                vctx, location,
                self.get_updated_nrule(**kwargs),
                self.get_updated_tags())

            self.assertEqual(mock_val_func.call_count, 0)

            # no warnings
            self.assertEqual(vctx.add_warning.call_count, 0)

    def test_tag_session_success(self):
        tag_session = "ts1"
        kwargs = {
            "tag_session": tag_session
        }
        with mock.patch(
                "course.validation.validate_identifier") as mock_val_func:
            validation.validate_session_start_rule(
                vctx, location,
                self.get_updated_nrule(**kwargs),
                self.get_updated_tags(["ts1", "ts2"]))

            self.assertEqual(mock_val_func.call_count, 1)
            self.assertEqual(mock_val_func.call_args[0][2], tag_session)

            # make sure validate_identifier only warn if invalid
            self.assertEqual(mock_val_func.call_args[1]["warning_only"], True)

    def test_tag_session_success_with_none_in_tags(self):
        # Note: can tags include element None?
        tag_session = None
        kwargs = {
            "tag_session": tag_session
        }
        with mock.patch(
                "course.validation.validate_identifier") as mock_val_func:
            validation.validate_session_start_rule(
                vctx, location,
                self.get_updated_nrule(**kwargs),

                # Note: can tags include element None?
                self.get_updated_tags(["ts1", None]))

            self.assertEqual(mock_val_func.call_count, 0)

    def test_tag_session_fail(self):
        tag_session = "ts1"
        kwargs = {
            "tag_session": tag_session
        }
        with mock.patch(
                "course.validation.validate_identifier") as mock_val_func:
            with self.assertRaises(ValidationError) as cm:
                validation.validate_session_start_rule(
                    vctx, location,
                    self.get_updated_nrule(**kwargs),
                    self.get_updated_tags(["ts2", "ts3"]))

            self.assertEqual(mock_val_func.call_count, 1)
            self.assertEqual(mock_val_func.call_args[0][2], tag_session)

            # make sure validate_identifier only warn if invalid
            self.assertEqual(mock_val_func.call_args[1]["warning_only"], True)

            expected_error_msg = "invalid tag 'ts1'"
            self.assertIn(expected_error_msg, str(cm.exception))

            # no warnings
            self.assertEqual(vctx.add_warning.call_count, 0)

    def test_default_expiration_mode_success(self):
        mode = "roll_over"
        kwargs = {
            "default_expiration_mode": mode
        }

        validation.validate_session_start_rule(
            vctx, location,
            self.get_updated_nrule(**kwargs),
            self.get_updated_tags())

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_default_expiration_mode_fail(self):
        mode = "unknown"
        kwargs = {
            "default_expiration_mode": mode
        }

        with self.assertRaises(ValidationError) as cm:
            validation.validate_session_start_rule(
                vctx, location,
                self.get_updated_nrule(**kwargs),
                self.get_updated_tags())

        expected_error_msg = (
                "invalid default expiration mode '%s'" % mode)
        self.assertIn(expected_error_msg, str(cm.exception))

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)


class ValidateSessionAccessRuleTest(ValidationTestMixin, unittest.TestCase):
    # test validation.validate_session_access_rule

    def get_updated_arule(self, **kwargs):
        rule = {"permissions": ["fp1", "fp2"]}
        rule.update(kwargs)
        return dict_to_struct(rule)

    def get_updated_tags(self, extra=None):
        tags = []

        if extra is not None:
            assert isinstance(extra, list)
        else:
            extra = []

        tags.extend(extra)
        return tags

    def test_success(self):
        with mock.patch(
                "course.validation.validate_flow_permission"
        ) as mock_vfp:
            validation.validate_session_access_rule(
                vctx, location, self.get_updated_arule(), self.get_updated_tags())
        self.assertEqual(mock_vfp.call_count, 2)

    def test_if_after(self):
        datespec = "some_time1"
        kwargs = {
            "if_after": datespec
        }

        with mock.patch(
                "course.validation.validate_flow_permission"
        ) as mock_vfp:
            validation.validate_session_access_rule(
                vctx, location,
                self.get_updated_arule(**kwargs),
                self.get_updated_tags())

        self.assertEqual(mock_vfp.call_count, 2)
        self.assertEqual(vctx.encounter_datespec.call_count, 1)
        self.assertIn(datespec, vctx.encounter_datespec.call_args[0])

    def test_if_before(self):
        datespec = "some_time2"
        kwargs = {
            "if_before": datespec
        }
        with mock.patch(
                "course.validation.validate_flow_permission"
        ) as mock_vfp:
            validation.validate_session_access_rule(
                vctx, location,
                self.get_updated_arule(**kwargs),
                self.get_updated_tags())

        self.assertEqual(mock_vfp.call_count, 2)
        self.assertEqual(vctx.encounter_datespec.call_count, 1)
        self.assertIn(datespec, vctx.encounter_datespec.call_args[0])

    def test_if_completed_before(self):
        datespec = "some_time3"
        kwargs = {
            "if_completed_before": datespec
        }
        with mock.patch(
                "course.validation.validate_flow_permission"
        ) as mock_vfp:
            validation.validate_session_access_rule(
                vctx, location,
                self.get_updated_arule(**kwargs),
                self.get_updated_tags())

        self.assertEqual(mock_vfp.call_count, 2)
        self.assertEqual(vctx.encounter_datespec.call_count, 1)
        self.assertIn(datespec, vctx.encounter_datespec.call_args[0])

    def test_if_has_role(self):
        roles = ["r1", "r2", "r3"]
        kwargs = {
            "if_has_role": roles
        }
        with mock.patch(
                "course.validation.validate_flow_permission"
        ) as mock_vfp, mock.patch(
                "course.validation.validate_role") as mock_val_func:
            validation.validate_session_access_rule(
                vctx, location,
                self.get_updated_arule(**kwargs),
                self.get_updated_tags())

        self.assertEqual(mock_val_func.call_count, 3)
        self.assertEqual(mock_vfp.call_count, 2)

    def test_if_has_participation_tags(self):
        ptags = ["t1", "t2", "t3"]
        kwargs1 = {
            "if_has_participation_tags_any": ptags
        }
        kwargs2 = {
            "if_has_participation_tags_all": ptags
        }
        with mock.patch(
                "course.validation.validate_flow_permission"
        ) as mock_vfp, mock.patch(
                "course.validation.validate_participationtag"
        ) as mock_val_func:
            validation.validate_session_access_rule(
                vctx, location,
                self.get_updated_arule(**kwargs1),
                self.get_updated_tags())
            self.assertEqual(mock_val_func.call_count, 3)
            mock_val_func.reset_mock()
            self.assertEqual(mock_vfp.call_count, 2)
            mock_vfp.reset_mock()

            validation.validate_session_access_rule(
                vctx, location,
                self.get_updated_arule(**kwargs2),
                self.get_updated_tags())
            self.assertEqual(mock_val_func.call_count, 3)
            self.assertEqual(mock_vfp.call_count, 2)

    def test_if_in_facility(self):
        faclity = "f1"
        kwargs = {
            "if_in_facility": faclity
        }

        with mock.patch(
                "course.validation.validate_flow_permission"
        ) as mock_vfp, mock.patch(
                "course.validation.validate_facility") as mock_val_func:
            validation.validate_session_access_rule(
                vctx, location,
                self.get_updated_arule(**kwargs),
                self.get_updated_tags())
            self.assertEqual(mock_val_func.call_count, 1)
            self.assertIn(faclity, mock_val_func.call_args[0])

            self.assertEqual(mock_vfp.call_count, 2)

    def test_if_has_tag_none(self):
        if_has_tag = None
        kwargs = {
            "if_has_tag": if_has_tag
        }

        with mock.patch(
                "course.validation.validate_flow_permission"
        ) as mock_vfp, mock.patch(
                "course.validation.validate_identifier") as mock_val_func:
            validation.validate_session_access_rule(
                vctx, location,
                self.get_updated_arule(**kwargs),
                self.get_updated_tags())

            self.assertEqual(mock_val_func.call_count, 0)

            # no warnings
            self.assertEqual(vctx.add_warning.call_count, 0)

            self.assertEqual(mock_vfp.call_count, 2)

    def test_if_has_tag_success(self):
        if_has_tag = "ts1"
        kwargs = {
            "if_has_tag": if_has_tag
        }
        with mock.patch(
                "course.validation.validate_flow_permission"
        ) as mock_vfp, mock.patch(
                "course.validation.validate_identifier") as mock_val_func:
            validation.validate_session_access_rule(
                vctx, location,
                self.get_updated_arule(**kwargs),
                self.get_updated_tags(["ts1", "ts2"]))

            self.assertEqual(mock_val_func.call_count, 1)
            self.assertEqual(mock_val_func.call_args[0][2], if_has_tag)

            # make sure validate_identifier only warn if invalid
            self.assertEqual(mock_val_func.call_args[1]["warning_only"], True)

            self.assertEqual(mock_vfp.call_count, 2)

    def test_if_has_tag_success_with_none_in_tags(self):
        # Note: can tags include element None?
        if_has_tag = None
        kwargs = {
            "if_has_tag": if_has_tag
        }
        with mock.patch(
                "course.validation.validate_flow_permission"
        ) as mock_vfp, mock.patch(
                "course.validation.validate_identifier") as mock_val_func:
            validation.validate_session_access_rule(
                vctx, location,
                self.get_updated_arule(**kwargs),

                # Note: can tags include element None?
                self.get_updated_tags(["ts1", None]))

            self.assertEqual(mock_val_func.call_count, 0)

            self.assertEqual(mock_vfp.call_count, 2)

    def test_if_has_tag_fail(self):
        if_has_tag = "ts1"
        kwargs = {
            "if_has_tag": if_has_tag
        }
        with mock.patch(
                "course.validation.validate_flow_permission"
        ) as mock_vfp, mock.patch(
                "course.validation.validate_identifier") as mock_val_func:
            with self.assertRaises(ValidationError) as cm:
                validation.validate_session_access_rule(
                    vctx, location,
                    self.get_updated_arule(**kwargs),
                    self.get_updated_tags(["ts2", "ts3"]))

            self.assertEqual(mock_val_func.call_count, 1)
            self.assertEqual(mock_val_func.call_args[0][2], if_has_tag)

            # make sure validate_identifier only warn if invalid
            self.assertEqual(mock_val_func.call_args[1]["warning_only"], True)

            expected_error_msg = "invalid tag 'ts1'"
            self.assertIn(expected_error_msg, str(cm.exception))

            # no warnings
            self.assertEqual(vctx.add_warning.call_count, 0)

            self.assertEqual(mock_vfp.call_count, 0)

    def test_default_expiration_mode_success(self):
        mode = "roll_over"
        kwargs = {
            "if_expiration_mode": mode
        }
        with mock.patch(
                "course.validation.validate_flow_permission"
        ) as mock_vfp:
            validation.validate_session_access_rule(
                vctx, location,
                self.get_updated_arule(**kwargs),
                self.get_updated_tags())

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

        self.assertEqual(mock_vfp.call_count, 2)

    def test_if_expiration_mode_fail(self):
        mode = "unknown"
        kwargs = {
            "if_expiration_mode": mode
        }

        with mock.patch(
                "course.validation.validate_flow_permission"
        ) as mock_vfp, self.assertRaises(ValidationError) as cm:
            validation.validate_session_access_rule(
                vctx, location,
                self.get_updated_arule(**kwargs),
                self.get_updated_tags())

        expected_error_msg = (
                "invalid expiration mode '%s'" % mode)
        self.assertIn(expected_error_msg, str(cm.exception))

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

        self.assertEqual(mock_vfp.call_count, 0)

    def test_if_in_progress_no_warning(self):
        if_in_progress = True
        kwargs = {
            "if_in_progress": if_in_progress,
            "permissions": []
        }
        validation.validate_session_access_rule(
            vctx, location,
            self.get_updated_arule(**kwargs),
            self.get_updated_tags())

        self.assertEqual(vctx.add_warning.call_count, 0)

        if_in_progress = False
        kwargs = {
            "if_in_progress": if_in_progress,
            "permissions": []
        }
        validation.validate_session_access_rule(
            vctx, location,
            self.get_updated_arule(**kwargs),
            self.get_updated_tags())

        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_if_in_progress_warned_ignore(self):
        if_in_progress = False
        kwargs = {
            "if_in_progress": if_in_progress,
            "permissions": [flow_permission.submit_answer]
        }

        expected_warn_msg = (
            "Rule specifies 'submit_answer' or 'end_session' "
            "permissions for non-in-progress flow. These "
            "permissions will be ignored.")
        validation.validate_session_access_rule(
            vctx, location,
            self.get_updated_arule(**kwargs),
            self.get_updated_tags())

        self.assertEqual(vctx.add_warning.call_count, 1)
        self.assertIn(expected_warn_msg, vctx.add_warning.call_args[0])
        vctx.reset_mock()

        kwargs = {
            "if_in_progress": if_in_progress,
            "permissions": [flow_permission.end_session]
        }

        expected_warn_msg = (
            "Rule specifies 'submit_answer' or 'end_session' "
            "permissions for non-in-progress flow. These "
            "permissions will be ignored.")
        validation.validate_session_access_rule(
            vctx, location,
            self.get_updated_arule(**kwargs),
            self.get_updated_tags())

        self.assertEqual(vctx.add_warning.call_count, 1)
        self.assertIn(expected_warn_msg, vctx.add_warning.call_args[0])
        vctx.reset_mock()

        kwargs = {
            "if_in_progress": if_in_progress,
            "permissions": [flow_permission.submit_answer,
                            flow_permission.end_session]
        }

        expected_warn_msg = (
            "Rule specifies 'submit_answer' or 'end_session' "
            "permissions for non-in-progress flow. These "
            "permissions will be ignored.")

        validation.validate_session_access_rule(
            vctx, location,
            self.get_updated_arule(**kwargs),
            self.get_updated_tags())

        self.assertEqual(vctx.add_warning.call_count, 1)
        self.assertIn(expected_warn_msg, vctx.add_warning.call_args[0])


class ValidateSessionGradingRule(ValidationTestMixin, unittest.TestCase):
    # test validation.validate_session_grading_rule

    default_grade_identifier = "my_grade_identifier"

    def get_updated_grule(self, **kwargs):
        rule = {}
        rule.update(kwargs)
        return dict_to_struct(rule)

    def get_updated_tags(self, extra=None):
        tags = []

        if extra is not None:
            assert isinstance(extra, list)
        else:
            extra = []

        tags.extend(extra)
        return tags

    def test_success(self):
        self.assertEqual(validation.validate_session_grading_rule(
            vctx, location, self.get_updated_grule(), self.get_updated_tags(),
            self.default_grade_identifier), False)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_removed_grade_identifier(self):
        kwargs = {
            "grade_identifier": "unknown"
        }

        with self.assertRaises(ValidationError) as cm:
            validation.validate_session_grading_rule(
                vctx, location,
                self.get_updated_grule(**kwargs),
                self.get_updated_tags(), self.default_grade_identifier)

        expected_error_msg = (
            "'grade_identifier' attribute found. "
            "This attribute is no longer allowed here "
            "and should be moved upward into the 'rules' "
            "block.")

        self.assertIn(expected_error_msg, str(cm.exception))

    def test_removed_grade_aggregation_strategy(self):
        kwargs = {
            "grade_aggregation_strategy": "unknown"
        }

        with self.assertRaises(ValidationError) as cm:
            validation.validate_session_grading_rule(
                vctx, location,
                self.get_updated_grule(**kwargs),
                self.get_updated_tags(), self.default_grade_identifier)

        expected_error_msg = (
            "'grade_aggregation_strategy' attribute found. "
            "This attribute is no longer allowed here "
            "and should be moved upward into the 'rules' "
            "block.")

        self.assertIn(expected_error_msg, str(cm.exception))

    def test_if_started_before(self):
        datespec = "some_time1"
        kwargs = {
            "if_started_before": datespec
        }
        self.assertEqual(validation.validate_session_grading_rule(
            vctx, location,
            self.get_updated_grule(**kwargs),
            self.get_updated_tags(), self.default_grade_identifier), True)

        self.assertEqual(vctx.encounter_datespec.call_count, 1)
        self.assertIn(datespec, vctx.encounter_datespec.call_args[0])

    def test_due(self):
        datespec = "some_time3"
        kwargs = {
            "due": datespec
        }
        self.assertEqual(validation.validate_session_grading_rule(
            vctx, location,
            self.get_updated_grule(**kwargs),
            self.get_updated_tags(), self.default_grade_identifier), False)

        self.assertEqual(vctx.encounter_datespec.call_count, 1)
        self.assertIn(datespec, vctx.encounter_datespec.call_args[0])

    def test_if_completed_before(self):
        datespec = "some_time2"
        kwargs = {
            "if_completed_before": datespec
        }
        self.assertEqual(validation.validate_session_grading_rule(
            vctx, location,
            self.get_updated_grule(**kwargs),
            self.get_updated_tags(), self.default_grade_identifier), True)

        self.assertEqual(vctx.encounter_datespec.call_count, 1)
        self.assertIn(datespec, vctx.encounter_datespec.call_args[0])

    def test_if_has_role(self):
        roles = ["r1", "r2", "r3"]
        kwargs = {
            "if_has_role": roles
        }
        with mock.patch("course.validation.validate_role") as mock_val_func:
            self.assertEqual(validation.validate_session_grading_rule(
                vctx, location,
                self.get_updated_grule(**kwargs),
                self.get_updated_tags(), self.default_grade_identifier), True)
        self.assertEqual(mock_val_func.call_count, 3)

    def test_if_has_participation_tags(self):
        ptags = ["t1", "t2", "t3"]
        kwargs1 = {
            "if_has_participation_tags_any": ptags
        }
        kwargs2 = {
            "if_has_participation_tags_all": ptags
        }
        with mock.patch(
                "course.validation.validate_participationtag") as mock_val_func:
            self.assertEqual(validation.validate_session_grading_rule(
                vctx, location,
                self.get_updated_grule(**kwargs1),
                self.get_updated_tags(), self.default_grade_identifier), True)
            self.assertEqual(mock_val_func.call_count, 3)
            mock_val_func.reset_mock()

            self.assertEqual(validation.validate_session_grading_rule(
                vctx, location,
                self.get_updated_grule(**kwargs2),
                self.get_updated_tags(), self.default_grade_identifier), True)
            self.assertEqual(mock_val_func.call_count, 3)

    def test_if_has_tag_none(self):
        if_has_tag = None
        kwargs = {
            "if_has_tag": if_has_tag
        }

        with mock.patch(
                "course.validation.validate_identifier") as mock_val_func:
            self.assertEqual(validation.validate_session_grading_rule(
                vctx, location,
                self.get_updated_grule(**kwargs),
                self.get_updated_tags(), self.default_grade_identifier), True)

            self.assertEqual(mock_val_func.call_count, 0)

            # no warnings
            self.assertEqual(vctx.add_warning.call_count, 0)

    def test_if_has_tag_success(self):
        if_has_tag = "ts1"
        kwargs = {
            "if_has_tag": if_has_tag
        }
        with mock.patch(
                "course.validation.validate_identifier") as mock_val_func:
            self.assertEqual(validation.validate_session_grading_rule(
                vctx, location,
                self.get_updated_grule(**kwargs),
                self.get_updated_tags(["ts1", "ts2"]),
                self.default_grade_identifier), True)

            self.assertEqual(mock_val_func.call_count, 1)
            self.assertEqual(mock_val_func.call_args[0][2], if_has_tag)

            # make sure validate_identifier only warn if invalid
            self.assertEqual(mock_val_func.call_args[1]["warning_only"], True)

    def test_if_has_tag_success_with_none_in_tags(self):
        # Note: can tags include element None?
        if_has_tag = None
        kwargs = {
            "if_has_tag": if_has_tag
        }
        with mock.patch(
                "course.validation.validate_identifier") as mock_val_func:
            self.assertEqual(validation.validate_session_grading_rule(
                vctx, location,
                self.get_updated_grule(**kwargs),

                # Note: can tags include element None?
                self.get_updated_tags(["ts1", None]), self.default_grade_identifier),
                True)

            self.assertEqual(mock_val_func.call_count, 0)

    def test_if_has_tag_fail(self):
        if_has_tag = "ts1"
        kwargs = {
            "if_has_tag": if_has_tag
        }
        with mock.patch(
                "course.validation.validate_identifier") as mock_val_func:
            with self.assertRaises(ValidationError) as cm:
                validation.validate_session_grading_rule(
                    vctx, location,
                    self.get_updated_grule(**kwargs),
                    self.get_updated_tags(["ts2", "ts3"]),
                    self.default_grade_identifier)

            self.assertEqual(mock_val_func.call_count, 1)
            self.assertEqual(mock_val_func.call_args[0][2], if_has_tag)

            # make sure validate_identifier only warn if invalid
            self.assertEqual(mock_val_func.call_args[1]["warning_only"], True)

            expected_error_msg = "invalid tag 'ts1'"
            self.assertIn(expected_error_msg, str(cm.exception))

            # no warnings
            self.assertEqual(vctx.add_warning.call_count, 0)

    def test_generates_grade_and_grade_identifier_is_none(self):
        kwargs = {
            "generates_grade": False
        }

        # success when not generates_grade
        self.assertEqual(validation.validate_session_grading_rule(
            vctx, location,
            self.get_updated_grule(**kwargs),
            self.get_updated_tags(), grade_identifier=None), False)

        expected_error_msg = (
            "'generates_grade' is true, but no 'grade_identifier'"
            "is given.")

        kwargs = {
            "generates_grade": True
        }

        # fail when generates_grade
        with self.assertRaises(ValidationError) as cm:
            validation.validate_session_grading_rule(
                vctx, location,
                self.get_updated_grule(**kwargs),
                self.get_updated_tags(), grade_identifier=None)
        self.assertIn(expected_error_msg, str(cm.exception))

        kwargs = {}

        # fail when generates_grade not configured
        with self.assertRaises(ValidationError) as cm:
            validation.validate_session_grading_rule(
                vctx, location,
                self.get_updated_grule(**kwargs),
                self.get_updated_tags(), grade_identifier=None)
        self.assertIn(expected_error_msg, str(cm.exception))


class ValidateFlowRules(ValidationTestMixin, unittest.TestCase):
    # test validation.validate_flow_rules

    default_grade_identifier = "my_grade_identifier"

    def get_updated_rule(
            self, no_grade_identifier=False,
            no_grade_aggregation_strategy=False,
            no_grading_rules=False,
            **kwargs):
        rule = {"access": ["access_rule1", "access_rule2"]}

        if not no_grade_identifier:
            rule["grade_identifier"] = self.default_grade_identifier
        if not no_grade_aggregation_strategy:
            rule["grade_aggregation_strategy"] = (
                grade_aggregation_strategy.use_latest)
        if not no_grading_rules:
            rule["grading"] = ["grading_rule1", "grading_rule2",
                               "grading_rule3"]
        rule.update(kwargs)
        return dict_to_struct(rule)

    def test_success(self):
        with mock.patch(
                "course.validation.validate_session_access_rule"
        ) as mock_vsar, mock.patch(
            "course.validation.validate_identifier"
        ) as mock_vi, mock.patch(
            "course.validation.validate_session_grading_rule"
        ) as mock_vsgr:
            mock_vsgr.side_effect = [True, True, False]
            validation.validate_flow_rules(
                vctx, location, self.get_updated_rule())

        self.assertEqual(mock_vi.call_count, 1)
        self.assertEqual(mock_vsar.call_count, 2)
        self.assertEqual(mock_vsgr.call_count, 3)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_success_with_grading_identifier_none(self):
        kwargs = {
            "grade_identifier": None
        }
        with mock.patch(
                "course.validation.validate_session_access_rule"
        ) as mock_vsar, mock.patch(
            "course.validation.validate_identifier"
        ) as mock_vi, mock.patch(
            "course.validation.validate_session_grading_rule"
        ) as mock_vsgr:
            mock_vsgr.side_effect = [True, True, False]
            validation.validate_flow_rules(
                vctx, location,
                self.get_updated_rule(
                    no_grading_rules=True,
                    **kwargs))

        self.assertEqual(mock_vsar.call_count, 2)
        self.assertEqual(mock_vi.call_count, 0)
        self.assertEqual(mock_vsgr.call_count, 0)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_no_grade_identifier_with_no_grading_rules(self):
        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_identifier"
        ) as mock_vi, mock.patch(
            "course.validation.validate_session_access_rule"
        ) as mock_vsar, mock.patch(
            "course.validation.validate_session_grading_rule"
        ) as mock_vsgr:
            mock_vsgr.side_effect = [True, True, False]

            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_rules(
                    vctx, location,
                    self.get_updated_rule(
                        no_grade_identifier=True, no_grading_rules=True))

            expected_error_msg = (
                "'rules' block does not have a grade_identifier "
                "attribute.")
            unexpected_error_msg = (
                "This attribute needs to be moved out of "
                "the lower-level 'grading' rules block and into "
                "the 'rules' block itself."
            )
            self.assertIn(expected_error_msg, str(cm.exception))
            self.assertNotIn(unexpected_error_msg, str(cm.exception))

        self.assertEqual(mock_vs.call_count, 1)
        self.assertEqual(mock_vi.call_count, 0)
        self.assertEqual(mock_vsar.call_count, 0)
        self.assertEqual(mock_vsgr.call_count, 0)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_no_grade_identifier_with_grading_rules_with_out_grade_identifier(self):
        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_identifier"
        ) as mock_vi, mock.patch(
            "course.validation.validate_session_access_rule"
        ) as mock_vsar, mock.patch(
            "course.validation.validate_session_grading_rule"
        ) as mock_vsgr:
            mock_vsgr.side_effect = [True, True, False]

            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_rules(
                    vctx, location,
                    self.get_updated_rule(no_grade_identifier=True))

            expected_error_msg = (
                "'rules' block does not have a grade_identifier "
                "attribute.")
            unexpected_error_msg = (
                "This attribute needs to be moved out of "
                "the lower-level 'grading' rules block and into "
                "the 'rules' block itself."
            )
            self.assertIn(expected_error_msg, str(cm.exception))
            self.assertNotIn(unexpected_error_msg, str(cm.exception))

        self.assertEqual(mock_vs.call_count, 1)
        self.assertEqual(mock_vi.call_count, 0)
        self.assertEqual(mock_vsar.call_count, 0)
        self.assertEqual(mock_vsgr.call_count, 0)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_no_grade_identifier_with_grading_rules_with_grade_identifier(self):

        kwargs = {
            "grading": dict_to_struct(
                {"grade_identifier": self.default_grade_identifier})
        }

        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_identifier"
        ) as mock_vi, mock.patch(
                "course.validation.validate_session_access_rule"
        ) as mock_vsar, mock.patch(
            "course.validation.validate_session_grading_rule"
        ) as mock_vsgr:
            mock_vsgr.side_effect = [True, True, False]

            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_rules(
                    vctx, location,
                    self.get_updated_rule(no_grade_identifier=True, **kwargs))

            expected_error_msg = (
                "'rules' block does not have a grade_identifier "
                "attribute. This attribute needs to be moved out of "
                "the lower-level 'grading' rules block and into "
                "the 'rules' block itself.")
            self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(mock_vs.call_count, 1)
        self.assertEqual(mock_vi.call_count, 0)
        self.assertEqual(mock_vsar.call_count, 0)
        self.assertEqual(mock_vsgr.call_count, 0)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_tags(self):

        kwargs = {
            "tags": ["tag1", "tag2"]
        }

        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_identifier"
        ) as mock_vi, mock.patch(
                "course.validation.validate_session_access_rule"
        ) as mock_vsar, mock.patch(
            "course.validation.validate_session_grading_rule"
        ) as mock_vsgr:
            mock_vsgr.side_effect = [True, True, False]

            validation.validate_flow_rules(
                vctx, location,
                self.get_updated_rule(**kwargs))

        self.assertEqual(mock_vs.call_count, 1)

        # two extra validate_identifier calls for tags
        self.assertEqual(mock_vi.call_count, 3)
        self.assertEqual(mock_vsar.call_count, 2)
        self.assertEqual(mock_vsgr.call_count, 3)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_start_rules_validated(self):

        kwargs = {
            "start": ["start_rule1", "start_rule2",
                      "start_rule3", "start_rule4"]
        }

        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_identifier"
        ) as mock_vi, mock.patch(
            "course.validation.validate_session_access_rule"
        ) as mock_vsar, mock.patch(
            "course.validation.validate_session_start_rule"
        ) as mock_vssr, mock.patch(
            "course.validation.validate_session_grading_rule"
        ) as mock_vsgr:
            mock_vsgr.side_effect = [True, True, False]

            validation.validate_flow_rules(
                vctx, location,
                self.get_updated_rule(**kwargs))

        self.assertEqual(mock_vs.call_count, 1)
        self.assertEqual(mock_vi.call_count, 1)
        self.assertEqual(mock_vsar.call_count, 2)
        self.assertEqual(mock_vssr.call_count, 4)
        self.assertEqual(mock_vsgr.call_count, 3)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_no_grade_aggregation_strategy(self):
        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_identifier"
        ) as mock_vi, mock.patch(
            "course.validation.validate_session_access_rule"
        ) as mock_vsar, mock.patch(
            "course.validation.validate_session_grading_rule"
        ) as mock_vsgr:
            mock_vsgr.side_effect = [True, True, False]

            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_rules(
                    vctx, location,
                    self.get_updated_rule(no_grade_aggregation_strategy=True))
            expected_error_msg = (
                "flows that have a grade "
                "identifier ('%(identifier)s') "
                "must have grading rules with a "
                "grade_aggregation_strategy"
                % {"identifier": self.default_grade_identifier})

            self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(mock_vs.call_count, 1)
        self.assertEqual(mock_vi.call_count, 1)
        self.assertEqual(mock_vsar.call_count, 2)
        self.assertEqual(mock_vsgr.call_count, 0)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_unknown_grade_aggregation_strategy(self):
        g_strategy = "unknown"
        kwargs = {
            "grade_aggregation_strategy": g_strategy
        }
        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_identifier"
        ) as mock_vi, mock.patch(
            "course.validation.validate_session_access_rule"
        ) as mock_vsar, mock.patch(
            "course.validation.validate_session_grading_rule"
        ) as mock_vsgr:
            mock_vsgr.side_effect = [True, True, False]

            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_rules(
                    vctx, location,
                    self.get_updated_rule(**kwargs))

            expected_error_msg = (
                "invalid grade aggregation strategy: %s" % g_strategy)

            self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(mock_vs.call_count, 1)
        self.assertEqual(mock_vi.call_count, 1)
        self.assertEqual(mock_vsar.call_count, 2)
        self.assertEqual(mock_vsgr.call_count, 0)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_grading_rules_not_present(self):
        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_identifier"
        ) as mock_vi, mock.patch(
            "course.validation.validate_session_access_rule"
        ) as mock_vsar, mock.patch(
            "course.validation.validate_session_grading_rule"
        ) as mock_vsgr:
            mock_vsgr.side_effect = [True, True, False]

            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_rules(
                    vctx, location,
                    self.get_updated_rule(no_grading_rules=True))

            expected_error_msg = (
                "'grading' block is required if grade_identifier "
                "is not null/None.")

            self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(mock_vs.call_count, 1)
        self.assertEqual(mock_vi.call_count, 1)
        self.assertEqual(mock_vsar.call_count, 2)
        self.assertEqual(mock_vsgr.call_count, 0)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_grading_rules_empty(self):

        kwargs = {"grading": []}

        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_identifier"
        ) as mock_vi, mock.patch(
            "course.validation.validate_session_access_rule"
        ) as mock_vsar, mock.patch(
            "course.validation.validate_session_grading_rule"
        ) as mock_vsgr:
            mock_vsgr.side_effect = [True, True, False]

            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_rules(
                    vctx, location,
                    self.get_updated_rule(**kwargs))

            expected_error_msg = "rules/grading: may not be an empty list"

            self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(mock_vs.call_count, 1)
        self.assertEqual(mock_vi.call_count, 1)
        self.assertEqual(mock_vsar.call_count, 2)
        self.assertEqual(mock_vsgr.call_count, 0)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_last_grading_rules_conditional(self):

        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_identifier"
        ) as mock_vi, mock.patch(
            "course.validation.validate_session_access_rule"
        ) as mock_vsar, mock.patch(
            "course.validation.validate_session_grading_rule"
        ) as mock_vsgr:
            mock_vsgr.side_effect = [True, True, True]

            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_rules(
                    vctx, location,
                    self.get_updated_rule())

            expected_error_msg = (
                "rules/grading: last grading rule must be unconditional")

            self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(mock_vs.call_count, 1)
        self.assertEqual(mock_vi.call_count, 1)
        self.assertEqual(mock_vsar.call_count, 2)
        self.assertEqual(mock_vsgr.call_count, 3)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)


class ValidateFlowPermission(ValidationTestMixin, unittest.TestCase):
    # test validation.validate_flow_permission

    def test_success(self):
        validation.validate_flow_permission(vctx, location, "submit_answer")
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_deprecated_modify(self):
        validation.validate_flow_permission(vctx, location, "modify")

        expected_warn_msg = (
            "Uses deprecated 'modify' permission--"
            "replace by 'submit_answer' and 'end_session'")
        self.assertIn(expected_warn_msg, vctx.add_warning.call_args[0])

    def test_deprecated_see_answer(self):
        validation.validate_flow_permission(vctx, location, "see_answer")

        expected_warn_msg = (
            "Uses deprecated 'see_answer' permission--"
            "replace by 'see_answer_after_submission'")
        self.assertIn(expected_warn_msg, vctx.add_warning.call_args[0])

    def test_unknown_flow_permission(self):
        with self.assertRaises(ValidationError) as cm:
            validation.validate_flow_permission(vctx, location, "unknown")

        expected_error_msg = "invalid flow permission 'unknown'"
        self.assertIn(expected_error_msg, str(cm.exception))


class ValidateFlowDescTest(ValidationTestMixin, unittest.TestCase):
    # test validation.validate_flow_desc

    default_flow_title = "test flow title"
    default_pages = ["page1", "page2", "page3"]
    default_groups = (
        dict_to_struct(
            {"id": "flow_group1",
             "pages": ["page1", "page2", "page3"]
             }),
        dict_to_struct(
            {"id": "flow_group2",
             "pages": ["page4"]
             })
    )

    def get_updated_flow_desc(
            self, no_title=False, no_description=False, no_groups_pages=False,
            use_groups=True, use_pages=False,
            **kwargs):
        flow_desc = {}

        if not no_groups_pages:
            assert not (use_pages and use_groups)
            if use_groups:
                flow_desc["groups"] = self.default_groups
            if use_pages:
                flow_desc["pages"] = self.default_pages

        if not no_title:
            flow_desc["title"] = self.default_flow_title
        if not no_description:
            flow_desc["description"] = "hello"

        flow_desc.update(kwargs)
        return dict_to_struct(flow_desc)

    def test_success(self):

        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_flow_rules"
        ) as mock_vfr, mock.patch(
            "course.validation.validate_flow_group"
        ) as mock_vfg, mock.patch(
            "course.content.normalize_flow_desc"
        ) as mock_nfd, mock.patch(
            "course.validation.validate_markup"
        ) as mock_mk:

            validation.validate_flow_desc(
                vctx, location,
                self.get_updated_flow_desc())

        self.assertEqual(mock_vs.call_count, 1)
        self.assertEqual(mock_vfr.call_count, 0)
        self.assertEqual(mock_vfg.call_count, 2)
        self.assertEqual(mock_nfd.call_count, 0)
        self.assertEqual(mock_mk.call_count, 1)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_success_use_pages(self):

        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_flow_rules"
        ) as mock_vfr, mock.patch(
            "course.validation.validate_flow_group"
        ) as mock_vfg, mock.patch(
            "course.content.normalize_flow_desc"
        ) as mock_nfd, mock.patch(
            "course.validation.validate_markup"
        ) as mock_mk:

            mock_nfd.return_value = dict_to_struct(
                {"description": "hi",
                 "groups": [dict_to_struct(
                     {"id": "my_group",
                      "pages": [
                          dict_to_struct({"id": "page1"}),
                          dict_to_struct({"id": "page2"})]
                      })]
                 })

            validation.validate_flow_desc(
                vctx, location,
                self.get_updated_flow_desc(use_groups=False, use_pages=True))

        self.assertEqual(mock_vs.call_count, 1)
        self.assertEqual(mock_vfr.call_count, 0)
        self.assertEqual(mock_vfg.call_count, 1)
        self.assertEqual(mock_nfd.call_count, 1)
        self.assertEqual(mock_mk.call_count, 1)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_success_with_rules(self):
        kwargs = {"rules": dict_to_struct({"start": "start_rule1"})}

        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_flow_rules"
        ) as mock_vfr, mock.patch(
            "course.validation.validate_flow_group"
        ) as mock_vfg, mock.patch(
            "course.content.normalize_flow_desc"
        ) as mock_nfd, mock.patch(
            "course.validation.validate_markup"
        ) as mock_mk:

            validation.validate_flow_desc(
                vctx, location,
                self.get_updated_flow_desc(**kwargs))

        self.assertEqual(mock_vs.call_count, 1)
        self.assertEqual(mock_vfr.call_count, 1)
        self.assertEqual(mock_vfg.call_count, 2)
        self.assertEqual(mock_nfd.call_count, 0)
        self.assertEqual(mock_mk.call_count, 1)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_neither_groups_nor_pages(self):

        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_flow_rules"
        ) as mock_vfr, mock.patch(
            "course.validation.validate_flow_group"
        ) as mock_vfg, mock.patch(
            "course.content.normalize_flow_desc"
        ) as mock_nfd, mock.patch(
            "course.validation.validate_markup"
        ) as mock_mk:
            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_desc(
                    vctx, location,
                    self.get_updated_flow_desc(no_groups_pages=True))

            expected_error_msg = "must have either 'groups' or 'pages'"
            self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(mock_vs.call_count, 1)
        self.assertEqual(mock_vfr.call_count, 0)
        self.assertEqual(mock_vfg.call_count, 0)
        self.assertEqual(mock_nfd.call_count, 0)
        self.assertEqual(mock_mk.call_count, 0)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_both_groups_and_pages(self):

        kwargs = {"pages": self.default_pages}

        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_flow_rules"
        ) as mock_vfr, mock.patch(
            "course.validation.validate_flow_group"
        ) as mock_vfg, mock.patch(
            "course.content.normalize_flow_desc"
        ) as mock_nfd, mock.patch(
            "course.validation.validate_markup"
        ) as mock_mk:
            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_desc(
                    vctx, location,
                    self.get_updated_flow_desc(**kwargs))

            expected_error_msg = "must have either 'groups' or 'pages'"
            self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(mock_vs.call_count, 1)
        self.assertEqual(mock_vfr.call_count, 0)
        self.assertEqual(mock_vfg.call_count, 0)
        self.assertEqual(mock_nfd.call_count, 0)
        self.assertEqual(mock_mk.call_count, 0)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_group_pages_not_list(self):
        kwargs = {"groups": [
            dict_to_struct(
                {"id": "flow_group1",
                 "pages": "not pages"
                 }),
            dict_to_struct(
                {"id": "flow_group2",
                 "pages": ["page4"]
                 })]}

        with mock.patch(
            "course.validation.validate_flow_rules"
        ) as mock_vfr, mock.patch(
            "course.content.normalize_flow_desc"
        ) as mock_nfd, mock.patch(
            "course.validation.validate_markup"
        ) as mock_mk:
            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_desc(
                    vctx, location,
                    self.get_updated_flow_desc(**kwargs))

            expected_error_msg = (
                "'pages' has wrong type")
            self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(mock_vfr.call_count, 0)
        self.assertEqual(mock_nfd.call_count, 0)
        self.assertEqual(mock_mk.call_count, 1)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_group_had_no_page(self):
        kwargs = {"groups": [
            dict_to_struct(
                {"id": "flow_group1",
                 "pages": []
                 }),
            dict_to_struct(
                {"id": "flow_group2",
                 "pages": ["page4"]
                 })]}

        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_flow_rules"
        ) as mock_vfr, mock.patch(
            "course.validation.validate_flow_group"
        ) as mock_vfg, mock.patch(
            "course.content.normalize_flow_desc"
        ) as mock_nfd, mock.patch(
            "course.validation.validate_markup"
        ) as mock_mk:
            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_desc(
                    vctx, location,
                    self.get_updated_flow_desc(**kwargs))

            expected_error_msg = (
                "group 1 ('flow_group1'): "
                "no pages found")
            self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(mock_vs.call_count, 1)
        self.assertEqual(mock_vfr.call_count, 0)
        self.assertEqual(mock_vfg.call_count, 2)
        self.assertEqual(mock_nfd.call_count, 0)
        self.assertEqual(mock_mk.call_count, 0)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_flow_has_no_page(self):
        kwargs = {"groups": []}

        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_flow_rules"
        ) as mock_vfr, mock.patch(
            "course.validation.validate_flow_group"
        ) as mock_vfg, mock.patch(
            "course.content.normalize_flow_desc"
        ) as mock_nfd, mock.patch(
            "course.validation.validate_markup"
        ) as mock_mk:
            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_desc(
                    vctx, location,
                    self.get_updated_flow_desc(**kwargs))

            expected_error_msg = (
                "%s: no pages found" % location)
            self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(mock_vs.call_count, 1)
        self.assertEqual(mock_vfr.call_count, 0)
        self.assertEqual(mock_vfg.call_count, 0)
        self.assertEqual(mock_nfd.call_count, 0)
        self.assertEqual(mock_mk.call_count, 0)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_group_id_not_unique(self):
        kwargs = {"groups": [dict_to_struct(
            {"id": "flow_group1",
             "pages": ["page1", "page2", "page3"]
             }),
            dict_to_struct(
                {"id": "flow_group2",
                 "pages": ["page4"]
                 }),
            dict_to_struct(
                {"id": "flow_group2",
                 "pages": ["page5"]
                 })]}

        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_flow_rules"
        ) as mock_vfr, mock.patch(
            "course.validation.validate_flow_group"
        ) as mock_vfg, mock.patch(
            "course.content.normalize_flow_desc"
        ) as mock_nfd, mock.patch(
            "course.validation.validate_markup"
        ) as mock_mk:
            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_desc(
                    vctx, location,
                    self.get_updated_flow_desc(**kwargs))

            expected_error_msg = (
                "group id 'flow_group2' not unique")
            self.assertIn(expected_error_msg, str(cm.exception))

            self.assertEqual(mock_vs.call_count, 1)
            self.assertEqual(mock_vfr.call_count, 0)
            self.assertEqual(mock_vfg.call_count, 3)
            self.assertEqual(mock_nfd.call_count, 0)
            self.assertEqual(mock_mk.call_count, 0)

        # no warnings
        self.assertEqual(vctx.add_warning.call_count, 0)

    def test_completion_text(self):
        kwargs = {"completion_text": "some completion text"}

        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_flow_rules"
        ) as mock_vfr, mock.patch(
            "course.validation.validate_flow_group"
        ) as mock_vfg, mock.patch(
            "course.content.normalize_flow_desc"
        ) as mock_nfd, mock.patch(
            "course.validation.validate_markup"
        ) as mock_mk:

            validation.validate_flow_desc(
                vctx, location,
                self.get_updated_flow_desc(**kwargs))

            self.assertEqual(mock_vs.call_count, 1)
            self.assertEqual(mock_vfr.call_count, 0)
            self.assertEqual(mock_vfg.call_count, 2)
            self.assertEqual(mock_nfd.call_count, 0)
            self.assertEqual(mock_mk.call_count, 2)

            # no warnings
            self.assertEqual(vctx.add_warning.call_count, 0)

    def test_notify_on_submit(self):
        kwargs0 = {"notify_on_submit": []}
        kwargs = {"notify_on_submit": ["email1", "email2", ("email3",)]}

        with mock.patch(
                "course.validation.validate_struct"
        ) as mock_vs, mock.patch(
            "course.validation.validate_flow_rules"
        ) as mock_vfr, mock.patch(
            "course.validation.validate_flow_group"
        ) as mock_vfg, mock.patch(
            "course.content.normalize_flow_desc"
        ) as mock_nfd, mock.patch(
            "course.validation.validate_markup"
        ) as mock_mk:

            validation.validate_flow_desc(
                vctx, location,
                self.get_updated_flow_desc(**kwargs0))

            self.assertEqual(mock_vs.call_count, 1)
            mock_vs.reset_mock()

            self.assertEqual(mock_vfr.call_count, 0)
            mock_vfr.reset_mock()

            self.assertEqual(mock_vfg.call_count, 2)
            mock_vfg.reset_mock()

            self.assertEqual(mock_nfd.call_count, 0)
            mock_nfd.reset_mock()

            self.assertEqual(mock_mk.call_count, 1)
            mock_mk.reset_mock()

            with self.assertRaises(ValidationError) as cm:
                validation.validate_flow_desc(
                    vctx, location,
                    self.get_updated_flow_desc(**kwargs))

            expected_error_msg = "notify_on_submit: item 3 is not a string"

            self.assertIn(expected_error_msg, str(cm.exception))
            self.assertEqual(mock_vs.call_count, 1)
            self.assertEqual(mock_vfr.call_count, 0)
            self.assertEqual(mock_vfg.call_count, 2)
            self.assertEqual(mock_nfd.call_count, 0)
            self.assertEqual(mock_mk.call_count, 1)

            # no warnings
            self.assertEqual(vctx.add_warning.call_count, 0)

    def test_deprecated_attr(self):
        deprecated_attrs = [
            "max_points", "max_points_enforced_cap", "bonus_points"]

        for attr in deprecated_attrs:
            kwargs = {attr: 10}

            with mock.patch(
                    "course.validation.validate_struct"
            ) as mock_vs, mock.patch(
                "course.validation.validate_flow_rules"
            ) as mock_vfr, mock.patch(
                "course.validation.validate_flow_group"
            ) as mock_vfg, mock.patch(
                "course.content.normalize_flow_desc"
            ) as mock_nfd, mock.patch(
                "course.validation.validate_markup"
            ) as mock_mk:

                validation.validate_flow_desc(
                    vctx, location,
                    self.get_updated_flow_desc(**kwargs))

                self.assertEqual(mock_vs.call_count, 1)
                mock_vs.reset_mock()

                self.assertEqual(mock_vfr.call_count, 0)
                mock_vfr.reset_mock()

                self.assertEqual(mock_vfg.call_count, 2)
                mock_vfg.reset_mock()

                self.assertEqual(mock_nfd.call_count, 0)
                mock_nfd.reset_mock()

                self.assertEqual(mock_mk.call_count, 1)
                mock_mk.reset_mock()

                # no warnings

                expected_warn_msg = (
                    "Attribute '%s' is deprecated as part of a flow. "
                    "Specify it as part of a grading rule instead." % attr)

                self.assertIn(expected_warn_msg, vctx.add_warning.call_args[0])
                self.assertEqual(vctx.add_warning.call_count, 1)
                vctx.reset_mock()


class ValidateCalendarDescStructTest(ValidationTestMixin, unittest.TestCase):
    # test validation.validate_calendar_desc_struct

    def get_updated_event_desc(self, **kwargs):
        event_desc = {}
        event_desc.update(kwargs)
        return dict_to_struct(event_desc)

    def test_success(self):
        validation.validate_calendar_desc_struct(
            vctx, location, self.get_updated_event_desc())

    def test_has_event_kinds(self):
        validation.validate_calendar_desc_struct(
            vctx, location,
            self.get_updated_event_desc(
                event_kinds=dict_to_struct({
                    "lecture": dict_to_struct({
                        "title": "Lecture {nr}",
                        "color": "blue"
                    })
                }),
                events=dict_to_struct({
                    "lecture 1": dict_to_struct({
                        "title": "l1"})
                })
            ))

    def test_show_description_from(self):
        datespec1 = "some_date"
        validation.validate_calendar_desc_struct(
            vctx, location,
            self.get_updated_event_desc(
                events=dict_to_struct({
                    "lecture 1": dict_to_struct({
                        "title": "l1",
                        "description": "blabla",
                        "show_description_from": datespec1,
                    })
                })
            ))

        self.assertEqual(vctx.encounter_datespec.call_count, 1)
        self.assertIn(datespec1, vctx.encounter_datespec.call_args[0])
        vctx.reset_mock()

        datespec2 = "another_date"
        validation.validate_calendar_desc_struct(
            vctx, location,
            self.get_updated_event_desc(
                events=dict_to_struct({
                    "lecture 2": dict_to_struct({
                        "title": "l2",
                        "description": "blablabla",
                        "show_description_until": datespec2
                    })
                })
            ))
        self.assertEqual(vctx.encounter_datespec.call_count, 1)
        self.assertIn(datespec2, vctx.encounter_datespec.call_args[0])


class GetYamlFromRepoSafelyTest(unittest.TestCase):
    def test_success(self):
        repo = mock.MagicMock()
        full_name = "some_file"
        commit_sha = "some_commit_sha"
        with mock.patch("course.content.get_yaml_from_repo") as mock_gyfr:
            mock_gyfr.return_value = "some_string"
            validation.get_yaml_from_repo_safely(repo, full_name, commit_sha)

            _, kwargs = mock_gyfr.call_args
            self.assertEqual(kwargs["full_name"], full_name)
            self.assertEqual(kwargs["commit_sha"], commit_sha)
            self.assertEqual(kwargs["cached"], False)

    @suppress_stdout_decorator(suppress_stderr=True)
    def test_fail(self):
        repo = mock.MagicMock()
        full_name = "some_file"
        commit_sha = "some_commit_sha"
        with mock.patch("course.content.get_yaml_from_repo") as mock_gyfr:
            mock_gyfr.side_effect = RuntimeError("some error")
            with self.assertRaises(ValidationError) as cm:
                validation.get_yaml_from_repo_safely(repo, full_name, commit_sha)

            _, kwargs = mock_gyfr.call_args

            self.assertEqual(kwargs["full_name"], full_name)
            self.assertEqual(kwargs["commit_sha"], commit_sha)
            self.assertEqual(kwargs["cached"], False)

            expected_error_msg = "some_file: RuntimeError: some error"
            self.assertIn(expected_error_msg, str(cm.exception))


class CheckGradeIdentifierLinkTest(
        ValidationTestMixin, CoursesTestMixinBase, TestCase):
    # test validation.check_grade_identifier_link

    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()

        cls.default_grade_indentifier = "gopp1"

        cls.course1 = factories.CourseFactory(identifier="test-course1")
        cls.course2 = factories.CourseFactory(identifier="test-course2")
        cls.course1_gopp = factories.GradingOpportunityFactory(
            course=cls.course1, identifier=cls.default_grade_indentifier,
            flow_id="flow1_id")

        # Ensure cross gopp independence
        factories.GradingOpportunityFactory(
            course=cls.course1, identifier="gopp2",
            flow_id="flow1_id")

        # Ensure cross course independence
        factories.GradingOpportunityFactory(
            course=cls.course2, identifier=cls.default_grade_indentifier,
            flow_id="flow2_id")

    def test_success(self):
        validation.check_grade_identifier_link(
            vctx, location, self.course1, flow_id="flow1_id",
            flow_grade_identifier=self.default_grade_indentifier)

    def test_fail(self):
        new_flow_id = "flow2_id"
        with self.assertRaises(ValidationError) as cm:
            validation.check_grade_identifier_link(
                vctx, location, self.course1, flow_id=new_flow_id,
                flow_grade_identifier=self.course1_gopp.identifier)

        expected_error_msg = (
            "{location}: existing grading opportunity with identifier "
            "'{grade_identifier}' refers to flow '{other_flow_id}', however "
            "flow code in this flow ('{new_flow_id}') specifies the same "
            "grade identifier. "
            "(Have you renamed the flow? If so, edit the grading "
            "opportunity to match.)".format(
                location=location,
                grade_identifier=self.course1_gopp.identifier,
                other_flow_id=self.course1_gopp.flow_id,
                new_flow_id=new_flow_id))
        self.assertIn(expected_error_msg, str(cm.exception))


class CheckForPageTypeChangesTest(
        ValidationTestMixin, CoursesTestMixinBase, TestCase):
    # test validation.check_for_page_type_changes

    flow_id = "flow_id"

    def get_updated_flow_desc(
            self, **kwargs):
        flow_desc = {"access": ["access_rule1", "access_rule2"]}
        flow_desc["title"] = "test flow title"
        flow_desc["pages"] = [
            dict_to_struct({"id": "page1", "type": "PType1"}),
            dict_to_struct({"id": "page2", "type": "PType2"}),
            dict_to_struct({"id": "page3", "type": None}),
        ]

        flow_desc.update(kwargs)
        return dict_to_struct(flow_desc)

    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()
        cls.course1 = factories.CourseFactory(identifier="test-course1")
        course1_participation = factories.ParticipationFactory(course=cls.course1)
        course1_session1 = factories.FlowSessionFactory(
            course=cls.course1, participation=course1_participation,
            flow_id=cls.flow_id)
        factories.FlowPageDataFactory(
            flow_session=course1_session1, group_id="main",
            page_id="page1", page_type="PType1")
        factories.FlowPageDataFactory(
            flow_session=course1_session1, group_id="main",
            page_id="page2", page_type="PType2")

        # this entry is used to ensure page_data with page_type None
        # be excluded
        factories.FlowPageDataFactory(
            flow_session=course1_session1, group_id="main",
            page_id="page2", page_type=None)

        # Ensure cross flow_id independence
        course1_session2 = factories.FlowSessionFactory(
            course=cls.course1, participation=course1_participation,
            flow_id="another_flow_id")

        factories.FlowPageDataFactory(
            flow_session=course1_session2, group_id="main",
            page_id="page2", page_type="PType10")

        # for failure test, also to ensure page_data from different
        # group is not included
        factories.FlowPageDataFactory(
            flow_session=course1_session1, group_id="grp1",
            page_id="page2", page_type="PType2")

        # this is to ensure course is called in filter
        cls.course2 = factories.CourseFactory(identifier="test-course2")
        course2_participation = factories.ParticipationFactory(course=cls.course2)
        course2_session1 = factories.FlowSessionFactory(
            course=cls.course2, participation=course2_participation,
            flow_id=cls.flow_id)
        factories.FlowPageDataFactory(
            flow_session=course2_session1, group_id="main",
            page_id="page1", page_type="PType3", page_ordinal=1)

    def test_success(self):
        validation.check_for_page_type_changes(
            vctx, location, self.course1, self.flow_id,
            self.get_updated_flow_desc())

    def test_fail(self):
        with self.assertRaises(ValidationError) as cm:
            validation.check_for_page_type_changes(
                vctx, location, self.course2, self.flow_id,
                self.get_updated_flow_desc())

        expected_error_msg = (
            "group 'main', page 'page1': page type ('PType1') "
            "differs from type used in database ('PType3')"
        )
        self.assertIn(expected_error_msg, str(cm.exception))


class ValidateFlowIdTest(ValidationTestMixin, unittest.TestCase):
    # test validation.validate_flow_id

    def test_success(self):
        flow_id = "abc-def"
        validation.validate_flow_id(vctx, location, flow_id)
        flow_id = "abc_def1"
        validation.validate_flow_id(vctx, location, flow_id)

    def test_fail(self):
        expected_error_msg = (
            "invalid flow name. Flow names may only contain (roman) "
            "letters, numbers, dashes and underscores.")

        flow_id = "abc def"
        with self.assertRaises(ValidationError) as cm:
            validation.validate_flow_id(vctx, location, flow_id)
        self.assertIn(expected_error_msg, str(cm.exception))

        flow_id = "abc/def"
        with self.assertRaises(ValidationError) as cm:
            validation.validate_flow_id(vctx, location, flow_id)
        self.assertIn(expected_error_msg, str(cm.exception))


class ValidateStaticPageNameTest(ValidationTestMixin, unittest.TestCase):
    # test validation.validate_static_page_name

    def test_success(self):
        page_name = "abc-def"
        validation.validate_static_page_name(vctx, location, page_name)

        page_name = "abc_def1"
        validation.validate_static_page_name(vctx, location, page_name)

    def test_fail(self):
        expected_error_msg = (
            "invalid page name. Page names may only contain alphanumeric "
            "characters (any language) and hyphens.")

        page_name = "abc/def"

        with self.assertRaises(ValidationError) as cm:
            validation.validate_static_page_name(vctx, location, page_name)
        self.assertIn(expected_error_msg, str(cm.exception))


VALID_ATTRIBUTES_YML = """
unenrolled:
    - test1.pdf
student:
    - test2.pdf
"""

INVALID_ATTRIBUTES_YML = """
unenrolled:
    - test1.pdf
student:
    - test2.pdf
    - 42
"""

VALID_ATTRIBUTES_WITH_PUBLIC_YML = """
public:
    - test1.pdf
student:
    - test2.pdf
"""

INVALID_ATTRIBUTES_WITH_PUBLIC_AND_UNENROLLED_YML = """
public:
    - test1.pdf
unenrolled:
    - test2.pdf
"""

GITIGNORE = b"""a_dir
another_dir/*"""

GITIGNORE_COMMENTED = b"""
# a_dir
"""

default_access_kinds = ["public", "in_exam", "student", "ta",
                        "unenrolled", "instructor"]


class FakeBlob:
    def __init__(self, data):
        self.data = data


class FakeRepo:
    def __setitem__(self, key, value):
        self.__dict__[key] = value

    def __getitem__(self, item):
        return self.__dict__[item]


class CheckAttributesYmlTest(ValidationTestMixin, unittest.TestCase):
    # test validation.check_attributes_yml

    def setUp(self):
        super().setUp()
        patch = mock.patch("course.content.get_true_repo_and_path")
        self.mock_get_true_repo_and_path = patch.start()

        self.mock_get_true_repo_and_path.return_value = (vctx.repo, "")
        self.addCleanup(patch.stop)

    def test_success_with_no_attributes_yml_and_no_gitignore(self):
        path = ""
        repo = vctx.repo
        tree = Tree()
        validation.check_attributes_yml(
            vctx, repo, path, tree, default_access_kinds)

    def test_success_with_no_attributes_yml_and_no_gitignore_root_only_contains_a_subfolder(self):  # noqa
        path = ""
        repo = vctx.repo
        tree = Tree()

        tree.add(b"a_dir", stat.S_IFDIR,
                 hashlib.sha224(b"a dir").hexdigest().encode())
        validation.check_attributes_yml(
            vctx, repo, path, tree, default_access_kinds)
        self.assertEqual(vctx.add_warning.call_count, 0)

        # make sure check_attributes_yml is called recursively
        self.assertEqual(
            self.mock_get_true_repo_and_path.call_count, 2,
            "check_attributes_yml is expected to be called recursively")
        self.assertEqual(
            self.mock_get_true_repo_and_path.call_args[0][1], "a_dir",
            "check_attributes_yml is expected call with subfolder'a_dir'"
        )

    def test_success_with_attributes_yml(self):
        path = ""
        repo = vctx.repo
        tree = Tree()
        tree.add(ATTRIBUTES_FILENAME.encode(), stat.S_IFREG,
                 b".attributes.yml_content")

        fake_repo = FakeRepo()
        fake_repo[b".attributes.yml_content"] = FakeBlob(VALID_ATTRIBUTES_YML)
        self.mock_get_true_repo_and_path.return_value = (fake_repo, "")

        validation.check_attributes_yml(
            vctx, repo, path, tree, default_access_kinds)

    def test_attributes_yml_public_deprecated(self):
        path = ""
        repo = vctx.repo
        tree = Tree()
        tree.add(ATTRIBUTES_FILENAME.encode(), stat.S_IFREG,
                 b".attributes.yml_content")

        fake_repo = FakeRepo()
        fake_repo[b".attributes.yml_content"] = FakeBlob(
            VALID_ATTRIBUTES_WITH_PUBLIC_YML)
        self.mock_get_true_repo_and_path.return_value = (fake_repo, "")

        validation.check_attributes_yml(
            vctx, repo, path, tree, default_access_kinds)
        self.assertEqual(vctx.add_warning.call_count, 1)

        expected_warn_msg = ("Access class 'public' is deprecated. "
                             "Use 'unenrolled' instead.")
        self.assertIn(expected_warn_msg, vctx.add_warning.call_args[0])

    def test_failure_with_invalid_attributes_yml(self):
        path = ""
        repo = vctx.repo
        tree = Tree()
        tree.add(ATTRIBUTES_FILENAME.encode(), stat.S_IFREG,
                 b".attributes.yml_content")

        fake_repo = FakeRepo()
        fake_repo[b".attributes.yml_content"] = FakeBlob(INVALID_ATTRIBUTES_YML)
        self.mock_get_true_repo_and_path.return_value = (fake_repo, "")

        with self.assertRaises(ValidationError) as cm:
            validation.check_attributes_yml(
                vctx, repo, path, tree, default_access_kinds)

        expected_error_msg = "entry 2 in 'student' is not a string"
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_attributes_yml_failed_with_public_and_unenrolled(self):
        path = ""
        repo = vctx.repo
        tree = Tree()
        tree.add(ATTRIBUTES_FILENAME.encode(), stat.S_IFREG,
                 b".attributes.yml_content")

        fake_repo = FakeRepo()
        fake_repo[b".attributes.yml_content"] = (
            FakeBlob(INVALID_ATTRIBUTES_WITH_PUBLIC_AND_UNENROLLED_YML))
        self.mock_get_true_repo_and_path.return_value = (fake_repo, "")

        with self.assertRaises(ValidationError) as cm:
            validation.check_attributes_yml(
                vctx, repo, path, tree, default_access_kinds)

        expected_error_msg = ("access classes 'public' and 'unenrolled' may not "
                              "exist simultaneously.")
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_attributes_yml_gitignore_subfolder(self):
        path = ""
        repo = vctx.repo
        tree = Tree()

        tree.add(b".gitignore", stat.S_IFREG, b".gitignore_content")
        tree.add(b"a_dir", stat.S_IFDIR, b"a_dir_content")

        fake_repo = FakeRepo()
        fake_repo[b".gitignore_content"] = (
            FakeBlob(GITIGNORE))

        fake_repo[b"a_dir_content"] = Tree()
        self.mock_get_true_repo_and_path.return_value = (fake_repo, "")

        validation.check_attributes_yml(
            vctx, repo, path, tree, default_access_kinds)
        self.assertEqual(vctx.add_warning.call_count, 0)

        # make sure check_attributes_yml is not called recursively
        self.assertEqual(
            self.mock_get_true_repo_and_path.call_count, 1,
            "check_attributes_yml is expected to be called only once")

    def test_attributes_yml_gitignore_subfolder_commented(self):
        path = ""
        repo = vctx.repo
        tree = Tree()

        tree.add(b".gitignore", stat.S_IFREG, b".gitignore_content")
        tree.add(b"a_dir", stat.S_IFDIR, b"a_dir_content")

        fake_repo = FakeRepo()
        fake_repo[b".gitignore_content"] = (
            FakeBlob(GITIGNORE_COMMENTED))

        fake_repo[b"a_dir_content"] = Tree()
        self.mock_get_true_repo_and_path.return_value = (fake_repo, "")

        validation.check_attributes_yml(
            vctx, repo, path, tree, default_access_kinds)
        self.assertEqual(vctx.add_warning.call_count, 0)

        # make sure check_attributes_yml is called recursively
        self.assertEqual(
            self.mock_get_true_repo_and_path.call_count, 2,
            "check_attributes_yml is expected to be called twice")

    def test_attributes_yml_failed_with_public_and_unenrolled_in_subfolder(self):
        path = ""
        repo = vctx.repo
        tree = Tree()

        tree.add(b"a_dir", stat.S_IFDIR, b"a_dir_content")

        fake_repo = FakeRepo()
        fake_sub_repo = FakeRepo()

        sub_tree = Tree()
        sub_tree.add(b"some_file", stat.S_IFREG, b"some_content")
        sub_tree.add(ATTRIBUTES_FILENAME.encode(), stat.S_IFREG,
                 b".attributes.yml_content")

        fake_sub_repo[b".attributes.yml_content"] = FakeBlob(
            INVALID_ATTRIBUTES_WITH_PUBLIC_AND_UNENROLLED_YML)

        fake_repo[b"a_dir_content"] = sub_tree
        self.mock_get_true_repo_and_path.side_effect = [
            (fake_repo, ""), (fake_sub_repo, "a_dir")]

        with self.assertRaises(ValidationError) as cm:
            validation.check_attributes_yml(
                vctx, repo, path, tree, default_access_kinds)

        expected_error_msg = ("access classes 'public' and 'unenrolled' may not "
                              "exist simultaneously.")
        self.assertIn(expected_error_msg, str(cm.exception))

        # make sure check_attributes_yml is called recursively
        self.assertEqual(
            self.mock_get_true_repo_and_path.call_count, 2,
            "check_attributes_yml is expected to be called twice")
