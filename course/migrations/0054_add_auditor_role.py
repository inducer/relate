# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0053_permission_and_help'),
    ]

    operations = [
        migrations.AlterField(
            model_name='participation',
            name='role',
            field=models.CharField(help_text='Instructors may update course content. Teaching assistants may access and change grade data. Observers may access analytics. Each role includes privileges from subsequent roles.', max_length=50, choices=[(b'instructor', b'Instructor'), (b'ta', b'Teaching Assistant'), (b'student', b'Student'), (b'observer', b'Observer'), (b'auditor', b'Auditor')]),
        ),
        migrations.AlterField(
            model_name='participationpreapproval',
            name='role',
            field=models.CharField(max_length=50, choices=[(b'instructor', b'Instructor'), (b'ta', b'Teaching Assistant'), (b'student', b'Student'), (b'observer', b'Observer'), (b'auditor', b'Auditor')]),
        ),
    ]
