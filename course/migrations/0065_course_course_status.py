# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0064_link_to_keygen_tool'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='course_status',
            field=models.CharField(default=b'available', help_text='The current status of the course. If ended, only Participants can see the course from his/her home page ', max_length=50, verbose_name='Course status', choices=[(b'available', 'Available'), (b'ended', 'Ended')]),
        ),
    ]
