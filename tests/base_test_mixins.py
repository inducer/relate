from __future__ import division

__copyright__ = "Copyright (C) 2017 Dong Zhuang, Andreas Kloeckner, Zesheng Wang"

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

import os
from django.conf import settings
from django.test import Client, override_settings
from django.urls import reverse, resolve
from django.contrib.auth import get_user_model
from relate.utils import force_remove_path
from course.models import Course, Participation, ParticipationRole, FlowSession
from course.constants import participation_status, user_status

CREATE_SUPERUSER_KWARGS = {
    "username": "test_admin",
    "password": "test_admin",
    "email": "test_admin@example.com",
    "first_name": "Test",
    "last_name": "Admin"}

SINGLE_COURSE_SETUP_LIST = [
    {
        "course": {
            "identifier": "test-course",
            "name": "Test Course",
            "number": "CS123",
            "time_period": "Fall 2016",
            "hidden": False,
            "listed": True,
            "accepts_enrollment": True,
            "git_source": "git://github.com/inducer/relate-sample",
            "course_file": "course.yml",
            "events_file": "events.yml",
            "enrollment_approval_required": False,
            "enrollment_required_email_suffix": "",
            "preapproval_require_verified_inst_id": True,
            "from_email": "inform@tiker.net",
            "notify_email": "inform@tiker.net"},
        "participations": [
            {
                "role_identifier": "instructor",
                "user": {
                    "username": "test_instructor",
                    "password": "test_instructor",
                    "email": "test_instructor@example.com",
                    "first_name": "Test",
                    "last_name": "Instructor"},
                "status": participation_status.active
            },
            {
                "role_identifier": "ta",
                "user": {
                    "username": "test_ta",
                    "password": "test",
                    "email": "test_ta@example.com",
                    "first_name": "Test",
                    "last_name": "TA"},
                "status": participation_status.active
            },
            {
                "role_identifier": "student",
                "user": {
                    "username": "test_student",
                    "password": "test",
                    "email": "test_student@example.com",
                    "first_name": "Test",
                    "last_name": "Student"},
                "status": participation_status.active
            }
        ],
    }
]


NONE_PARTICIPATION_USER_CREATE_KWARG_LIST = [
    {
        "username": "test_user1",
        "password": "test_user1",
        "email": "test_user1@suffix.com",
        "first_name": "Test",
        "last_name": "User1",
        "institutional_id": "test_user1_institutional_id",
        "institutional_id_verified": True,
        "status": user_status.active
    },
    {
        "username": "test_user2",
        "password": "test_user2",
        "email": "test_user2@nosuffix.com",
        "first_name": "Test",
        "last_name": "User2",
        "institutional_id": "test_user2_institutional_id",
        "institutional_id_verified": False,
        "status": user_status.active
    },
    {
        "username": "test_user3",
        "password": "test_user3",
        "email": "test_user3@suffix.com",
        "first_name": "Test",
        "last_name": "User3",
        "institutional_id": "test_user3_institutional_id",
        "institutional_id_verified": True,
        "status": user_status.unconfirmed
    },
    {
        "username": "test_user4",
        "password": "test_user4",
        "email": "test_user4@no_suffix.com",
        "first_name": "Test",
        "last_name": "User4",
        "institutional_id": "test_user4_institutional_id",
        "institutional_id_verified": False,
        "status": user_status.unconfirmed
    }
]


class SuperuserCreateMixin(object):
    create_superuser_kwargs = CREATE_SUPERUSER_KWARGS

    @classmethod
    def setUpTestData(cls):  # noqa
        # Create superuser, without this, we cannot
        # create user, course and participation.
        cls.superuser = cls.create_superuser()
        cls.c = Client()
        super(SuperuserCreateMixin, cls).setUpTestData()

    @classmethod
    def tearDownClass(cls):  # noqa
        super(SuperuserCreateMixin, cls).tearDownClass()

    @classmethod
    def create_superuser(cls):
        return get_user_model().objects.create_superuser(
                                                **cls.create_superuser_kwargs)


