# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0030_change_expmode_descr'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='shown_in_calendar',
            field=models.BooleanField(default=True),
            preserve_default=True,
        ),
    ]
