# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0044_require_notify_email'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='listed',
            field=models.BooleanField(default=False, help_text='Should the course be listed on the main page?'),
            preserve_default=True,
        ),
        migrations.AlterField(
            model_name='course',
            name='hidden',
            field=models.BooleanField(default=True, help_text='Is the course only accessible to course staff?'),
            preserve_default=True,
        ),
    ]
