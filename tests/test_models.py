__doc__ = """
This is testing uncovering part of course.models by other tests
"""

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

from datetime import datetime, timedelta
import pytest
import unittest
import pytz_deprecation_shim as pytz

from django.conf import settings
from django.test import TestCase, override_settings
from django.core.exceptions import ValidationError
from django.utils.timezone import now

from course import models
from course.constants import participation_permission as pperm
from course import constants
from course.content import dict_to_struct

from tests.base_test_mixins import CoursesTestMixinBase
from tests import factories
from tests.utils import mock


@pytest.mark.django_db
class CourseTest(CoursesTestMixinBase, unittest.TestCase):
    def setUp(self):
        self.course1 = factories.CourseFactory()
        self.course2 = factories.CourseFactory(identifier="another-course")

    def test_get_absolute_url(self):
        self.assertEqual(
            self.course1.get_absolute_url(),
            self.get_course_page_url(self.course1.identifier)
        )

        self.assertEqual(
            self.course2.get_absolute_url(),
            self.get_course_page_url(self.course2.identifier)
        )

    def test_get_from_email(self):
        with override_settings(RELATE_EMAIL_SMTP_ALLOW_NONAUTHORIZED_SENDER=True):
            self.assertEqual(self.course1.get_from_email(), self.course1.from_email)
            self.assertEqual(self.course2.get_from_email(), self.course2.from_email)

        notification_email_from = "expected_email_from@example.com"
        robot_email_from = "robot@example.com"
        with override_settings(
                RELATE_EMAIL_SMTP_ALLOW_NONAUTHORIZED_SENDER=False,
                NOTIFICATION_EMAIL_FROM=notification_email_from,
                ROBOT_EMAIL_FROM=robot_email_from):
            self.assertEqual(self.course1.get_from_email(), notification_email_from)
            self.assertEqual(self.course2.get_from_email(), notification_email_from)

            del settings.NOTIFICATION_EMAIL_FROM
            self.assertEqual(self.course1.get_from_email(), robot_email_from)
            self.assertEqual(self.course2.get_from_email(), robot_email_from)

    def test_get_reply_to_email(self):
        with override_settings(RELATE_EMAIL_SMTP_ALLOW_NONAUTHORIZED_SENDER=True):
            self.assertEqual(
                self.course1.get_reply_to_email(), self.course1.from_email)
            self.assertEqual(
                self.course2.get_reply_to_email(), self.course2.from_email)

        with override_settings(
                RELATE_EMAIL_SMTP_ALLOW_NONAUTHORIZED_SENDER=False):
            self.assertEqual(
                self.course1.get_reply_to_email(), self.course1.notify_email)
            self.assertEqual(
                self.course2.get_reply_to_email(), self.course2.notify_email)

    def test_add_default_roles_and_permissions(self):
        # make sure add_default_roles_and_permissions is called after
        # a course is created, and not called when updated.
        with mock.patch(
                "course.models.add_default_roles_and_permissions"
        ) as mock_add_default_roles_and_permissions:
            new_course = factories.CourseFactory(identifier="yet-another-course")
            self.assertEqual(mock_add_default_roles_and_permissions.call_count, 1)
            self.assertIn(
                new_course, mock_add_default_roles_and_permissions.call_args[0])

            mock_add_default_roles_and_permissions.reset_mock()

            new_course.is_hidden = False
            new_course.save()
            self.assertEqual(mock_add_default_roles_and_permissions.call_count, 0)


@pytest.mark.django_db
class RelateModelTestMixin:
    def setUp(self):
        self.course = factories.CourseFactory()


