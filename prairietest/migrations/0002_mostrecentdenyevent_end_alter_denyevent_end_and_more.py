# Generated by Django 5.1 on 2024-09-13 15:39

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('prairietest', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='mostrecentdenyevent',
            name='end',
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name='End time'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='denyevent',
            name='end',
            field=models.DateTimeField(verbose_name='End time'),
        ),
        migrations.AlterField(
            model_name='denyevent',
            name='start',
            field=models.DateTimeField(verbose_name='Start time'),
        ),
        migrations.AddIndex(
            model_name='mostrecentdenyevent',
            index=models.Index(fields=['end'], name='prairietest_end_31b76d_idx'),
        ),
    ]
