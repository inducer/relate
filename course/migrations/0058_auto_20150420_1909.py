# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0057_auto_20150420_0857'),
    ]

    operations = [
        migrations.AlterField(
            model_name='course',
            name='from_email',
            field=models.EmailField(help_text=b"This email address will be used in the 'From' line of automated emails sent by RELATE.", max_length=254),
        ),
        migrations.AlterField(
            model_name='course',
            name='notify_email',
            field=models.EmailField(help_text=b'This email address will receive notifications about the course.', max_length=254),
        ),
    ]
