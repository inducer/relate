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

from django.utils.timezone import now
import factory
from django.contrib.auth import get_user_model
from django.utils.translation import ugettext_lazy as _
from course import models
from course import constants

from .base_test_mixins import SINGLE_COURSE_SETUP_LIST

DEFAULT_COURSE_IDENTIFIER = SINGLE_COURSE_SETUP_LIST[0]["course"]["identifier"]
DEFAULT_FLOW_ID = "quiz-test"
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


class CourseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Course
        django_get_or_create = ('identifier',)

    identifier = DEFAULT_COURSE_IDENTIFIER


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

    @factory.post_generation
    def roles(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return
        else:
            role = ParticipationRoleFactory(course=self.course)
            self.roles.set([role])


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
        lambda x: x.page_data.flow_session.participation.user)
    answer = None
