# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0048_default_listed_to_true'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='accepts_enrollment',
            field=models.BooleanField(default=True),
            preserve_default=True,
        ),
    ]
