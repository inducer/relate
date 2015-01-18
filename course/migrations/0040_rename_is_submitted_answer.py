# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0039_flow_start_rules'),
    ]

    operations = [
        migrations.RenameField(
            model_name='flowpagevisit',
            old_name='is_graded_answer',
            new_name='is_submitted_answer',
        ),
    ]
