# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0054_add_auditor_role'),
    ]

    operations = [
        migrations.CreateModel(
            name='Facility',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('identifier', models.CharField(help_text=b'Format is lower-case-with-hyphens. Do not use spaces.', unique=True, max_length=50)),
                ('description', models.CharField(max_length=100)),
            ],
        ),
        migrations.CreateModel(
            name='FacilityIPRange',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('ip_range', models.CharField(max_length=200)),
                ('ip_range_description', models.CharField(max_length=100)),
                ('facility', models.ForeignKey(to='course.Facility')),
            ],
        ),
    ]
