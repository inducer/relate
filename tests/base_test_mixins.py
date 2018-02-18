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

import sys
import six
import re
import tempfile
import os
import shutil
import hashlib
import datetime
import memcache
from copy import deepcopy
from django.test import Client, override_settings
from django.urls import reverse, resolve
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured

from tests.utils import mock
from course.models import (
    Course, Participation, ParticipationRole, FlowSession, FlowPageData,
    FlowPageVisit)
from course.constants import participation_status, user_status
from course.content import get_course_repo_path

ATOL = 1e-05

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
    mc = memcache.Client(['127.0.0.1:11211'])
except Exception:
    pass


SELECT2_HTML_FIELD_ID_SEARCH_PATTERN = re.compile(r'data-field_id="([^"]+)"')


def git_source_url_to_cache_keys(url):
    url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
    return (
        "test_course:%s" % url_hash,
        "test_sha:%s" % url_hash
    )


class CourseCreateFailure(Exception):
    pass


class ResponseContextMixin(object):
    """
    Response context refers to "the template Context instance that was used
    to render the template that produced the response content".
    Ref: https://docs.djangoproject.com/en/dev/topics/testing/tools/#django.test.Response.context  # noqa
    """
    def get_response_context_value_by_name(self, response, context_name):
        value = response.context.__getitem__(context_name)
        self.assertIsNotNone(
            value,
            msg="%s does not exist in given response" % context_name)
        return value

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
        self.assertEqual(value, expected_value)

    def assertResponseContextContains(self, resp,  # noqa
                                      context_name, expected_value, html=False):
        value = self.get_response_context_value_by_name(resp, context_name)
        if not html:
            self.assertIn(expected_value, value)
        else:
            self.assertInHTML(expected_value, value)

    def assertResponseContextRegex(  # noqa
            self, resp,  # noqa
            context_name, expected_value_regex):
        value = self.get_response_context_value_by_name(resp, context_name)
        six.assertRegex(self, value, expected_value_regex)

    def get_response_context_answer_feedback(self, response):
        return self.get_response_context_value_by_name(response, "feedback")

    def assertResponseContextAnswerFeedbackContainsFeedback(  # noqa
            self, response, expected_feedback,
            include_bulk_feedback=True, html=False):
        answer_feedback = self.get_response_context_answer_feedback(response)
        feedback_str = answer_feedback.feedback
        if include_bulk_feedback:
            feedback_str += answer_feedback.bulk_feedback

        self.assertTrue(hasattr(answer_feedback, "feedback"))
        if not html:
            self.assertIn(expected_feedback, feedback_str)
        else:
            self.assertInHTML(expected_feedback, feedback_str)

    def assertResponseContextAnswerFeedbackNotContainsFeedback(  # noqa
                                        self, response, expected_feedback,
                                        html=False):
        answer_feedback = self.get_response_context_answer_feedback(response)
        self.assertTrue(hasattr(answer_feedback, "feedback"))
        if not html:
            self.assertNotIn(expected_feedback, answer_feedback.feedback)
        else:
            self.assertInHTML(expected_feedback, answer_feedback.feedback, count=0)

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
                    - float(str(expected_correctness))) < ATOL,
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
                            select2_urlname='django_select2-json'):

        select2_url = reverse(select2_urlname)
        params = {"field_id": field_id}
        if term is not None:
            assert isinstance(term, six.string_types)
            term = term.strip()
            if term:
                params["term"] = term

        return self.c.get(select2_url, params,
                          HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def get_select2_response_data(self, response, key="results"):
        import json
        return json.loads(response.content.decode('utf-8'))[key]


class SuperuserCreateMixin(ResponseContextMixin):
    create_superuser_kwargs = CREATE_SUPERUSER_KWARGS

    @classmethod
    def setUpTestData(cls):  # noqa
        # Create superuser, without this, we cannot
        # create user, course and participation.
        cls.superuser = cls.create_superuser()
        cls.c = Client()
        cls.settings_git_root_override = (
            override_settings(GIT_ROOT=tempfile.mkdtemp()))
        cls.settings_git_root_override.enable()
        super(SuperuserCreateMixin, cls).setUpTestData()

    @classmethod
    def create_superuser(cls):
        return get_user_model().objects.create_superuser(
                                                **cls.create_superuser_kwargs)

    def get_sign_up_view_url(self):
        return reverse("relate-sign_up")

    def get_sign_up(self, follow=True):
        return self.c.get(self.get_sign_up_view_url(), follow=follow)

    def post_sign_up(self, data, follow=True):
        return self.c.post(self.get_sign_up_view_url(), data, follow=follow)

    def get_profile_view_url(self):
        return reverse("relate-user_profile")

    def get_profile(self, follow=True):
        return self.c.get(self.get_profile_view_url(), follow=follow)

    def post_profile(self, data, follow=True):
        data.update({"submit_user": [""]})
        return self.c.post(self.get_profile_view_url(), data, follow=follow)

    def post_signout(self, data, follow=True):
        return self.c.post(self.get_sign_up_view_url(), data, follow=follow)

    def get_impersonate_view_url(self):
        return reverse("relate-impersonate")

    def get_stop_impersonate_view_url(self):
        return reverse("relate-stop_impersonating")

    def get_impersonate(self):
        return self.c.get(self.get_impersonate_view_url())

    def post_impersonate(self, impersonatee, follow=True):
        data = {"add_impersonation_header": ["on"],
                "submit": [''],
                }
        data["user"] = [str(impersonatee.pk)]
        return self.c.post(self.get_impersonate_view_url(), data, follow=follow)

    def get_stop_impersonate(self, follow=True):
        return self.c.get(self.get_stop_impersonate_view_url(), follow=follow)

    def post_stop_impersonate(self, follow=True):
        data = {"submit": ['']}
        return self.c.post(
            self.get_stop_impersonate_view_url(), data, follow=follow)

    def get_confirm_stop_impersonate_view_url(self):
        return reverse("relate-confirm_stop_impersonating")

    def get_confirm_stop_impersonate(self, follow=True):
        return self.c.get(
            self.get_confirm_stop_impersonate_view_url(), follow=follow)

    def post_confirm_stop_impersonate(self, follow=True):
        return self.c.post(
            self.get_confirm_stop_impersonate_view_url(), {}, follow=follow)

    @classmethod
    def get_reset_password_url(cls, use_instid=False):
        kwargs = {}
        if use_instid:
            kwargs["field"] = "instid"
        return reverse("relate-reset_password", kwargs=kwargs)

    @classmethod
    def get_reset_password(cls, use_instid=False):
        return cls.c.get(cls.get_reset_password_url(use_instid))

    @classmethod
    def post_reset_password(cls, data, use_instid=False):
        return cls.c.post(cls.get_reset_password_url(use_instid),
                          data=data)

    def get_reset_password_stage2_url(self, user_id, sign_in_key, **kwargs):
        url = reverse("relate-reset_password_stage2", args=(user_id, sign_in_key))
        querystring = kwargs.pop("querystring", None)
        if querystring is not None:
            assert isinstance(querystring, dict)
            url += ("?%s"
                    % "&".join(
                        ["%s=%s" % (k, v)
                         for (k, v) in six.iteritems(querystring)]))
        return url

    def get_reset_password_stage2(self, user_id, sign_in_key, **kwargs):
        return self.c.get(self.get_reset_password_stage2_url(
            user_id=user_id, sign_in_key=sign_in_key, **kwargs))

    def post_reset_password_stage2(self, user_id, sign_in_key, data, **kwargs):
        return self.c.post(self.get_reset_password_stage2_url(
            user_id=user_id, sign_in_key=sign_in_key, **kwargs), data=data)

    def get_fake_time_url(self):
        return reverse("relate-set_fake_time")

    def get_set_fake_time(self):
        return self.c.get(self.get_fake_time_url())

    def post_set_fake_time(self, data, follow=True):
        return self.c.post(self.get_fake_time_url(), data, follow=follow)

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

    def get_set_pretend_facilities_url(self):
        return reverse("relate-set_pretend_facilities")

    def get_set_pretend_facilities(self):
        return self.c.get(self.get_set_pretend_facilities_url())

    def post_set_pretend_facilities(self, data, follow=True):
        return self.c.post(self.get_set_pretend_facilities_url(), data,
                           follow=follow)

    def force_remove_all_course_dir(self):
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
            form_errors = list(
                itertools.chain(*response.context[form_name].errors.values()))
        except TypeError:
            form_errors = None

        if form_errors is None or not form_errors:
            if errors:
                self.fail("%(form_name)s have no errors")
            else:
                return
        for err in errors:
            self.assertIn(err, form_errors)


# {{{ defined here so that they can be used by in classmethod and instance method

def get_flow_page_ordinal_from_page_id(flow_session_id, page_id):
    flow_page_data = FlowPageData.objects.get(
        flow_session__id=flow_session_id,
        page_id=page_id
    )
    return flow_page_data.page_ordinal


def get_flow_page_id_from_page_ordinal(flow_session_id, page_ordinal):
    flow_page_data = FlowPageData.objects.get(
        flow_session__id=flow_session_id,
        page_ordinal=page_ordinal
    )
    return flow_page_data.page_id

# }}}


class CoursesTestMixinBase(SuperuserCreateMixin):

    # A list of Dicts, each of which contain a course dict and a list of
    # participations. See SINGLE_COURSE_SETUP_LIST for the setup for one course.
    courses_setup_list = []
    none_participation_user_create_kwarg_list = []
    courses_attributes_extra_list = None
    override_settings_at_post_create_course = {}

    @classmethod
    def setUpTestData(cls):  # noqa
        super(CoursesTestMixinBase, cls).setUpTestData()
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
            try:
                cls.create_course(course_setup_kwargs)
            except Exception:
                raise

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

    @classmethod
    def post_create_course(cls, create_course_kwargs, raise_error=True,
                           login_superuser=True):
        # To speed up, use create_course instead, this is better used for tests
        if login_superuser:
            cls.c.force_login(cls.superuser)
        existing_course_count = Course.objects.count()
        with override_settings(**cls.override_settings_at_post_create_course):
            resp = cls.c.post(cls.get_set_up_new_course_url(),
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
                           "\n".join(["%s:%s" % (type(e).__name__, str(e))
                                      for e in errs]))
                        for field, errs
                        in six.iteritems(form_context.errors.as_data())]
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
            url_cache_key, commit_sha_cach_key = (
                git_source_url_to_cache_keys(last_course.git_source))
            mc.set_multi({url_cache_key: get_course_repo_path(last_course),
                          commit_sha_cach_key: last_course.active_git_commit_sha},
                         time=120000
                         )
        return resp

    @classmethod
    def create_course(cls, create_course_kwargs, raise_error=True):
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
                create_course_kwargs, raise_error=raise_error)
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
    def get_set_up_new_course_url(cls):
        return reverse("relate-set_up_new_course")

    @classmethod
    def get_set_up_new_course(cls):
        return cls.c.get(cls.get_update_course_url)

    @classmethod
    def get_edit_course_url(cls, course_identifier=None):
        return cls.get_course_view_url("relate-edit_course", course_identifier)

    @classmethod
    def post_edit_course(cls, data, course=None):
        course = course or cls.get_default_course()
        edit_course_url = cls.get_edit_course_url(course.identifier)
        return cls.c.post(edit_course_url, data)

    @classmethod
    def get_edit_course(cls, course=None):
        course = course or cls.get_default_course()
        return cls.c.get(cls.get_edit_course_url(course.identifier))

    @classmethod
    def get_course_page_url(cls, course_identifier=None):
        return cls.get_course_view_url("relate-course_page", course_identifier)

    def get_logged_in_user(self):
        try:
            logged_in_user_id = self.c.session['_auth_user_id']
            from django.contrib.auth import get_user_model
            logged_in_user = get_user_model().objects.get(
                pk=int(logged_in_user_id))
        except KeyError:
            logged_in_user = None
        return logged_in_user

    def temporarily_switch_to_user(self, switch_to):
        _self = self

        from functools import wraps

        class ClientUserSwitcher(object):
            def __init__(self, switch_to):
                self.client = _self.c
                self.switch_to = switch_to
                self.logged_in_user = _self.get_logged_in_user()

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
                @wraps(func)
                def wrapper(*args, **kw):
                    with self:
                        return func(*args, **kw)
                return wrapper

        return ClientUserSwitcher(switch_to)

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

    def get_latest_session_id(self, course_identifier):
        flow_session_qset = FlowSession.objects.filter(
            course__identifier=course_identifier).order_by('-pk')[:1]
        if flow_session_qset:
            return flow_session_qset[0].id
        else:
            return None

    def get_default_flow_session_id(self, course_identifier):
        raise NotImplementedError

    @classmethod
    def update_default_flow_session_id(cls, course_identifier):
        raise NotImplementedError

    def get_default_instructor_user(self, course_identifier):
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
    def start_flow(cls, flow_id, course_identifier=None):
        """
        Notice: this is a classmethod, so this will change the data
        created in setUpTestData, so don't do this in individual tests, or
        testdata will be different between tests.
        """
        course_identifier = course_identifier or cls.get_default_course_identifier()
        existing_session_count = FlowSession.objects.all().count()
        params = {"course_identifier": course_identifier,
                  "flow_id": flow_id}
        resp = cls.c.post(reverse("relate-view_start_flow", kwargs=params))
        assert resp.status_code == 302
        new_session_count = FlowSession.objects.all().count()
        assert new_session_count == existing_session_count + 1
        _, _, params = resolve(resp.url)
        del params["page_ordinal"]
        cls.default_flow_params = params
        cls.update_default_flow_session_id(course_identifier)
        return resp

    @classmethod
    def end_flow(cls, course_identifier=None, flow_session_id=None):
        """
        Be cautious that this is a classmethod
        """
        if cls.default_flow_params is None:
            raise RuntimeError("There's no started flow_sessions.")
        params = deepcopy(cls.default_flow_params)
        if course_identifier:
            params["course_identifier"] = course_identifier
        if flow_session_id:
            params["flow_session_id"] = flow_session_id
        resp = cls.c.post(reverse("relate-finish_flow_session_view",
                                  kwargs=params), {'submit': ['']})
        return resp

    def get_flow_params(self, course_identifier=None, flow_session_id=None):
        course_identifier = (
            course_identifier or self.get_default_course_identifier())
        if flow_session_id is None:
            flow_session_id = self.get_default_flow_session_id(course_identifier)
        return {
            "course_identifier": course_identifier,
            "flow_session_id": flow_session_id
        }

    def get_page_params(self, course_identifier=None, flow_session_id=None,
                        page_ordinal=None):
        page_params = self.get_flow_params(course_identifier, flow_session_id)
        if page_ordinal is None:
            page_ordinal = 0
        page_params.update({"page_ordinal": page_ordinal})
        return page_params

    def get_page_ordinal_via_page_id(
            self, page_id, course_identifier=None, flow_session_id=None):
        flow_params = self.get_flow_params(course_identifier, flow_session_id)
        return (
            get_flow_page_ordinal_from_page_id(
                flow_params["flow_session_id"], page_id))

    def get_page_view_url_by_ordinal(
            self, viewname, page_ordinal, course_identifier=None,
            flow_session_id=None):
        page_params = self.get_page_params(
            course_identifier, flow_session_id, page_ordinal)
        return reverse(viewname, kwargs=page_params)

    def get_page_view_url_by_page_id(
            self, viewname, page_id, course_identifier=None, flow_session_id=None):
        page_ordinal = self.get_page_ordinal_via_page_id(
            page_id, course_identifier, flow_session_id)
        return self.get_page_view_url_by_ordinal(
            viewname, page_ordinal, course_identifier, flow_session_id)

    def get_page_url_by_ordinal(
            self, page_ordinal, course_identifier=None, flow_session_id=None):
        return self.get_page_view_url_by_ordinal(
            "relate-view_flow_page",
            page_ordinal, course_identifier, flow_session_id)

    def get_page_url_by_page_id(
            self, page_id, course_identifier=None, flow_session_id=None):
        page_ordinal = self.get_page_ordinal_via_page_id(
            page_id, course_identifier, flow_session_id)
        return self.get_page_url_by_ordinal(
            page_ordinal, course_identifier, flow_session_id)

    def get_page_grading_url_by_ordinal(
            self, page_ordinal, course_identifier=None, flow_session_id=None):
        return self.get_page_view_url_by_ordinal(
            "relate-grade_flow_page",
            page_ordinal, course_identifier, flow_session_id)

    def get_page_grading_url_by_page_id(
            self, page_id, course_identifier=None, flow_session_id=None):
        page_ordinal = self.get_page_ordinal_via_page_id(
            page_id, course_identifier, flow_session_id)
        return self.get_page_grading_url_by_ordinal(
            page_ordinal, course_identifier, flow_session_id)

    def post_answer_by_ordinal(
            self, page_ordinal, answer_data,
            course_identifier=None, flow_session_id=None):
        submit_data = answer_data
        submit_data.update({"submit": ["Submit final answer"]})
        resp = self.c.post(
            self.get_page_url_by_ordinal(
                page_ordinal, course_identifier, flow_session_id),
            submit_data)
        return resp

    def post_answer_by_page_id(self, page_id, answer_data,
                               course_identifier=None, flow_session_id=None):
        page_ordinal = self.get_page_ordinal_via_page_id(
            page_id, course_identifier, flow_session_id)
        return self.post_answer_by_ordinal(
            page_ordinal, answer_data, course_identifier, flow_session_id)

    @classmethod
    def post_answer_by_ordinal_class(cls, page_ordinal, answer_data,
                                     course_identifier, flow_session_id):
        submit_data = answer_data
        submit_data.update({"submit": ["Submit final answer"]})
        page_params = {
            "course_identifier": course_identifier,
            "flow_session_id": flow_session_id,
            "page_ordinal": page_ordinal
        }
        page_url = reverse("relate-view_flow_page", kwargs=page_params)
        resp = cls.c.post(page_url, submit_data)
        return resp

    @classmethod
    def post_answer_by_page_id_class(cls, page_id, answer_data,
                                     course_identifier, flow_session_id):
        page_ordinal = get_flow_page_ordinal_from_page_id(flow_session_id, page_id)
        return cls.post_answer_by_ordinal_class(page_ordinal, answer_data,
                                                course_identifier, flow_session_id)

    def post_grade_by_ordinal(self, page_ordinal, grade_data,
                              course_identifier=None, flow_session_id=None,
                              force_login_instructor=True):
        post_data = {"submit": [""]}
        post_data.update(grade_data)

        page_params = self.get_page_params(
            course_identifier, flow_session_id, page_ordinal)

        force_login_user = self.get_logged_in_user()
        if force_login_instructor:
            force_login_user = self.get_default_instructor_user(
                page_params["course_identifier"])

        with self.temporarily_switch_to_user(force_login_user):
            response = self.c.post(
                self.get_page_grading_url_by_ordinal(**page_params),
                data=post_data,
                follow=True)
        return response

    def post_grade_by_page_id(self, page_id, grade_data,
                              course_identifier=None, flow_session_id=None,
                              force_login_instructor=True):
        page_ordinal = self.get_page_ordinal_via_page_id(
            page_id, course_identifier, flow_session_id)

        return self.post_grade_by_ordinal(
            page_ordinal, grade_data, course_identifier,
            flow_session_id, force_login_instructor)

    def assertSessionScoreEqual(  # noqa
            self, expect_score, course_identifier=None, flow_session_id=None):
        if flow_session_id is None:
            flow_params = self.get_flow_params(course_identifier, flow_session_id)
            flow_session_id = flow_params["flow_session_id"]
        flow_session = FlowSession.objects.get(id=flow_session_id)
        if expect_score is not None:
            from decimal import Decimal
            self.assertEqual(flow_session.points, Decimal(str(expect_score)))
        else:
            self.assertIsNone(flow_session.points)

    def get_page_submit_history_url_by_ordinal(
            self, page_ordinal, course_identifier=None, flow_session_id=None):
        return self.get_page_view_url_by_ordinal(
            "relate-get_prev_answer_visits_dropdown_content",
            page_ordinal, course_identifier, flow_session_id)

    def get_page_grade_history_url_by_ordinal(
            self, page_ordinal, course_identifier=None, flow_session_id=None):
        return self.get_page_view_url_by_ordinal(
            "relate-get_prev_grades_dropdown_content",
            page_ordinal, course_identifier, flow_session_id)

    def get_page_submit_history_by_ordinal(
            self, page_ordinal, course_identifier=None, flow_session_id=None):
        resp = self.c.get(
            self.get_page_submit_history_url_by_ordinal(
                page_ordinal, course_identifier, flow_session_id),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        return resp

    def get_page_grade_history_by_ordinal(
            self, page_ordinal, course_identifier=None, flow_session_id=None):
        resp = self.c.get(
            self.get_page_grade_history_url_by_ordinal(
                page_ordinal, course_identifier, flow_session_id),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        return resp

    def assertSubmitHistoryItemsCount(  # noqa
            self, page_ordinal, expected_count, course_identifier=None,
            flow_session_id=None):
        resp = self.get_page_submit_history_by_ordinal(
            page_ordinal, course_identifier, flow_session_id)
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
                page_ordinal, course_identifier, flow_session_id)

        import json
        result = json.loads(resp.content.decode())["result"]
        self.assertEqual(len(result), expected_count)

    def get_update_course_url(self, course_identifier=None):
        if course_identifier is None:
            course_identifier = self.get_default_course_identifier()
        return reverse("relate-update_course", args=[course_identifier])

    def post_update_course_content(self, commit_sha,
                                   fetch_update=False,
                                   prevent_discarding_revisions=True,
                                   force_login_instructor=True,
                                   course=None,
                                   ):
        # course instead of course_identifier because we need to do
        # refresh_from_db
        course = course or self.get_default_course()

        try:
            commit_sha = commit_sha.decode()
        except Exception:
            pass

        data = {"new_sha": [commit_sha]}

        if not prevent_discarding_revisions:
            data["prevent_discarding_revisions"] = ["on"]

        if not fetch_update:
            data["update"] = ["Update"]
        else:
            data["fetch_update"] = ["Fetch and update"]

        force_login_user = None
        if force_login_instructor:
            force_login_user = self.get_default_instructor_user(course.identifier)

        with self.temporarily_switch_to_user(force_login_user):
            response = self.c.post(
                self.get_update_course_url(course.identifier), data)
            course.refresh_from_db()

        return response

    def get_page_data_by_page_id(
            self, page_id, course_identifier=None, flow_session_id=None):
        flow_params = self.get_flow_params(course_identifier, flow_session_id)
        return FlowPageData.objects.get(
            flow_session_id=flow_params["flow_session_id"], page_id=page_id)

    def get_page_visits(self, course_identifier=None,
                        flow_session_id=None, page_ordinal=None, page_id=None,
                        **kwargs):
        query_kwargs = {}
        if kwargs.get("answer_visit", False):
            query_kwargs.update({"answer__isnull": False})
        flow_params = self.get_flow_params(course_identifier, flow_session_id)
        query_kwargs.update({"flow_session_id": flow_params["flow_session_id"]})
        if page_ordinal is not None:
            query_kwargs.update({"page_data__page_ordinal": page_ordinal})
        elif page_id is not None:
            query_kwargs.update({"page_data__page_id": page_id})
        return FlowPageVisit.objects.filter(**query_kwargs)

    def get_last_answer_visit(self, course_identifier=None,
                              flow_session_id=None, page_ordinal=None,
                              page_id=None, assert_not_none=True):
        result_qset = self.get_page_visits(course_identifier,
                                           flow_session_id, page_ordinal, page_id,
                                           answer_visit=True).order_by('-pk')[:1]
        if result_qset:
            result = result_qset[0]
        else:
            result = None
        if assert_not_none:
            self.assertIsNotNone(result, "The query returns None")
        return result

    def download_all_submissions_url(self, flow_id, course_identifier):
        params = {"course_identifier": course_identifier,
                  "flow_id": flow_id}
        return reverse("relate-download_all_submissions", kwargs=params)

    def get_download_all_submissions(self, flow_id, course_identifier=None):
        if course_identifier is None:
            course_identifier = self.get_default_course_identifier()

        return self.c.get(
            self.download_all_submissions_url(flow_id, course_identifier))

    def post_download_all_submissions_by_group_page_id(
            self, group_page_id, flow_id, course_identifier=None, **kwargs):
        """
        :param group_page_id: format: group_id/page_id
        :param flow_id:
        :param course_identifier:
        :param kwargs: for updating the default post_data
        :return: response
        """
        if course_identifier is None:
            course_identifier = self.get_default_course_identifier()

        data = {'restrict_to_rules_tag': '<<<ALL>>>',
                'which_attempt': 'last',
                'extra_file': '', 'download': 'Download',
                'page_id': group_page_id,
                'non_in_progress_only': 'on'}

        data.update(kwargs)

        return self.c.post(
            self.download_all_submissions_url(flow_id, course_identifier),
            data=data
        )

    def get_flow_page_analytics(self, flow_id, group_id, page_id,
                                course_identifier=None):
        if course_identifier is None:
            course_identifier = self.get_default_course_identifier()

        params = {"course_identifier": course_identifier,
                  "flow_id": flow_id,
                  "group_id": group_id,
                  "page_id": page_id}

        return self.c.get(reverse("relate-page_analytics", kwargs=params))


class SingleCourseTestMixin(CoursesTestMixinBase):
    courses_setup_list = SINGLE_COURSE_SETUP_LIST

    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCourseTestMixin, cls).setUpTestData()
        assert len(cls.course_qset) == 1
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
        cls.course_page_url = cls.get_course_page_url()

    def setUp(self):  # noqa
        super(SingleCourseTestMixin, self).setUp()

        # reload objects created during setUpTestData in case they were modified in
        # tests. Ref: https://goo.gl/AuzJRC#django.test.TestCase.setUpTestData
        self.course.refresh_from_db()
        self.instructor_participation.refresh_from_db()
        self.student_participation.refresh_from_db()
        self.ta_participation.refresh_from_db()

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

        import six
        for k, v in six.iteritems(kwargs):
            if v is None:
                kwargs[k] = ""
        return kwargs


