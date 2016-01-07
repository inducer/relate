# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0068_exam_tickets'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='facility',
            name='exams_only',
        ),
        migrations.AddField(
            model_name='exam',
            name='lock_down_sessions',
            field=models.BooleanField(default=True, help_text='Only allow access to exam content (and no other content in this RELATE instance) in sessions logged in through this exam', verbose_name='Lock down sessions'),
        ),
    ]
