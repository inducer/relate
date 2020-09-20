from __future__ import division

__copyright__ = "Copyright (C) 2017 Dong Zhuang"

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

import pytest
from django.test import TestCase

from course.constants import participation_status

from tests import factories
from tests.utils import mock
from tests.base_test_mixins import SingleCourseTestMixin

HANDLE_ENROLLMENT_PATH = "course.enrollment.handle_enrollment_request"


@pytest.mark.slow
class UpdateCouresOrUserSignalTest(SingleCourseTestMixin, TestCase):

    def test_update_course_no_requested(self):
        with mock.patch(HANDLE_ENROLLMENT_PATH) as mock_handle_enrollment:
            mock_handle_enrollment.return_value = None
            self.course.listed = not self.course.listed
            self.course.save()

            self.assertEqual(mock_handle_enrollment.call_count, 0)

    def test_update_course_exist_requested_not_preapprove(self):
        user = factories.UserFactory()
        factories.ParticipationFactory(
            course=self.course,
            user=user,
            status=participation_status.requested)

        with mock.patch(HANDLE_ENROLLMENT_PATH) as mock_handle_enrollment:
            mock_handle_enrollment.return_value = None

            self.course.listed = not self.course.listed
            self.course.save()
            self.assertEqual(mock_handle_enrollment.call_count, 0)

    def test_update_course_exist_requested_preapproved(self):
        user = factories.UserFactory()
        factories.ParticipationFactory(
            course=self.course,
            user=user,
            status=participation_status.requested)

        factories.ParticipationPreapprovalFactory(
            course=self.course,
            email=user.email
        )

        with mock.patch(HANDLE_ENROLLMENT_PATH) as mock_handle_enrollment:
            mock_handle_enrollment.return_value = None

            self.course.listed = not self.course.listed
            self.course.save()
            self.assertEqual(mock_handle_enrollment.call_count, 1)

    def test_update_course_exist_requested_preapproved_instid(self):
        user1 = factories.UserFactory(email="", institutional_id="1234")
        factories.ParticipationFactory(
            course=self.course,
            user=user1,
            status=participation_status.requested)

        factories.ParticipationPreapprovalFactory(
            course=self.course,
            institutional_id="4321"
        )

        user2 = factories.UserFactory(email="", institutional_id="2345")
        factories.ParticipationFactory(
            course=self.course,
            user=user2,
            status=participation_status.requested)

        factories.ParticipationPreapprovalFactory(
            course=self.course,
            institutional_id="2345"
        )

        with mock.patch(HANDLE_ENROLLMENT_PATH) as mock_handle_enrollment:
            mock_handle_enrollment.return_value = None

            self.course.listed = not self.course.listed
            self.course.save()
            self.assertEqual(mock_handle_enrollment.call_count, 0)

            self.course.preapproval_require_verified_inst_id = False
            self.course.save()
            self.assertEqual(mock_handle_enrollment.call_count, 1)

            mock_handle_enrollment.reset_mock()

            user1.institutional_id = "4321"
            user1.save()
            self.assertEqual(mock_handle_enrollment.call_count, 1)

    def test_update_course_user_not_active(self):
        user = factories.UserFactory(is_active=False)
        factories.ParticipationFactory(
            course=self.course,
            user=user,
            status=participation_status.requested)
        factories.ParticipationPreapprovalFactory(
            course=self.course,
            email=user.email
        )
        with mock.patch(
                "course.models.ParticipationPreapproval.objects.get")\
                as mock_pprvl_get,\
                mock.patch(HANDLE_ENROLLMENT_PATH) as mock_handle_enrollment:
            self.course.listed = not self.course.listed
            self.course.save()
            self.assertEqual(mock_pprvl_get.call_count, 0)
            self.assertEqual(mock_handle_enrollment.call_count, 0)
