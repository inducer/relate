# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0005_make_session_course_not_nullable'),
    ]

    operations = [
        migrations.AddField(
            model_name='flowpagevisit',
            name='remote_address',
            field=models.GenericIPAddressField(null=True, blank=True),
            preserve_default=True,
        ),
    ]
