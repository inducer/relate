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

import six
from copy import deepcopy
import unittest
from django.test import TestCase, RequestFactory
from dulwich.contrib.paramiko_vendor import ParamikoSSHVendor

from course.models import Course, Participation
from course import versioning

from tests.base_test_mixins import (
    CoursesTestMixinBase, SINGLE_COURSE_SETUP_LIST,
    FallBackStorageMessageTestMixin)
from tests.utils import suppress_stdout_decorator, mock
from tests import factories

TEST_PUBLIC_KEY = """
-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA7A1rTpbRpCek4tZZKa8QH14/pYzraN7hDnx3BKrqRxghP/0Q
uc98qeQkA5T3EYjHsConAAArLzbo6PMGwM9353dFixGUHegZe3jUmszX7G2veZx5
1xJ20pffbi8ohjv2Lj+nr799oGw7pGcEUXMr2v0b+UfToNFJAWGY3j9G+vTT7JEY
b9hq+XTOvoF+pLWbU7mIock5CxP3Q5NGS3/SjX2Qv50m6uc0dP34mGL4zDzgAMiC
99OpFms7CoO4AMWa/CfDCKl2vZHqDEF7Pd02vUP3ddb5pyGDeZmfhtK2LDLKi7ke
1pv1B4BwZ6HPmNep2CKEK6jf0+o5fIKm1uy3iQIDAQABAoIBAHCxl2FVr5BnPNju
7HJyGYhgPpKSzHCst1VrJocb8e0vH/CkqK+M1z9ko6zyGWJNosf/186wRe2skVVl
cPvsEJp43sKeCdCdVk0USqv8z7kYRIYSpjh/oCq6RvkbmoU7azR5P10wVpGYGoFK
jU01ZuKNpCVGnUpRoEEAjzLLkt+LyBjcey4ZUntp5L4h+ahm14Z8GLKbO2UCYZk6
nUnfigxiw/otXL+lN4+LjwjgTWS9JvG6Z+OQSf9b/G9DuDjpbvS5JQ0FONmUUH6m
nLwvJrePT50OPdB9mM4f+Ev03oRr9EXBXPL5t33SqRjhVn3dzH2wcuyhMUnZfGg0
MMksBAECgYEA/9VGBzaHYF2Va5OsNe3nvsOU9RI/n4/lN31MzDYwHDj2/NIDPR6S
7y42BxnGXce28t50ly/9ogut/yWfv0gyRbJ1tshl4/Lk4nqi9LwOOydL7XCd0+iM
ZiHfJafkItRNmVJjjX8OT0B0lfdmY/dJQJVH7zo6KzLlDNnzufZJSZECgYEA7DTX
kbGWrqtZl9wIvAdgfAlnagGpS/qUN8rB39TMHN5FpGH4xLV4BCyB6qacbF8YD3FB
14F4DVQh3/d6l0iybRBKFqxx3laUVeVYZNbvfaiCWvRJnnTZxI2ofQvK8nDhINiL
J4dpsRrxnTUrpoxg9xOejaLJHi9uPwOw0tjw0nkCgYBSAPvsbfcg1X6CuBgYRUTm
aezCTXIlZEt16O0H/EqZkUziJzMwkS9KCYb56bIi91RWLyYyHAjxu0qvoVC+UJcE
rjp7N2spkP769ZJsXic1oNf+qP1+Iml2h17uxA0leOXSwoz0mwhsMN3uABpK6sYJ
NJCVRxXEKREweGBeeGpvcQKBgAVkT2dr/lyOXMUyqKBiKrmqHUo2L38kgS2k2zgY
y2/9Qum1stAKtGqj+XM5ymhO42W22CHrOqpTOVK7e3jol+oVbRuHZDIHF+u+CH6E
yYK8zfz1hpivYikycp4oHsHaAcmWJ9cHKEp6qvlDtXNf0PbS49On259sxb96fhbS
DO1BAoGBAMvipNBiAbZXzNm6eTa6NMYcmiZpgV2zvx/Rbq+L2heOoBA7jyH41nl/
XHYymOvk4oiQKCfgal4+fqSpHSs6/S1MyLmHbONTLTwS8yHU9esi6ntEnse28ewc
yZ/atCI8q7Wyi7i2wr/okVekQYWdMSbnamp0A3zkYW6mhKpvibdN
-----END RSA PRIVATE KEY-----
"""


class VersioningTestMixin(CoursesTestMixinBase, FallBackStorageMessageTestMixin):
    courses_setup_list = []

    @classmethod
    def setUpTestData(cls):  # noqa
        super(VersioningTestMixin, cls).setUpTestData()
        cls.instructor = cls.create_user(
            SINGLE_COURSE_SETUP_LIST[0]["participations"][0]["user"])
        cls.add_user_permission(cls.instructor, "add_course")

    def setUp(self):
        super(VersioningTestMixin, self).setUp()
        self.rf = RequestFactory()
        self.addCleanup(self.force_remove_all_course_dir)

    def get_set_up_new_course_form_data(self):
        return deepcopy(SINGLE_COURSE_SETUP_LIST[0]["course"])

    @classmethod
    def add_user_permission(cls, user, perm):
        from django.contrib.contenttypes.models import ContentType
        content_type = ContentType.objects.get_for_model(Course)
        from django.contrib.auth.models import Permission
        permission = Permission.objects.get(
            codename=perm, content_type=content_type)
        user.user_permissions.add(permission)


