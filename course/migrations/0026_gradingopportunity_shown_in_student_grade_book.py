# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0025_add_more_permission_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='gradingopportunity',
            name='shown_in_student_grade_book',
            field=models.BooleanField(default=True),
            preserve_default=True,
        ),
    ]