class CoursesTestMixinBase(SuperuserCreateMixin):

    # A list of Dicts, each of which contain a course dict and a list of
    # participations. See SINGLE_COURSE_SETUP_LIST for the setup for one course.
    courses_setup_list = []
    none_participation_user_create_kwarg_list = []

    @classmethod
    def setUpTestData(cls):  # noqa
        super(CoursesTestMixinBase, cls).setUpTestData()
        cls.n_courses = 0
        for course_setup in cls.courses_setup_list:
            if "course" not in course_setup:
                continue

            cls.n_courses += 1
            course_identifier = course_setup["course"]["identifier"]
            cls.remove_exceptionally_undelete_course_repos(course_identifier)
            cls.create_course(**course_setup["course"])
            course = Course.objects.get(identifier=course_identifier)
            if "participations" in course_setup:
                for participation in course_setup["participations"]:
                    create_user_kwargs = participation.get("user")
                    if not create_user_kwargs:
                        continue
                    role_identifier = participation.get("role_identifier")
                    if not role_identifier:
                        continue
                    cls.create_participation(
                        course=course,
                        user_or_create_user_kwargs=create_user_kwargs,
                        role_identifier=role_identifier,
                        status=participation.get("status",
                                                 participation_status.active)
                    )

                    # Remove superuser from participation for further test
                    # such as impersonate in auth module
                    if role_identifier == "instructor":
                        try:
                            superuser_participation = (
                                Participation.objects.get(user=cls.superuser))
                            Participation.delete(superuser_participation)
                        except Participation.DoesNotExist:
                            pass
            cls.non_participation_users = get_user_model().objects.none
            if cls.none_participation_user_create_kwarg_list:
                pks = []
                for create_user_kwargs in (
                        cls.none_participation_user_create_kwarg_list):
                    user = cls.create_user(create_user_kwargs)
                    pks.append(user.pk)
                cls.non_participation_users = (
                    get_user_model().objects.filter(pk__in=pks))

        cls.course_qset = Course.objects.all()

    @classmethod
    def remove_exceptionally_undelete_course_repos(cls, course_identifier):
        """
        Remove existing course repo folders resulted in unexpected
        exceptions in previous tests.
        """
        repo_path = os.path.join(settings.GIT_ROOT, course_identifier)
        try:
            force_remove_path(repo_path)
        except OSError:
            if not os.path.isdir(repo_path):
                # The repo path does not exist, that's good!
                return
            raise

    @classmethod
    def remove_course_repo(cls, course):
        from course.content import get_course_repo_path
        repo_path = get_course_repo_path(course)
        force_remove_path(repo_path)

    @classmethod
    def tearDownClass(cls):
        cls.c.logout()
        # Remove repo folder for all courses
        for course in Course.objects.all():
            cls.remove_course_repo(course)
        super(CoursesTestMixinBase, cls).tearDownClass()

    @classmethod
    def create_user(cls, create_user_kwargs):
        user, created = get_user_model().objects.get_or_create(**create_user_kwargs)
        if created:
            try:
                # TODO: why pop failed here?
                password = create_user_kwargs["password"]
            except:
                raise
            user.set_password(password)
            user.save()
        return user

    @classmethod
    def create_participation(
            cls, course, user_or_create_user_kwargs,
            role_identifier=None, status=None):
        if isinstance(user_or_create_user_kwargs, get_user_model()):
            user = user_or_create_user_kwargs
        else:
            assert isinstance(user_or_create_user_kwargs, dict)
            user = cls.create_user(user_or_create_user_kwargs)
        participation, p_created = Participation.objects.get_or_create(
            user=user,
            course=course,
            status=status
        )
        if role_identifier is None:
            role_identifier = "student"
        if status is None:
            status = participation_status.active
        if p_created:
            role = ParticipationRole.objects.filter(
                course=course, identifier=role_identifier)
            participation.roles.set(role)
        return participation

    @classmethod
    def create_course(cls, **create_course_kwargs):
        cls.c.force_login(cls.superuser)
        cls.c.post(reverse("relate-set_up_new_course"), create_course_kwargs)

    @classmethod
    def get_course_page_url(cls, course):
        return reverse("relate-course_page", args=[course.identifier])


