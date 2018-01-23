# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0016_flowpagevisitgrade_graded_at_git_commit_sha'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='all_day',
            field=models.BooleanField(default=False, help_text='Only affects the rendering in the class calendar, in that a start time is not shown'),
            preserve_default=True,
        ),
    ]