class TwoCourseTestMixin(CoursesTestMixinBase):
    courses_setup_list = []

    @classmethod
    def setUpTestData(cls):  # noqa
        super(TwoCourseTestMixin, cls).setUpTestData()
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

        cls.c.logout()

    def setUp(self):  # noqa
        super(TwoCourseTestMixin, self).setUp()
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


class SingleCoursePageTestMixin(SingleCourseTestMixin):
    # This serves as cache
    _default_session_id = None

    @property
    def flow_id(self):
        raise NotImplementedError

    @classmethod
    def update_default_flow_session_id(cls, course_identifier):
        cls._default_session_id = cls.default_flow_params["flow_session_id"]

    def get_default_flow_session_id(self, course_identifier):
        if self._default_session_id is not None:
            return self._default_session_id
        self._default_session_id = self.get_latest_session_id(course_identifier)
        return self._default_session_id


class TwoCoursePageTestMixin(TwoCourseTestMixin):
    _course1_default_session_id = None
    _course2_default_session_id = None

    @property
    def flow_id(self):
        raise NotImplementedError

    def get_default_flow_session_id(self, course_identifier):
        if course_identifier == self.course1.identifier:
            if self._course1_default_session_id is not None:
                return self._course1_default_session_id
            self._course1_default_session_id = (
                self.get_last_session_id(course_identifier))
            return self._course1_default_session_id
        if course_identifier == self.course2.identifier:
            if self._course2_default_session_id is not None:
                return self._course2_default_session_id
            self._course2_default_session_id = (
                self.get_last_session_id(course_identifier))
            return self._course2_default_session_id

    @classmethod
    def update_default_flow_session_id(cls, course_identifier):
        new_session_id = cls.default_flow_params["flow_session_id"]
        if course_identifier == cls.course1.identifier:
            cls._course1_default_session_id = new_session_id
        elif course_identifier == cls.course2.identifier:
            cls._course2_default_session_id = new_session_id