class CourseCreationTest(VersioningTestMixin, TestCase):
    def test_non_auth_set_up_new_course(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_set_up_new_course()
            self.assertTrue(resp.status_code, 403)

            data = SINGLE_COURSE_SETUP_LIST[0]["course"]
            resp = self.post_create_course(data, raise_error=False,
                                           login_superuser=False)
            self.assertTrue(resp.status_code, 403)
            self.assertEqual(Course.objects.count(), 0)

    def test_set_up_new_course_no_perm(self):
        # create a user which has no perm for creating course
        ta = self.create_user(
            SINGLE_COURSE_SETUP_LIST[0]["participations"][1]["user"])
        self.assertFalse(ta.has_perm("course.add_course"))
        self.assertFalse(ta.has_perm("course.change_course"))
        self.assertFalse(ta.has_perm("course.delete_course"))

        with self.temporarily_switch_to_user(ta):
            resp = self.get_set_up_new_course()
            self.assertTrue(resp.status_code, 403)

            data = self.get_set_up_new_course_form_data()
            resp = self.post_create_course(data, raise_error=False,
                                           login_superuser=False)
            self.assertTrue(resp.status_code, 403)
            self.assertEqual(Course.objects.count(), 0)

    def test_set_up_new_course(self):
        # In this test, we use client instead of request factory to simplify
        # the logic.

        with self.temporarily_switch_to_user(self.instructor):
            # the permission is cached, need to repopulated from db
            resp = self.get_set_up_new_course()
            self.assertTrue(resp.status_code, 200)

            with mock.patch("dulwich.client.GitClient.fetch",
                            return_value={b"HEAD": b"some_commit_sha"}), \
                 mock.patch("course.versioning.transfer_remote_refs",
                            return_value=None), \
                 mock.patch('course.versioning.messages') as mock_messages, \
                    mock.patch("course.validation.validate_course_content",
                               return_value=None):
                data = self.get_set_up_new_course_form_data()

                resp = self.post_create_course(data, raise_error=False,
                                               login_superuser=False)
                self.assertTrue(resp.status_code, 200)
                self.assertEqual(Course.objects.count(), 1)
                self.assertEqual(Participation.objects.count(), 1)
                self.assertEqual(Participation.objects.first().user.username,
                                 "test_instructor")
                self.assertIn("Course content validated, creation succeeded.",
                              mock_messages.add_message.call_args[0])

                from course.enrollment import get_participation_role_identifiers

                # the user who setup the course has role instructor
                self.assertTrue(
                    get_participation_role_identifiers(
                        Course.objects.first(),
                        Participation.objects.first()),
                    "instructor")

    def test_set_up_new_course_form_invalid(self):
        for field_name in ["identifier", "name", "number", "time_period",
                           "git_source", "from_email", "notify_email"]:
            form_data = self.get_set_up_new_course_form_data()
            del form_data[field_name]
            request = self.rf.post(self.get_set_up_new_course_url(), data=form_data)
            request.user = self.instructor
            form = versioning.CourseCreationForm(request.POST)
            self.assertFalse(form.is_valid())

    @suppress_stdout_decorator(suppress_stderr=True)
    def test_set_up_new_course_git_source_invalid(self):
        data = self.get_set_up_new_course_form_data()
        request = self.rf.post(self.get_set_up_new_course_url(), data=data)
        request.user = self.instructor
        with mock.patch("dulwich.client.GitClient.fetch",
                        return_value=None), \
             mock.patch('course.versioning.messages') as mock_messages, \
                mock.patch("course.models.Course.save") as mock_save, \
                mock.patch("course.versioning.render"):
            resp = versioning.set_up_new_course(request)
            self.assertTrue(resp.status_code, 200)
            self.assertEqual(mock_save.call_count, 0)
            self.assertIn("No refs found in remote repository",
                          mock_messages.add_message.call_args[0][2])

    @suppress_stdout_decorator(suppress_stderr=True)
    def test_set_up_new_course_subdir(self):
        data = self.get_set_up_new_course_form_data()
        data["course_root_path"] = "some_dir"
        request = self.rf.post(self.get_set_up_new_course_url(), data=data)
        request.user = self.instructor
        with mock.patch("dulwich.client.GitClient.fetch",
                        return_value={b"HEAD": b"some_commit_sha"}), \
             mock.patch('course.versioning.messages'), \
             mock.patch("course.validation.validate_course_content",
                        return_value=None) as mock_validate, \
                mock.patch("course.models.Course.save"), \
                mock.patch("course.models.Participation.save", return_value=True), \
                mock.patch("course.versioning.render"):
            resp = versioning.set_up_new_course(request)
            from course.content import SubdirRepoWrapper
            self.assertIsInstance(mock_validate.call_args[0][0], SubdirRepoWrapper)
            self.assertTrue(resp.status_code, 200)


class ParamikoSSHVendorTest(unittest.TestCase):
    # A simple integration tests, making sure ParamikoSSHVendor is used
    # for ssh protocol.

    @classmethod
    def setUpClass(cls):  # noqa
        course = factories.CourseFactory.create(**cls.prepare_data())
        cls.git_client, _ = (
            versioning.get_dulwich_client_and_remote_path_from_course(course))
        cls.ssh_vendor = cls.git_client.ssh_vendor
        assert isinstance(cls.ssh_vendor, ParamikoSSHVendor)

    @classmethod
    def prepare_data(cls):
        data = deepcopy(SINGLE_COURSE_SETUP_LIST[0]["course"])
        data["identifier"] = "my-private-course"
        data["git_source"] = "git+ssh://foo.com:1234/bar/baz"
        data["ssh_private_key"] = TEST_PUBLIC_KEY
        return data

    def test_invalid(self):
        from paramiko.ssh_exception import AuthenticationException

        expected_error_msg = "Authentication failed"
        with self.assertRaises(AuthenticationException) as cm:
            # This is also used to ensure paramiko.client.MissingHostKeyPolicy
            # is added to the client
            self.ssh_vendor.run_command(
                host="github.com",
                command="git-upload-pack '/bar/baz'",
                username=None,
                port=None)
        self.assertIn(expected_error_msg, str(cm.exception))

        with self.assertRaises(AuthenticationException) as cm:
            self.ssh_vendor.run_command(
                host="github.com",
                command="git-upload-pack '/bar/baz'",
                username="me",
                port=22)
        self.assertIn(expected_error_msg, str(cm.exception))

        expected_error_msg = "Bad authentication type"

        with self.assertRaises(AuthenticationException) as cm:
            self.ssh_vendor.run_command(
                host="github.com",
                command="git-upload-pack '/bar/baz'",
                password="mypass")

        self.assertIn(expected_error_msg, str(cm.exception))

        if six.PY2:
            exception = IOError
        else:
            exception = FileNotFoundError
        with self.assertRaises(exception) as cm:
            self.ssh_vendor.run_command(
                host="github.com",
                command="git-upload-pack '/bar/baz'",
                key_filename="key_file")

        expected_error_msg = "No such file or directory: 'key_file'"
        self.assertIn(expected_error_msg, str(cm.exception))

        with self.assertRaises(AttributeError) as cm:
            self.ssh_vendor.run_command(
                host="github.com",
                command="git-upload-pack '/bar/baz'",
                pkey="invalid_key")

    @suppress_stdout_decorator(suppress_stderr=True)
    def test_set_up_ensure_get_transport_called(self):
        with mock.patch(
                "course.versioning.paramiko.SSHClient.connect"
        ) as mock_connect, mock.patch(
            "course.versioning.paramiko.SSHClient.get_transport"
        ) as mock_get_transport:
            mock_channel = mock.MagicMock()
            mock_get_transport.return_value.open_session.return_value = mock_channel
            mock_channel.exec_command = mock.MagicMock()
            mock_channel.recv.side_effect = [b"10"]
            mock_channel.recv_stderr.side_effect = [b"my custom error", "", ""]

            try:
                self.ssh_vendor.run_command(
                    host="github.com",
                    command="git-upload-pack '/bar/baz'")
            except StopIteration:
                pass

            self.assertEqual(mock_connect.call_count, 1)

            from paramiko.rsakey import RSAKey
            used_rsa_key = None

            # make sure rsa_key is used when connect
            for v in mock_connect.call_args[1].values():
                if isinstance(v, RSAKey):
                    used_rsa_key = v

            self.assertIsNotNone(used_rsa_key)

            # make sure get_transport is called
            self.assertEqual(mock_get_transport.call_count, 1)

            # make sure exec_command is called
            self.assertEqual(mock_channel.exec_command.call_count, 1)
            self.assertIn(
                "git-upload-pack '/bar/baz'",
                mock_channel.exec_command.call_args[0])


class TransferRemoteRefsTest(unittest.TestCase):
    # test versioning.transfer_remote_refs

    # Fixme: need better tests
    def test_remote_ref_none(self):
        repo = mock.MagicMock()
        repo[b"refs/remotes/origin/1"] = b"some_bytes"
        repo[b'HEAD'] = b"some_head"
        repo.get_refs.return_value = {
            b"refs/remotes/origin/1": "some_text1",
            b"refs/remotes/other/1": "some_text2"}
        versioning.transfer_remote_refs(repo, None)
