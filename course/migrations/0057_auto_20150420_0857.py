# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0056_facility_tweaks'),
    ]

    operations = [
        migrations.AlterField(
            model_name='course',
            name='from_email',
            field=models.EmailField(help_text=b"This email address will be used in the 'From' line of automated emails sent by RELATE.", max_length=75),
            preserve_default=True,
        ),
        migrations.AlterField(
            model_name='course',
            name='notify_email',
            field=models.EmailField(help_text=b'This email address will receive notifications about the course.', max_length=75),
            preserve_default=True,
        ),
        migrations.AlterField(
            model_name='facilityiprange',
            name='facility',
            field=models.ForeignKey(related_name='ip_ranges', to='course.Facility'),
            preserve_default=True,
        ),
    ]
