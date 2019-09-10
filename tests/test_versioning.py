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

from relate.utils import force_remove_path

from course.models import Course, Participation
from course import versioning
from course.validation import ValidationWarning
from course.constants import participation_permission as pperm

from tests.base_test_mixins import (
    SingleCourseTestMixin, MockAddMessageMixing,
    CoursesTestMixinBase, SINGLE_COURSE_SETUP_LIST)
from tests.utils import (
    suppress_stdout_decorator, mock, may_run_expensive_tests,
    SKIP_EXPENSIVE_TESTS_REASON)
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


class VersioningTestMixin(CoursesTestMixinBase, MockAddMessageMixing):
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


class CourseCreationTest(VersioningTestMixin, TestCase):
    def test_get_set_up_new_course_view(self):
        with self.temporarily_switch_to_user(self.instructor):
            resp = self.c.get(self.get_set_up_new_course_url(),
                              data=SINGLE_COURSE_SETUP_LIST[0]["course"])
            self.assertEqual(resp.status_code, 200)

    def test_non_auth_set_up_new_course(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_set_up_new_course()
            self.assertTrue(resp.status_code, 403)

            data = SINGLE_COURSE_SETUP_LIST[0]["course"]
            resp = self.post_create_course(data, raise_error=False,
                                           login_superuser=False)
            self.assertTrue(resp.status_code, 403)
            self.assertEqual(Course.objects.count(), 0)

    def test_post_set_up_new_course_form_not_valid(self):
        data = SINGLE_COURSE_SETUP_LIST[0]["course"].copy()
        del data["identifier"]
        resp = self.post_create_course(data, raise_error=False)
        self.assertTrue(resp.status_code, 200)
        self.assertEqual(Course.objects.count(), 0)
        self.assertFormErrorLoose(resp, "This field is required.")

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
                self.assertAddMessageCalledWith(
                    "Course content validated, creation succeeded.")

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
    def test_set_up_new_course_error_with_no_repo_created(self):
        resp = self.get_set_up_new_course()
        self.assertTrue(resp.status_code, 403)

        data = SINGLE_COURSE_SETUP_LIST[0]["course"]

        with mock.patch("course.versioning.Repo.init") as mock_repo_innit:
            mock_repo_innit.side_effect = RuntimeError("Repo init error")
            resp = self.post_create_course(data, raise_error=False)
            self.assertTrue(resp.status_code, 200)
            self.assertEqual(Course.objects.count(), 0)

            self.assertAddMessageCalledWith(
                "Course creation failed: RuntimeError: Repo init error")

    @suppress_stdout_decorator(suppress_stderr=True)
    def test_set_up_new_course_failed_to_delete_repo(self):
        resp = self.get_set_up_new_course()
        self.assertTrue(resp.status_code, 403)

        def force_remove_path_side_effect(path):
            # we need to delete the path, or tests followed will fail
            force_remove_path(path)
            raise OSError("my os error")

        data = SINGLE_COURSE_SETUP_LIST[0]["course"]

        with mock.patch(
                "dulwich.client.GitClient.fetch"
        ) as mock_fetch, mock.patch(
                'relate.utils.force_remove_path'
        )as mock_force_remove_path:
            mock_fetch.side_effect = RuntimeError("my fetch error")
            mock_force_remove_path.side_effect = force_remove_path_side_effect
            resp = self.post_create_course(data, raise_error=False)
            self.assertTrue(resp.status_code, 200)
            self.assertEqual(Course.objects.count(), 0)

            self.assertAddMessageCallCount(2)

            self.assertAddMessageCalledWith(
                "Failed to delete unused repository directory", reset=False)
            self.assertAddMessageCalledWith(
                "Course creation failed: RuntimeError: my fetch error")

    @suppress_stdout_decorator(suppress_stderr=True)
    def test_set_up_new_course_git_source_invalid(self):
        data = self.get_set_up_new_course_form_data()
        request = self.rf.post(self.get_set_up_new_course_url(), data=data)
        request.user = self.instructor
        with mock.patch("dulwich.client.GitClient.fetch",
                        return_value=None), \
                mock.patch("course.models.Course.save") as mock_save, \
                mock.patch("course.versioning.render"):
            resp = versioning.set_up_new_course(request)
            self.assertTrue(resp.status_code, 200)
            self.assertEqual(mock_save.call_count, 0)
            self.assertAddMessageCalledWith(
                "No refs found in remote repository")

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


@unittest.skipUnless(may_run_expensive_tests(), SKIP_EXPENSIVE_TESTS_REASON)
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

        expected_error_msgs = [
                "Authentication failed",

                # Raised when run in a user account that has
                # an (encrypted) key file in $HOME/.ssh.
                "Private key file is encrypted"]
        with self.assertRaises(AuthenticationException) as cm:
            # This is also used to ensure paramiko.client.MissingHostKeyPolicy
            # is added to the client
            self.ssh_vendor.run_command(
                host="github.com",
                command="git-upload-pack '/bar/baz'",
                username=None,
                port=None)
        self.assertTrue(any(
            msg in str(cm.exception) for msg in expected_error_msgs))

        with self.assertRaises(AuthenticationException) as cm:
            self.ssh_vendor.run_command(
                host="github.com",
                command="git-upload-pack '/bar/baz'",
                username="me",
                port=22)
        self.assertTrue(any(
            msg in str(cm.exception) for msg in expected_error_msgs))

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
        repo_dict = {}
        repo_dict[b"refs/remotes/origin/1"] = b"some_bytes"
        repo_dict[b'HEAD'] = b"some_head"

        repo = mock.MagicMock()
        repo.__getitem__.side_effect = repo_dict.__getitem__

        repo.get_refs.return_value = {
            b"refs/remotes/origin/1": "some_text1",
            b"refs/remotes/other/1": "some_text2"}
        versioning.transfer_remote_refs(repo, None)


class FakeCommit(object):
    def __init__(self, name, parents=None, id=None,
                 message=b"my commit message"):
        self.name = name
        self.parents = parents or []
        self.message = message
        self.id = id

    def __repr__(self):
        return "%s: %s" % self.__class__.__name__ + str(self.name)


class IsParentCommitTest(unittest.TestCase):
    def setUp(self):
        repo_dict = {}
        repo = mock.MagicMock()
        repo.__getitem__.side_effect = repo_dict.__getitem__
        repo.__setitem__.side_effect = repo_dict.__setitem__
        self.repo = repo

    def test_false(self):
        c0 = FakeCommit(b"head", None)
        self.repo[b"HEAD"] = c0
        self.repo[c0] = FakeCommit(b"none", None)

        c1 = FakeCommit(b"first", [c0])

        self.assertFalse(
            versioning.is_parent_commit(
                self.repo, potential_parent=c0, child=c1))

        self.assertFalse(
            versioning.is_parent_commit(
                self.repo, potential_parent=c0, child=c1,
                max_history_check_size=2))

    def test_true(self):
        c0 = FakeCommit(b"head", None)
        self.repo[b"HEAD"] = c0
        self.repo[c0] = c0

        c1 = FakeCommit(b"first", [c0])
        self.repo[c1] = FakeCommit(b"first_c", [c0])

        c2 = FakeCommit(b"second", [c1])
        self.repo[c2] = FakeCommit(b"second_c", [c1])

        c3 = FakeCommit(b"third", [c2])

        self.assertFalse(
            versioning.is_parent_commit(
                self.repo, potential_parent=c0, child=c3,
                max_history_check_size=1))

        self.assertTrue(
            versioning.is_parent_commit(
                self.repo, potential_parent=c0, child=c3,
                max_history_check_size=20))


class DirectGitEndpointTest(TestCase):
    def test_no_authentication_headers(self):
        course = factories.CourseFactory()

        request = mock.MagicMock()
        obj = object()

        def no_header_mock(a, b=obj):
            if b == obj:
                raise KeyError
            return b

        request.META.get = no_header_mock
        response = versioning.git_endpoint(request, course.identifier, "")
        self.assertEqual(response.status_code, 401)

    def test_b64encoded_authentication_headers(self):
        from base64 import b64encode
        course = factories.CourseFactory()
        request = mock.MagicMock()

        request.META.get.return_value = "foo"
        response = versioning.git_endpoint(request, course.identifier, "")
        self.assertEqual(response.status_code, 401)

        request.META.get.return_value = "NonBasic foo"
        response = versioning.git_endpoint(request, course.identifier, "")
        self.assertEqual(response.status_code, 401)

        request.META.get.return_value = "Basic foo"
        response = versioning.git_endpoint(request, course.identifier, "")
        self.assertEqual(response.status_code, 401)

        auth_data = b64encode("foo".encode()).decode("utf-8")
        request.META.get.return_value = "Basic {}".format(auth_data)
        response = versioning.git_endpoint(request, course.identifier, "")
        self.assertEqual(response.status_code, 401)

    def test_auth_student(self):
        from base64 import b64encode
        from course.models import AuthenticationToken
        from django.contrib.auth.hashers import make_password

        course = factories.CourseFactory()
        student = factories.UserFactory()
        student2 = factories.UserFactory()
        student_role = factories.ParticipationRoleFactory(
            course=course,
            identifier="student"
        )
        participation1 = factories.ParticipationFactory(
            course=course,
            user=student)
        participation1.roles.set([student_role])

        auth_token = AuthenticationToken(
                user=student,
                participation=participation1,
                token_hash=make_password("spam"))
        auth_token.save()

        # Check invalid token format
        auth_data_unencoded = "{}:{}".format(student.username, "spam").encode()
        auth_data = b64encode(auth_data_unencoded).decode("utf-8")
        request = mock.MagicMock()
        request.META.get.return_value = "Basic {}".format(auth_data)
        response = versioning.git_endpoint(request, course.identifier, "")
        self.assertEqual(response.status_code, 401)

        # Check invalid token id
        auth_data_unencoded = "{}:{}_{}".format(student.username,
                                                "eggs", "ham").encode()
        auth_data = b64encode(auth_data_unencoded).decode("utf-8")
        request = mock.MagicMock()
        request.META.get.return_value = "Basic {}".format(auth_data)
        response = versioning.git_endpoint(request, course.identifier, "")
        self.assertEqual(response.status_code, 401)

        # Check non-existing user
        auth_data_unencoded = "{}:{}_{}".format("spam",
                                                "eggs", "ham").encode()
        auth_data = b64encode(auth_data_unencoded).decode("utf-8")
        request = mock.MagicMock()
        request.META.get.return_value = "Basic {}".format(auth_data)
        response = versioning.git_endpoint(request, course.identifier, "")
        self.assertEqual(response.status_code, 401)

        # Check token from other user
        auth_data_unencoded = "{}:{}_{}".format(student2.username,
                                                auth_token.id, "ham").encode()
        auth_data = b64encode(auth_data_unencoded).decode("utf-8")
        request = mock.MagicMock()
        request.META.get.return_value = "Basic {}".format(auth_data)
        response = versioning.git_endpoint(request, course.identifier, "")
        self.assertEqual(response.status_code, 401)

        # Check student with no permission
        auth_data_unencoded = "{}:{}_{}".format(student.username,
                                                auth_token.id, "spam").encode()
        auth_data = b64encode(auth_data_unencoded).decode("utf-8")
        request = mock.MagicMock()
        request.META.get.return_value = "Basic {}".format(auth_data)
        response = versioning.git_endpoint(request, course.identifier, "")
        self.assertEqual(response.status_code, 401)

    def test_auth_instructor(self):
        from base64 import b64encode
        from course.models import ParticipationRolePermission, AuthenticationToken
        from course.constants import participation_permission as pp
        from django.contrib.auth.hashers import make_password

        course = factories.CourseFactory()
        instructor = factories.UserFactory()
        instructor_role = factories.ParticipationRoleFactory(
            course=course,
            identifier="instructor"
        )
        participation1 = factories.ParticipationFactory(
            course=course,
            user=instructor)
        participation1.roles.set([instructor_role])
        ParticipationRolePermission(role=instructor_role,
                                    permission=pp.direct_git_endpoint).save()

        auth_token = AuthenticationToken(
                user=instructor,
                participation=participation1,
                token_hash=make_password("spam"))
        auth_token.save()

        fake_call_wsgi_app = mock.patch("course.versioning.call_wsgi_app")
        fake_get_course_repo = mock.patch("course.content.get_course_repo")
        mock_call_wsgi_app = fake_call_wsgi_app.start()
        mock_get_course_repo = fake_get_course_repo.start()

        auth_data_unencoded = "{}:{}_{}".format(instructor.username,
                                                auth_token.id, "spam").encode()
        auth_data = b64encode(auth_data_unencoded).decode("utf-8")
        request = mock.MagicMock()
        request.META.get.return_value = "Basic {}".format(auth_data)
        versioning.git_endpoint(request, course.identifier, "")
        self.assertEqual(mock_call_wsgi_app.call_count, 1)
        self.assertEqual(mock_get_course_repo.call_count, 1)

        fake_call_wsgi_app.stop()
        fake_get_course_repo.stop()

        fake_dulwich_web_backend = mock.patch("dulwich.web.DictBackend")
        fake_get_course_repo = mock.patch("course.content.get_course_repo")
        mock_dulwich_web_backend = fake_dulwich_web_backend.start()
        mock_get_course_repo = fake_get_course_repo.start()
        request = mock.MagicMock()
        request.META.get.return_value = "Basic {}".format(auth_data)
        versioning.git_endpoint(request, course.identifier, "")
        self.assertEqual(mock_dulwich_web_backend.call_count, 1)
        self.assertEqual(mock_get_course_repo.call_count, 1)
        fake_dulwich_web_backend.stop()
        fake_get_course_repo.stop()


FETCHED_LITERAL = "Fetch successful."
VALIDATE_SUCCESS_LITERAL = "Course content validated successfully."
PREVIEW_END_LITERAL = "Preview ended."
UPDATE_APPLIED_LITERAL = "Update applied."
WARNINGS_LITERAL = "Course content validated OK, with warnings:"
VALIDATE_FAILURE_LITERAL = "Course content did not validate successfully:"
NOT_UPDATED_LITERAL = "Update not applied."
FAILURE_MSG = "my validation error."
LOCATION1 = "location1"
LOCATION2 = "location2"
WARNING1 = "some waring1"
WARNING2 = "some waring2"


class RunCourseUpdateCommandTest(MockAddMessageMixing, unittest.TestCase):
    # test versioning.run_course_update_command

    default_preview_sha = "preview_sha"
    default_old_sha = "old_sha"
    default_switch_to_sha = "switch_sha"
    default_lastest_sha = "latest_sha"

    def setUp(self):
        super(RunCourseUpdateCommandTest, self).setUp()
        self.course = factories.CourseFactory(
            active_git_commit_sha=self.default_old_sha)
        user = factories.UserFactory()
        instructor_role = factories.ParticipationRoleFactory(
            course=self.course,
            identifier="instructor"
        )

        self.participation = factories.ParticipationFactory(
            course=self.course,
            preview_git_commit_sha=None,
            user=user)
        self.participation.roles.set([instructor_role])

        self.request = mock.MagicMock()
        self.request.user = user

        self.pctx = mock.MagicMock()
        self.pctx.course = self.course
        self.pctx.participation = self.participation

        self.repo = mock.MagicMock()
        self.content_repo = self.repo

        fake_get_dulwich_client_and_remote_path_from_course = mock.patch(
            "course.versioning.get_dulwich_client_and_remote_path_from_course")
        self.mock_get_dulwich_client_and_remote_path_from_course = (
            fake_get_dulwich_client_and_remote_path_from_course.start()
        )

        self.mock_client = mock.MagicMock()
        remote_path = "/remote/path"
        self.mock_get_dulwich_client_and_remote_path_from_course.return_value = (
            self.mock_client, remote_path
        )
        self.mock_client.fetch.return_value = {
            b"HEAD": self.default_switch_to_sha.encode()}

        self.addCleanup(fake_get_dulwich_client_and_remote_path_from_course.stop)

        fake_transfer_remote_refs = mock.patch(
            "course.versioning.transfer_remote_refs")
        self.mock_transfer_remote_refs = fake_transfer_remote_refs.start()
        self.addCleanup(fake_transfer_remote_refs.stop)

        fake_is_parent_commit = mock.patch("course.versioning.is_parent_commit")
        self.mock_is_parent_commit = fake_is_parent_commit.start()
        self.mock_is_parent_commit.return_value = False
        self.addCleanup(fake_is_parent_commit.stop)

        fake_validate_course_content = mock.patch(
            "course.validation.validate_course_content")
        self.mock_validate_course_content = fake_validate_course_content.start()
        self.mock_validate_course_content.return_value = []
        self.addCleanup(fake_validate_course_content.stop)

    def tearDown(self):
        for course in Course.objects.all():
            course.delete()

    @unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_is_parent_commit_checked(self):
        may_update = True
        prevent_discarding_revisions = True

        command_tup = [
            ("fetch", True),
            ("fetch_update", True),
            ("update", False),
            ("fetch_preview", True),
            ("preview", False),
            ("end_preview", False)]

        for command, will_check in command_tup:
            self.mock_is_parent_commit.reset_mock()
            with self.subTest(
                    command=command,
                    prevent_discarding_revisions=prevent_discarding_revisions):
                versioning.run_course_update_command(
                    self.request, self.repo, self.content_repo, self.pctx, command,
                    self.default_switch_to_sha.encode(), may_update,
                    prevent_discarding_revisions)
                if will_check and self.mock_is_parent_commit.call_count != 1:
                    self.fail(
                        "'is_parent_commit' is expected for command '%s' to be "
                        "called while not" % command)
                elif not will_check and self.mock_is_parent_commit.call_count > 0:
                    self.fail(
                        "'is_parent_commit' is not expected for command '%s' to be "
                        "called while called" % command)

        # when not prevent_discarding_revisions, is_parent_commit
        # should not be checked (expensive operation)

        prevent_discarding_revisions = False
        for command, _ in command_tup:
            self.mock_is_parent_commit.reset_mock()
            with self.subTest(
                    command=command,
                    prevent_discarding_revisions=prevent_discarding_revisions):
                versioning.run_course_update_command(
                    self.request, self.repo, self.content_repo, self.pctx, command,
                    self.default_switch_to_sha.encode(),
                    may_update, prevent_discarding_revisions)
                if self.mock_is_parent_commit.call_count > 0:
                    self.fail(
                        "'is_parent_commit' is not expected for command '%s' to be "
                        "called while called (expensive)" % command)
                elif self.mock_is_parent_commit.call_count > 0:
                    self.fail(
                        "'is_parent_commit' is not expected for command '%s' to be "
                        "called while called" % command)

    @unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_is_content_validated(self):
        may_update = True

        command_tup = [
            ("fetch", False),
            ("fetch_update", True),
            ("update", True),
            ("fetch_preview", True),
            ("preview", True),
            ("end_preview", False)]

        for command, will_validate in command_tup:
            self.mock_validate_course_content.reset_mock()
            with self.subTest(command=command):
                versioning.run_course_update_command(
                    self.request, self.repo, self.content_repo, self.pctx, command,
                    self.default_switch_to_sha.encode(),
                    may_update, prevent_discarding_revisions=False)
                if (will_validate
                        and self.mock_validate_course_content.call_count != 1):
                    self.fail(
                        "'validate_course_content' is expected for "
                        "command '%s' to be called while not" % command)
                elif (not will_validate
                      and self.mock_validate_course_content.call_count > 0):
                    self.fail(
                        "'validate_course_content' is not expected for "
                        "command '%s' to be called while called" % command)

    def test_unknown_command(self):
        command = "unknown"
        may_update = True
        prevent_discarding_revisions = False

        with self.assertRaises(RuntimeError) as cm:
            versioning.run_course_update_command(
                self.request, self.repo, self.content_repo, self.pctx, command,
                self.default_switch_to_sha.encode(),
                may_update, prevent_discarding_revisions)

        self.assertEqual(self.mock_validate_course_content.call_count, 0)
        self.assertEqual(self.mock_is_parent_commit.call_count, 0)

        expected_error_msg = "invalid command"
        self.assertIn(expected_error_msg, str(cm.exception))

    def check_command_message_result(
            self, command, add_message_expected_call_count=0,
            expected_add_message_literals=None,
            not_expected_add_message_literals=None,
            is_previewing=False,
            expected_error_type=None,
            expected_error_msg=None,
            **call_kwargs
    ):
        kwargs = {
            "request": self.request,
            "repo": self.repo,
            "content_repo": self.content_repo,
            "pctx": self.pctx,
            "command": command,
            "new_sha": self.default_switch_to_sha.encode(),
            "may_update": True,
            "prevent_discarding_revisions": True
        }
        kwargs.update(call_kwargs)

        if expected_add_message_literals is None:
            expected_add_message_literals = []
        else:
            assert isinstance(expected_add_message_literals, list)

        if not_expected_add_message_literals is None:
            not_expected_add_message_literals = []
        else:
            assert isinstance(not_expected_add_message_literals, list)

        if is_previewing:
            self.participation.preview_git_commit_sha = self.default_preview_sha
            self.participation.save()

        if expected_error_type:
            assert expected_error_msg is not None
            with self.assertRaises(expected_error_type) as cm:
                versioning.run_course_update_command(**kwargs)

            self.assertIn(expected_error_msg, str(cm.exception))
        else:
            versioning.run_course_update_command(**kwargs)

        self.assertAddMessageCallCount(add_message_expected_call_count)
        self.assertAddMessageCalledWith(
            expected_add_message_literals, reset=False)
        self.assertAddMessageNotCalledWith(
            not_expected_add_message_literals, reset=False)
        self.reset_add_message_mock()

    def test_fetch(self):
        self.check_command_message_result(
            command="fetch",
            add_message_expected_call_count=1,
            expected_add_message_literals=[
                FETCHED_LITERAL
            ],
            not_expected_add_message_literals=[PREVIEW_END_LITERAL]
        )

    def test_end_preview(self):
        self.check_command_message_result(
            command="end_preview",
            add_message_expected_call_count=1,
            is_previewing=True,
            expected_add_message_literals=[
                PREVIEW_END_LITERAL
            ]
        )
        self.assertIsNone(self.participation.preview_git_commit_sha)

    @unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_fetch_not_prevent_discarding_revisions(self):
        self.mock_client.fetch.return_value = {
            b"HEAD": self.default_lastest_sha.encode()}

        command_tup = (
            ("fetch", 1, [FETCHED_LITERAL], [UPDATE_APPLIED_LITERAL],
             self.default_old_sha),
            ("fetch_update", 3, [FETCHED_LITERAL, UPDATE_APPLIED_LITERAL,
                                 VALIDATE_SUCCESS_LITERAL], [],
             self.default_lastest_sha)
        )

        for (command, add_message_call_count, expected, not_expected,
             expected_course_sha) in command_tup:
            with self.subTest(command=command):
                self.mock_is_parent_commit.return_value = False
                self.check_command_message_result(
                    command=command,
                    add_message_expected_call_count=add_message_call_count,
                    expected_add_message_literals=expected,
                    not_expected_add_message_literals=not_expected,
                    prevent_discarding_revisions=False
                )

                self.mock_is_parent_commit.return_value = True
                self.check_command_message_result(
                    command=command,
                    add_message_expected_call_count=add_message_call_count,
                    expected_add_message_literals=expected,
                    not_expected_add_message_literals=not_expected,
                    prevent_discarding_revisions=False
                )

                self.assertEqual(
                    self.course.active_git_commit_sha, expected_course_sha)

    def test_fetch_prevent_discarding_revisions(self):
        self.mock_is_parent_commit.return_value = True
        self.check_command_message_result(
            command="fetch",
            expected_error_type=RuntimeError,
            expected_error_msg="fetch would discard commits, refusing",
            add_message_expected_call_count=0,
            prevent_discarding_revisions=True
        )
        self.assertAddMessageCallCount(0)

    def test_internal_git_repo_more_commits(self):
        from collections import defaultdict
        self.mock_is_parent_commit.return_value = False
        repo = defaultdict(lambda : "bar")
        repo[b"HEAD"]="foo"

        self.check_command_message_result(
            command="fetch",
            expected_error_type=RuntimeError,
            expected_error_msg="internal git repo has more commits."
                " Fetch, merge and push.",
            add_message_expected_call_count=0,
            prevent_discarding_revisions=True,
            repo=repo,
        )
        self.assertAddMessageCallCount(0)

    def test_fetch_update_success_with_warnings(self):
        self.mock_client.fetch.return_value = {
            b"HEAD": self.default_lastest_sha.encode()}
        self.mock_validate_course_content.return_value = (
            ValidationWarning(LOCATION1, WARNING1),
            ValidationWarning(LOCATION2, WARNING2),
        )

        self.check_command_message_result(
            command="fetch_update",
            add_message_expected_call_count=3,
            expected_add_message_literals=[
                FETCHED_LITERAL,
                WARNINGS_LITERAL, LOCATION1, WARNING1, LOCATION2, WARNING2,
            ],
            not_expected_add_message_literals=[PREVIEW_END_LITERAL])
        self.assertIsNone(self.participation.preview_git_commit_sha)
        self.assertEqual(
            self.course.active_git_commit_sha, self.default_lastest_sha)

    def test_fetch_update_success_with_warnings_previewing(self):
        self.mock_client.fetch.return_value = {
            b"HEAD": self.default_lastest_sha.encode()}
        self.mock_validate_course_content.return_value = (
            ValidationWarning(LOCATION1, WARNING1),
            ValidationWarning(LOCATION2, WARNING2),
        )

        self.check_command_message_result(
            command="fetch_update",
            is_previewing=True,
            add_message_expected_call_count=4,
            expected_add_message_literals=[
                FETCHED_LITERAL,
                WARNINGS_LITERAL, LOCATION1, WARNING1, LOCATION2, WARNING2,
                PREVIEW_END_LITERAL
            ])
        self.assertIsNone(self.participation.preview_git_commit_sha)
        self.assertEqual(
            self.course.active_git_commit_sha, self.default_lastest_sha)

    def test_fetch_update_with_validation_error(self):
        from course.validation import ValidationError
        my_validation_error_msg = "my validation error."
        self.mock_validate_course_content.side_effect = (
            ValidationError(my_validation_error_msg))

        self.check_command_message_result(
            command="fetch_update",
            add_message_expected_call_count=2,
            expected_add_message_literals=[
                FETCHED_LITERAL,
                VALIDATE_FAILURE_LITERAL, my_validation_error_msg],
            not_expected_add_message_literals=[PREVIEW_END_LITERAL])
        self.assertIsNone(self.participation.preview_git_commit_sha)
        self.assertEqual(self.course.active_git_commit_sha, self.default_old_sha)

    def test_update_with_validation_error(self):
        from course.validation import ValidationError
        my_validation_error_msg = "my validation error."
        self.mock_validate_course_content.side_effect = (
            ValidationError(my_validation_error_msg))

        self.check_command_message_result(
            command="update",
            add_message_expected_call_count=1,
            expected_add_message_literals=[
                VALIDATE_FAILURE_LITERAL, my_validation_error_msg],
            not_expected_add_message_literals=[PREVIEW_END_LITERAL]
        )
        self.assertIsNone(self.participation.preview_git_commit_sha)
        self.assertEqual(self.course.active_git_commit_sha, self.default_old_sha)

    def test_update_with_validation_error_previewing(self):
        from course.validation import ValidationError
        my_validation_error_msg = "my validation error."
        self.mock_validate_course_content.side_effect = (
            ValidationError(my_validation_error_msg))

        self.check_command_message_result(
            command="update",
            add_message_expected_call_count=1,
            is_previewing=True,
            expected_add_message_literals=[
                VALIDATE_FAILURE_LITERAL, my_validation_error_msg],
            not_expected_add_message_literals=[PREVIEW_END_LITERAL]
        )
        self.assertIsNotNone(self.participation.preview_git_commit_sha)
        self.assertEqual(
            self.participation.preview_git_commit_sha, self.default_preview_sha)
        self.assertEqual(self.course.active_git_commit_sha, self.default_old_sha)

    @unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_fetch_not_may_update(self):
        self.mock_client.fetch.return_value = {
            b"HEAD": self.default_lastest_sha.encode()}

        command_tup = (
            ("fetch", 1, [FETCHED_LITERAL], [UPDATE_APPLIED_LITERAL],
             self.default_old_sha),
            ("fetch_update", 2, [FETCHED_LITERAL, VALIDATE_SUCCESS_LITERAL],
             [UPDATE_APPLIED_LITERAL],
             self.default_old_sha)
        )

        for (command, add_message_call_count, expected, not_expected,
             expected_course_sha) in command_tup:
            with self.subTest(command=command):
                self.check_command_message_result(
                    command=command,
                    add_message_expected_call_count=add_message_call_count,
                    expected_add_message_literals=expected,
                    not_expected_add_message_literals=not_expected,
                    may_update=False
                )

                self.check_command_message_result(
                    command=command,
                    add_message_expected_call_count=add_message_call_count,
                    expected_add_message_literals=expected,
                    not_expected_add_message_literals=not_expected,
                    may_update=False
                )

                self.assertEqual(
                    self.course.active_git_commit_sha, expected_course_sha)


class VersioningRepoMixin(object):
    @classmethod
    def setUpTestData(cls):  # noqa
        super(VersioningRepoMixin, cls).setUpTestData()
        cls.rf = RequestFactory()
        request = cls.rf.get(cls.get_update_course_url())
        request.user = cls.instructor_participation.user

        from course.utils import CoursePageContext
        pctx = CoursePageContext(request, cls.course.identifier)
        cls.repo = pctx.repo


class GitUpdateFormTest(VersioningRepoMixin, SingleCourseTestMixin, TestCase):

    # Todo: test inner format_commit
    def test_may_not_update(self):
        form = versioning.GitUpdateForm(
            may_update=False, previewing=True, repo=self.repo)
        from crispy_forms.layout import Submit
        submit_input_names = [
            input.name for input in form.helper.inputs
            if isinstance(input, Submit)
        ]

        self.assertNotIn("fetch_update", submit_input_names)
        self.assertNotIn("update", submit_input_names)

    def test_may_update(self):
        form = versioning.GitUpdateForm(
            may_update=True, previewing=True, repo=self.repo)
        from crispy_forms.layout import Submit
        submit_input_names = [
            input.name for input in form.helper.inputs
            if isinstance(input, Submit)
        ]

        self.assertIn("fetch_update", submit_input_names)
        self.assertIn("update", submit_input_names)

    def test_not_previewing(self):
        form = versioning.GitUpdateForm(
            may_update=True, previewing=False, repo=self.repo)
        from crispy_forms.layout import Submit
        submit_input_names = [
            input.name for input in form.helper.inputs
            if isinstance(input, Submit)
        ]

        self.assertNotIn("end_preview", submit_input_names)

    def test_previewing(self):
        form = versioning.GitUpdateForm(
            may_update=True, previewing=True, repo=self.repo)
        from crispy_forms.layout import Submit
        submit_input_names = [
            input.name for input in form.helper.inputs
            if isinstance(input, Submit)
        ]

        self.assertIn("end_preview", submit_input_names)


class GetCommitMessageAsHtmlTest(VersioningRepoMixin, SingleCourseTestMixin,
                                 TestCase):
    # test versioning._get_commit_message_as_html
    def test_result_text(self):
        commit_sha = "593a1cdcecc6f4759fd5cadaacec0ba9dd0715a7"
        expected_msg = ("Added an optional_page, another "
                        "PythonCodeQuestionWithHumanTextFeedback page.")
        self.assertEqual(
            versioning._get_commit_message_as_html(self.repo, commit_sha),
            expected_msg)

    def test_result_byte(self):
        commit_sha = b"593a1cdcecc6f4759fd5cadaacec0ba9dd0715a7"
        expected_msg = ("Added an optional_page, another "
                        "PythonCodeQuestionWithHumanTextFeedback page.")
        self.assertEqual(
            versioning._get_commit_message_as_html(self.repo, commit_sha),
            expected_msg)

    def test_non_exist_commit(self):
        commit_sha = b"unknown"
        expected_msg = "- not found -"

        self.assertEqual(
            versioning._get_commit_message_as_html(self.repo, commit_sha),
            expected_msg)

    def test_escape_html(self):
        commit_sha_1 = b"a_commit"
        commit_sha_2 = b"another_commit"
        commit_sha_3 = b"yet_another_commit"
        repo_dict = {
            commit_sha_1: FakeCommit("a_commit", message=b"test a > b  "),
            commit_sha_2: FakeCommit("another_commit", message=b"  <p>test</p>"),
            commit_sha_3: FakeCommit("another_commit", message=b"abc\\uDC80"),
        }
        repo = mock.MagicMock()
        repo.__getitem__.side_effect = repo_dict.__getitem__
        repo.__setitem__.side_effect = repo_dict.__setitem__

        expected_msg = "test a &gt; b"
        self.assertEqual(
            versioning._get_commit_message_as_html(repo, commit_sha_1),
            expected_msg)

        expected_msg = "&lt;p&gt;test&lt;/p&gt;"
        self.assertEqual(
            versioning._get_commit_message_as_html(repo, commit_sha_2),
            expected_msg)

        expected_msg = "abc\\uDC80"
        self.assertEqual(
            versioning._get_commit_message_as_html(repo, commit_sha_3),
            expected_msg)


class UpdateCourseTest(SingleCourseTestMixin, MockAddMessageMixing, TestCase):
    def test_no_permission(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(self.get_update_course_url())
            self.assertEqual(resp.status_code, 403)

            for command in versioning.ALLOWED_COURSE_REVISIOIN_COMMANDS:
                resp = self.post_update_course_content(
                    "some_commit_sha", command=command,
                    force_login_instructor=False)
                self.assertEqual(resp.status_code, 403)

    def test_participation_with_preview_permission(self):
        # Just to make sure it won't fail, Todo: assersion on form kwargs
        from course.models import ParticipationPermission
        pp = ParticipationPermission(
            participation=self.student_participation,
            permission=pperm.preview_content)
        pp.save()
        self.student_participation.individual_permissions.set([pp])

        with self.temporarily_switch_to_user(self.student_participation.user):
            for command in versioning.ALLOWED_COURSE_REVISIOIN_COMMANDS:
                resp = self.post_update_course_content(
                    "some_commit_sha", command=command,
                    force_login_instructor=False)
                self.assertEqual(resp.status_code, 200, command)

    def test_participation_with_update_permission(self):
        # Just to make sure it won't fail, Todo: assersion on form kwargs
        from course.models import ParticipationPermission
        pp = ParticipationPermission(
            participation=self.student_participation,
            permission=pperm.update_content)
        pp.save()
        self.student_participation.individual_permissions.set([pp])

        with self.temporarily_switch_to_user(self.student_participation.user):
            for command in versioning.ALLOWED_COURSE_REVISIOIN_COMMANDS:
                resp = self.post_update_course_content(
                    "some_commit_sha", command=command,
                    force_login_instructor=False)
                self.assertEqual(resp.status_code, 200, command)

    def test_get(self):
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.c.get(self.get_update_course_url())
            self.assertEqual(resp.status_code, 200)

    def test_unknown_command(self):
        resp = self.post_update_course_content(
            "some_commit_sha", command="unknown")
        self.assertEqual(resp.status_code, 400)

    @suppress_stdout_decorator(suppress_stderr=True)
    def test_run_course_update_command_failure(self):
        with mock.patch(
            "course.versioning.run_course_update_command"
        ) as mock_run_update:
            error_msg = "my runtime error"
            mock_run_update.side_effect = RuntimeError(error_msg)
            resp = self.post_update_course_content(
                self.course.active_git_commit_sha, command="update")
            self.assertEqual(resp.status_code, 200)
            self.assertAddMessageCallCount(1)
            expected_error_msg = "Error: RuntimeError %s" % error_msg
            self.assertAddMessageCalledWith(expected_error_msg)

    def test_form_not_valid(self):
        with mock.patch(
                "course.versioning.GitUpdateForm.is_valid"
        ) as mock_form_valid, mock.patch(
            "course.versioning.run_course_update_command"
        ) as mock_run_update:
            mock_form_valid.return_value = False
            resp = self.post_update_course_content(
                "some_commit_sha", command="update")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(mock_run_update.call_count, 0)

    def test_repo_is_in_subdir(self):
        self.course.course_root_path = "/subdir"
        self.course.save()

        from course.content import get_course_repo, SubdirRepoWrapper
        self.assertIsInstance(get_course_repo(self.course), SubdirRepoWrapper)

        with mock.patch(
            "course.versioning.run_course_update_command"
        ) as mock_run_update:
            self.post_update_course_content(
                self.course.active_git_commit_sha, command="update")

            self.assertEqual(mock_run_update.call_count, 1)

            from course.content import SubdirRepoWrapper
            from dulwich.repo import Repo
            self.assertIsInstance(mock_run_update.call_args[0][1], Repo)