class EventTest(RelateModelTestMixin, unittest.TestCase):
    def test_unicode(self):
        event1 = factories.EventFactory(course=self.course, kind="my_event",
                                        ordinal=None)
        event2 = factories.EventFactory(course=self.course, kind="my_event2",
                                        ordinal=None)
        self.assertNotEqual(str(event1), str(event2))

        event3 = factories.EventFactory(course=self.course, kind="my_event3",
                                        ordinal=1)
        event4 = factories.EventFactory(course=self.course, kind="my_event3",
                                        ordinal=2)
        self.assertNotEqual(str(event3), str(event4))

    def test_validate_kind_with_spaces(self):
        with self.assertRaises(ValidationError) as cm:
            factories.EventFactory(course=self.course, kind="my event")

        expected_error_msg = (
            "Should be lower_case_with_underscores, no spaces "
            "allowed.")
        self.assertIn(expected_error_msg, cm.exception.message_dict["kind"])

    def test_validate_kind_with_upper_case(self):
        with self.assertRaises(ValidationError) as cm:
            factories.EventFactory(course=self.course, kind="myEvent")

        expected_error_msg = (
            "Should be lower_case_with_underscores, no spaces "
            "allowed.")
        self.assertIn(expected_error_msg, cm.exception.message_dict["kind"])

    def test_validate_kind_with_hyphen(self):
        with self.assertRaises(ValidationError) as cm:
            factories.EventFactory(course=self.course, kind="my-event")

        expected_error_msg = (
            "Should be lower_case_with_underscores, no spaces "
            "allowed.")
        self.assertIn(expected_error_msg, cm.exception.message_dict["kind"])

    def test_clean_end_time(self):
        now_dt = now()
        with self.assertRaises(ValidationError) as cm:
            factories.EventFactory(
                course=self.course, time=now_dt, kind="some_kind",
                end_time=now_dt - timedelta(seconds=1))

        expected_error_msg = "End time must not be ahead of start time."
        self.assertIn(expected_error_msg, cm.exception.message_dict["end_time"])

        # make sure end_time >= time is valid
        factories.EventFactory(
            course=self.course, time=now(), kind="some_kind",
            end_time=now())

        factories.EventFactory(
            course=self.course, time=now(), kind="some_kind",
            end_time=now() + timedelta(seconds=1))

    def test_event_with_no_ordinal_uniqueness(self):
        kwargs = {"course": self.course, "time": now(),
                  "kind": "some_kind", "ordinal": None}
        event = factories.EventFactory(**kwargs)

        # make sure it can be updated
        event.time = now() - timedelta(days=1)
        event.save()

        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            factories.EventFactory(**kwargs)


class ParticipationTagTest(RelateModelTestMixin, unittest.TestCase):
    def test_unicode(self):
        tag1 = factories.ParticipationTagFactory(course=self.course, name="tag1")
        tag2 = factories.ParticipationTagFactory(course=self.course, name="tag2")
        self.assertNotEqual(str(tag1), str(tag2))

    def test_clean_success(self):
        tag = models.ParticipationTag(course=self.course, name="abcd")
        tag.clean()

        tag = models.ParticipationTag(course=self.course, name="tag_1")
        tag.clean()

        tag = models.ParticipationTag(course=self.course, name="标签")
        tag.clean()

    def test_clean_failure(self):
        tag = models.ParticipationTag(course=self.course, name="~abcd")
        expected_error_msg = "'name' contains invalid characters."

        with self.assertRaises(ValidationError) as cm:
            tag.clean()

        self.assertIn(expected_error_msg, cm.exception.message_dict["name"])

        tag = models.ParticipationTag(course=self.course, name="ab-cd")
        with self.assertRaises(ValidationError) as cm:
            tag.clean()

        self.assertIn(expected_error_msg, cm.exception.message_dict["name"])


