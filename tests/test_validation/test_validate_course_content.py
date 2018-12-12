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

import stat
from dulwich.repo import Tree

from django.core.exceptions import ObjectDoesNotExist
from django.test import TestCase

from relate.utils import dict_to_struct

from course.models import (
    ParticipationRole,
    ParticipationPermission, ParticipationRolePermission)
from course import validation
from course.validation import ValidationError
from course.content import get_yaml_from_repo, get_repo_blob, load_yaml
from course.validation import get_yaml_from_repo_safely
from course.constants import (
    DEFAULT_ACCESS_KINDS, participation_permission as pperm)

from tests import factories
from tests.base_test_mixins import CoursesTestMixinBase
from tests.utils import mock

FLOW_WITHOUT_RULE_YAML = """
title: "Flow 1 without rule"
description: |
    # Linear Algebra Recap

pages:

-
    type: Page
    id: intro
    content: |

        # Hello World

"""

FLOW_WITH_ACCESS_RULE_YAML = """
title: "Flow 1 with access rule"
description: |
    # Linear Algebra Recap

rules:
    access:
    -
        if_has_role: [student, ta, instructor]
        permissions: [view]

    grade_identifier: null

pages:

-
    type: Page
    id: intro
    content: |

        # Hello World

"""

FLOW_WITH_GRADING_RULE_YAML_PATTERN = """
title: "RELATE Test Quiz1"
description: |

    # RELATE Test Quiz

rules:
    grade_identifier: %(grade_identifier)s
    grade_aggregation_strategy: use_latest

    grading:
    -
        credit_percent: 100

groups:
-
    id: quiz_start
    shuffle: False
    pages:
    -
        type: TextQuestion
        id: half
        value: 5
        prompt: |

          # A half

          What's a half?

        answers:

          - type: float
            value: 0.5
            rtol: 1e-4
          - <plain>half
          - <plain>a half

"""

events_file = "events.yml"
my_events_file = "my_events_file.yml"
course_file = "test_course_file"
course_desc = mock.MagicMock()
validate_sha = "test_validate_sha"

staticpage1_path = "staticpages/spage1.yml"
staticpage1_location = "spage1.yml"
staticpage1_id = "spage1"
staticpage1_desc = mock.MagicMock()

staticpage2_path = "staticpages/spage2.yml"
staticpage2_location = "spage2.yml"
staticpage2_id = "spage2"
staticpage2_desc = mock.MagicMock()

flow1_path = "flows/flow1.yml"
flow1_location = "flow1.yml"
flow1_id = "flow1"
flow1_no_rule_desc = dict_to_struct(load_yaml(FLOW_WITHOUT_RULE_YAML))
flow1_with_access_rule_desc = dict_to_struct(load_yaml(FLOW_WITH_ACCESS_RULE_YAML))

flow2_path = "flows/flow2.yml"
flow2_location = "flow2.yml"
flow2_id = "flow2"
flow2_grade_identifier = "la_quiz"
flow2_default_desc = dict_to_struct(load_yaml(
    FLOW_WITH_GRADING_RULE_YAML_PATTERN % {
        "grade_identifier": flow2_grade_identifier}))

flow3_path = "flows/flow3.yml"
flow3_location = "flow3.yml"
flow3_id = "flow3"
flow3_grade_identifier = "la_quiz2"
flow3_default_desc = dict_to_struct(load_yaml(
    FLOW_WITH_GRADING_RULE_YAML_PATTERN % {
        "grade_identifier": flow3_grade_identifier}))

flow3_with_duplicated_grade_identifier_desc = flow2_default_desc


def get_yaml_from_repo_side_effect(repo, full_name, commit_sha, cached=True):
    if full_name == events_file:
        return dict_to_struct(
            {"event_kinds": dict_to_struct({
                "lecture": dict_to_struct({
                    "title": "Lecture {nr}",
                    "color": "blue"
                })}),
                "events": dict_to_struct({
                    "lecture 1": dict_to_struct({
                        "title": "l1"})
                })})
    else:
        return get_yaml_from_repo(repo, full_name, commit_sha, cached)


