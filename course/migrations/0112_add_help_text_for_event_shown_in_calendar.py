# -*- coding: utf-8 -*-
# Generated by Django 1.10.7 on 2017-09-25 10:37
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0111_alter_git_source_in_course_to_a_required_field'),
    ]

    operations = [
        migrations.AlterField(
            model_name='event',
            name='shown_in_calendar',
            field=models.BooleanField(default=True, help_text="Shown in students' calendar", verbose_name='Shown in calendar'),
        ),
    ]
