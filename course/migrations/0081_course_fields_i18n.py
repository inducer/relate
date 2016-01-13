# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0080_remove_userstatus'),
    ]

    operations = [
        migrations.AlterField(
            model_name='course',
            name='name',
            field=models.CharField(help_text="A human-readable name for the course. (e.g. 'Numerical Methods')", max_length=200, null=True, verbose_name='Course name'),
        ),
        migrations.AlterField(
            model_name='course',
            name='number',
            field=models.CharField(help_text="A human-readable course number/ID for the course (e.g. 'CS123')", max_length=200, null=True, verbose_name='Course number'),
        ),
        migrations.AlterField(
            model_name='course',
            name='time_period',
            field=models.CharField(help_text="A human-readable description of the time period for the course (e.g. 'Fall 2014')", max_length=200, null=True, verbose_name='Time Period'),
        ),
    ]
