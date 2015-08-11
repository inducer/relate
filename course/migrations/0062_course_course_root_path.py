# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0061_add_course_id_validation'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='course_root_path',
            field=models.CharField(help_text='Subdirectory in git repository to use as course root directory. Should not include trailing slash.', max_length=200, verbose_name='Course root directory', blank=True),
        ),
    ]