def get_yaml_from_repo_no_events_file_side_effect(
        repo, full_name, commit_sha, cached=True):
    if full_name in [events_file, my_events_file]:
        raise ObjectDoesNotExist
    else:
        return get_yaml_from_repo(repo, full_name, commit_sha, cached)


def get_yaml_from_repo_safely_side_effect(repo, full_name, commit_sha):
    if full_name == course_file:
        return course_desc
    if full_name == flow1_path:
        return flow1_no_rule_desc
    if full_name == flow2_path:
        return flow2_default_desc
    if full_name == flow3_path:
        return flow3_default_desc

    if full_name == staticpage1_path:
        return staticpage1_desc
    if full_name == staticpage2_path:
        return staticpage2_desc

    return get_yaml_from_repo_safely(repo, full_name, commit_sha)


def get_yaml_from_repo_safely_with_duplicate_grade_identifier_side_effect(
        repo, full_name, commit_sha):
    if full_name == course_file:
        return course_desc
    if full_name == flow1_path:
        return flow1_with_access_rule_desc

    if full_name == flow2_path:
        return flow2_default_desc
    if full_name == flow3_path:
        return flow3_with_duplicated_grade_identifier_desc

    if full_name == staticpage1_path:
        return staticpage1_desc
    if full_name == staticpage2_path:
        return staticpage2_desc

    return get_yaml_from_repo_safely(repo, full_name, commit_sha)


def get_repo_blob_side_effect(repo, full_name, commit_sha, allow_tree=True):
    if full_name == "media" and allow_tree:
        raise ObjectDoesNotExist()
    if full_name == "flows" and allow_tree:
        tree = Tree()
        tree.add(b"not_a_flow", stat.S_IFREG, b"not a flow")
        tree.add(flow1_location.encode(), stat.S_IFREG, b"a flow")

        tree.add(flow2_location.encode(), stat.S_IFREG, b"another flow")
        tree.add(flow3_location.encode(), stat.S_IFREG, b"yet another flow")
        return tree
    if full_name == "staticpages":
        tree = Tree()
        tree.add(b"not_a_page", stat.S_IFREG, b"not a page")
        tree.add(staticpage1_location.encode(), stat.S_IFREG, b"a static page")

        tree.add(staticpage2_location.encode(), stat.S_IFREG, b"a static page")
        return tree
    if full_name == "":
        return Tree()

    return get_repo_blob(repo, full_name, commit_sha, allow_tree)


def get_repo_blob_side_effect1(repo, full_name, commit_sha, allow_tree=True):
    if full_name == "media" and allow_tree:
        tree = Tree()
        tree.add(b"media", stat.S_IFDIR, b"some media")
        return tree
    if full_name == "flows" and allow_tree:
        tree = Tree()
        tree.add(b"not_a_flow", stat.S_IFREG, b"not a flow")
        tree.add(flow1_location.encode(), stat.S_IFREG, b"a flow")
        return tree
    if full_name == "staticpages":
        tree = Tree()
        tree.add(b"not_a_page", stat.S_IFREG, b"not a page")
        tree.add(staticpage1_location.encode(), stat.S_IFREG, b"a static page")

        tree.add(staticpage2_location.encode(), stat.S_IFREG, b"a static page")
        return tree
    if full_name == "":
        return Tree()

    return get_repo_blob(repo, full_name, commit_sha, allow_tree)


def get_repo_blob_side_effect2(repo, full_name, commit_sha, allow_tree=True):
    if full_name == "media" and allow_tree:
        raise ObjectDoesNotExist()
    if full_name == "flows" and allow_tree:
        raise ObjectDoesNotExist()
    if full_name == "staticpages":
        tree = Tree()
        tree.add(b"not_a_page", stat.S_IFREG, b"not a page")
        tree.add(staticpage1_location.encode(), stat.S_IFREG, b"a static page")

        tree.add(staticpage2_location.encode(), stat.S_IFREG, b"a static page")
        return tree
    if full_name == "":
        return Tree()

    return get_repo_blob(repo, full_name, commit_sha, allow_tree)


