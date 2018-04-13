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

import six
import pytz
from datetime import datetime

from django.utils.timezone import now
import factory
from factory import fuzzy
from django.contrib.auth import get_user_model
from django.utils.translation import ugettext_lazy as _

from course import models
from course import constants

from tests.base_test_mixins import SINGLE_COURSE_SETUP_LIST
from tests.constants import QUIZ_FLOW_ID

DEFAULT_COURSE_IDENTIFIER = SINGLE_COURSE_SETUP_LIST[0]["course"]["identifier"]
DEFAULT_FLOW_ID = QUIZ_FLOW_ID
DEFAULT_GRADE_IDENTIFIER = "la_quiz"
DEFAULT_GRADE_AGGREGATION_STRATEGY = constants.grade_aggregation_strategy.use_latest
DEFAULT_GOPP_TITLE = "TEST RELATE Test Quiz"


def get_default_gopp_name(title=DEFAULT_GOPP_TITLE):
    return (
            _("Flow: %(flow_desc_title)s")
            % {"flow_desc_title": title})


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = get_user_model()

    username = factory.Sequence(lambda n: "testuser_%03d" % n)
    email = factory.Sequence(lambda n: "test_factory_%03d@exmaple.com" % n)
    status = constants.user_status.active
    password = factory.Sequence(lambda n: "password_%03d" % n)
    institutional_id = factory.Sequence(lambda n: "institutional_id%03d" % n)


class CourseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Course
        django_get_or_create = ('identifier', 'git_source')

    identifier = DEFAULT_COURSE_IDENTIFIER
    name = "test-course"
    number = factory.Sequence(lambda n: "%03d" % n)
    time_period = "Spring"
    git_source = SINGLE_COURSE_SETUP_LIST[0]["course"]["git_source"]
    notify_email = factory.Sequence(lambda n: "test_notify_%03d@exmaple.com" % n)
    from_email = factory.Sequence(lambda n: "test_from_%03d@exmaple.com" % n)
    active_git_commit_sha = "some_sha"


class ParticipationRoleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.ParticipationRole
        django_get_or_create = ('course', 'identifier',)

    course = factory.SubFactory(CourseFactory)
    identifier = "student"


class ParticipationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Participation

    user = factory.SubFactory(UserFactory)
    course = factory.SubFactory(CourseFactory)
    enroll_time = factory.LazyFunction(now)
    status = constants.participation_status.active

    @factory.post_generation
    def roles(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return

        if extracted:
            for role in extracted:
                if isinstance(role, six.string_types):
                    role = ParticipationRoleFactory(
                        course=self.course, identifier=role)
                else:
                    assert isinstance(role, models.ParticipationRole)
                self.roles.set([role])
                return

        role = ParticipationRoleFactory(course=self.course)
        self.roles.set([role])


class ParticipationTagFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.ParticipationTag
        django_get_or_create = ('course', 'name', 'shown_to_participant')

    course = factory.SubFactory(CourseFactory)
    name = "tag1"
    shown_to_participant = True


class FlowSessionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.FlowSession

    course = factory.lazy_attribute(lambda x: x.participation.course)
    participation = factory.SubFactory(ParticipationFactory)
    user = factory.lazy_attribute(lambda x: x.participation.user)
    active_git_commit_sha = factory.lazy_attribute(
        lambda x: x.course.active_git_commit_sha)
    flow_id = DEFAULT_FLOW_ID
    start_time = factory.LazyFunction(now)
    in_progress = False
    expiration_mode = constants.flow_session_expiration_mode.end


class GradingOpportunityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.GradingOpportunity
        django_get_or_create = ('course', 'identifier',)

    course = factory.SubFactory(CourseFactory)
    identifier = DEFAULT_GRADE_IDENTIFIER
    name = get_default_gopp_name()
    flow_id = DEFAULT_FLOW_ID
    aggregation_strategy = DEFAULT_GRADE_AGGREGATION_STRATEGY


class FlowPageDataFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.FlowPageData

    flow_session = factory.SubFactory(FlowSessionFactory)
    page_ordinal = 1
    page_type = "TestPageType"
    group_id = "TestGroupId"
    page_id = "TestPageId"
    data = {}
    title = "TestPageTitle"


class FlowPageVisitFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.FlowPageVisit

    page_data = factory.SubFactory(FlowPageDataFactory)
    flow_session = factory.lazy_attribute(lambda x: x.page_data.flow_session)
    visit_time = factory.LazyFunction(now)
    user = factory.lazy_attribute(
        lambda x: x.page_data.flow_session.participation.user
        if x.page_data.flow_session.participation is not None else None)
    answer = None


class FlowPageVisitGradeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.FlowPageVisitGrade

    visit = factory.SubFactory(FlowPageVisitFactory)
    grade_time = factory.lazy_attribute(lambda x: x.visit.visit_time)
    correctness = None


class EventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Event

    course = factory.SubFactory(CourseFactory)
    kind = "default_kind"
    ordinal = factory.Sequence(lambda n: n)
    time = factory.LazyFunction(now)


class GradeChangeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.GradeChange

    opportunity = factory.SubFactory(GradingOpportunityFactory)
    participation = factory.SubFactory(ParticipationFactory)
    state = constants.grade_state_change_types.graded
    attempt_id = None
    points = None
    max_points = 10
    comment = None
    due_time = None
    creator = None
    grade_time = now()
    flow_session = factory.SubFactory(FlowSessionFactory)


class ParticipationPreapprovalFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.ParticipationPreapproval

    email = factory.Sequence(lambda n: "test_preappro_%03d@preapprv.com" % n)
    institutional_id = factory.Sequence(lambda n: "%03d" % n)
    course = factory.SubFactory(CourseFactory)

    @factory.post_generation
    def roles(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return
        if extracted:
            for role in extracted:
                if isinstance(role, six.string_types):
                    role = ParticipationRoleFactory(
                        course=self.course, identifier=role)
                else:
                    assert isinstance(role, models.ParticipationRole)
                self.roles.set([role])
                return
        else:
            role = ParticipationRoleFactory(course=self.course)
            self.roles.set([role])


def generate_random_hash():
    import hashlib
    from random import random

    hash = hashlib.sha1()
    hash.update(str(random()).encode())
    hash.hexdigest()
    return hash.hexdigest()[:10]


class AuthenticationTokenFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.AuthenticationToken

    user = factory.lazy_attribute(lambda x: x.participation.user)
    participation = factory.SubFactory(ParticipationFactory)

    description = factory.Sequence(
        lambda n: "test description %03d" % n)

    token_hash = fuzzy.FuzzyText()

    @factory.post_generation
    def restrict_to_participation_role(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return
        else:
            role = ParticipationRoleFactory(course=self.participation.course)
            self.restrict_to_participation_role = role


class InstantFlowRequestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.InstantFlowRequest
        django_get_or_create = ('course', 'flow_id')

    course = factory.SubFactory(CourseFactory)
    flow_id = "my_flow_id"
    start_time = fuzzy.FuzzyDateTime(
        datetime(2019, 1, 1, tzinfo=pytz.UTC),
        datetime(2019, 1, 31, tzinfo=pytz.UTC))
    end_time = fuzzy.FuzzyDateTime(
        datetime(2019, 2, 1, tzinfo=pytz.UTC),
        datetime(2019, 3, 1, tzinfo=pytz.UTC))
    cancelled = False


class FlowRuleExceptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.FlowRuleException

    flow_id = DEFAULT_FLOW_ID
    participation = factory.SubFactory(ParticipationFactory)
    creation_time = fuzzy.FuzzyDateTime(
        datetime(2019, 1, 1, tzinfo=pytz.UTC),
        datetime(2019, 1, 31, tzinfo=pytz.UTC))

    kind = constants.flow_rule_kind.start
    rule = {
        "if_before": "some_date",
    }
    active = True


class InstantMessageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.InstantMessage
        django_get_or_create = ('participation', 'text')

    participation = factory.SubFactory(ParticipationFactory)
    text = fuzzy.FuzzyText()
    time = fuzzy.FuzzyDateTime(
        datetime(2019, 2, 1, tzinfo=pytz.UTC),
        datetime(2019, 3, 1, tzinfo=pytz.UTC))


class ExamFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Exam
        django_get_or_create = ('course', 'description')

    course = factory.SubFactory(CourseFactory)
    description = "desc of exam"
    flow_id = DEFAULT_FLOW_ID
    active = True
    listed = True

    no_exams_before = fuzzy.FuzzyDateTime(
        datetime(2019, 1, 1, tzinfo=pytz.UTC),
        datetime(2019, 1, 31, tzinfo=pytz.UTC))
    no_exams_after = fuzzy.FuzzyDateTime(
        datetime(2019, 2, 1, tzinfo=pytz.UTC),
        datetime(2019, 3, 1, tzinfo=pytz.UTC))


class ExamTicketFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.ExamTicket
        django_get_or_create = ('exam', 'participation')

    exam = factory.SubFactory(ExamFactory)

    participation = factory.SubFactory(ParticipationFactory)

    creation_time = now()
    state = constants.exam_ticket_states.valid
    code = fuzzy.FuzzyText()
    valid_start_time = fuzzy.FuzzyDateTime(
        datetime(2019, 1, 1, tzinfo=pytz.UTC),
        datetime(2019, 1, 31, tzinfo=pytz.UTC))
    valid_end_time = fuzzy.FuzzyDateTime(
        datetime(2019, 2, 1, tzinfo=pytz.UTC),
        datetime(2019, 3, 1, tzinfo=pytz.UTC))
    restrict_to_facility = ""