class SingleCourseTestMixin(CoursesTestMixinBase):
    courses_setup_list = SINGLE_COURSE_SETUP_LIST

    # This is used when there are some attributes which need to be configured
    # differently from what are in the courses_setup_list
    course_attributes_extra = {}

    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCourseTestMixin, cls).setUpTestData()
        cls.course = cls.course_qset.first()
        cls.instructor_participation = Participation.objects.filter(
            course=cls.course,
            roles__identifier="instructor",
            status=participation_status.active
        ).first()
        assert cls.instructor_participation

        cls.student_participation = Participation.objects.filter(
            course=cls.course,
            roles__identifier="student",
            status=participation_status.active
        ).first()
        assert cls.student_participation

        cls.ta_participation = Participation.objects.filter(
            course=cls.course,
            roles__identifier="ta",
            status=participation_status.active
        ).first()
        assert cls.ta_participation
        cls.c.logout()
        cls.course_page_url = cls.get_course_page_url(cls.course)

        if cls.course_attributes_extra:
            cls._update_course_attribute()

    @classmethod
    def _update_course_attribute(cls):
        # This should be used only in setUpTestData
        attrs = cls.course_attributes_extra
        if attrs:
            assert isinstance(attrs, dict)
            cls.course.__dict__.update(attrs)
            cls.course.save()

    @classmethod
    def tearDownClass(cls):
        super(SingleCourseTestMixin, cls).tearDownClass()


