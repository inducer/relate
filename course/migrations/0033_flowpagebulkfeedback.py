# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import jsonfield.fields


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0032_access_rules_not_required'),
    ]

    operations = [
        migrations.CreateModel(
            name='FlowPageBulkFeedback',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('bulk_feedback', jsonfield.fields.JSONField(null=True, blank=True)),
                ('grade', models.ForeignKey(to='course.FlowPageVisitGrade')),
                ('page_data', models.OneToOneField(to='course.FlowPageData')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
    ]