class ParticipationRoleTest(RelateModelTestMixin, unittest.TestCase):
    def test_unicode(self):
        tag1 = factories.ParticipationRoleFactory(course=self.course,
                                                  identifier="ta")
        tag2 = factories.ParticipationRoleFactory(course=self.course,
                                                  identifier="stu")
        self.assertNotEqual(str(tag1), str(tag2))

    def test_clean_success(self):
        role = models.ParticipationRole(
            course=self.course, name="role 1", identifier="role1")
        role.clean()

        role = models.ParticipationRole(
            course=self.course, name="role 1", identifier="role_1")
        role.clean()

        role = models.ParticipationRole(
            course=self.course, name="role 1", identifier="指导老师")
        role.clean()

    def test_clean_failure(self):
        role = models.ParticipationRole(
            course=self.course, name="role 1", identifier="role 1")
        expected_error_msg = "'identifier' contains invalid characters."

        with self.assertRaises(ValidationError) as cm:
            role.clean()

        self.assertIn(expected_error_msg, cm.exception.message_dict["identifier"])

        role = models.ParticipationRole(
            course=self.course, name="role 1", identifier="role-1")
        with self.assertRaises(ValidationError) as cm:
            role.clean()

        self.assertIn(expected_error_msg, cm.exception.message_dict["identifier"])

    def test_has_permission(self):
        student_pr = models.ParticipationRole.objects.get(
            course=self.course, identifier="student")
        self.assertFalse(
            student_pr.has_permission(pperm.access_files_for, "ta"))
        self.assertTrue(
            student_pr.has_permission(pperm.access_files_for, "student"))
        self.assertFalse(
            student_pr.has_permission(pperm.view_gradebook))

        instructor_pr = models.ParticipationRole.objects.get(
            course=self.course, identifier="instructor")
        self.assertTrue(
            instructor_pr.has_permission(pperm.access_files_for, "instructor"))
        self.assertTrue(
            instructor_pr.has_permission(pperm.view_gradebook))

    def test_permission_tuples_cached(self):
        student_pr = models.ParticipationRole.objects.get(
            course=self.course, identifier="student")
        self.assertFalse(
            student_pr.has_permission(pperm.access_files_for, "ta"))

        with mock.patch(
                "course.models.ParticipationRolePermission.objects.filter"
        ) as mock_filter:
            self.assertFalse(
                student_pr.has_permission(pperm.access_files_for, "instructor"))
            self.assertTrue(
                student_pr.has_permission(pperm.access_files_for, "unenrolled"))

            self.assertEqual(
                mock_filter.call_count, 0,
                "permission_tuples is expected to be cached.")


class ParticipationRolePermissionTest(RelateModelTestMixin, unittest.TestCase):
    def test_unicode(self):
        all_objects = models.ParticipationRolePermission.objects.all()
        count = all_objects.count()
        self.assertGreater(count, 0)

        prp_unicode_list = []
        for prp in all_objects:
            self.assertNotIn(
                str(prp), prp_unicode_list,
                "ParticipationRolePermission objects are expected to "
                "have different stringified result")
            prp_unicode_list.append(str(prp))


class ParticipationTest(RelateModelTestMixin, unittest.TestCase):
    def test_unicode(self):
        course2 = factories.CourseFactory(identifier="another-course")
        user = factories.UserFactory()

        participation1 = factories.ParticipationFactory(course=self.course,
                                                        user=user)
        participation2 = factories.ParticipationFactory(course=course2,
                                                        user=user)

        self.assertNotEqual(str(participation1), str(participation2))

    def test_has_permission(self):
        user = factories.UserFactory()
        participation = factories.ParticipationFactory(course=self.course,
                                                       user=user)

        self.assertTrue(
            participation.has_permission(pperm.access_files_for, "unenrolled"))
        self.assertFalse(
            participation.has_permission(pperm.view_gradebook))

        instructor = factories.UserFactory()
        instructor_role = factories.ParticipationRoleFactory(
            course=self.course,
            identifier="instructor"
        )
        instructor_participation = factories.ParticipationFactory(
            course=self.course,
            user=instructor)
        instructor_participation.roles.set([instructor_role])

        self.assertTrue(
            participation.has_permission(pperm.access_files_for, "unenrolled"))
        self.assertTrue(
            participation.has_permission(pperm.access_files_for, "student"))

    def test_get_role_desc(self):
        course2 = factories.CourseFactory(identifier="another-course")
        user = factories.UserFactory()

        participation1 = factories.ParticipationFactory(course=self.course,
                                                        user=user)
        participation2 = factories.ParticipationFactory(course=course2,
                                                        user=user)

        self.assertIsInstance(participation1.get_role_desc(), str)
        self.assertEqual(
            participation1.get_role_desc(), participation2.get_role_desc())

        instructor_role = factories.ParticipationRoleFactory(
            course=self.course,
            identifier="instructor"
        )
        participation2.roles.set([instructor_role])
        self.assertNotEqual(
            participation1.get_role_desc(), participation2.get_role_desc())

    def test_permission_cached(self):
        user = factories.UserFactory()
        participation = factories.ParticipationFactory(course=self.course,
                                                       user=user)

        self.assertTrue(
            participation.has_permission(pperm.access_files_for, "unenrolled"))

        with mock.patch(
                "course.models.ParticipationRolePermission.objects.filter"
        ) as mock_filter:
            self.assertFalse(
                participation.has_permission(pperm.view_gradebook))

            self.assertEqual(
                mock_filter.call_count, 0,
                "participation permissions is expected to be cached.")


