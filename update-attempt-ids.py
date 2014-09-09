# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import django

django.setup()

from course.models import GradeChange

for gchange in GradeChange.objects.all():
    if gchange.flow_session is not None:
        gchange.attempt_id = "flow-session-%d" % gchange.flow_session.id
        gchange.save()
