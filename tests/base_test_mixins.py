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

import sys
import re
import tempfile
import os
import shutil
import hashlib
import datetime
from types import MethodType
from functools import partial

import memcache

from collections import OrderedDict
from copy import deepcopy
from django.test import Client, override_settings, RequestFactory
from django.urls import reverse, resolve
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured

from course.flow import GradeInfo
from course.models import (
    Course, Participation, ParticipationRole, FlowSession, FlowPageData,
    FlowPageVisit, GradingOpportunity)
from course.constants import (
    participation_status, user_status,
    grade_aggregation_strategy as g_strategy,
    flow_permission as fperm)
from course.content import get_course_repo_path, get_repo_blob

from tests.constants import (
    QUIZ_FLOW_ID, TEST_PAGE_TUPLE, FAKED_YAML_PATH, COMMIT_SHA_MAP)
from tests.utils import mock

# {{{ data

CORRECTNESS_ATOL = 1e-05

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
            "git_source": "https://github.com/inducer/relate-sample.git",
            "course_file": "course.yml",
            "events_file": "events.yml",
            "enrollment_approval_required": False,
            "enrollment_required_email_suffix": "",
            "preapproval_require_verified_inst_id": True,
            "from_email": "inform@tiker.net",
            "notify_email": "inform@tiker.net",
            },
        "participations": [
            {
                "role_identifier": "instructor",
                "user": {
                    "username": "test_instructor",
                    "password": "test_instructor",
                    "email": "test_instructor@example.com",
                    "first_name": "Test_ins",
                    "last_name": "Instructor"},
                "status": participation_status.active
            },
            {
                "role_identifier": "ta",
                "user": {
                    "username": "test_ta",
                    "password": "test",
                    "email": "test_ta@example.com",
                    "first_name": "Test_ta",
                    "last_name": "TA"},
                "status": participation_status.active
            },
            {
                "role_identifier": "student",
                "user": {
                    "username": "test_student",
                    "password": "test",
                    "email": "test_student@example.com",
                    "first_name": "Test_stu",
                    "last_name": "Student"},
                "status": participation_status.active
            }
        ],
    }
]

TWO_COURSE_SETUP_LIST = deepcopy(SINGLE_COURSE_SETUP_LIST)
TWO_COURSE_SETUP_LIST[0]["course"]["identifier"] = "test-course1"
TWO_COURSE_SETUP_LIST += deepcopy(SINGLE_COURSE_SETUP_LIST)
TWO_COURSE_SETUP_LIST[1]["course"]["identifier"] = "test-course2"

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

try:
    mc = memcache.Client(["127.0.0.1:11211"])
except Exception:
    pass


SELECT2_HTML_FIELD_ID_SEARCH_PATTERN = re.compile(r'data-field_id="([^"]+)"')

# }}}


def git_source_url_to_cache_keys(url):
    url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
    return (
        "test_course:%s" % url_hash,
        "test_sha:%s" % url_hash
    )


class CourseCreateFailure(Exception):
    pass


class classmethod_with_client:  # noqa: N801
    """This acts like Python's built-in ``classmethod``, with one change:
    When called on an instance (i.e. not a class), it automatically supplies
    ``self.client`` as the first argument.

    .. note::

        This isn't immensely logical, but it helped avoid an expensive
        refactor of the test code to explicitly always pass the client.
        (The prior state was much worse: a class-global client was being
        used. Almost fortunately, this Django 3.2 broke this usage.)
    """

    def __init__(self, f):
        self.f = f

    def __get__(self, obj, cls=None):
        if obj is None:
            return MethodType(self.f, cls)
        else:
            return partial(MethodType(self.f, type(obj)), obj.client)


# {{{ ResponseContextMixin