class FallBackStorageMessageTestMixin(object):
    # In case other message storage are used, the following is the default
    # storage used by django and RELATE. Tests which concerns the message
    # should not include this mixin.
    storage = 'django.contrib.messages.storage.fallback.FallbackStorage'

    def setUp(self):  # noqa
        super(FallBackStorageMessageTestMixin, self).setUp()
        self.msg_settings_override = override_settings(MESSAGE_STORAGE=self.storage)
        self.msg_settings_override.enable()
        self.addCleanup(self.msg_settings_override.disable)

    def get_listed_storage_from_response(self, response):
        return list(self.get_response_context_value_by_name(response, 'messages'))

    def clear_message_response_storage(self, response):
        # this should only be used for debug, because we are using private method
        # which might change
        try:
            storage = self.get_response_context_value_by_name(response, 'messages')
        except AssertionError:
            # message doesn't exist in response context
            return
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
        if not isinstance(expected_messages, list):
            expected_messages = [expected_messages]
        self.assertEqual(len([m for m in storage]), len(expected_messages))
        self.assertEqual([m.message for m in storage], expected_messages)

    def assertResponseMessagesEqualRegex(self, response, expected_message_regexs):  # noqa
        storage = self.get_listed_storage_from_response(response)
        if not isinstance(expected_message_regexs, list):
            expected_message_regexs = [expected_message_regexs]
        self.assertEqual(len([m for m in storage]), len(expected_message_regexs))
        messages = [m.message for m in storage]
        for idx, m in enumerate(messages):
            six.assertRegex(self, m, expected_message_regexs[idx])

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


