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

import pytest
from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils.timezone import now
from django.contrib.auth import get_user_model
from django.contrib.admin import site
from django.contrib.admin.models import LogEntry

from course.models import Participation
from accounts.admin import UserAdmin
from accounts.models import User

from tests.base_test_mixins import AdminTestMixin


@pytest.mark.slow
class AccountsAdminTest(AdminTestMixin, TestCase):

    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()

        cls.user_change_list_url = cls.get_admin_change_list_view_url()
        cls.superuser_change_url = (
            cls.get_admin_change_view_url(args=(cls.superuser.pk,)))
        cls.instructor1_change_url = (
            cls.get_admin_change_view_url(args=(cls.instructor1.pk,)))
        cls.student1_change_url = (
            cls.get_admin_change_view_url(
                args=(cls.course1_student_participation.user.pk,)))
        cls.student2_change_url = (
            cls.get_admin_change_view_url(
                args=(cls.course1_student_participation2.user.pk,)))

    @classmethod
    def get_admin_change_list_view_url(cls):
        return super().get_admin_change_list_view_url(
            app_name="accounts", model_name="user")

    @classmethod
    def get_admin_change_view_url(cls, args=None):
        return super().get_admin_change_view_url(
            app_name="accounts", model_name="user", args=args)

    def setUp(self):
        super().setUp()
        self.superuser.refresh_from_db()
        self.rf = RequestFactory()

    def test_change_view(self):

        with self.subTest("superuser admin change/changelist for "
                          "accounts.user"):
            with self.temporarily_switch_to_user(self.superuser):
                # list view
                resp = self.c.get(self.user_change_list_url)
                self.assertEqual(resp.status_code, 200)

                # change view
                resp = self.c.get(self.superuser_change_url)
                self.assertEqual(resp.status_code, 200)

                resp = self.c.get(self.instructor1_change_url)
                self.assertEqual(resp.status_code, 200)

        with self.subTest("staff 1 admin change/changelist for "
                          "accounts.user"):
            with self.temporarily_switch_to_user(self.instructor1):
                resp = self.c.get(self.user_change_list_url)
                self.assertEqual(resp.status_code, 200)

                resp = self.c.get(self.superuser_change_url)
                self.assertEqual(resp.status_code, 200)

                resp = self.c.get(self.instructor1_change_url)
                self.assertEqual(resp.status_code, 200)

                resp = self.c.get(self.student2_change_url)
                self.assertEqual(resp.status_code, 200)

                # because that student joined 2 courses
                resp = self.c.get(self.student1_change_url)
                self.assertEqual(resp.status_code, 200)

        with self.subTest("staff 2 admin change/changelist for "
                          "accounts.user"):
            with self.temporarily_switch_to_user(self.instructor2):
                resp = self.c.get(self.user_change_list_url)
                self.assertEqual(resp.status_code, 200)

                resp = self.c.get(self.superuser_change_url)
                self.assertEqual(resp.status_code, 200)

                # Because instructor 1 is also a staff
                resp = self.c.get(self.instructor1_change_url)
                self.assertEqual(resp.status_code, 200)

                # because that student joined 2 courses
                resp = self.c.get(self.student1_change_url)
                self.assertEqual(resp.status_code, 200)

                # because that student didn't join this course
                resp = self.c.get(self.student2_change_url)
                self.assertEqual(resp.status_code, 200)

    def test_admin_add_user(self):
        # This is to make sure admin can add user without email.
        # Make sure https://github.com/inducer/relate/issues/447 is fixed
        with self.temporarily_switch_to_user(self.instructor1):
            user_count = get_user_model().objects.count()
            resp = self.c.post(reverse('admin:accounts_user_add'), {
                'username': 'newuser',
                'password1': 'newpassword',
                'password2': 'newpassword',
            })
            new_user = get_user_model().objects.get(username='newuser')
            self.assertRedirects(resp, reverse('admin:accounts_user_change',
                                                   args=(new_user.pk,)))
            self.assertEqual(get_user_model().objects.count(), user_count + 1)
            self.assertTrue(new_user.has_usable_password())

    def test_admin_user_change_fieldsets(self):
        # This test is using request factory
        change_url = reverse('admin:accounts_user_change',
                    args=(self.course1_student_participation3.user.pk,))

        common_fields = (
            "username",
            "password",
            "status",
            "first_name",
            "last_name",
            "name_verified",
            "email",
            "institutional_id",
            "institutional_id_verified",
            "editor_mode",
            "last_login",
            "date_joined",
        )

        superuser_only_fields = (
            "is_active",
            "is_staff",
            "is_superuser",
            "groups",
            "user_permissions",
        )

        test_dicts = [{"user": self.superuser,
                       "see_common_fields": True,
                       "see_superuser_only_fields": True},
                      {"user": self.instructor1,
                       "see_common_fields": True,
                       "see_superuser_only_fields": False}]

        for td in test_dicts:
            with self.subTest(user=td["user"]):
                with self.temporarily_switch_to_user(td["user"]):
                    resp = self.c.get(change_url)
                    self.assertEqual(resp.status_code, 200)
                    field_names = self.get_admin_form_fields_names(resp)

                    for f in common_fields:
                        self.assertEqual(
                            td["see_common_fields"], f in field_names,
                            "'%s' unexpectedly %s SHOWN in %s"
                            % (f,
                               "NOT" if td["see_superuser_only_fields"]
                               else "",
                               repr(field_names))
                        )
                    for f in superuser_only_fields:
                        self.assertEqual(
                            td["see_superuser_only_fields"], f in field_names,
                            "'%s' unexpectedly %s SHOWN in %s"
                            % (f,
                              "NOT" if td["see_superuser_only_fields"]
                              else "",
                              repr(field_names)))

    def test_list_display_is_staff_field(self):
        modeladmin = UserAdmin(User, site)
        request = self.rf.get(self.user_change_list_url, {})
        request.user = self.superuser
        list_display = modeladmin.get_list_display(request)
        self.assertIn("is_staff", list_display)

        # ensure "is_staff" not present in list_display of staff view
        request.user = self.instructor1
        list_display = modeladmin.get_list_display(request)
        self.assertNotIn("is_staff", list_display)

    def test_list_filter_is_staff_field(self):
        modeladmin = UserAdmin(User, site)
        request = self.rf.get(self.user_change_list_url, {})
        request.user = self.superuser
        list_filter = modeladmin.get_list_filter(request)
        self.assertIn("is_staff", list_filter)

        # ensure "is_staff" not present in list_filter of staff view
        request.user = self.instructor1
        list_filter = modeladmin.get_list_filter(request)
        self.assertNotIn("is_staff", list_filter)

    def test_list_editable_is_staff_field(self):
        # ensuer "is_staff" not present in list_editable
        # notice that, list_editable must be a subset of list_display,
        # or it will raise an check error.
        modeladmin = UserAdmin(User, site)
        request = self.rf.get(self.user_change_list_url, {})
        request.user = self.superuser

        changelist = self.get_changelist(request, User, modeladmin)
        self.assertNotIn("is_staff", changelist.list_editable)

        request.user = self.instructor1
        changelist = self.get_changelist(request, User, modeladmin)
        self.assertNotIn("is_staff", changelist.list_editable)

    def test_list_filter_queryset_filter(self):
        """
        A list filter that filters the queryset by default gives the correct
        full_result_count.
        """
        total_user_count = User.objects.count()
        modeladmin = UserAdmin(User, site)

        # {{{ not filtered
        request = self.rf.get(self.user_change_list_url, {})
        request.user = self.superuser
        changelist = self.get_changelist(request, User, modeladmin)

        changelist.get_results(request)
        self.assertEqual(changelist.full_result_count, total_user_count)

        filterspec_list = self.get_filterspec_list(request, changelist)
        self.assertIn(('All', self.course1.identifier, self.course2.identifier),
                      filterspec_list)

        request = self.rf.get(self.user_change_list_url, {})
        request.user = self.instructor1
        changelist = self.get_changelist(request, User, modeladmin)
        changelist.get_results(request)
        filterspec_list = self.get_filterspec_list(request, changelist)

        # 2 users created in setUp 'testuser_001', 'testuser_000',
        # 4 non-participation users 'test_user4', 'test_user3', 'test_user2',
        # 'test_user1',
        # 1 instructor 'test_instructor' (request.user)
        self.assertEqual(changelist.full_result_count, 10)

        queryset = changelist.get_queryset(request)
        self.assertIn(self.instructor1, queryset)

        self.assertIn(self.superuser, queryset)
        self.assertIn(self.course1_student_participation.user, queryset)
        self.assertIn(self.instructor2, queryset)

        # Although instructor 1 attended course2, the list_filter did not have that
        # choice, because he/she has no view_admin_interface pperm in that course
        self.assertIn(('All', self.course1.identifier), filterspec_list)

        # }}}

        # {{{ filtered by course 1

        request = self.rf.get(self.user_change_list_url,
                              {"course__identifier": self.course1.identifier})
        request.user = self.superuser
        changelist = self.get_changelist(request, User, modeladmin)

        queryset = changelist.get_queryset(request)
        self.assertEqual(
            queryset.count(),
            Participation.objects.filter(
                course__identifier=self.course1.identifier).count())

        request = self.rf.get(self.user_change_list_url,
                              {"course__identifier": self.course1.identifier})
        request.user = self.instructor1
        changelist = self.get_changelist(request, User, modeladmin)
        queryset = changelist.get_queryset(request)

        # 2 users created in setUp 'testuser_001', 'testuser_000',
        # 1 instructor 'test_instructor'
        self.assertEqual(queryset.count(), 5)

        # }}}

    def get_user_data(self, user):
        if not user.last_login:
            user.last_login = now()
        if not user.date_joined:
            user.date_joined = now()
        return {
            'username': user.username,
            'password': user.password,
            'email': user.email,
            'is_active': user.is_active,
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
            'last_login_0': user.last_login.strftime('%Y-%m-%d'),
            'last_login_1': user.last_login.strftime('%H:%M:%S'),
            'initial-last_login_0': user.last_login.strftime('%Y-%m-%d'),
            'initial-last_login_1': user.last_login.strftime('%H:%M:%S'),
            'date_joined_0': user.date_joined.strftime('%Y-%m-%d'),
            'date_joined_1': user.date_joined.strftime('%H:%M:%S'),
            'initial-date_joined_0': user.date_joined.strftime('%Y-%m-%d'),
            'initial-date_joined_1': user.date_joined.strftime('%H:%M:%S'),
            'first_name': user.first_name,
            'last_name': user.last_name,
            'editor_mode': user.editor_mode,
            'status': user.status
        }

    def test_set_superuser_and_staff_by_superuser(self):
        user = self.course1_student_participation2.user
        with self.temporarily_switch_to_user(self.superuser):
            staff_count = User.objects.filter(is_staff=True).count()
            superuser_count = User.objects.filter(is_superuser=True).count()
            data = self.get_user_data(user)
            data["is_staff"] = True
            resp = self.c.post(self.student2_change_url, data)
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(User.objects.filter(is_staff=True).count(),
                             staff_count + 1)
            row = LogEntry.objects.latest('id')
            self.assertIn("Changed", row.get_change_message())
            self.assertIn("Staff status", row.get_change_message())

            data = self.get_user_data(user)
            data["is_superuser"] = True
            self.c.post(self.student2_change_url, data)
            self.assertEqual(User.objects.filter(is_superuser=True).count(),
                             superuser_count + 1)
            row = LogEntry.objects.latest('id')
            self.assertIn("Changed", row.get_change_message())
            self.assertIn("Staff status", row.get_change_message())

    def test_set_superuser_and_staff_by_staff(self):
        user = self.course1_student_participation2.user
        with self.temporarily_switch_to_user(self.instructor1):
            staff_count = User.objects.filter(is_staff=True).count()
            superuser_count = User.objects.filter(is_superuser=True).count()
            data = self.get_user_data(user)
            data["is_staff"] = True
            resp = self.c.post(self.student2_change_url, data)
            self.assertEqual(resp.status_code, 302)

            # non-superuser staff can't post create staff
            self.assertEqual(User.objects.filter(is_staff=True).count(),
                             staff_count)
            row = LogEntry.objects.latest('id')
            self.assertNotIn("is_staff", row.get_change_message())

            data = self.get_user_data(user)
            data["is_superuser"] = True
            self.c.post(self.student2_change_url, data)

            # non-superuser staff can't post create superuser
            self.assertEqual(User.objects.filter(is_superuser=True).count(),
                             superuser_count)
            row = LogEntry.objects.latest('id')
            self.assertNotIn("Staff status", row.get_change_message())

    def test_add_permissions_by_superuser(self):
        user = self.course1_student_participation2.user
        with self.temporarily_switch_to_user(self.superuser):
            data = self.get_user_data(user)
            # add a permission in post data
            data["user_permissions"] = [1, ]

            self.c.post(self.student2_change_url, data)

            row = LogEntry.objects.latest('id')
            self.assertIn("Changed", row.get_change_message())
            self.assertIn("User permissions",  row.get_change_message())

    def test_add_permissions_by_staff(self):
        user = self.course1_student_participation2.user
        with self.temporarily_switch_to_user(self.instructor1):
            data = self.get_user_data(user)
            # try to add a permission in post data
            data["user_permissions"] = [1, ]

            self.c.post(self.student2_change_url, data)

            row = LogEntry.objects.latest('id')
            self.assertIn("Changed", row.get_change_message())

            # no change was made to user_permissions
            self.assertNotIn("User permissions", row.get_change_message())

# vim: foldmethod=marker
