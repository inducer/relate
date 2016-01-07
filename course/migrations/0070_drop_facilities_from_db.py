# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0069_exam_lockdown'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='facilityiprange',
            name='facility',
        ),
        migrations.DeleteModel(
            name='Facility',
        ),
        migrations.DeleteModel(
            name='FacilityIPRange',
        ),
    ]