def get_repo_blob_side_effect3(repo, full_name, commit_sha, allow_tree=True):
    if full_name == "media" and allow_tree:
        raise ObjectDoesNotExist()
    if full_name == "flows" and allow_tree:
        tree = Tree()
        tree.add(b"not_a_flow", stat.S_IFREG, b"not a flow")
        tree.add(flow1_location.encode(), stat.S_IFREG, b"a flow")
        return tree
    if full_name == "staticpages":
        raise ObjectDoesNotExist()
    if full_name == "":
        return Tree()

    return get_repo_blob(repo, full_name, commit_sha, allow_tree)


class ValidateCourseContentTest(CoursesTestMixinBase, TestCase):
    # test validation.validate_course_content

    def setUp(self):
        self.repo = mock.MagicMock()

        self.course = factories.CourseFactory()

        fake_get_yaml_from_repo_safely = mock.patch(
            "course.validation.get_yaml_from_repo_safely")
        self.mock_get_yaml_from_repo_safely = fake_get_yaml_from_repo_safely.start()
        self.mock_get_yaml_from_repo_safely.side_effect = (
            get_yaml_from_repo_safely_side_effect)
        self.addCleanup(fake_get_yaml_from_repo_safely.stop)

        fake_validate_staticpage_desc = mock.patch(
            "course.validation.validate_staticpage_desc")
        self.mock_validate_staticpage_desc = fake_validate_staticpage_desc.start()
        self.addCleanup(fake_validate_staticpage_desc.stop)

        fake_get_yaml_from_repo = mock.patch(
            "course.content.get_yaml_from_repo")
        self.mock_get_yaml_from_repo = fake_get_yaml_from_repo.start()
        self.mock_get_yaml_from_repo.side_effect = get_yaml_from_repo_side_effect
        self.addCleanup(fake_get_yaml_from_repo.stop)

        fake_validate_calendar_desc_struct = mock.patch(
            "course.validation.validate_calendar_desc_struct"
        )
        self.mock_validate_calendar_desc_struct = (
            fake_validate_calendar_desc_struct.start())
        self.addCleanup(fake_validate_calendar_desc_struct.stop)

        fake_check_attributes_yml = (
            mock.patch("course.validation.check_attributes_yml"))
        self.mock_check_attributes_yml = fake_check_attributes_yml.start()
        self.addCleanup(fake_check_attributes_yml.stop)

        fake_validate_flow_id = (
            mock.patch("course.validation.validate_flow_id"))
        self.mock_validate_flow_id = fake_validate_flow_id.start()
        self.addCleanup(fake_validate_flow_id.stop)

        fake_validate_flow_desc = (
            mock.patch("course.validation.validate_flow_desc"))
        self.mock_validate_flow_desc = fake_validate_flow_desc.start()
        self.addCleanup(fake_validate_flow_desc.stop)

        fake_check_for_page_type_changes = (
            mock.patch("course.validation.check_for_page_type_changes"))
        self.mock_check_for_page_type_changes = (
            fake_check_for_page_type_changes.start())
        self.addCleanup(fake_check_for_page_type_changes.stop)

        fake_check_grade_identifier_link = (
            mock.patch("course.validation.check_grade_identifier_link"))
        self.mock_check_grade_identifier_link = (
            fake_check_grade_identifier_link.start())
        self.addCleanup(fake_check_grade_identifier_link.stop)

        fake_get_repo_blob = (
            mock.patch("course.validation.get_repo_blob"))
        self.mock_get_repo_blob = fake_get_repo_blob.start()
        self.mock_get_repo_blob.side_effect = get_repo_blob_side_effect
        self.addCleanup(fake_get_repo_blob.stop)

        fake_validate_static_page_name = (
            mock.patch("course.validation.validate_static_page_name"))
        self.mock_validate_static_page_name = fake_validate_static_page_name.start()
        self.addCleanup(fake_validate_static_page_name.stop)

        fake_vctx_add_warning = (
            mock.patch("course.validation.ValidationContext.add_warning"))
        self.mock_vctx_add_warning = fake_vctx_add_warning.start()
        self.addCleanup(fake_vctx_add_warning.stop)

    def test_course_none(self):
        validation.validate_course_content(
            self.repo, course_file, events_file, validate_sha, course=None)
        self.assertEqual(self.mock_vctx_add_warning.call_count, 0)

        # validate_staticpage_desc call to validate course_page, and 2 staticpages
        self.assertEqual(self.mock_validate_staticpage_desc.call_count, 3)

        # make sure validate_staticpage_desc was called with expected args
        expected_validate_staticpage_desc_call_args = {
            (course_file, course_desc),
            (staticpage1_path, staticpage1_desc),
            (staticpage2_path, staticpage2_desc)}
        args_set = set()
        for args, kwargs in self.mock_validate_staticpage_desc.call_args_list:
            args_set.add(args[1:])

        self.assertSetEqual(expected_validate_staticpage_desc_call_args,
                            args_set)

        # validate_calendar_desc_struct is called
        self.assertEqual(self.mock_validate_calendar_desc_struct.call_count, 1)

        # check_attributes_yml is called
        self.assertEqual(self.mock_check_attributes_yml.call_count, 1)
        expected_check_attributes_yml_call_args_access_kinds = DEFAULT_ACCESS_KINDS
        self.assertEqual(
            self.mock_check_attributes_yml.call_args[0][-1],
            expected_check_attributes_yml_call_args_access_kinds)

        # validate_flow_id is called 3 times, for 3 flow files
        self.assertEqual(self.mock_validate_flow_id.call_count, 3)

        # make sure validate_flow_id was called with expected args
        expected_validate_flow_id_call_args = {
            (flow1_location, flow1_id),
            (flow2_location, flow2_id),
            (flow3_location, flow3_id), }
        args_set = set()
        for args, kwargs in self.mock_validate_flow_id.call_args_list:
            args_set.add(args[1:])

        self.assertSetEqual(expected_validate_flow_id_call_args, args_set)

        # validate_flow_desc is called 3 times, for 3 flow files
        self.assertEqual(self.mock_validate_flow_desc.call_count, 3)

        # make sure validate_flow_desc was called with expected args
        expected_validate_flow_desc_call_args = {
            (flow1_path, flow1_no_rule_desc),
            (flow2_path, flow2_default_desc),
            (flow3_path, flow3_default_desc), }
        args_set = set()
        for args, kwargs in self.mock_validate_flow_desc.call_args_list:
            args_set.add(args[1:])

        self.assertSetEqual(expected_validate_flow_desc_call_args, args_set)

        # check_grade_identifier_link is not called, because course is None
        self.assertEqual(self.mock_check_grade_identifier_link.call_count, 0)

        # check_for_page_type_changes is not called, because course is None
        self.assertEqual(self.mock_check_for_page_type_changes.call_count, 0)

        # validate_static_page_name is called once for 2 static pages
        self.assertEqual(self.mock_validate_static_page_name.call_count, 2)

        # make sure validate_static_page_name was called with expected args
        expected_validate_static_page_name_call_args = {
            (staticpage1_location, staticpage1_id),
            (staticpage2_location, staticpage2_id)}
        args_set = set()
        for args, kwargs in self.mock_validate_static_page_name.call_args_list:
            args_set.add(args[1:])

        self.assertSetEqual(expected_validate_static_page_name_call_args, args_set)

    def test_course_not_none(self):
        validation.validate_course_content(
            self.repo, course_file, events_file, validate_sha, course=self.course)
        self.assertEqual(self.mock_vctx_add_warning.call_count, 0)

        # validate_staticpage_desc call to validate course_page, and 2 staticpages
        self.assertEqual(self.mock_validate_staticpage_desc.call_count, 3)

        # validate_calendar_desc_struct is called
        self.assertEqual(self.mock_validate_calendar_desc_struct.call_count, 1)

        # check_attributes_yml is called
        self.assertEqual(self.mock_check_attributes_yml.call_count, 1)

        # validate_flow_id is called 3 times, for 3 flow files
        self.assertEqual(self.mock_validate_flow_id.call_count, 3)

        # validate_flow_desc is called 3 times, for 3 flow files
        self.assertEqual(self.mock_validate_flow_desc.call_count, 3)

        # check_grade_identifier_link is call twice, only 2 flow
        # has grade_identifier
        self.assertEqual(self.mock_check_grade_identifier_link.call_count, 2)
        # make sure validate_static_page_name was called with expected args
        expected_check_grade_identifier_link_call_args = {
            (flow2_path, self.course, flow2_id, flow2_grade_identifier),
            (flow3_path, self.course, flow3_id, flow3_grade_identifier)}
        args_set = set()
        for args, kwargs in self.mock_check_grade_identifier_link.call_args_list:
            args_set.add(args[1:])

        self.assertSetEqual(
            expected_check_grade_identifier_link_call_args, args_set)

        # check_for_page_type_changes is called 3 times for 3 flows
        self.assertEqual(self.mock_check_for_page_type_changes.call_count, 3)

        # validate_static_page_name is called once for 2 static pages
        self.assertEqual(self.mock_validate_static_page_name.call_count, 2)

    def test_course_custom_events_file_does_not_exist(self):
        self.mock_get_yaml_from_repo.side_effect = (
            get_yaml_from_repo_no_events_file_side_effect)
        validation.validate_course_content(
            self.repo, course_file, "my_events_file.yml", validate_sha,
            course=self.course)
        self.assertEqual(self.mock_vctx_add_warning.call_count, 1)
        expected_warn_msg = (
            "Your course repository does not have an events "
            "file named 'my_events_file.yml'.")

        self.assertIn(expected_warn_msg, self.mock_vctx_add_warning.call_args[0])

        # validate_staticpage_desc call to validate course_page, and 2 staticpages
        self.assertEqual(self.mock_validate_staticpage_desc.call_count, 3)

        # validate_calendar_desc_struct is not called
        self.assertEqual(self.mock_validate_calendar_desc_struct.call_count, 0)

        # check_attributes_yml is called
        self.assertEqual(self.mock_check_attributes_yml.call_count, 1)

        # validate_flow_id is called 3 times, for 3 flow files
        self.assertEqual(self.mock_validate_flow_id.call_count, 3)

        # validate_flow_desc is called 3 times, for 3 flow files
        self.assertEqual(self.mock_validate_flow_desc.call_count, 3)

        # check_for_page_type_changes is called 3 times for 3 flows
        self.assertEqual(self.mock_check_for_page_type_changes.call_count, 3)

        # validate_static_page_name is called once for 2 static pages
        self.assertEqual(self.mock_validate_static_page_name.call_count, 2)

    def test_course_no_events_file(self):
        self.mock_get_yaml_from_repo.side_effect = (
            get_yaml_from_repo_no_events_file_side_effect)
        validation.validate_course_content(
            self.repo, course_file, events_file, validate_sha, course=self.course)
        self.assertEqual(self.mock_vctx_add_warning.call_count, 0)

        # validate_staticpage_desc call to validate course_page, and 2 staticpages
        self.assertEqual(self.mock_validate_staticpage_desc.call_count, 3)

        # validate_calendar_desc_struct is not called
        self.assertEqual(self.mock_validate_calendar_desc_struct.call_count, 0)

        # check_attributes_yml is called
        self.assertEqual(self.mock_check_attributes_yml.call_count, 1)

        # validate_flow_id is called 3 times, for 3 flow files
        self.assertEqual(self.mock_validate_flow_id.call_count, 3)

        # validate_flow_desc is called 3 times, for 3 flow files
        self.assertEqual(self.mock_validate_flow_desc.call_count, 3)

        # check_for_page_type_changes is called 3 times for 3 flows
        self.assertEqual(self.mock_check_for_page_type_changes.call_count, 3)

        # validate_static_page_name is called once for 2 static pages
        self.assertEqual(self.mock_validate_static_page_name.call_count, 2)

    def test_get_repo_blob_media_dir_not_empty(self):
        self.mock_get_repo_blob.side_effect = get_repo_blob_side_effect1
        validation.validate_course_content(
            self.repo, course_file, events_file, validate_sha, course=self.course)
        self.assertEqual(self.mock_vctx_add_warning.call_count, 1)

        expected_warn_msg = (
            "Your course repository has a 'media/' directory. Linking to "
            "media files using 'media:' is discouraged. Use the 'repo:' "
            "and 'repocur:' linkng schemes instead.")

        self.assertIn(expected_warn_msg, self.mock_vctx_add_warning.call_args[0])

        # validate_staticpage_desc call to validate course_page, and 2 staticpages
        self.assertEqual(self.mock_validate_staticpage_desc.call_count, 3)

        # validate_calendar_desc_struct is called
        self.assertEqual(self.mock_validate_calendar_desc_struct.call_count, 1)

        # check_attributes_yml is called
        self.assertEqual(self.mock_check_attributes_yml.call_count, 1)

        # validate_flow_id is called once, there's only 1 flow file
        self.assertEqual(self.mock_validate_flow_id.call_count, 1)

        # validate_flow_desc is called once, there's only 1 flow file
        self.assertEqual(self.mock_validate_flow_desc.call_count, 1)

        # check_for_page_type_changes is called once, there's only 1 flow file
        self.assertEqual(self.mock_check_for_page_type_changes.call_count, 1)

        # validate_static_page_name is called twice for 2 static pages
        self.assertEqual(self.mock_validate_static_page_name.call_count, 2)

    def test_get_repo_blob_flows_dir_empty(self):
        self.mock_get_repo_blob.side_effect = get_repo_blob_side_effect2
        validation.validate_course_content(
            self.repo, course_file, events_file, validate_sha, course=self.course)
        self.assertEqual(self.mock_vctx_add_warning.call_count, 0)

        # validate_staticpage_desc call to validate course_page, and 2 staticpages
        self.assertEqual(self.mock_validate_staticpage_desc.call_count, 3)

        # validate_calendar_desc_struct is called
        self.assertEqual(self.mock_validate_calendar_desc_struct.call_count, 1)

        # check_attributes_yml is called
        self.assertEqual(self.mock_check_attributes_yml.call_count, 1)

        # validate_flow_id is not called, because no flow files
        self.assertEqual(self.mock_validate_flow_id.call_count, 0)

        # validate_flow_desc is not called, because no flow files
        self.assertEqual(self.mock_validate_flow_desc.call_count, 0)

        # check_for_page_type_changes is not called, because no flow files
        self.assertEqual(self.mock_check_for_page_type_changes.call_count, 0)

        # validate_static_page_name is called twice for two static pages
        self.assertEqual(self.mock_validate_static_page_name.call_count, 2)

    def test_get_repo_blob_staticpages_empty(self):
        self.mock_get_repo_blob.side_effect = get_repo_blob_side_effect3
        validation.validate_course_content(
            self.repo, course_file, events_file, validate_sha, course=self.course)
        self.assertEqual(self.mock_vctx_add_warning.call_count, 0)

        # validate_staticpage_desc call to validate course_page only
        self.assertEqual(self.mock_validate_staticpage_desc.call_count, 1)

        # validate_calendar_desc_struct is called
        self.assertEqual(self.mock_validate_calendar_desc_struct.call_count, 1)

        # check_attributes_yml is called
        self.assertEqual(self.mock_check_attributes_yml.call_count, 1)

        # validate_flow_id is called 3 times, there's only 1 flow file
        self.assertEqual(self.mock_validate_flow_id.call_count, 1)

        # validate_flow_desc is called once, there's only 1 flow file
        self.assertEqual(self.mock_validate_flow_desc.call_count, 1)

        # check_for_page_type_changes is called once, there's only 1 flow file
        self.assertEqual(self.mock_check_for_page_type_changes.call_count, 1)

        # validate_static_page_name is not called, no static page
        self.assertEqual(self.mock_validate_static_page_name.call_count, 0)

    def test_duplicated_grade_identifier(self):
        self.mock_get_yaml_from_repo_safely.side_effect = (
            get_yaml_from_repo_safely_with_duplicate_grade_identifier_side_effect
        )
        with self.assertRaises(ValidationError) as cm:
            validation.validate_course_content(
                self.repo, course_file, events_file, validate_sha,
                course=self.course)

        expected_error_msg = ("flows/flow3.yml: flow uses the same "
                              "grade_identifier as another flow")
        self.assertIn(expected_error_msg, str(cm.exception))
        self.assertEqual(self.mock_vctx_add_warning.call_count, 0)

    def test_course_not_none_check_attributes_yml(self):
        # This test check_attributes_yml args access_type
        # is generated with course-specific pperm.access_files_for

        user = factories.UserFactory()

        # {{{ create another course with different set of participation role
        # permission and participation permission

        another_course = factories.CourseFactory(identifier="another-course")
        another_course_prole = ParticipationRole(
            course=another_course,
            identifier="another_course_role",
            name="another_course_role")
        another_course_prole.save()

        another_course_participation = factories.ParticipationFactory(
            course=another_course, user=user)
        another_course_participation.roles.set([another_course_prole])

        another_course_ppm_access_files_for_roles = "another_role"
        ParticipationPermission(
            participation=another_course_participation,
            permission=pperm.access_files_for,
            argument=another_course_ppm_access_files_for_roles
        ).save()

        another_course_rpm_access_files_for_roles = "another_course_everyone"
        ParticipationRolePermission(
            role=another_course_prole,
            permission=pperm.access_files_for,
            argument=another_course_rpm_access_files_for_roles).save()

        self.assertTrue(
            another_course_participation.has_permission(
                pperm.access_files_for,
                argument=another_course_ppm_access_files_for_roles))

        self.assertTrue(
            another_course_participation.has_permission(
                pperm.access_files_for,
                argument=another_course_rpm_access_files_for_roles))
        # }}}

        # {{{ create for default test course extra participation role
        # permission and participation permission

        this_course_prole = ParticipationRole(
            course=self.course,
            identifier="another_course_role",
            name="another_course_role")
        this_course_prole.save()

        this_course_participation = factories.ParticipationFactory(
            course=self.course, user=user)
        this_course_participation.roles.set([this_course_prole])

        this_course_ppm_access_files_for_roles = "this_course_some_role"
        ParticipationPermission(
            participation=this_course_participation,
            permission=pperm.access_files_for,
            argument=this_course_ppm_access_files_for_roles
        ).save()

        this_course_rpm_access_files_for_roles = "this_course_everyone"
        ParticipationRolePermission(
            role=this_course_prole,
            permission=pperm.access_files_for,
            argument=this_course_rpm_access_files_for_roles).save()

        self.assertTrue(
            this_course_participation.has_permission(
                pperm.access_files_for,
                argument=this_course_ppm_access_files_for_roles))

        self.assertTrue(
            this_course_participation.has_permission(
                pperm.access_files_for,
                argument=this_course_rpm_access_files_for_roles))
        # }}}

        validation.validate_course_content(
            self.repo, course_file, events_file, validate_sha, course=self.course)
        self.assertEqual(self.mock_vctx_add_warning.call_count, 0)

        # check_attributes_yml is called
        self.assertEqual(self.mock_check_attributes_yml.call_count, 1)

        access_kinds = list(self.mock_check_attributes_yml.call_args[0][-1])

        self.assertIn(this_course_ppm_access_files_for_roles, access_kinds)
        self.assertIn(this_course_rpm_access_files_for_roles, access_kinds)

        self.assertNotIn(another_course_ppm_access_files_for_roles, access_kinds)
        self.assertNotIn(another_course_rpm_access_files_for_roles, access_kinds)

# vim: foldmethod=marker
