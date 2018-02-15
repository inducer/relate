# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0008_add_flow_page_visit_grade'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flowaccessexceptionentry',
            name='exception',
            field=models.ForeignKey(related_name='entries', to='course.FlowAccessException', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='flowpagedata',
            name='flow_session',
            field=models.ForeignKey(related_name='page_data', to='course.FlowSession', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='flowpagevisitgrade',
            name='visit',
            field=models.ForeignKey(related_name='grades', to='course.FlowPageVisit', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='gradechange',
            name='flow_session',
            field=models.ForeignKey(related_name='grade_changes', blank=True, to='course.FlowSession', null=True, on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='userstatus',
            name='user',
            field=models.OneToOneField(related_name='user_status', to=settings.AUTH_USER_MODEL, on_delete=models.CASCADE),
        ),
    ]
