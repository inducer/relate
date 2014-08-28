# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0009_more_stored_grading_changes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flowsession',
            name='flow_id',
            field=models.CharField(max_length=200, db_index=True),
        ),
    ]