class ResponseContextMixin:
    """
    Response context refers to "the template Context instance that was used
    to render the template that produced the response content".
    Ref: https://docs.djangoproject.com/en/dev/topics/testing/tools/#django.test.Response.context  # noqa
    """
    def get_response_context_value_by_name(self, response, context_name):
        try:
            value = response.context[context_name]
        except KeyError:
            self.fail("%s does not exist in given response" % context_name)
        else:
            return value

    def assertResponseHasNoContext(self, response, context_name):  # noqa
        has_context = True
        try:
            response.context[context_name]
        except KeyError:
            has_context = False
        if has_context:
            self.fail("%s unexpectedly exist in given response" % context_name)

    def assertResponseContextIsNone(self, resp, context_name):  # noqa
        try:
            value = self.get_response_context_value_by_name(resp, context_name)
        except AssertionError:
            # the context item doesn't exist
            pass
        else:
            self.assertIsNone(value)

    def assertResponseContextIsNotNone(self, resp, context_name, msg=""):  # noqa
        value = self.get_response_context_value_by_name(resp, context_name)
        self.assertIsNotNone(value, msg)

    def assertResponseContextEqual(self, resp, context_name, expected_value):  # noqa
        value = self.get_response_context_value_by_name(resp, context_name)
        try:
            self.assertTrue(float(value) - float(expected_value) <= 1e-04)
            return
        except Exception:
            self.assertEqual(value, expected_value)

    def assertResponseContextContains(self, resp,  # noqa
                                      context_name, expected_value, html=False,
                                      in_bulk=False):
        value = self.get_response_context_value_by_name(resp, context_name)
        if in_bulk:
            if not isinstance(expected_value, list):
                expected_value = [expected_value]

            for v in expected_value:
                if not html:
                    self.assertIn(v, value)
                else:
                    self.assertInHTML(v, value)
        else:
            if not html:
                self.assertIn(expected_value, value)
            else:
                self.assertInHTML(expected_value, value)

    def assertResponseContextRegex(  # noqa
            self, resp,  # noqa
            context_name, expected_value_regex):
        value = self.get_response_context_value_by_name(resp, context_name)
        self.assertRegex(value, expected_value_regex)

    def get_response_context_answer_feedback(self, response):
        return self.get_response_context_value_by_name(response, "feedback")

    def get_response_context_answer_feedback_string(self, response,
                                             include_bulk_feedback=True):
        answer_feedback = self.get_response_context_value_by_name(
            response, "feedback")

        self.assertTrue(hasattr(answer_feedback, "feedback"))
        if not include_bulk_feedback:
            return answer_feedback.feedback

        if answer_feedback.bulk_feedback is None:
            return answer_feedback.feedback
        else:
            if answer_feedback.feedback is None:
                return answer_feedback.bulk_feedback
            return answer_feedback.feedback + answer_feedback.bulk_feedback

    def assertResponseContextAnswerFeedbackContainsFeedback(  # noqa
            self, response, expected_feedback,
            include_bulk_feedback=True, html=False):
        feedback_str = self.get_response_context_answer_feedback_string(
            response, include_bulk_feedback)

        if not html:
            self.assertIn(expected_feedback, feedback_str)
        else:
            self.assertInHTML(expected_feedback, feedback_str)

    def assertResponseContextAnswerFeedbackNotContainsFeedback(  # noqa
            self, response, expected_feedback,
            include_bulk_feedback=True,
            html=False):
        feedback_str = self.get_response_context_answer_feedback_string(
            response, include_bulk_feedback)

        if not html:
            self.assertNotIn(expected_feedback, feedback_str)
        else:
            self.assertInHTML(expected_feedback, feedback_str, count=0)

    def assertResponseContextAnswerFeedbackCorrectnessEquals(  # noqa
                                        self, response, expected_correctness):
        answer_feedback = self.get_response_context_answer_feedback(response)
        if expected_correctness is None:
            try:
                self.assertTrue(hasattr(answer_feedback, "correctness"))
            except AssertionError:
                pass
            else:
                self.assertIsNone(answer_feedback.correctness)
        else:
            if answer_feedback.correctness is None:
                return self.fail("The returned correctness is None, not %s"
                          % expected_correctness)
            self.assertTrue(
                abs(float(answer_feedback.correctness)
                    - float(str(expected_correctness))) < CORRECTNESS_ATOL,
                "%s does not equal %s"
                % (str(answer_feedback.correctness)[:5],
                   str(expected_correctness)[:5]))

    def get_response_body(self, response):
        return self.get_response_context_value_by_name(response, "body")

    def get_page_response_correct_answer(self, response):
        return self.get_response_context_value_by_name(response, "correct_answer")

    def get_page_response_feedback(self, response):
        return self.get_response_context_value_by_name(response, "feedback")

    def debug_print_response_context_value(self, resp, context_name):
        try:
            value = self.get_response_context_value_by_name(resp, context_name)
            print("\n-----------context %s-------------"
                  % context_name)
            if isinstance(value, (list, tuple)):
                from course.validation import ValidationWarning
                for v in value:
                    if isinstance(v, ValidationWarning):
                        print(v.text)
                    else:
                        print(repr(v))
            else:
                print(value)
            print("-----------context end-------------\n")
        except AssertionError:
            print("\n-------no value for context %s----------" % context_name)

    def get_select2_field_id_from_response(self, response,
                                           form_context_name="form"):
        self.assertResponseContextIsNotNone(
            response, form_context_name,
            "The response doesn't contain a context named '%s'"
            % form_context_name)
        form_str = str(response.context[form_context_name])
        m = SELECT2_HTML_FIELD_ID_SEARCH_PATTERN.search(form_str)
        assert m, "pattern not found in %s" % form_str
        return m.group(1)

    def select2_get_request(self, field_id, term=None,
                            select2_urlname="django_select2:auto-json"):

        select2_url = reverse(select2_urlname)
        params = {"field_id": field_id}
        if term is not None:
            assert isinstance(term, str)
            term = term.strip()
            if term:
                params["term"] = term

        return self.client.get(select2_url, params,
                          HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def get_select2_response_data(self, response, key="results"):
        import json
        return json.loads(response.content.decode("utf-8"))[key]


class SuperuserCreateMixin(ResponseContextMixin):
    create_superuser_kwargs = CREATE_SUPERUSER_KWARGS

    @classmethod
    def setUpTestData(cls):  # noqa
        # Create superuser, without this, we cannot
        # create user, course and participation.
        cls.superuser = cls.create_superuser()
        cls.settings_git_root_override = (
            override_settings(GIT_ROOT=tempfile.mkdtemp()))
        cls.settings_git_root_override.enable()
        super().setUpTestData()

    @classmethod
    def add_user_permission(cls, user, perm, model=Course):
        from django.contrib.contenttypes.models import ContentType
        content_type = ContentType.objects.get_for_model(model)
        from django.contrib.auth.models import Permission
        permission = Permission.objects.get(
            codename=perm, content_type=content_type)
        user.user_permissions.add(permission)

    @classmethod
    def create_superuser(cls):
        return get_user_model().objects.create_superuser(
            **cls.create_superuser_kwargs)

    @classmethod
    def get_sign_up_view_url(cls):
        return reverse("relate-sign_up")

    @classmethod_with_client
    def get_sign_up(cls, client, *, follow=True):  # noqa: N805
        return client.get(cls.get_sign_up_view_url(), follow=follow)

    @classmethod_with_client
    def post_sign_up(cls, client, data, *, follow=True):  # noqa: N805
        return client.post(cls.get_sign_up_view_url(), data, follow=follow)

    @classmethod
    def get_profile_view_url(cls):
        return reverse("relate-user_profile")

    @classmethod_with_client
    def get_profile(cls, client, *, follow=True):  # noqa: N805
        return client.get(cls.get_profile_view_url(), follow=follow)

    @classmethod_with_client
    def post_profile(cls, client, data, *, follow=True):  # noqa: N805
        data.update({"submit_user": [""]})
        return client.post(cls.get_profile_view_url(), data, follow=follow)

    @classmethod
    def post_signout(cls, client, data, *, follow=True):
        return client.post(cls.get_sign_up_view_url(), data, follow=follow)

    @classmethod
    def get_impersonate_view_url(cls):
        return reverse("relate-impersonate")

    @classmethod
    def get_stop_impersonate_view_url(cls):
        return reverse("relate-stop_impersonating")

    @classmethod_with_client
    def get_impersonate_view(cls, client):  # noqa: N805
        return client.get(cls.get_impersonate_view_url())

    @classmethod_with_client
    def post_impersonate_view(cls, client,  # noqa: N805
            impersonatee, *, follow=True):
        data = {"add_impersonation_header": ["on"],
                "submit": [""],
                }
        data["user"] = [str(impersonatee.pk)]
        return client.post(cls.get_impersonate_view_url(), data, follow=follow)

    @classmethod_with_client
    def get_stop_impersonate(cls, client, *, follow=True):  # noqa: N805
        return client.get(cls.get_stop_impersonate_view_url(), follow=follow)

    @classmethod_with_client
    def post_stop_impersonate(cls, client, *,  # noqa: N805
            data=None, follow=True):
        if not data:
            data = {"stop_impersonating": ""}
        return client.post(
            cls.get_stop_impersonate_view_url(), data, follow=follow)

    @classmethod
    def get_confirm_stop_impersonate_view_url(cls):
        return reverse("relate-confirm_stop_impersonating")

    @classmethod
    def get_confirm_stop_impersonate(cls, client, *, follow=True):
        return client.get(
            cls.get_confirm_stop_impersonate_view_url(), follow=follow)

    @classmethod
    def post_confirm_stop_impersonate(cls, client, *, follow=True):
        return client.post(
            cls.get_confirm_stop_impersonate_view_url(), {}, follow=follow)

    @classmethod
    def get_reset_password_url(cls, use_instid=False):
        kwargs = {}
        if use_instid:
            kwargs["field"] = "instid"
        return reverse("relate-reset_password", kwargs=kwargs)

    @classmethod_with_client
    def get_reset_password(cls, client, *, use_instid=False):  # noqa: N805
        return client.get(cls.get_reset_password_url(use_instid))

    @classmethod_with_client
    def post_reset_password(cls, client, data, *, use_instid=False):  # noqa: N805
        return client.post(cls.get_reset_password_url(use_instid),
                          data=data)

    def get_reset_password_stage2_url(self, user_id, sign_in_key, **kwargs):
        url = reverse("relate-reset_password_stage2", args=(user_id, sign_in_key))
        querystring = kwargs.pop("querystring", None)
        if querystring is not None:
            assert isinstance(querystring, dict)
            url += ("?%s"
                    % "&".join(
                        [f"{k}={v}"
                         for (k, v) in querystring.items()]))
        return url

    def get_reset_password_stage2(self, user_id, sign_in_key, **kwargs):
        return self.client.get(self.get_reset_password_stage2_url(
            user_id=user_id, sign_in_key=sign_in_key, **kwargs))

    def post_reset_password_stage2(self, user_id, sign_in_key, data, **kwargs):
        return self.client.post(self.get_reset_password_stage2_url(
            user_id=user_id, sign_in_key=sign_in_key, **kwargs), data=data)

    @classmethod
    def get_fake_time_url(cls):
        return reverse("relate-set_fake_time")

    @classmethod_with_client
    def get_set_fake_time(cls, client):  # noqa: N805
        return client.get(cls.get_fake_time_url())

    @classmethod_with_client
    def post_set_fake_time(cls, client, data, *, follow=True):  # noqa: N805
        return client.post(cls.get_fake_time_url(), data, follow=follow)

    def assertSessionFakeTimeEqual(self, session, expected_date_time):  # noqa
        fake_time_timestamp = session.get("relate_fake_time", None)
        if fake_time_timestamp is None:
            faked_time = None
            if expected_date_time is not None:
                raise AssertionError(
                    "the session doesn't have 'relate_fake_time' attribute")
        else:
            faked_time = datetime.datetime.fromtimestamp(fake_time_timestamp)
        self.assertEqual(faked_time, expected_date_time)

    def assertSessionFakeTimeIsNone(self, session):  # noqa
        self.assertSessionFakeTimeEqual(session, None)

    @classmethod
    def get_set_pretend_facilities_url(cls):
        return reverse("relate-set_pretend_facilities")

    @classmethod_with_client
    def get_set_pretend_facilities(cls, client):  # noqa: N805
        return client.get(cls.get_set_pretend_facilities_url())

    @classmethod_with_client
    def post_set_pretend_facilities(cls, client, data, *,  # noqa: N805
            follow=True):
        return client.post(cls.get_set_pretend_facilities_url(), data,
                          follow=follow)

    @classmethod
    def force_remove_all_course_dir(cls):
        # This is only necessary for courses which are created test wise,
        # not class wise.
        from relate.utils import force_remove_path
        from course.content import get_course_repo_path
        for c in Course.objects.all():
            force_remove_path(get_course_repo_path(c))

    def assertSessionPretendFacilitiesContains(self, session, expected_facilities):  # noqa
        pretended = session.get("relate_pretend_facilities", None)
        if expected_facilities is None:
            return self.assertIsNone(pretended)
        if pretended is None:
            raise AssertionError(
                "the session doesn't have "
                "'relate_pretend_facilities' attribute")

        if isinstance(expected_facilities, (list, tuple)):
            self.assertTrue(set(expected_facilities).issubset(set(pretended)))
        else:
            self.assertTrue(expected_facilities in pretended)

    def assertSessionPretendFacilitiesIsNone(self, session):  # noqa
        pretended = session.get("relate_pretend_facilities", None)
        self.assertIsNone(pretended)

    def assertFormErrorLoose(self, response, errors, form_name="form"):  # noqa
        """Assert that errors is found in response.context['form'] errors"""
        import itertools
        if errors is None:
            errors = []
        if not isinstance(errors, (list, tuple)):
            errors = [errors]
        try:
            form_errors = ". ".join(list(
                itertools.chain(*response.context[form_name].errors.values())))
        except TypeError:
            form_errors = None

        if form_errors is None or not form_errors:
            if errors:
                self.fail("%s has no error" % form_name)
            else:
                return

        if form_errors:
            if not errors:
                self.fail("%s unexpectedly has following errors: %s"
                          % (form_name, repr(form_errors)))

        for err in errors:
            self.assertIn(err, form_errors)

# }}}


# {{{ get_flow_page_ordinal_from_page_id, get_flow_page_id_from_page_ordinal

def get_flow_page_ordinal_from_page_id(flow_session_id, page_id,
                                       with_group_id=False):
    flow_page_data = FlowPageData.objects.get(
        flow_session__id=flow_session_id,
        page_id=page_id
    )
    if with_group_id:
        return flow_page_data.page_ordinal, flow_page_data.group_id
    return flow_page_data.page_ordinal


def get_flow_page_id_from_page_ordinal(flow_session_id, page_ordinal,
                                       with_group_id=False):
    flow_page_data = FlowPageData.objects.get(
        flow_session__id=flow_session_id,
        page_ordinal=page_ordinal
    )
    if with_group_id:
        return flow_page_data.page_id, flow_page_data.group_id
    return flow_page_data.page_id

# }}}


# {{{ CoursesTestMixinBase

class _ClientUserSwitcher:
    def __init__(self, client, logged_in_user, switch_to):
        self.client = client
        self.logged_in_user = logged_in_user
        self.switch_to = switch_to

    def __enter__(self):
        if self.logged_in_user == self.switch_to:
            return
        if self.switch_to is None:
            self.client.logout()
            return
        self.client.force_login(self.switch_to)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.logged_in_user == self.switch_to:
            return
        if self.logged_in_user is None:
            self.client.logout()
            return
        self.client.force_login(self.logged_in_user)

    def __call__(self, func):
        from functools import wraps

        @wraps(func)
        def wrapper(*args, **kw):
            with self:
                return func(*args, **kw)
        return wrapper


class CoursesTestMixinBase(SuperuserCreateMixin):

    # A list of Dicts, each of which contain a course dict and a list of
    # participations. See SINGLE_COURSE_SETUP_LIST for the setup for one course.
    courses_setup_list = []
    none_participation_user_create_kwarg_list = []
    courses_attributes_extra_list = None
    override_settings_at_post_create_course = {}

    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()

        client = Client()
        client.force_login(cls.superuser)
        cls.default_flow_params = None
        cls.n_courses = 0
        if cls.courses_attributes_extra_list is not None:
            if (len(cls.courses_attributes_extra_list)
                    != len(cls.courses_setup_list)):
                raise ValueError(
                    "'courses_attributes_extra_list' must has equal length "
                    "with courses")

        for i, course_setup in enumerate(cls.courses_setup_list):
            if "course" not in course_setup:
                continue

            cls.n_courses += 1
            course_identifier = course_setup["course"]["identifier"]
            course_setup_kwargs = course_setup["course"]
            if cls.courses_attributes_extra_list:
                extra_attrs = cls.courses_attributes_extra_list[i]
                assert isinstance(extra_attrs, dict)
                course_setup_kwargs.update(extra_attrs)

            cls.create_course(client, course_setup_kwargs)

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
            try:
                superuser_participations = (
                    Participation.objects.filter(user=cls.superuser))
                for sp in superuser_participations:
                    Participation.delete(sp)
            except Participation.DoesNotExist:
                pass

            cls.non_participation_users = get_user_model().objects.none()
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
    def create_user(cls, create_user_kwargs):
        user, created = get_user_model().objects.get_or_create(
            email__iexact=create_user_kwargs["email"], defaults=create_user_kwargs)
        if created:
            try:
                # TODO: why pop failed here?
                password = create_user_kwargs["password"]
            except Exception:
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
        if status is None:
            status = participation_status.active
        participation, p_created = Participation.objects.get_or_create(
            user=user,
            course=course,
            status=status
        )
        if role_identifier is None:
            role_identifier = "student"
        if p_created:
            role = ParticipationRole.objects.filter(
                course=course, identifier=role_identifier)
            participation.roles.set(role)
        return participation

    @classmethod_with_client
    def post_create_course(cls, client, create_course_kwargs, *,  # noqa: N805
            raise_error=True, login_superuser=True):
        # To speed up, use create_course instead, this is better used for tests
        if login_superuser:
            client.force_login(cls.superuser)
        existing_course_count = Course.objects.count()
        with override_settings(**cls.override_settings_at_post_create_course):
            resp = client.post(cls.get_set_up_new_course_url(),
                              data=create_course_kwargs)
        if raise_error:
            all_courses = Course.objects.all()
            if not all_courses.count() == existing_course_count + 1:
                error_string = None
                # most probably the reason course creation form error
                form_context = resp.context.__getitem__("form")
                assert form_context
                error_list = []
                if form_context.errors:
                    error_list = [
                        "%s: %s"
                        % (field,
                           "\n".join(["{}:{}".format(type(e).__name__, str(e))
                                      for e in errs]))
                        for field, errs
                        in form_context.errors.as_data().items()]
                non_field_errors = form_context.non_field_errors()
                if non_field_errors:
                    error_list.append(repr(non_field_errors))
                if error_list:
                    error_string = "\n".join(error_list)
                if not error_string:
                    error_string = ("course creation failed for unknown errors")
                raise CourseCreateFailure(error_string)
            # the course is created successfully
            last_course = all_courses.last()
            assert last_course
            if "trusted_for_markup" in create_course_kwargs:
                # This attribute is not settable via POST by the user, so set it
                # manually here.
                last_course.trusted_for_markup = \
                        create_course_kwargs["trusted_for_markup"]
                last_course.save()

            url_cache_key, commit_sha_cach_key = (
                git_source_url_to_cache_keys(last_course.git_source))
            mc.set_multi({url_cache_key: get_course_repo_path(last_course),
                          commit_sha_cach_key: last_course.active_git_commit_sha},
                         time=120000
                         )
        return resp

    @classmethod_with_client
    def create_course(cls, client, create_course_kwargs, *,  # noqa: N805
            raise_error=True):
        has_cached_repo = False
        repo_cache_key, commit_sha_cach_key = (
            git_source_url_to_cache_keys(create_course_kwargs["git_source"]))
        try:
            exist_course_repo_path = mc.get(repo_cache_key)
            exist_commit_sha = mc.get(commit_sha_cach_key)
            if os.path.isdir(exist_course_repo_path):
                has_cached_repo = bool(exist_course_repo_path and exist_commit_sha)
            else:
                has_cached_repo = False
        except Exception:
            pass

        if not has_cached_repo:
            # fall back to post create
            return cls.post_create_course(
                    client, create_course_kwargs, raise_error=raise_error)
        existing_course_count = Course.objects.count()
        new_course_repo_path = os.path.join(settings.GIT_ROOT,
                                        create_course_kwargs["identifier"])
        shutil.copytree(exist_course_repo_path, new_course_repo_path)
        create_kwargs = deepcopy(create_course_kwargs)
        create_kwargs["active_git_commit_sha"] = exist_commit_sha
        Course.objects.create(**create_kwargs)
        assert Course.objects.count() == existing_course_count + 1

    @classmethod
    def get_course_view_url(cls, view_name, course_identifier=None):
        course_identifier = (
            course_identifier or cls.get_default_course_identifier())
        return reverse(view_name, args=[course_identifier])

    @classmethod
    def get_course_calender_url(cls, course_identifier=None):
        return cls.get_course_view_url(
            "relate-view_calendar", course_identifier)

    @classmethod
    def get_set_up_new_course_url(cls):
        return reverse("relate-set_up_new_course")

    @classmethod_with_client
    def get_set_up_new_course(cls, client):  # noqa: N805
        return client.get(cls.get_update_course_url)

    @classmethod
    def get_edit_course_url(cls, course_identifier=None):  # noqa: N805
        course_identifier = (
            course_identifier or cls.get_default_course_identifier())
        return cls.get_course_view_url("relate-edit_course", course_identifier)

    @classmethod_with_client
    def post_edit_course(cls, client, data, *, course=None):  # noqa: N805
        course = course or cls.get_default_course()
        edit_course_url = cls.get_edit_course_url(course.identifier)
        return client.post(edit_course_url, data)

    @classmethod_with_client
    def get_edit_course(cls, client, *, course=None):  # noqa: N805
        course = course or cls.get_default_course()
        return client.get(cls.get_edit_course_url(course.identifier))

    @classmethod
    def get_course_page_url(cls, course_identifier=None):
        return cls.get_course_view_url("relate-course_page", course_identifier)

    @classmethod
    def get_finish_flow_session_view_url(cls, course_identifier=None,
                                         flow_session_id=None):
        course_identifier = (
            course_identifier or cls.get_default_course_identifier())
        if flow_session_id is None:
            flow_session_id = cls.get_default_flow_session_id(course_identifier)

        kwargs = {"course_identifier": course_identifier,
                  "flow_session_id": flow_session_id}
        return reverse("relate-finish_flow_session_view", kwargs=kwargs)

    @classmethod
    def _get_grades_url(cls, args=None, kwargs=None):
        return reverse("relate-view_participant_grades",
                       args=args, kwargs=kwargs)

    @classmethod
    def get_my_grades_url(cls, course_identifier=None):
        course_identifier = (
            course_identifier or cls.get_default_course_identifier())
        return cls._get_grades_url(args=[course_identifier])

    @classmethod_with_client
    def get_my_grades_view(cls, client, *, course_identifier=None):  # noqa: N805
        return client.get(cls.get_my_grades_url(course_identifier))

    @classmethod
    def get_participant_grades_url(cls, participation_id, course_identifier=None):
        course_identifier = (
            course_identifier or cls.get_default_course_identifier())
        return cls._get_grades_url(
            kwargs={"course_identifier": course_identifier,
                    "participation_id": participation_id})

    @classmethod_with_client
    def get_participant_grades_view(
            cls, client, participation_id, *,  # noqa: N805
            course_identifier=None, force_login_instructor=True):
        course_identifier = (
            course_identifier or cls.get_default_course_identifier())
        if force_login_instructor:
            switch_to = cls.get_default_instructor_user(course_identifier)
        else:
            switch_to = cls.get_logged_in_user()

        with cls.temporarily_switch_to_user(switch_to):
            return client.get(
                cls.get_participant_grades_url(participation_id, course_identifier))

    @classmethod
    def get_gradebook_url_by_opp_id(cls, opp_id, course_identifier=None):
        course_identifier = (
            course_identifier or cls.get_default_course_identifier())

        kwargs = {"course_identifier": course_identifier,
                  "opp_id": opp_id}
        return reverse("relate-view_grades_by_opportunity",
                                  kwargs=kwargs)

    def view_participant_grades_url(self, participation_id, course_identifier=None):
        course_identifier = (
            course_identifier or self.get_default_course_identifier())
        kwargs = {"course_identifier": course_identifier}

        if participation_id is not None:
            kwargs["participation_id"] = participation_id

        return reverse("relate-view_participant_grades", kwargs=kwargs)

    def get_view_participant_grades(self, participation_id, course_identifier=None):
        return self.client.get(self.view_participant_grades_url(
            participation_id, course_identifier))

    def get_view_my_grades(self, course_identifier=None):
        return self.client.get(self.view_participant_grades_url(
            participation_id=None, course_identifier=course_identifier))

    @classmethod
    def get_gradebook_by_opp_url(
            cls, gopp_identifier, view_page_grades=False, course_identifier=None):
        course_identifier = (
            course_identifier or cls.get_default_course_identifier())

        opp_id = GradingOpportunity.objects.get(
            course__identifier=course_identifier,
            identifier=gopp_identifier).pk

        url = cls.get_gradebook_url_by_opp_id(opp_id, course_identifier)

        if view_page_grades:
            url += "?view_page_grades=1"
        return url

    @classmethod_with_client
    def get_gradebook_by_opp_view(
            cls, client, gopp_identifier, *,  # noqa: N805
            view_page_grades=False, course_identifier=None,
            force_login_instructor=True):
        course_identifier = (
            course_identifier or cls.get_default_course_identifier())
        if force_login_instructor:
            switch_to = cls.get_default_instructor_user(course_identifier)
        else:
            switch_to = cls.get_logged_in_user(client)

        with cls.temporarily_switch_to_user(client, switch_to):
            return client.get(cls.get_gradebook_by_opp_url(
                gopp_identifier, view_page_grades, course_identifier))

    @classmethod_with_client
    def post_gradebook_by_opp_view(
            cls, client, gopp_identifier, post_data, *,  # noqa: N805
            view_page_grades=False,
            course_identifier=None,
            force_login_instructor=True):
        course_identifier = (
            course_identifier or cls.get_default_course_identifier())
        if force_login_instructor:
            switch_to = cls.get_default_instructor_user(course_identifier)
        else:
            switch_to = cls.get_logged_in_user(client)

        with cls.temporarily_switch_to_user(client, switch_to):
            return client.post(
                cls.get_gradebook_by_opp_url(
                    gopp_identifier, view_page_grades, course_identifier),
                data=post_data)

    @classmethod
    def get_reopen_session_url(cls, gopp_identifier, flow_session_id=None,
                               course_identifier=None):

        course_identifier = (
                course_identifier or cls.get_default_course_identifier())

        opp_id = GradingOpportunity.objects.get(
            course__identifier=course_identifier,
            identifier=gopp_identifier).pk

        if flow_session_id is None:
            flow_session_id = cls.get_default_flow_session_id(course_identifier)

        kwargs = {"course_identifier": course_identifier,
                  "opportunity_id": opp_id,
                  "flow_session_id": flow_session_id}
        return reverse("relate-view_reopen_session", kwargs=kwargs)

    @classmethod_with_client
    def get_reopen_session_view(cls, client,  # noqa: N805
            gopp_identifier, *, flow_session_id=None,
            course_identifier=None, force_login_instructor=True):

        course_identifier = (
                course_identifier or cls.get_default_course_identifier())
        if force_login_instructor:
            switch_to = cls.get_default_instructor_user(course_identifier)
        else:
            switch_to = cls.get_logged_in_user()

        with cls.temporarily_switch_to_user(client, switch_to):
            return client.get(
                cls.get_reopen_session_url(
                    gopp_identifier, flow_session_id, course_identifier))

    @classmethod_with_client
    def post_reopen_session_view(cls, client,  # noqa: N805
            gopp_identifier, data, *,
            flow_session_id=None, course_identifier=None,
            force_login_instructor=True):

        course_identifier = (
                course_identifier or cls.get_default_course_identifier())
        if force_login_instructor:
            switch_to = cls.get_default_instructor_user(course_identifier)
        else:
            switch_to = cls.get_logged_in_user()

        with cls.temporarily_switch_to_user(client, switch_to):
            return client.post(
                cls.get_reopen_session_url(
                    gopp_identifier, flow_session_id, course_identifier), data=data)

    @classmethod
    def get_single_grade_url(cls, participation_id, opp_id,
                             course_identifier=None):

        course_identifier = (
            course_identifier or cls.get_default_course_identifier())

        kwargs = {"course_identifier": course_identifier,
                  "opportunity_id": opp_id,
                  "participation_id": participation_id}

        return reverse("relate-view_single_grade", kwargs=kwargs)

    @classmethod_with_client
    def get_view_single_grade(cls, client,  # noqa: N805
            participation, gopp, *,
            course_identifier=None, force_login_instructor=True):

        course_identifier = (
                course_identifier or cls.get_default_course_identifier())

        opp_id = GradingOpportunity.objects.get(
            course__identifier=course_identifier,
            identifier=gopp.identifier).pk

        if force_login_instructor:
            switch_to = cls.get_default_instructor_user(course_identifier)
        else:
            switch_to = cls.get_logged_in_user(client)

        with cls.temporarily_switch_to_user(client, switch_to):
            return client.get(cls.get_single_grade_url(
                participation.pk, opp_id, course_identifier))

    @classmethod_with_client
    def post_view_single_grade(cls, client,  # noqa: N805
            participation, gopp, data, *,
            course_identifier=None, force_login_instructor=True):

        course_identifier = (
                course_identifier or cls.get_default_course_identifier())

        opp_id = GradingOpportunity.objects.get(
            course__identifier=course_identifier,
            identifier=gopp.identifier).pk

        if force_login_instructor:
            switch_to = cls.get_default_instructor_user(course_identifier)
        else:
            switch_to = cls.get_logged_in_user(client)

        with cls.temporarily_switch_to_user(client, switch_to):
            return client.post(cls.get_single_grade_url(
                participation.pk, opp_id, course_identifier),
                data=data)

    @classmethod_with_client
    def get_logged_in_user(cls, client):  # noqa: N805
        try:
            logged_in_user_id = client.session["_auth_user_id"]
            from django.contrib.auth import get_user_model
            logged_in_user = get_user_model().objects.get(
                pk=int(logged_in_user_id))
        except KeyError:
            logged_in_user = None
        return logged_in_user

    @classmethod_with_client
    def temporarily_switch_to_user(cls, client, switch_to):  # noqa: N805
        return _ClientUserSwitcher(
                client, cls.get_logged_in_user(client), switch_to)

    @classmethod
    def get_default_course(cls):
        if Course.objects.count() > 1:
            raise AttributeError(
                "'course' arg can not be omitted for "
                "testcases with more than one courses")
        raise NotImplementedError

    @classmethod
    def get_default_course_identifier(cls):
        if Course.objects.count() > 1:
            raise AttributeError(
                "'course_identifier' arg can not be omitted for "
                "testcases with more than one courses")
        raise NotImplementedError

    @classmethod
    def get_latest_session_id(cls, course_identifier):
        flow_session_qset = FlowSession.objects.filter(
            course__identifier=course_identifier).order_by("-pk")[:1]
        if flow_session_qset:
            return flow_session_qset[0].id
        else:
            return None

    @classmethod
    def get_default_flow_session_id(cls, course_identifier):
        raise NotImplementedError

    @classmethod
    def update_default_flow_session_id(cls, course_identifier):
        raise NotImplementedError

    @classmethod
    def get_default_instructor_user(cls, course_identifier):
        return Participation.objects.filter(
            course__identifier=course_identifier,
            roles__identifier="instructor",
            status=participation_status.active
        ).first().user

    @classmethod
    def update_course_attribute(cls, attrs, course=None):
        # course instead of course_identifier because we need to do
        # refresh_from_db
        assert isinstance(attrs, dict)
        course = course or cls.get_default_course()
        if attrs:
            course.__dict__.update(attrs)
            course.save()
            course.refresh_from_db()

    @classmethod
    def get_view_start_flow_url(cls, flow_id, course_identifier=None):
        course_identifier = course_identifier or cls.get_default_course_identifier()
        kwargs = {"course_identifier": course_identifier,
                  "flow_id": flow_id}
        return reverse("relate-view_start_flow", kwargs=kwargs)

    @classmethod_with_client
    def start_flow(cls, client, flow_id, *,  # noqa: N805
            course_identifier=None,
            ignore_cool_down=True, assume_success=True):
        """
        Notice: be cautious to use this in setUpTestData, because this will
        create many related objects in db, if those objects are changed in
        individual test, other tests followed might fail.
        """
        existing_session_count = FlowSession.objects.all().count()
        if ignore_cool_down:
            cool_down_seconds = 0
        else:
            cool_down_seconds = settings.RELATE_SESSION_RESTART_COOLDOWN_SECONDS
        with override_settings(
                RELATE_SESSION_RESTART_COOLDOWN_SECONDS=cool_down_seconds):
            resp = client.post(
                cls.get_view_start_flow_url(flow_id, course_identifier))

        if assume_success:
            assert resp.status_code == 302, resp.content
            new_session_count = FlowSession.objects.all().count()
            assert new_session_count == existing_session_count + 1
            _, _, params = resolve(resp.url)
            del params["page_ordinal"]
            cls.default_flow_params = params
            cls.update_default_flow_session_id(course_identifier)

        return resp

    @classmethod_with_client
    def end_flow(cls, client, *,  # noqa: N805
            course_identifier=None, flow_session_id=None,
            post_parameter="submit"):
        if not course_identifier or not flow_session_id:
            if cls.default_flow_params is None:
                raise RuntimeError(
                    "There's no started flow_sessions, or "
                    "the session is not started by start_flow")
        resp = client.post(
            cls.get_finish_flow_session_view_url(
                course_identifier, flow_session_id),
            data={post_parameter: [""]})
        return resp

    @classmethod
    def get_resume_flow_url(cls, course_identifier=None, flow_session_id=None):
        flow_params = cls.get_flow_params(course_identifier, flow_session_id)
        return reverse("relate-view_resume_flow", kwargs=flow_params)

    @classmethod
    def get_flow_params(cls, course_identifier=None, flow_session_id=None):
        course_identifier = (
                course_identifier or cls.get_default_course_identifier())
        if flow_session_id is None:
            flow_session_id = cls.get_default_flow_session_id(course_identifier)
        return {
            "course_identifier": course_identifier,
            "flow_session_id": flow_session_id
        }

    @classmethod
    def get_page_params(cls, course_identifier=None, flow_session_id=None,
                        page_ordinal=None):
        page_params = cls.get_flow_params(course_identifier, flow_session_id)
        if page_ordinal is None:
            page_ordinal = 0
        page_params.update({"page_ordinal": page_ordinal})
        return page_params

    @classmethod
    def get_page_ordinal_via_page_id(
            cls, page_id, course_identifier=None, flow_session_id=None,
            with_group_id=False):
        flow_params = cls.get_flow_params(course_identifier, flow_session_id)
        return (
            get_flow_page_ordinal_from_page_id(
                flow_params["flow_session_id"], page_id,
                with_group_id=with_group_id))

    @classmethod
    def get_page_id_via_page_oridnal(
            cls, page_ordinal, course_identifier=None, flow_session_id=None,
            with_group_id=False):
        flow_params = cls.get_flow_params(course_identifier, flow_session_id)
        return (
            get_flow_page_id_from_page_ordinal(
                flow_params["flow_session_id"], page_ordinal,
                with_group_id=with_group_id))

    @classmethod
    def get_page_view_url_by_ordinal(
            cls, viewname, page_ordinal, course_identifier=None,
            flow_session_id=None):
        page_params = cls.get_page_params(
            course_identifier, flow_session_id, page_ordinal)
        return reverse(viewname, kwargs=page_params)

    @classmethod
    def get_page_view_url_by_page_id(
            cls, viewname, page_id, course_identifier=None, flow_session_id=None):
        page_ordinal = cls.get_page_ordinal_via_page_id(
            page_id, course_identifier, flow_session_id)
        return cls.get_page_view_url_by_ordinal(
            viewname, page_ordinal, course_identifier, flow_session_id)

    @classmethod
    def get_page_url_by_ordinal(
            cls, page_ordinal, course_identifier=None, flow_session_id=None,
            visit_id=None):
        url = cls.get_page_view_url_by_ordinal(
            "relate-view_flow_page",
            page_ordinal, course_identifier, flow_session_id)
        if visit_id is not None:
            url += "?visit_id=%s" % str(visit_id)

        return url

    @classmethod
    def get_page_url_by_page_id(
            cls, page_id, course_identifier=None, flow_session_id=None,
            visit_id=None):
        page_ordinal = cls.get_page_ordinal_via_page_id(
            page_id, course_identifier, flow_session_id)
        return cls.get_page_url_by_ordinal(
            page_ordinal, course_identifier, flow_session_id, visit_id)

    @classmethod
    def get_page_grading_url_by_ordinal(
            cls, page_ordinal, course_identifier=None, flow_session_id=None):
        return cls.get_page_view_url_by_ordinal(
            "relate-grade_flow_page",
            page_ordinal, course_identifier, flow_session_id)

    @classmethod
    def get_page_grading_url_by_page_id(
            cls, page_id, course_identifier=None, flow_session_id=None):
        page_ordinal = cls.get_page_ordinal_via_page_id(
            page_id, course_identifier, flow_session_id)
        return cls.get_page_grading_url_by_ordinal(
            page_ordinal, course_identifier, flow_session_id)

    @classmethod_with_client
    def post_answer_by_ordinal(cls, client,  # noqa: N805
            page_ordinal, answer_data, *,
            course_identifier=None, flow_session_id=None, visit_id=None):
        submit_data = answer_data
        submit_data.update({"submit": ["Submit final answer"]})
        resp = client.post(
            cls.get_page_url_by_ordinal(
                page_ordinal, course_identifier, flow_session_id, visit_id),
            submit_data)
        return resp

    @classmethod_with_client
    def post_answer_by_page_id(
            cls, client, page_id, answer_data, *,  # noqa: N805
            course_identifier=None, flow_session_id=None, visit_id=None):
        page_ordinal = cls.get_page_ordinal_via_page_id(
            page_id, course_identifier, flow_session_id)
        return cls.post_answer_by_ordinal(client,
            page_ordinal, answer_data,
            course_identifier=course_identifier,
            flow_session_id=flow_session_id, visit_id=visit_id)

    @classmethod_with_client
    def post_answer_by_ordinal_class(cls, client,  # noqa: N805
            page_ordinal, answer_data,
            course_identifier, flow_session_id):
        submit_data = answer_data
        submit_data.update({"submit": ["Submit final answer"]})
        page_params = {
            "course_identifier": course_identifier,
            "flow_session_id": flow_session_id,
            "page_ordinal": page_ordinal
        }
        page_url = reverse("relate-view_flow_page", kwargs=page_params)
        resp = client.post(page_url, submit_data)
        return resp

    @classmethod_with_client
    def post_answer_by_page_id_class(cls, client,  # noqa: N805
            page_id, answer_data, course_identifier, flow_session_id):
        page_ordinal = get_flow_page_ordinal_from_page_id(flow_session_id, page_id)
        return cls.post_answer_by_ordinal_class(page_ordinal, answer_data,
                                                course_identifier, flow_session_id)

    @classmethod_with_client
    def post_grade_by_ordinal(cls, client,  # noqa: N805
            page_ordinal, grade_data, *,
            course_identifier=None, flow_session_id=None,
            force_login_instructor=True):
        post_data = {"submit": [""]}
        post_data.update(grade_data)

        page_params = cls.get_page_params(
            course_identifier, flow_session_id, page_ordinal)

        force_login_user = cls.get_logged_in_user(client)
        if force_login_instructor:
            force_login_user = cls.get_default_instructor_user(
                page_params["course_identifier"])

        with cls.temporarily_switch_to_user(client, force_login_user):
            response = client.post(
                cls.get_page_grading_url_by_ordinal(**page_params),
                data=post_data,
                follow=True)
        return response

    @classmethod_with_client
    def post_grade_by_page_id(cls, client,  # noqa: N805
            page_id, grade_data, *,
            course_identifier=None, flow_session_id=None,
            force_login_instructor=True):
        page_ordinal = cls.get_page_ordinal_via_page_id(
            page_id, course_identifier, flow_session_id)

        return cls.post_grade_by_ordinal(client,
            page_ordinal, grade_data,
            course_identifier=course_identifier,
            flow_session_id=flow_session_id,
            force_login_instructor=force_login_instructor)

    @classmethod
    def assertSessionScoreEqual(  # noqa
            cls, expected_score, course_identifier=None, flow_session_id=None):
        if flow_session_id is None:
            flow_params = cls.get_flow_params(course_identifier, flow_session_id)
            flow_session_id = flow_params["flow_session_id"]
        flow_session = FlowSession.objects.get(id=flow_session_id)
        if expected_score is not None:
            from decimal import Decimal
            assert flow_session.points == Decimal(str(expected_score)), (
                "The flow session got '%s' in stead of '%s'"
                % (str(flow_session.points), str(Decimal(str(expected_score))))
            )
        else:
            assert flow_session.points is None, (
                    "This flow session unexpectedly got %s instead of None"
                    % flow_session.points)

    @classmethod
    def get_page_submit_history_url_by_ordinal(
            cls, page_ordinal, course_identifier=None, flow_session_id=None):
        return cls.get_page_view_url_by_ordinal(
            "relate-get_prev_answer_visits_dropdown_content",
            page_ordinal, course_identifier, flow_session_id)

    @classmethod
    def get_page_grade_history_url_by_ordinal(
            cls, page_ordinal, course_identifier=None, flow_session_id=None):
        return cls.get_page_view_url_by_ordinal(
            "relate-get_prev_grades_dropdown_content",
            page_ordinal, course_identifier, flow_session_id)

    @classmethod_with_client
    def get_page_submit_history_by_ordinal(
            cls, client, page_ordinal, *,  # noqa: N805
            course_identifier=None, flow_session_id=None):
        resp = client.get(
            cls.get_page_submit_history_url_by_ordinal(
                page_ordinal, course_identifier, flow_session_id),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        return resp

    @classmethod_with_client
    def get_page_grade_history_by_ordinal(
            cls, client, page_ordinal, *,  # noqa: N805
            course_identifier=None, flow_session_id=None):
        resp = client.get(
            cls.get_page_grade_history_url_by_ordinal(
                page_ordinal, course_identifier, flow_session_id),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        return resp

    def assertSubmitHistoryItemsCount(  # noqa
            self, page_ordinal, expected_count, course_identifier=None,
            flow_session_id=None):
        resp = self.get_page_submit_history_by_ordinal(
            page_ordinal, course_identifier=course_identifier,
            flow_session_id=flow_session_id)
        import json
        result = json.loads(resp.content.decode())["result"]
        self.assertEqual(len(result), expected_count)

    def assertGradeHistoryItemsCount(  # noqa
            self, page_ordinal, expected_count,
            course_identifier=None,
            flow_session_id=None,
            force_login_instructor=True):

        if course_identifier is None:
            course_identifier = self.get_default_course_identifier()

        if force_login_instructor:
            switch_to = self.get_default_instructor_user(course_identifier)
        else:
            switch_to = self.get_logged_in_user()

        with self.temporarily_switch_to_user(switch_to):
            resp = self.get_page_grade_history_by_ordinal(
                page_ordinal, course_identifier=course_identifier,
                flow_session_id=flow_session_id)

        import json
        result = json.loads(resp.content.decode())["result"]
        self.assertEqual(len(result), expected_count)

    @classmethod
    def get_update_course_url(cls, course_identifier=None):
        if course_identifier is None:
            course_identifier = cls.get_default_course_identifier()
        return reverse("relate-update_course", args=[course_identifier])

    @classmethod
    def get_course_commit_sha(cls, participation, course=None):
        course = course or cls.get_default_course()
        from course.content import get_course_commit_sha
        return get_course_commit_sha(course, participation)

    @classmethod_with_client
    def post_update_course_content(cls, client, commit_sha, *,  # noqa: N805
                                   prevent_discarding_revisions=True,
                                   force_login_instructor=True,
                                   course=None,
                                   command="update",
                                   ):
        # course instead of course_identifier because we need to do
        # refresh_from_db
        course = course or cls.get_default_course()

        try:
            commit_sha = commit_sha.decode()
        except Exception:
            pass

        data = {"new_sha": [commit_sha]}

        if not prevent_discarding_revisions:
            data["prevent_discarding_revisions"] = ["on"]

        # normally, command should be in
        # ["fetch", "fetch_update", "update", "fetch_preview", "preview",
        #  "end_preview"]
        data[command] = "on"

        force_login_user = cls.get_logged_in_user(client)
        if force_login_instructor:
            force_login_user = cls.get_default_instructor_user(course.identifier)

        with cls.temporarily_switch_to_user(client, force_login_user):
            response = client.post(
                cls.get_update_course_url(course.identifier), data)
            course.refresh_from_db()

        return response

    @classmethod
    def get_page_data_by_page_id(
            cls, page_id, course_identifier=None, flow_session_id=None):
        flow_params = cls.get_flow_params(course_identifier, flow_session_id)
        return FlowPageData.objects.get(
            flow_session_id=flow_params["flow_session_id"], page_id=page_id)

    @classmethod
    def get_page_visits(cls, course_identifier=None,
                        flow_session_id=None, page_ordinal=None, page_id=None,
                        **kwargs):
        query_kwargs = {}
        if kwargs.get("answer_visit", False):
            query_kwargs.update({"answer__isnull": False})
        flow_params = cls.get_flow_params(course_identifier, flow_session_id)
        query_kwargs.update({"flow_session_id": flow_params["flow_session_id"]})
        if page_ordinal is not None:
            query_kwargs.update({"page_data__page_ordinal": page_ordinal})
        elif page_id is not None:
            query_kwargs.update({"page_data__page_id": page_id})
        return FlowPageVisit.objects.filter(**query_kwargs)

    @classmethod
    def get_last_answer_visit(cls, course_identifier=None,
                              flow_session_id=None, page_ordinal=None,
                              page_id=None, assert_not_none=True):
        result_qset = cls.get_page_visits(course_identifier,
                                          flow_session_id, page_ordinal, page_id,
                                          answer_visit=True).order_by("-pk")[:1]
        if result_qset:
            result = result_qset[0]
        else:
            result = None
        if assert_not_none:
            assert result is not None, "The query returns None"
        return result

    @classmethod
    def download_all_submissions_url(cls, flow_id, course_identifier):
        params = {"course_identifier": course_identifier,
                  "flow_id": flow_id}
        return reverse("relate-download_all_submissions", kwargs=params)

    @classmethod_with_client
    def get_download_all_submissions(cls, client, flow_id, *,  # noqa: N805
            course_identifier=None):
        if course_identifier is None:
            course_identifier = cls.get_default_course_identifier()

        return client.get(
            cls.download_all_submissions_url(flow_id, course_identifier))

    @classmethod_with_client
    def post_download_all_submissions_by_group_page_id(
            cls, client,  # noqa: N805
            group_page_id, flow_id, *, course_identifier=None, **kwargs):
        """
        :param group_page_id: format: group_id/page_id
        :param flow_id:
        :param course_identifier:
        :param kwargs: for updating the default post_data
        :return: response
        """
        if course_identifier is None:
            course_identifier = cls.get_default_course_identifier()

        data = {"restrict_to_rules_tag": "<<<ALL>>>",
                "which_attempt": "last",
                "extra_file": "", "download": "Download",
                "page_id": group_page_id,
                "non_in_progress_only": "on"}

        non_in_progress_only = kwargs.pop("non_in_progress_only", True)
        if not non_in_progress_only:
            del data["non_in_progress_only"]

        data.update(kwargs)

        return client.post(
            cls.download_all_submissions_url(flow_id, course_identifier),
            data=data
        )

    @classmethod
    def get_flow_page_analytics_url(cls, flow_id, group_id, page_id,
                                    course_identifier=None,
                                    restrict_to_first_attempt=False):
        if course_identifier is None:
            course_identifier = cls.get_default_course_identifier()

        params = {"course_identifier": course_identifier,
                  "flow_id": flow_id,
                  "group_id": group_id,
                  "page_id": page_id}

        url = reverse("relate-page_analytics", kwargs=params)
        if restrict_to_first_attempt:
            url += "?restrict_to_first_attempt=1"

        return url

    @classmethod_with_client
    def get_flow_page_analytics(cls, client,  # noqa: N805
            flow_id, group_id, page_id, *,
            course_identifier=None,
            force_login_instructor=True,
            restrict_to_first_attempt=False):

        course_identifier = course_identifier or cls.get_default_course_identifier()
        url = cls.get_flow_page_analytics_url(
            flow_id, group_id, page_id, course_identifier, restrict_to_first_attempt)

        if not force_login_instructor:
            user = cls.get_logged_in_user(client)
        else:
            user = cls.instructor_participation.user

        with cls.temporarily_switch_to_user(client, user):
            return client.get(url)

    # {{{ hack getting session rules

    default_session_start_rule = {
        "tag_session": None,
        "may_start_new_session": True,
        "may_list_existing_sessions": True,
        "default_expiration_mode": None}

    def get_hacked_session_start_rule(self, **kwargs):
        """
        Used for mocking session_start_rule
        :param kwargs: attributes in the mocked FlowSessionStartRule instance
        :return: a :class:`FlowSessionStartRule` instance

        Example:

            with mock.patch(
                "course.flow.get_session_start_rule") as mock_get_nrule:
                mock_get_nrule.return_value = (
                    self.get_hacked_session_start_rule())
        """
        from course.utils import FlowSessionStartRule
        defaults = deepcopy(self.default_session_start_rule)
        defaults.update(kwargs)
        return FlowSessionStartRule(**defaults)

    default_session_access_rule = {
        "permissions": [fperm.view, fperm.end_session]}

    def get_hacked_session_access_rule(self, **kwargs):
        """
        Used for mocking session_access_rule
        :param kwargs: attributes in the mocked FlowSessionAccessRule instance
        :return: a :class:`FlowSessionAccessRule` instance

        Example:

            with mock.patch(
                    "course.flow.get_session_access_rule") as mock_get_arule:
                mock_get_arule.return_value = (
                    self.get_hacked_session_access_rule(
                        permissions=[fperm.end_session]))
        """
        from course.utils import FlowSessionAccessRule
        defaults = deepcopy(self.default_session_access_rule)
        defaults.update(kwargs)
        return FlowSessionAccessRule(**defaults)

    default_session_grading_rule = {
        "grade_identifier": "la_quiz",
        "grade_aggregation_strategy": g_strategy.use_latest,
        "due": None,
        "generates_grade": True,
        "description": None,
        "credit_percent": 100,
        "use_last_activity_as_completion_time": False,
        "bonus_points": 0,
        "max_points": None,
        "max_points_enforced_cap": None,
    }

    def get_hacked_session_grading_rule(self, **kwargs):
        """
        Used for mocking session_grading_rule
        :param kwargs: attributes in the mocked FlowSessionGradingRule instance
        :return: a :class:`FlowSessionGradingRule` instance

        Example:

            with mock.patch(
                "course.flow.get_session_grading_rule") as mock_get_grule:
                mock_get_grule.return_value = \
                    self.get_hacked_session_grading_rule(bonus_points=2)
        """
        from course.utils import FlowSessionGradingRule
        defaults = deepcopy(self.default_session_grading_rule)
        defaults.update(kwargs)
        return FlowSessionGradingRule(**defaults)

    # }}}

    def get_form_submit_inputs(self, form):
        from crispy_forms.layout import Submit
        inputs = [
            (input.name, input.value) for input in form.helper.inputs
            if isinstance(input, Submit)
        ]
        names = list(dict(inputs).keys())
        values = list(dict(inputs).values())
        return names, values

    def get_flow_analytics_url(self, flow_id, course_identifier,
                               restrict_to_first_attempt=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        kwargs = {
            "flow_id": flow_id,
            "course_identifier": course_identifier}
        result = reverse("relate-flow_analytics", kwargs=kwargs)
        if restrict_to_first_attempt:
            result += "?restrict_to_first_attempt=%s" % restrict_to_first_attempt
        return result

    def get_flow_analytics_view(self, flow_id, course_identifier=None,
                                restrict_to_first_attempt=None,
                                force_login_instructor=True):
        course_identifier = course_identifier or self.get_default_course_identifier()
        if not force_login_instructor:
            user = self.get_logged_in_user()
        else:
            user = self.instructor_participation.user

        with self.temporarily_switch_to_user(user):
            return self.client.get(
                self.get_flow_analytics_url(
                    flow_id, course_identifier=course_identifier,
                    restrict_to_first_attempt=restrict_to_first_attempt))

    def get_manage_authentication_token_url(self, course_identifier=None):
        course_identifier = course_identifier or self.get_default_course_identifier()
        return reverse("relate-manage_authentication_tokens",
                       args=(course_identifier,))

# }}}


# {{{ SingleCourseTestMixin

class SingleCourseTestMixin(CoursesTestMixinBase):
    courses_setup_list = SINGLE_COURSE_SETUP_LIST
    initial_commit_sha = None

    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()
        assert len(cls.course_qset) == 1
        cls.course = cls.course_qset.first()
        if cls.initial_commit_sha is not None:
            cls.course.active_git_commit_sha = cls.initial_commit_sha
            cls.course.save()

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

        cls.course_page_url = cls.get_course_page_url()

    def setUp(self):  # noqa
        super().setUp()

        # reload objects created during setUpTestData in case they were modified in
        # tests. Ref: https://goo.gl/AuzJRC#django.test.TestCase.setUpTestData
        self.course.refresh_from_db()
        self.instructor_participation.refresh_from_db()
        self.student_participation.refresh_from_db()
        self.ta_participation.refresh_from_db()

        self.client.force_login(self.student_participation.user)

    @classmethod
    def get_default_course(cls):
        return cls.course

    @classmethod
    def get_default_course_identifier(cls):
        return cls.get_default_course().identifier

    def copy_course_dict_and_set_attrs_for_post(self, attrs_dict={}):
        from course.models import Course
        kwargs = Course.objects.first().__dict__
        kwargs.update(attrs_dict)

        for k, v in kwargs.items():
            if v is None:
                kwargs[k] = ""
        return kwargs

    @classmethod
    def get_course_page_context(cls, user):
        rf = RequestFactory()
        request = rf.get(cls.get_course_page_url())
        request.user = user

        from course.utils import CoursePageContext
        pctx = CoursePageContext(request, cls.course.identifier)
        return pctx

    @classmethod
    def get_hacked_flow_desc(
            cls, user=None, flow_id=None, commit_sha=None,
            del_rules=False, as_dict=False, **kwargs):
        """
        Get a hacked version of flow_desc
        :param user: the flow_desc viewed by which user, default to a student
        :param flow_id: the flow_desc of which flow_id, default to `quiz-test`
        :param commit_sha: default to corrent running commit_sha
        :param kwargs: the attributes of the hacked flow_dec
        :return: the faked flow_desc
        """

        # {{{ get the actual flow_desc by a real visit
        rf = RequestFactory()
        request = rf.get(cls.get_course_page_url())
        if user is None:
            user = cls.student_participation.user
        request.user = user

        if flow_id is None:
            flow_id = QUIZ_FLOW_ID

        if commit_sha is None:
            commit_sha = cls.course.active_git_commit_sha

        if isinstance(commit_sha, str):
            commit_sha = commit_sha.encode()

        from course.content import get_flow_desc
        with cls.get_course_page_context(user) as pctx:
            flow_desc = get_flow_desc(
                pctx.repo, pctx.course, flow_id, commit_sha)

        # }}}

        from relate.utils import struct_to_dict, dict_to_struct
        flow_desc_dict = struct_to_dict(flow_desc)

        if del_rules:
            del flow_desc_dict["rules"]

        flow_desc_dict.update(kwargs)

        if as_dict:
            return flow_desc_dict

        return dict_to_struct(flow_desc_dict)

    def get_hacked_flow_desc_with_access_rule_tags(self, rule_tags):
        assert isinstance(rule_tags, list)
        from relate.utils import struct_to_dict, dict_to_struct
        hacked_flow_desc_dict = self.get_hacked_flow_desc(as_dict=True)
        rules = hacked_flow_desc_dict["rules"]
        rules_dict = struct_to_dict(rules)
        rules_dict["tags"] = rule_tags
        rules = dict_to_struct(rules_dict)
        hacked_flow_desc_dict["rules"] = rules
        hacked_flow_desc = dict_to_struct(hacked_flow_desc_dict)
        assert hacked_flow_desc.rules.tags == rule_tags
        return hacked_flow_desc

# }}}


# {{{ TwoCourseTestMixin

class TwoCourseTestMixin(CoursesTestMixinBase):
    courses_setup_list = TWO_COURSE_SETUP_LIST

    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()
        assert len(cls.course_qset) == 2, (
            "'courses_setup_list' should contain two courses")
        cls.course1 = cls.course_qset.first()
        cls.course1_instructor_participation = Participation.objects.filter(
            course=cls.course1,
            roles__identifier="instructor",
            status=participation_status.active
        ).first()
        assert cls.course1_instructor_participation

        cls.course1_student_participation = Participation.objects.filter(
            course=cls.course1,
            roles__identifier="student",
            status=participation_status.active
        ).first()
        assert cls.course1_student_participation

        cls.course1_ta_participation = Participation.objects.filter(
            course=cls.course1,
            roles__identifier="ta",
            status=participation_status.active
        ).first()
        assert cls.course1_ta_participation
        cls.course1_page_url = cls.get_course_page_url(cls.course1.identifier)

        cls.course2 = cls.course_qset.last()
        cls.course2_instructor_participation = Participation.objects.filter(
            course=cls.course2,
            roles__identifier="instructor",
            status=participation_status.active
        ).first()
        assert cls.course2_instructor_participation

        cls.course2_student_participation = Participation.objects.filter(
            course=cls.course2,
            roles__identifier="student",
            status=participation_status.active
        ).first()
        assert cls.course2_student_participation

        cls.course2_ta_participation = Participation.objects.filter(
            course=cls.course2,
            roles__identifier="ta",
            status=participation_status.active
        ).first()
        assert cls.course2_ta_participation
        cls.course2_page_url = cls.get_course_page_url(cls.course2.identifier)

    def setUp(self):  # noqa
        super().setUp()
        # reload objects created during setUpTestData in case they were modified in
        # tests. Ref: https://goo.gl/AuzJRC#django.test.TestCase.setUpTestData
        self.course1.refresh_from_db()
        self.course1_instructor_participation.refresh_from_db()
        self.course1_student_participation.refresh_from_db()
        self.course1_ta_participation.refresh_from_db()

        self.course2.refresh_from_db()
        self.course2_instructor_participation.refresh_from_db()
        self.course2_student_participation.refresh_from_db()
        self.course2_ta_participation.refresh_from_db()

# }}}


# {{{ SingleCoursePageTestMixin

class SingleCoursePageTestMixin(SingleCourseTestMixin):
    # This serves as cache
    _default_session_id = None

    flow_id = QUIZ_FLOW_ID

    @classmethod
    def update_default_flow_session_id(cls, course_identifier):
        cls._default_session_id = cls.default_flow_params["flow_session_id"]

    @classmethod
    def get_default_flow_session_id(cls, course_identifier):
        if cls._default_session_id is not None:
            return cls._default_session_id
        cls._default_session_id = cls.get_latest_session_id(course_identifier)
        return cls._default_session_id

# }}}


# {{{ TwoCoursePageTestMixin

class TwoCoursePageTestMixin(TwoCourseTestMixin):
    _course1_default_session_id = None
    _course2_default_session_id = None

    @property
    def flow_id(self):
        raise NotImplementedError

    @classmethod
    def get_default_flow_session_id(cls, course_identifier):
        if course_identifier == cls.course1.identifier:
            if cls._course1_default_session_id is not None:
                return cls._course1_default_session_id
            cls._course1_default_session_id = (
                cls.get_last_session_id(course_identifier))
            return cls._course1_default_session_id
        if course_identifier == cls.course2.identifier:
            if cls._course2_default_session_id is not None:
                return cls._course2_default_session_id
            cls._course2_default_session_id = (
                cls.get_last_session_id(course_identifier))
            return cls._course2_default_session_id

    @classmethod
    def update_default_flow_session_id(cls, course_identifier):
        new_session_id = cls.default_flow_params["flow_session_id"]
        if course_identifier == cls.course1.identifier:
            cls._course1_default_session_id = new_session_id
        elif course_identifier == cls.course2.identifier:
            cls._course2_default_session_id = new_session_id

# }}}


# {{{ SingleCourseQuizPageTestMixin

class SingleCourseQuizPageTestMixin(SingleCoursePageTestMixin):

    skip_code_question = True

    @classmethod_with_client
    def ensure_grading_ui_get(cls, client, page_id):  # noqa: N805
        with cls.temporarily_switch_to_user(
                client, cls.instructor_participation.user):
            url = cls.get_page_grading_url_by_page_id(page_id)
            resp = client.get(url)
            assert resp.status_code == 200

    @classmethod_with_client
    def ensure_analytic_page_get(cls, client, group_id, page_id):  # noqa: N805
        with cls.temporarily_switch_to_user(
                client, cls.instructor_participation.user):
            resp = cls.get_flow_page_analytics(
                    client,
                    flow_id=cls.flow_id, group_id=group_id,
                    page_id=page_id)
            assert resp.status_code == 200

    @classmethod_with_client
    def ensure_download_submission(
            cls, client, group_id, page_id, *,  # noqa: N805
            dl_file_extension=None, file_with_ext_count=None):
        with cls.temporarily_switch_to_user(
                client, cls.instructor_participation.user):
            group_page_id = f"{group_id}/{page_id}"
            resp = cls.post_download_all_submissions_by_group_page_id(
                    client,
                    group_page_id=group_page_id, flow_id=cls.flow_id)
            assert resp.status_code == 200
            prefix, zip_file = resp["Content-Disposition"].split("=")
            assert prefix == "attachment; filename"
            assert resp.get("Content-Type") == "application/zip"

            import io
            if dl_file_extension:
                buf = io.BytesIO(resp.content)
                import zipfile
                with zipfile.ZipFile(buf, "r") as zf:
                    assert zf.testzip() is None
                    # todo: make more assertions in terms of file content

                    for f in zf.filelist:
                        assert f.file_size > 0

                    if file_with_ext_count is None:
                        assert len([f for f in zf.filelist if
                                    f.filename.endswith(dl_file_extension)]) > 0, \
                            ("The zipped file unexpectedly didn't contain "
                             "file with extension '%s', the actual file list "
                             "is %s" % (
                                 dl_file_extension,
                                 repr([f.filename for f in zf.filelist])))
                    else:
                        assert (
                                len([f for f in zf.filelist if
                                     f.filename.endswith(dl_file_extension)])
                                == file_with_ext_count), \
                            ("The zipped file unexpectedly didn't contain "
                             "%d files with extension '%s', the actual file list "
                             "is %s" % (
                                 file_with_ext_count,
                                 dl_file_extension,
                                 repr([f.filename for f in zf.filelist])))

    @classmethod_with_client
    def submit_page_answer_by_ordinal_and_test(
            cls, client, page_ordinal, *,  # noqa: N805
            use_correct_answer=True, answer_data=None,
            skip_code_question=True,
            expected_grades=None, expected_post_answer_status_code=200,
            do_grading=False, do_human_grade=False, grade_data=None,
            grade_data_extra_kwargs=None,
            dl_file_extension=None,
            ensure_grading_ui_get_before_grading=False,
            ensure_grading_ui_get_after_grading=False,
            ensure_analytic_page_get_before_submission=False,
            ensure_analytic_page_get_after_submission=False,
            ensure_analytic_page_get_before_grading=False,
            ensure_analytic_page_get_after_grading=False,
            ensure_download_before_submission=False,
            ensure_download_after_submission=False,
            ensure_download_before_grading=False,
            ensure_download_after_grading=False,
            dl_file_with_ext_count=None):
        page_id = cls.get_page_id_via_page_oridnal(page_ordinal)

        return cls.submit_page_answer_by_page_id_and_test(
            client, page_id,
            use_correct_answer=use_correct_answer,
            answer_data=answer_data, skip_code_question=skip_code_question,
            expected_grades=expected_grades,
            expected_post_answer_status_code=expected_post_answer_status_code,
            do_grading=do_grading, do_human_grade=do_human_grade,
            grade_data=grade_data, grade_data_extra_kwargs=grade_data_extra_kwargs,
            dl_file_extension=dl_file_extension,
            ensure_grading_ui_get_before_grading=(
                ensure_grading_ui_get_before_grading),
            ensure_grading_ui_get_after_grading=ensure_grading_ui_get_after_grading,
            ensure_analytic_page_get_before_submission=(
                ensure_analytic_page_get_before_submission),
            ensure_analytic_page_get_after_submission=(
                ensure_analytic_page_get_after_submission),
            ensure_analytic_page_get_before_grading=(
                ensure_analytic_page_get_before_grading),
            ensure_analytic_page_get_after_grading=(
                ensure_analytic_page_get_after_grading),
            ensure_download_before_submission=ensure_download_before_submission,
            ensure_download_after_submission=ensure_download_after_submission,
            ensure_download_before_grading=ensure_download_before_grading,
            ensure_download_after_grading=ensure_download_after_grading,
            dl_file_with_ext_count=dl_file_with_ext_count)

    @classmethod_with_client
    def submit_page_answer_by_page_id_and_test(
            cls, client, page_id, *,  # noqa: N805
            use_correct_answer=True, answer_data=None,
            skip_code_question=True,
            expected_grades=None, expected_post_answer_status_code=200,
            do_grading=False, do_human_grade=False, grade_data=None,
            grade_data_extra_kwargs=None,
            dl_file_extension=None,
            ensure_grading_ui_get_before_grading=False,
            ensure_grading_ui_get_after_grading=False,
            ensure_analytic_page_get_before_submission=False,
            ensure_analytic_page_get_after_submission=False,
            ensure_analytic_page_get_before_grading=False,
            ensure_analytic_page_get_after_grading=False,
            ensure_download_before_submission=False,
            ensure_download_after_submission=False,
            ensure_download_before_grading=False,
            ensure_download_after_grading=False,
            dl_file_with_ext_count=None):

        if answer_data is not None:
            assert isinstance(answer_data, dict)
            use_correct_answer = False

        submit_answer_response = None
        post_grade_response = None

        for page_tuple in TEST_PAGE_TUPLE:
            if skip_code_question and page_tuple.need_runpy:
                continue
            if page_id == page_tuple.page_id:
                group_id = page_tuple.group_id
                if ensure_grading_ui_get_before_grading:
                    cls.ensure_grading_ui_get(client, page_id)

                if ensure_analytic_page_get_before_submission:
                    cls.ensure_analytic_page_get(client, group_id, page_id)

                if ensure_download_before_submission:
                    cls.ensure_download_submission(client, group_id, page_id)

                if page_tuple.correct_answer is not None:

                    if answer_data is None:
                        answer_data = page_tuple.correct_answer

                    if page_id in ["anyup", "proof"]:
                        file_path = answer_data["uploaded_file"]
                        if not file_path:
                            # submitting an empty answer
                            submit_answer_response = (
                                cls.post_answer_by_page_id(
                                    client, page_id, answer_data))
                        else:
                            if isinstance(file_path, list):
                                file_path, = file_path

                            file_path = file_path.strip()
                            with open(file_path, "rb") as fp:
                                answer_data = {"uploaded_file": fp}
                                submit_answer_response = (
                                    cls.post_answer_by_page_id(client,
                                        page_id, answer_data))
                    else:
                        submit_answer_response = (
                            cls.post_answer_by_page_id(client, page_id, answer_data))

                    # Fixed #514
                    # https://github.com/inducer/relate/issues/514
                    submit_answer_response.context["form"].as_p()

                    assert (submit_answer_response.status_code
                            == expected_post_answer_status_code), (
                            "{} != {}".format(submit_answer_response.status_code,
                                          expected_post_answer_status_code))

                    if ensure_analytic_page_get_after_submission:
                        cls.ensure_analytic_page_get(client, group_id, page_id)

                    if ensure_download_after_submission:
                        cls.ensure_download_submission(client, group_id, page_id)

                if not do_grading:
                    break

                assert cls.end_flow(client).status_code == 200

                if ensure_analytic_page_get_before_grading:
                    cls.ensure_analytic_page_get(client, group_id, page_id)

                if ensure_download_before_grading:
                    cls.ensure_download_submission(client, group_id, page_id)

                if page_tuple.correct_answer is not None:
                    if use_correct_answer:
                        expected_grades = page_tuple.full_points

                    if page_tuple.need_human_grade:
                        if not do_human_grade:
                            cls.assertSessionScoreEqual(None)
                            break
                        if grade_data is not None:
                            assert isinstance(grade_data, dict)
                        else:
                            grade_data = page_tuple.grade_data.copy()

                        if grade_data_extra_kwargs:
                            assert isinstance(grade_data_extra_kwargs, dict)
                            grade_data.update(grade_data_extra_kwargs)

                        post_grade_response = cls.post_grade_by_page_id(
                            client, page_id, grade_data)
                    cls.assertSessionScoreEqual(expected_grades)

                    if not dl_file_extension:
                        dl_file_extension = page_tuple.dl_file_extension

                    if ensure_download_after_grading:
                        cls.ensure_download_submission(
                                client,
                                group_id, page_id,
                                dl_file_extension=dl_file_extension,
                                file_with_ext_count=dl_file_with_ext_count)

                if ensure_analytic_page_get_after_grading:
                    cls.ensure_analytic_page_get(client, group_id, page_id)

                if ensure_grading_ui_get_after_grading:
                    cls.ensure_grading_ui_get(client, page_id)

        return submit_answer_response, post_grade_response

    def default_submit_page_answer_by_page_id_and_test(self, page_id,
                                                       answer_data=None,
                                                       expected_grade=None,
                                                       do_grading=True,
                                                       grade_data=None,
                                                       grade_data_extra_kwargs=None,
                                                       ):
        return self.submit_page_answer_by_page_id_and_test(
            page_id, answer_data=answer_data,
            skip_code_question=self.skip_code_question,
            expected_grades=expected_grade, expected_post_answer_status_code=200,
            do_grading=do_grading, do_human_grade=True, grade_data=grade_data,
            grade_data_extra_kwargs=grade_data_extra_kwargs,
            ensure_grading_ui_get_before_grading=True,
            ensure_grading_ui_get_after_grading=True,
            ensure_analytic_page_get_before_submission=True,
            ensure_analytic_page_get_after_submission=True,
            ensure_analytic_page_get_before_grading=True,
            ensure_analytic_page_get_after_grading=True,
            ensure_download_before_submission=True,
            ensure_download_after_submission=True,
            ensure_download_before_grading=True,
            ensure_download_after_grading=True)

    @classmethod_with_client
    def submit_page_human_grading_by_page_id_and_test(
            cls, client, page_id, *,  # noqa: N805
            expected_post_grading_status_code=200,
            grade_data=None,
            expected_grades=None,
            do_session_score_equal_assersion=True,
            grade_data_extra_kwargs=None,
            force_login_instructor=True,
            ensure_grading_ui_get_before_grading=False,
            ensure_grading_ui_get_after_grading=False,
            ensure_analytic_page_get_before_grading=False,
            ensure_analytic_page_get_after_grading=False,
            ensure_download_before_grading=False,
            ensure_download_after_grading=False):

        # this helper is expected to be used when the session is finished

        post_grade_response = None

        for page_tuple in TEST_PAGE_TUPLE:
            if page_id == page_tuple.page_id:
                group_id = page_tuple.group_id
                if ensure_grading_ui_get_before_grading:
                    cls.ensure_grading_ui_get(page_id)

                if ensure_analytic_page_get_before_grading:
                    cls.ensure_analytic_page_get(group_id, page_id)

                if ensure_download_before_grading:
                    cls.ensure_download_submission(group_id, page_id)

                if not page_tuple.need_human_grade:
                    break

                assign_full_grades = True

                if grade_data is not None:
                    assert isinstance(grade_data, dict)
                    assign_full_grades = False
                else:
                    grade_data = page_tuple.grade_data.copy()

                if assign_full_grades:
                    expected_grades = page_tuple.full_points

                if grade_data_extra_kwargs:
                    assert isinstance(grade_data_extra_kwargs, dict)
                    grade_data.update(grade_data_extra_kwargs)

                post_grade_response = cls.post_grade_by_page_id(
                        client,
                        page_id, grade_data,
                        force_login_instructor=force_login_instructor)

                assert (post_grade_response.status_code
                        == expected_post_grading_status_code)

                if post_grade_response.status_code == 200:
                    if do_session_score_equal_assersion:
                        cls.assertSessionScoreEqual(expected_grades)

                if ensure_download_after_grading:
                    cls.ensure_download_submission(group_id, page_id)

                if ensure_analytic_page_get_after_grading:
                    cls.ensure_analytic_page_get(group_id, page_id)

                if ensure_grading_ui_get_after_grading:
                    cls.ensure_grading_ui_get(page_id)

        return post_grade_response

# }}}


# {{{ MockAddMessageMixing

class MockAddMessageMixing:
    """
    The mixing for testing django.contrib.messages.add_message
    """

    def setUp(self):
        super().setUp()
        self._fake_add_message_path = "django.contrib.messages.add_message"
        fake_add_messag = mock.patch(self._fake_add_message_path)

        self._mock_add_message = fake_add_messag.start()
        self.addCleanup(fake_add_messag.stop)

    def _get_added_messages(self, join=True):
        try:
            msgs = [
                "'%s'" % str(arg[2])
                for arg, _ in self._mock_add_message.call_args_list]
        except IndexError:
            self.fail("%s is unexpectedly not called." % self._fake_add_message_path)
        else:
            if join:
                return "; ".join(msgs)
            return msgs

    def assertAddMessageCallCount(self, expected_call_count, reset=False):  # noqa
        fail_msg = (
            "%s is unexpectedly called %d times, instead of %d times." %
            (self._fake_add_message_path, self._mock_add_message.call_count,
             expected_call_count))
        if self._mock_add_message.call_count > 0:
            fail_msg += ("The called messages are: %s"
                         % repr(self._get_added_messages(join=False)))
        self.assertEqual(
            self._mock_add_message.call_count, expected_call_count, msg=fail_msg)
        if reset:
            self._mock_add_message.reset_mock()

    def assertAddMessageCalledWith(self, expected_messages, reset=True):  # noqa
        joined_msgs = self._get_added_messages()

        if not isinstance(expected_messages, list):
            expected_messages = [expected_messages]

        not_called = []
        for msg in expected_messages:
            if msg not in joined_msgs:
                not_called.append(msg)

        if not_called:
            fail_msg = "%s unexpectedly not added in messages. " % repr(not_called)
            if joined_msgs:
                fail_msg += 'the actual message are "%s"' % joined_msgs
            self.fail(fail_msg)
        if reset:
            self._mock_add_message.reset_mock()

    def assertAddMessageNotCalledWith(self, expected_messages, reset=False):  # noqa
        joined_msgs = self._get_added_messages()

        if not isinstance(expected_messages, list):
            expected_messages = [expected_messages]

        called = []
        for msg in expected_messages:
            if msg in joined_msgs:
                called.append(msg)

        if called:
            fail_msg = "%s unexpectedly added in messages. " % repr(called)
            fail_msg += 'the actual message are \"%s\"' % joined_msgs
            self.fail(fail_msg)
        if reset:
            self._mock_add_message.reset_mock()

    def reset_add_message_mock(self):
        self._mock_add_message.reset_mock()

# }}}


# {{{ SubprocessRunpyContainerMixin

class SubprocessRunpyContainerMixin:
    """
    This mixin is used to fake a runpy container, only needed when
    the TestCase include test(s) for code questions
    """
    @classmethod
    def setUpClass(cls):  # noqa
        super().setUpClass()

        python_executable = os.getenv("PY_EXE")

        if not python_executable:
            python_executable = sys.executable

        import subprocess
        args = [python_executable,
                os.path.abspath(
                    os.path.join(
                        os.path.dirname(__file__), os.pardir,
                        "docker-image-run-py", "runcode")),
                ]
        cls.faked_container_process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,

            # because runpy prints to stderr
            stderr=subprocess.DEVNULL
        )

    def setUp(self):
        super().setUp()
        self.faked_container_patch = mock.patch(
            "course.page.code.SPAWN_CONTAINERS", False)
        self.faked_container_patch.start()
        self.addCleanup(self.faked_container_patch.stop)

    @classmethod
    def tearDownClass(cls):  # noqa
        super().tearDownClass()

        from course.page.code import SPAWN_CONTAINERS
        # Make sure SPAWN_CONTAINERS is reset to True
        assert SPAWN_CONTAINERS
        if sys.platform.startswith("win"):
            # Without these lines, tests on Appveyor hanged when all tests
            # finished.
            # However, On nix platforms, these lines resulted in test
            # failure when there were more than one TestCases which were using
            # this mixin. So we don't kill the subprocess, and it won't bring
            # bad side effects to remainder tests.
            cls.faked_container_process.kill()

# }}}


def improperly_configured_cache_patch():
    # can be used as context manager or decorator
    built_in_import_path = "builtins.__import__"
    import builtins  # noqa

    built_in_import = builtins.__import__

    def my_disable_cache_import(name, globals=None, locals=None, fromlist=(),
                                level=0):
        if name == "django.core.cache":
            raise ImproperlyConfigured()
        return built_in_import(name, globals, locals, fromlist, level)

    return mock.patch(built_in_import_path, side_effect=my_disable_cache_import)


# {{{ admin

ADMIN_TWO_COURSE_SETUP_LIST = deepcopy(TWO_COURSE_SETUP_LIST)
# switch roles
ADMIN_TWO_COURSE_SETUP_LIST[1]["participations"][0]["role_identifier"] = "ta"
ADMIN_TWO_COURSE_SETUP_LIST[1]["participations"][1]["role_identifier"] = "instructor"  # noqa


class AdminTestMixin(TwoCourseTestMixin):
    courses_setup_list = ADMIN_TWO_COURSE_SETUP_LIST
    none_participation_user_create_kwarg_list = (
        NONE_PARTICIPATION_USER_CREATE_KWARG_LIST)

    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()  # noqa

        # create 2 participation (with new user) for course1
        from tests.factories import ParticipationFactory

        cls.course1_student_participation2 = (
            ParticipationFactory.create(course=cls.course1))
        cls.course1_student_participation3 = (
            ParticipationFactory.create(course=cls.course1))
        cls.instructor1 = cls.course1_instructor_participation.user
        cls.instructor2 = cls.course2_instructor_participation.user
        assert cls.instructor1 != cls.instructor2

        # grant all admin permissions to instructors
        from django.contrib.auth.models import Permission

        for user in [cls.instructor1, cls.instructor2]:
            user.is_staff = True
            user.save()
            for perm in Permission.objects.all():
                user.user_permissions.add(perm)

    @classmethod
    def get_admin_change_list_view_url(cls, app_name, model_name):
        return reverse(f"admin:{app_name}_{model_name}_changelist")

    @classmethod
    def get_admin_change_view_url(cls, app_name, model_name, args=None):
        if args is None:
            args = []
        return reverse(f"admin:{app_name}_{model_name}_change", args=args)

    @classmethod
    def get_admin_add_view_url(cls, app_name, model_name, args=None):
        if args is None:
            args = []
        return reverse(f"admin:{app_name}_{model_name}_add", args=args)

    def get_admin_form_fields(self, response):
        """
        Return a list of AdminFields for the AdminForm in the response.
        """
        admin_form = response.context["adminform"]
        fieldsets = list(admin_form)

        field_lines = []
        for fieldset in fieldsets:
            field_lines += list(fieldset)

        fields = []
        for field_line in field_lines:
            fields += list(field_line)

        return fields

    def get_admin_form_fields_names(self, response):
        return [f.field.name for f in self.get_admin_form_fields(response)]

    def get_changelist(self, request, model, model_admin):
        from django.contrib.admin.views.main import ChangeList
        return ChangeList(
            request, model, model_admin.list_display,
            model_admin.list_display_links, model_admin.get_list_filter(request),
            model_admin.date_hierarchy, model_admin.search_fields,
            model_admin.list_select_related, model_admin.list_per_page,
            model_admin.list_max_show_all, model_admin.list_editable,
            model_admin=model_admin,
            sortable_by=model_admin.sortable_by,
            search_help_text="(no help text)",
        )

    def get_filterspec_list(self, request, changelist=None, model=None,
                            model_admin=None):
        if changelist is None:
            assert request and model and model_admin
            changelist = self.get_changelist(request, model, model_admin)

        filterspecs = changelist.get_filters(request)[0]
        filterspec_list = []
        for filterspec in filterspecs:
            choices = tuple(c["display"] for c in filterspec.choices(changelist))
            filterspec_list.append(choices)

        return filterspec_list

# }}}


# {{{ api

class APITestMixin(SingleCoursePageTestMixin):
    # test manage_authentication_tokens
    flow_id = QUIZ_FLOW_ID
    force_login_student_for_each_test = False
    default_token_hash_str = "my0token0string"

    def get_get_flow_session_api_url(
            self, course_identifier=None, flow_id=None,
            auto_add_default_flow_id=True):
        course_identifier = (
            course_identifier or self.get_default_course_identifier())
        if auto_add_default_flow_id:
            flow_id = flow_id or self.flow_id
        kwargs = {"course_identifier": course_identifier}

        url = reverse("relate-course_get_flow_session", kwargs=kwargs)

        if flow_id:
            url += "?flow_id=%s" % flow_id
        return url

    def get_get_flow_session_content_url(
            self, course_identifier=None, flow_session_id=None,
            auto_add_default_flow_session_id=True):
        course_identifier = (
            course_identifier or self.get_default_course_identifier())
        if auto_add_default_flow_session_id:
            flow_session_id = (
                flow_session_id
                or self.get_default_flow_session_id(course_identifier))
        kwargs = {"course_identifier": course_identifier}

        url = reverse("relate-course_get_flow_session_content", kwargs=kwargs)

        if flow_session_id:
            url += "?flow_session_id=%s" % flow_session_id
        return url

    def create_token(self, token_hash_str=None, participation=None, **kwargs):
        token_hash_str = token_hash_str or self.default_token_hash_str
        participation = participation or self.instructor_participation

        from tests.factories import AuthenticationTokenFactory
        with mock.patch("tests.factories.make_sign_in_key") as mock_mk_sign_in_key:
            mock_mk_sign_in_key.return_value = token_hash_str
            token = AuthenticationTokenFactory(
                user=participation.user,
                participation=participation,
                **kwargs
            )
            return token

    def create_basic_auth(self, token=None, participation=None, user=None):
        participation = participation or self.instructor_participation
        user = user or participation.user
        token = token or self.create_token(participation=participation)
        basic_auth_str = "{}:{}_{}".format(
            user.username,
            token.id, self.default_token_hash_str)

        from base64 import b64encode
        return b64encode(basic_auth_str.encode("utf-8")).decode()


# }}}


# {{{ HackRepoMixin

class HackRepoMixin:

    # This is need to for correctly getting other blobs
    fallback_commit_sha = b"4124e0c23e369d6709a670398167cb9c2fe52d35"

    # This need to be configured when the module tested imported get_repo_blob
    # at module level
    get_repo_blob_patching_path = "course.content.get_repo_blob"

    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()

        class Blob:
            def __init__(self, yaml_file_name):
                with open(os.path.join(FAKED_YAML_PATH, yaml_file_name), "rb") as f:
                    data = f.read()
                self.data = data

        def get_repo_side_effect(repo, full_name, commit_sha, allow_tree=True):
            commit_sha_path_maps = COMMIT_SHA_MAP.get(full_name)
            if commit_sha_path_maps:
                assert isinstance(commit_sha_path_maps, list)
                for cs_map in commit_sha_path_maps:
                    if commit_sha.decode() in cs_map:
                        path = cs_map[commit_sha.decode()]["path"]
                        return Blob(path)

            return get_repo_blob(repo, full_name, cls.fallback_commit_sha,
                                 allow_tree=allow_tree)

        cls.batch_fake_get_repo_blob = mock.patch(cls.get_repo_blob_patching_path)
        cls.mock_get_repo_blob = cls.batch_fake_get_repo_blob.start()
        cls.mock_get_repo_blob.side_effect = get_repo_side_effect

    @classmethod
    def tearDownClass(cls):  # noqa
        # This must be done to avoid inconsistency
        super().tearDownClass()
        cls.batch_fake_get_repo_blob.stop()

    def get_current_page_ids(self):
        current_sha = self.course.active_git_commit_sha
        for commit_sha_path_maps in COMMIT_SHA_MAP.values():
            for cs_map in commit_sha_path_maps:
                if current_sha in cs_map:
                    return cs_map[current_sha]["page_ids"]

        raise ValueError("Page_ids for that commit_sha doesn't exist")

    def assertGradeInfoEqual(self, resp, expected_grade_info_dict=None):  # noqa
        grade_info = resp.context["grade_info"]

        assert isinstance(grade_info, GradeInfo)
        if not expected_grade_info_dict:
            import json
            error_msg = ("\n%s" % json.dumps(OrderedDict(
                sorted(
                    [(k, v) for (k, v) in grade_info.__dict__.items()])),
                indent=4))
            error_msg = error_msg.replace("null", "None")
            self.fail(error_msg)

        assert isinstance(expected_grade_info_dict, dict)

        grade_info_dict = grade_info.__dict__
        not_match_infos = []
        for k in grade_info_dict.keys():
            if grade_info_dict[k] != expected_grade_info_dict[k]:
                not_match_infos.append(
                    "'%s' is expected to be %s, while got %s"
                    % (k, str(expected_grade_info_dict[k]),
                       str(grade_info_dict[k])))

        if not_match_infos:
            self.fail("\n".join(not_match_infos))

# }}}

# vim: fdm=marker