class ParticipationPreapprovalTest(RelateModelTestMixin, unittest.TestCase):
    def test_unicode(self):
        paprv1 = factories.ParticipationPreapprovalFactory(
            course=self.course, institutional_id=None
        )
        paprv2 = factories.ParticipationPreapprovalFactory(
            course=self.course, institutional_id=None
        )
        self.assertNotEqual(str(paprv1), str(paprv2))

        paprv3 = factories.ParticipationPreapprovalFactory(
            course=self.course, email=None
        )
        paprv4 = factories.ParticipationPreapprovalFactory(
            course=self.course, email=None
        )
        self.assertNotEqual(str(paprv3), str(paprv4))

        paprv5 = factories.ParticipationPreapprovalFactory(
            course=self.course, email=None, institutional_id=None,
        )
        paprv6 = factories.ParticipationPreapprovalFactory(
            course=self.course, email=None, institutional_id=None,
        )
        self.assertNotEqual(str(paprv5), str(paprv6))


class AuthenticationTokenTest(RelateModelTestMixin, unittest.TestCase):
    def test_unicode(self):
        participation1 = factories.ParticipationFactory(
            course=self.course,
            user=factories.UserFactory())

        participation2 = factories.ParticipationFactory(
            course=self.course,
            user=factories.UserFactory())

        token1 = factories.AuthenticationTokenFactory(
            participation=participation1)

        token2 = factories.AuthenticationTokenFactory(
            participation=participation2)

        self.assertNotEqual(str(token1), str(token2))


class InstantFlowRequestTest(RelateModelTestMixin, unittest.TestCase):
    def test_unicode(self):
        ifr1 = factories.InstantFlowRequestFactory(course=self.course)
        ifr2 = factories.InstantFlowRequestFactory(course=self.course,
                                                   flow_id="another-flow")
        self.assertNotEqual(str(ifr1), str(ifr2))