class SingleCoursePageTestMixin(SingleCourseTestMixin):
    @property
    def flow_id(self):
        raise NotImplementedError

    @classmethod
    def start_quiz(cls, flow_id):
        existing_quiz_count = FlowSession.objects.all().count()
        params = {"course_identifier": cls.course.identifier,
                  "flow_id": flow_id}
        resp = cls.c.post(reverse("relate-view_start_flow", kwargs=params))
        assert resp.status_code == 302
        new_quiz_count = FlowSession.objects.all().count()
        assert new_quiz_count == existing_quiz_count + 1

        # Yep, no regax!
        _, _, kwargs = resolve(resp.url)
        # Should be in correct course
        assert kwargs["course_identifier"] == cls.course.identifier
        # Should redirect us to welcome page
        assert int(kwargs["ordinal"]) == 0
        cls.page_params = kwargs

    @classmethod
    def end_quiz(cls):
        from copy import deepcopy
        page_params = deepcopy(cls.page_params)
        del page_params["ordinal"]
        resp = cls.c.post(reverse("relate-finish_flow_session_view",
                                  kwargs=page_params), {'submit': ['']})
        return resp

    @classmethod
    def get_ordinal_via_page_id(cls, page_id):
        from course.models import FlowPageData
        flow_page_data = FlowPageData.objects.get(
            flow_session__id=cls.page_params["flow_session_id"],
            page_id=page_id
        )
        return flow_page_data.ordinal

    @classmethod
    def client_post_answer_by_page_id(cls, page_id, answer_data):
        page_ordinal = cls.get_ordinal_via_page_id(page_id)
        return cls.client_post_answer_by_ordinal(page_ordinal, answer_data)

    @classmethod
    def client_post_answer_by_ordinal(cls, page_ordinal, answer_data):
        from copy import deepcopy
        page_params = deepcopy(cls.page_params)
        page_params.update({"ordinal": str(page_ordinal)})
        submit_data = answer_data
        submit_data.update({"submit": ["Submit final answer"]})
        resp = cls.c.post(
            reverse("relate-view_flow_page", kwargs=page_params),
            submit_data)
        return resp

    def assertSessionScoreEqual(self, expect_score):  # noqa
        from decimal import Decimal
        if expect_score is not None:
            self.assertEqual(FlowSession.objects.all()[0].points,
                                                    Decimal(str(expect_score)))
        else:
            self.assertIsNone(FlowSession.objects.all()[0].points)

    def page_submit_history_url(self, flow_session_id, page_ordinal):
        return reverse("relate-get_prev_answer_visits_dropdown_content",
                       args=[self.course.identifier, flow_session_id, page_ordinal])

    def page_grade_history_url(self, flow_session_id, page_ordinal):
        return reverse("relate-get_prev_grades_dropdown_content",
                       args=[self.course.identifier, flow_session_id, page_ordinal])

    def get_page_submit_history(self, flow_session_id, page_ordinal):
        resp = self.c.get(
            self.page_submit_history_url(flow_session_id, page_ordinal),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        return resp

    def get_page_grade_history(self, flow_session_id, page_ordinal):
        resp = self.c.get(
            self.page_grade_history_url(flow_session_id, page_ordinal),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        return resp

    def assertSubmitHistoryItemsCount(  # noqa
            self, page_ordinal, expected_count, flow_session_id=None):
        if flow_session_id is None:
            flow_session_id = FlowSession.objects.all().last().pk
        resp = self.get_page_submit_history(flow_session_id, page_ordinal)
        import json
        result = json.loads(resp.content.decode())["result"]
        self.assertEqual(len(result), expected_count)

    def assertGradeHistoryItemsCount(  # noqa
            self, page_ordinal, expected_count, flow_session_id=None):
        if flow_session_id is None:
            flow_session_id = FlowSession.objects.all().last().pk
        resp = self.get_page_grade_history(flow_session_id, page_ordinal)
        import json
        result = json.loads(resp.content.decode())["result"]
        self.assertEqual(len(result), expected_count)


class FallBackStorageMessageTestMixin(object):
    # In case other message storage are used, the following is the default
    # storage used by django and RELATE. Tests which concerns the message
    # should not include this mixin.
    storage = 'django.contrib.messages.storage.fallback.FallbackStorage'

    def setUp(self):  # noqa
        self.settings_override = override_settings(MESSAGE_STORAGE=self.storage)
        self.settings_override.enable()

    def tearDown(self):  # noqa
        self.settings_override.disable()

    def get_storage_from_response(self, response):
        return response.context['messages']

    def get_listed_storage_from_response(self, response):
        return list(self.get_storage_from_response(response))

    def clear_message_response_storage(self, response):
        # this should only be used for debug, because we are using private method
        # which might change
        storage = self.get_storage_from_response(response)
        if hasattr(storage, '_loaded_data'):
            storage._loaded_data = []
        elif hasattr(storage, '_loaded_message'):
            storage._loaded_messages = []

        if hasattr(storage, '_queued_messages'):
            storage._queued_messages = []

        self.assertEqual(len(storage), 0)

    def assertResponseMessagesCount(self, response, expected_count):  # noqa
        storage = self.get_listed_storage_from_response(response)
        self.assertEqual(len(storage), expected_count)

    def assertResponseMessagesEqual(self, response, expected_messages):  # noqa
        storage = self.get_listed_storage_from_response(response)
        self.assertEqual([m.message for m in storage], expected_messages)

    def assertResponseMessagesContains(self, response, expected_messages):  # noqa
        storage = self.get_listed_storage_from_response(response)
        if isinstance(expected_messages, str):
            expected_messages = [expected_messages]
        messages = [m.message for m in storage]
        for em in expected_messages:
            self.assertIn(em, messages)

    def assertResponseMessageLevelsEqual(self, response, expected_levels):  # noqa
        storage = self.get_listed_storage_from_response(response)
        self.assertEqual([m.level for m in storage], expected_levels)

    def debug_print_response_messages(self, response):
        """
        For debugging :class:`django.contrib.messages` objects in post response
        :param response: response
        """
        try:
            storage = self.get_listed_storage_from_response(response)
            print("\n-----------message start (%i total)-------------"
                  % len(storage))
            for m in storage:
                print(m.message)
            print("-----------message end-------------\n")
        except KeyError:
            print("\n-------no message----------")