class SubprocessRunpyContainerMixin(object):
    """
    This mixin is used to fake a runpy container, only needed when
    the TestCase include test(s) for code questions
    """
    @classmethod
    def setUpClass(cls):  # noqa
        if six.PY2:
            from unittest import SkipTest
            raise SkipTest("In process fake container is configured for "
                           "PY3 only, since currently runpy docker only "
                           "provide PY3 envrionment")

        super(SubprocessRunpyContainerMixin, cls).setUpClass()

        python_executable = os.getenv("PY_EXE")

        if not python_executable:
            python_executable = sys.executable

        import subprocess
        args = [python_executable,
                os.path.abspath(
                    os.path.join(
                        os.path.dirname(__file__), os.pardir,
                        "docker-image-run-py", "runpy")),
                ]
        cls.faked_container_process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,

            # because runpy prints to stderr
            stderr=subprocess.DEVNULL
        )

    def setUp(self):
        super(SubprocessRunpyContainerMixin, self).setUp()
        self.faked_container_patch = mock.patch(
            "course.page.code.SPAWN_CONTAINERS_FOR_RUNPY", False)
        self.faked_container_patch.start()
        self.addCleanup(self.faked_container_patch.stop)

    @classmethod
    def tearDownClass(cls):  # noqa
        super(SubprocessRunpyContainerMixin, cls).tearDownClass()

        from course.page.code import SPAWN_CONTAINERS_FOR_RUNPY
        # Make sure SPAWN_CONTAINERS_FOR_RUNPY is reset to True
        assert SPAWN_CONTAINERS_FOR_RUNPY
        if sys.platform.startswith("win"):
            # Without these lines, tests on Appveyor hanged when all tests
            # finished.
            # However, On nix platforms, these lines resulted in test
            # failure when there were more than one TestCases which were using
            # this mixin. So we don't kill the subprocess, and it won't bring
            # bad side effects to remainder tests.
            cls.faked_container_process.kill()


