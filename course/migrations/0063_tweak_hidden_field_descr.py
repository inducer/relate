# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0062_course_course_root_path'),
    ]

    operations = [
        migrations.AlterField(
            model_name='course',
            name='hidden',
            field=models.BooleanField(default=True, help_text='Is the course only accessible to course staff?', verbose_name='Only visible to course staff'),
        ),
    ]
