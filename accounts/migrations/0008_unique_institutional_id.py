# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_migrate_user_status_data'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='institutional_id',
            field=models.CharField(null=True, default=None, max_length=100, blank=True, unique=True, verbose_name='Institutional ID'),
        ),
    ]