def improperly_configured_cache_patch():
    # can be used as context manager or decorator
    if six.PY3:
        built_in_import_path = "builtins.__import__"
        import builtins  # noqa
    else:
        built_in_import_path = "__builtin__.__import__"
        import __builtin__ as builtins  # noqa
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
        super(AdminTestMixin, cls).setUpTestData()  # noqa

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
        return reverse("admin:%s_%s_changelist" % (app_name, model_name))

    @classmethod
    def get_admin_change_view_url(cls, app_name, model_name, args=None):
        if args is None:
            args = []
        return reverse("admin:%s_%s_change" % (app_name, model_name), args=args)

    def get_admin_form_fields(self, response):
        """
        Return a list of AdminFields for the AdminForm in the response.
        """
        admin_form = response.context['adminform']
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

    def get_changelist(self, request, model, modeladmin):
        from django.contrib.admin.views.main import ChangeList
        return ChangeList(
            request, model, modeladmin.list_display,
            modeladmin.list_display_links, modeladmin.list_filter,
            modeladmin.date_hierarchy, modeladmin.search_fields,
            modeladmin.list_select_related, modeladmin.list_per_page,
            modeladmin.list_max_show_all, modeladmin.list_editable, modeladmin,
        )

    def get_filterspec_list(self, request, changelist=None, model=None,
                            modeladmin=None):
        if changelist is None:
            assert request and model and modeladmin
            changelist = self.get_changelist(request, model, modeladmin)

        filterspecs = changelist.get_filters(request)[0]
        filterspec_list = []
        for filterspec in filterspecs:
            choices = tuple(c['display'] for c in filterspec.choices(changelist))
            filterspec_list.append(choices)

        return filterspec_list

# }}}

# vim: fdm=marker
