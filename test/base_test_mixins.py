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
from django.test import Client
from django.urls import reverse, resolve
from django.contrib.auth import get_user_model
from relate.utils import force_remove_path
from course.models import Course, Participation, ParticipationRole, FlowSession
from course.constants import participation_status

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
            "enrollment_required_email_suffix": None,
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
        ]
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
                        create_user_kwargs=create_user_kwargs,
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
    def create_participation(
            cls, course, create_user_kwargs, role_identifier, status):
        user, created = get_user_model().objects.get_or_create(**create_user_kwargs)
        if created:
            try:
                # TODO: why pop failed here?
                password = create_user_kwargs["password"]
            except:
                raise
            user.set_password(password)
            user.save()
        participation, p_created = Participation.objects.get_or_create(
            user=user,
            course=course,
            status=status
        )
        if p_created:
            role = ParticipationRole.objects.filter(
                course=course, identifier=role_identifier)
            participation.roles.set(role)
        return participation

    @classmethod
    def create_course(cls, **create_course_kwargs):
        cls.c.force_login(cls.superuser)
        cls.c.post(reverse("relate-set_up_new_course"), create_course_kwargs)

    def assertMessageContains(self, resp, expected_message):  # noqa
        """
        :param resp: response
        :param expected_message: message string or list containing message string
        """
        if isinstance(expected_message, list):
            self.assertTrue(set(expected_message).issubset(
                set([m.message for m in list(resp.context['messages'])])))
        if isinstance(expected_message, str):
            self.assertIn(expected_message,
                          [m.message for m in list(resp.context['messages'])])

    def debug_print_response_messages(self, resp):
        """
        For debugging :class:`django.contrib.messages` objects in post response
        :param resp: response
        """
        print("\n")
        print("-----------message start-------------")
        for m in list(resp.context['messages']):
            print(m.message)
        print("-----------message end-------------")


class SingleCourseTestMixin(CoursesTestMixinBase):
    courses_setup_list = SINGLE_COURSE_SETUP_LIST

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

    @classmethod
    def tearDownClass(cls):
        super(SingleCourseTestMixin, cls).tearDownClass()


class SingleCoursePageTestMixin(SingleCourseTestMixin):
    @property
    def flow_id(self):
        raise NotImplementedError

    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCoursePageTestMixin, cls).setUpTestData()
        cls.c.force_login(cls.student_participation.user)
        cls.start_quiz(cls.flow_id)

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
        self.assertEqual(FlowSession.objects.all()[0].points,
                                                Decimal(str(expect_score)))