class FlowSessionTest(RelateModelTestMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.user = factories.UserFactory()
        self.participation = factories.ParticipationFactory(
            course=self.course,
            user=self.user)

    def test_unicode(self):
        fs1 = factories.FlowSessionFactory(
            participation=self.participation)
        fs2 = factories.FlowSessionFactory(
            participation=self.participation)

        self.assertNotEqual(str(fs1), str(fs2))

        fs3 = factories.FlowSessionFactory(
            user=None,
            course=self.course,
            participation=None)
        fs4 = factories.FlowSessionFactory(
            user=None,
            course=self.course,
            participation=None)

        self.assertNotEqual(str(fs3), str(fs4))

    def test_points_percentage(self):
        fs = factories.FlowSessionFactory(
            participation=self.participation, points=None)
        self.assertEqual(fs.points_percentage(), None)

        fs = factories.FlowSessionFactory(
            participation=self.participation, points=20, max_points=None)
        self.assertEqual(fs.points_percentage(), None)

        fs = factories.FlowSessionFactory(
            participation=self.participation, points=20, max_points=20)
        self.assertEqual(fs.points_percentage(), 100)

    def test_last_activity(self):
        fs = factories.FlowSessionFactory(participation=self.participation)
        fpdata = factories.FlowPageDataFactory(flow_session=fs)
        factories.FlowPageVisitFactory(
            page_data=fpdata, answer=None,
            visit_time=datetime(2019, 1, 1, tzinfo=pytz.UTC)
        )
        factories.FlowPageVisitFactory(
            page_data=fpdata, answer=None,
            visit_time=datetime(2019, 1, 2, tzinfo=pytz.UTC)
        )
        self.assertEqual(fs.last_activity(), None)

        fpv = factories.FlowPageVisitFactory(
            page_data=fpdata, answer={"answer": "hi"},
            visit_time=datetime(2018, 12, 31, tzinfo=pytz.UTC)
        )

        self.assertEqual(fs.last_activity(), fpv.visit_time)


class FlowPageDataTest(RelateModelTestMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.user = factories.UserFactory()
        self.participation = factories.ParticipationFactory(
            course=self.course,
            user=self.user)

    def test_unicode(self):
        fs = factories.FlowSessionFactory(participation=self.participation)
        fpdata = factories.FlowPageDataFactory(flow_session=fs)
        self.assertIsNotNone(str(fpdata))


class FlowPageVisitTest(RelateModelTestMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.user = factories.UserFactory()
        self.participation = factories.ParticipationFactory(
            course=self.course,
            user=self.user)
        fs = factories.FlowSessionFactory(participation=self.participation)
        self.fpdata = factories.FlowPageDataFactory(flow_session=fs)

    def test_unicode(self):
        visit1 = factories.FlowPageVisitFactory(
            page_data=self.fpdata, answer=None,
            visit_time=datetime(2019, 1, 1, tzinfo=pytz.UTC)
        )
        visit2 = factories.FlowPageVisitFactory(
            page_data=self.fpdata, answer=None,
            visit_time=datetime(2019, 1, 2, tzinfo=pytz.UTC)
        )

        self.assertNotEqual(str(visit1), str(visit2))
        self.assertNotIn("with answer", str(visit1))

    def test_unicode_with_answer(self):
        visit1 = factories.FlowPageVisitFactory(
            page_data=self.fpdata, answer={"answer": "hi"},
            visit_time=datetime(2019, 1, 1, tzinfo=pytz.UTC)
        )
        visit2 = factories.FlowPageVisitFactory(
            page_data=self.fpdata, answer={"answer": "hi"},
            visit_time=datetime(2019, 1, 2, tzinfo=pytz.UTC)
        )

        self.assertNotEqual(str(visit1), str(visit2))
        self.assertIn("with answer", str(visit1))


class FlowPageVisitGradeTest(RelateModelTestMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.user = factories.UserFactory()
        self.participation = factories.ParticipationFactory(
            course=self.course,
            user=self.user)
        fs = factories.FlowSessionFactory(participation=self.participation)
        self.fpdata = factories.FlowPageDataFactory(flow_session=fs)

    def test_percentage_none(self):
        visit = factories.FlowPageVisitFactory(
            page_data=self.fpdata, answer=None,
            visit_time=datetime(2019, 1, 1, tzinfo=pytz.UTC),
        )
        fpvg = factories.FlowPageVisitGradeFactory(
            visit=visit, correctness=None
        )
        self.assertEqual(fpvg.percentage(), None)

    def test_percentage(self):
        visit = factories.FlowPageVisitFactory(
            page_data=self.fpdata, answer={"answer": "hi"},
            visit_time=datetime(2019, 1, 1, tzinfo=pytz.UTC),
        )
        fpvg = factories.FlowPageVisitGradeFactory(
            visit=visit, correctness=0.5
        )
        self.assertEqual(fpvg.percentage(), 50)

    def test_uniqueness(self):
        visit = factories.FlowPageVisitFactory(
            page_data=self.fpdata, answer=None,
            visit_time=datetime(2019, 1, 1, tzinfo=pytz.UTC),
        )

        factories.FlowPageVisitGradeFactory(
            visit=visit
        )
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            factories.FlowPageVisitGradeFactory(
                visit=visit
            )

    def test_unicode(self):
        visit = factories.FlowPageVisitFactory(
            page_data=self.fpdata, answer=None,
            visit_time=datetime(2019, 1, 1, tzinfo=pytz.UTC),
        )
        visit2 = factories.FlowPageVisitFactory(
            page_data=self.fpdata, answer=None,
            visit_time=datetime(2019, 1, 2, tzinfo=pytz.UTC),
        )

        fpvg = factories.FlowPageVisitGradeFactory(
            visit=visit
        )
        fpvg2 = factories.FlowPageVisitGradeFactory(
            visit=visit2
        )
        self.assertEqual(fpvg.percentage(), None)

        self.assertNotEqual(str(fpvg), str(fpvg2))


class GetFeedbackForGradeTest(RelateModelTestMixin, unittest.TestCase):
    # test models.get_feedback_for_grade
    def test_grade_is_none(self):
        self.assertIsNone(models.get_feedback_for_grade(None))


class FlowRuleExceptionTest(RelateModelTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        user = factories.UserFactory()
        self.participation = factories.ParticipationFactory(
            course=self.course,
            user=user)
        fake_get_course_repo = mock.patch("course.content.get_course_repo")
        self.mock_get_course_repo = fake_get_course_repo.start()
        self.mock_get_course_repo.return_value = mock.MagicMock()
        self.addCleanup(fake_get_course_repo.stop)

        fake_get_flow_desc = mock.patch("course.content.get_flow_desc")
        self.mock_get_flow_desc = fake_get_flow_desc.start()
        self.addCleanup(fake_get_flow_desc.stop)

        fake_validate_session_start_rule = mock.patch(
            "course.validation.validate_session_start_rule")
        self.mock_validate_session_start_rule = (
            fake_validate_session_start_rule.start())
        self.addCleanup(fake_validate_session_start_rule.stop)

        fake_validate_session_access_rule = mock.patch(
            "course.validation.validate_session_access_rule")
        self.mock_validate_session_access_rule = (
            fake_validate_session_access_rule.start())
        self.addCleanup(fake_validate_session_access_rule.stop)

        fake_validate_session_grading_rule = mock.patch(
            "course.validation.validate_session_grading_rule")
        self.mock_validate_session_grading_rule = (
            fake_validate_session_grading_rule.start())
        self.addCleanup(fake_validate_session_grading_rule.stop)

    def test_unicode(self):
        fre1 = factories.FlowRuleExceptionFactory(
            participation=self.participation)
        fre2 = factories.FlowRuleExceptionFactory(
            participation=self.participation)

        self.assertNotEqual(str(fre1), str(fre2))

    def test_clean_success_null_exception_rule(self):
        rule = {}
        fre = models.FlowRuleException(
            flow_id=factories.DEFAULT_FLOW_ID,
            participation=self.participation,
            kind=constants.flow_rule_kind.start,
            rule=rule,
            expiration=None
        )

        fre.clean()
        self.assertEqual(self.mock_get_course_repo.call_count, 1)
        self.assertEqual(self.mock_get_flow_desc.call_count, 1)
        self.assertEqual(self.mock_validate_session_start_rule.call_count, 1)

    def test_clean_failure_with_invalid_existing_session_rules(self):
        rule = {}
        fre = models.FlowRuleException(
            flow_id=factories.DEFAULT_FLOW_ID,
            participation=self.participation,
            kind=constants.flow_rule_kind.start,
            rule=rule,
            expiration=None
        )
        from course import validation
        my_custom_error = "my custom error"
        self.mock_validate_session_start_rule.side_effect = (
            validation.ValidationError(my_custom_error))

        with self.assertRaises(ValidationError) as cm:
            fre.clean()

        expected_error_msg = "invalid existing_session_rules: %s" % my_custom_error
        self.assertIn(expected_error_msg, str(cm.exception))
        self.assertEqual(self.mock_get_course_repo.call_count, 1)
        self.assertEqual(self.mock_get_flow_desc.call_count, 1)
        self.assertEqual(self.mock_validate_session_start_rule.call_count, 1)

    def test_clean_success_no_existing_rules(self):
        self.mock_get_flow_desc.return_value = dict_to_struct(
            {"id": "no_existing_flow"})
        rule = {}
        fre = models.FlowRuleException(
            flow_id=factories.DEFAULT_FLOW_ID,
            participation=self.participation,
            kind=constants.flow_rule_kind.start,
            rule=rule,
            expiration=None
        )

        fre.clean()
        self.assertEqual(self.mock_get_course_repo.call_count, 1)
        self.assertEqual(self.mock_get_flow_desc.call_count, 1)
        self.assertEqual(self.mock_validate_session_start_rule.call_count, 1)

    def test_clean_grading_success(self):
        rule = {
            "if_completed_before": now(),
            "credit_percent": 100
        }
        fre = models.FlowRuleException(
            flow_id=factories.DEFAULT_FLOW_ID,
            participation=self.participation,
            kind=constants.flow_rule_kind.grading,
            rule=rule,
            expiration=None
        )

        fre.clean()
        self.assertEqual(self.mock_get_course_repo.call_count, 1)
        self.assertEqual(self.mock_get_flow_desc.call_count, 1)
        self.assertEqual(self.mock_validate_session_grading_rule.call_count, 1)

    def test_clean_grading_no_expire_failure(self):
        rule = {
            "if_completed_before": now(),
            "credit_percent": 100
        }
        expected_error_msg = "grading rules may not expire"
        with self.assertRaises(ValidationError) as cm:
            fre = models.FlowRuleException(
                flow_id=factories.DEFAULT_FLOW_ID,
                participation=self.participation,
                kind=constants.flow_rule_kind.grading,
                rule=rule,
                expiration=now()
            )

            fre.clean()
        self.assertIn(expected_error_msg, str(cm.exception))

        self.assertEqual(
            self.mock_get_course_repo.call_count, 0,
            "The expensive operation should be skipped in this case")
        self.assertEqual(
            self.mock_get_flow_desc.call_count, 0,
            "The expensive operation should be skipped in this case")
        self.assertEqual(self.mock_validate_session_grading_rule.call_count, 0,
                         "The expensive operation should be skipped in this case")

    def test_clean_access_success(self):
        rule = {
            "if_before": now()
        }
        fre = models.FlowRuleException(
            flow_id=factories.DEFAULT_FLOW_ID,
            participation=self.participation,
            kind=constants.flow_rule_kind.access,
            rule=rule,
            expiration=now()
        )

        fre.clean()
        self.assertEqual(self.mock_get_course_repo.call_count, 1)
        self.assertEqual(self.mock_get_flow_desc.call_count, 1)
        self.assertEqual(self.mock_validate_session_access_rule.call_count, 1)

    def test_clean_unknown_exception_rule(self):
        unknown_flow_rule_kind = "unknown_kind"
        rule = {
            "if_before": now()
        }
        fre = models.FlowRuleException(
            flow_id=factories.DEFAULT_FLOW_ID,
            participation=self.participation,
            kind=unknown_flow_rule_kind,
            rule=rule,
            expiration=now()
        )

        with self.assertRaises(ValidationError) as cm:
            fre.clean()
        expected_error_msg = "invalid exception rule kind"
        self.assertIn(expected_error_msg, str(cm.exception))

        for call in (self.mock_get_course_repo,
                     self.mock_get_flow_desc,
                     self.mock_validate_session_access_rule,
                     self.mock_validate_session_access_rule,
                     self.mock_validate_session_access_rule,
                     self.mock_validate_session_access_rule):
            self.assertEqual(
                call.call_count, 0,
                "The expensive operation should be skipped in this case")


class GradingChangeTest(RelateModelTestMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.user = factories.UserFactory()
        self.participation = factories.ParticipationFactory(
            course=self.course,
            user=self.user)
        self.flow_session = factories.FlowSessionFactory(
            participation=self.participation)
        self.opportunity1 = factories.GradingOpportunityFactory(
            course=self.course, identifier="gopp1"
        )
        self.opportunity2 = factories.GradingOpportunityFactory(
            course=self.course, identifier="gopp2"
        )

    def test_unicode(self):
        gc1 = factories.GradeChangeFactory(
            opportunity=self.opportunity1, participation=self.participation)
        self.assertIsNotNone(str(gc1))

    def test_clean(self):
        gc = factories.GradeChangeFactory(
            opportunity=self.opportunity1, participation=self.participation)
        gc.clean()

    def test_clean_fail(self):
        course2 = factories.CourseFactory(identifier="another-course")
        opportunity3 = factories.GradingOpportunityFactory(
            course=course2, identifier="gopp3"
        )
        gc = factories.GradeChangeFactory(
            opportunity=opportunity3, participation=self.participation)

        with self.assertRaises(ValidationError) as cm:
            gc.clean()

        expected_error_msg = ("Participation and opportunity must live "
                              "in the same course")
        self.assertIn(expected_error_msg, str(cm.exception))


class InstantMessageTest(RelateModelTestMixin, unittest.TestCase):
    def test_unicode(self):
        user = factories.UserFactory()
        participation = factories.ParticipationFactory(
            course=self.course,
            user=user)
        im1 = factories.InstantMessageFactory(
            participation=participation, text="my message")
        im2 = factories.InstantMessageFactory(
            participation=participation, text="my message2")

        self.assertNotEqual(str(im1), str(im2))


class ExamTest(RelateModelTestMixin, unittest.TestCase):
    def test_unicode(self):
        exam1 = factories.ExamFactory(
            course=self.course, description="hello", flow_id="exam-1")
        exam2 = factories.ExamFactory(
            course=self.course, description="exam", flow_id="exam-1")

        self.assertNotEqual(str(exam1), str(exam2))


class ExamTicketTest(RelateModelTestMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.exam = factories.ExamFactory(course=self.course)

        self.user1 = factories.UserFactory()
        self.participation1 = factories.ParticipationFactory(
            course=self.course,
            user=self.user1)
        self.user2 = factories.UserFactory()
        self.participation2 = factories.ParticipationFactory(
            course=self.course,
            user=self.user2)

    def test_unicode(self):
        et1 = factories.ExamTicketFactory(
            exam=self.exam, participation=self.participation1, code="abcd")
        et2 = factories.ExamTicketFactory(
            exam=self.exam, participation=self.participation2, code="cdef")

        self.assertNotEqual(str(et1), str(et2))

    def test_clean(self):
        et1 = models.ExamTicket(
            exam=self.exam, participation=self.participation1, code="abcd")
        et1.clean()

    def test_clean_failure(self):
        course2 = factories.CourseFactory(identifier="another-course")
        participation3 = factories.ParticipationFactory(
            course=course2,
            user=self.user2)

        et2 = models.ExamTicket(
            exam=self.exam, participation=participation3, code="cdef")

        with self.assertRaises(ValidationError) as cm:
            et2.clean()

        expected_error_msg = ("Participation and exam must live "
                              "in the same course")
        self.assertIn(expected_error_msg, str(cm.exception))

    def test_clean_no_participation(self):
        et1 = models.ExamTicket(
            exam=self.exam, participation=None, code="abcd")
        et1.clean()
