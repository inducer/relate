# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0010_add_flowsession_flow_id_index'),
    ]

    operations = [
        migrations.AddField(
            model_name='flowsession',
            name='access_rules_id',
            field=models.CharField(max_length=200, null=True),
            preserve_default=True,
        ),
    ]
