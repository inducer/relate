# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0058_differentiate_see_answer_permission'),
    ]

    operations = [
        migrations.AlterField(
            model_name='facilityiprange',
            name='facility',
            field=models.ForeignKey(related_name='ip_ranges', to='course.Facility', on_delete=models.CASCADE),
        ),
    ]
