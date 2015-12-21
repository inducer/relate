# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0065_flowsession_user'),
    ]

    operations = [
        migrations.AlterField(
            model_name='event',
            name='course',
            field=models.ForeignKey(verbose_name='Course', to='course.Course', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='course',
            field=models.ForeignKey(verbose_name='Course', to='course.Course', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='gradingopportunity',
            name='course',
            field=models.ForeignKey(verbose_name='Course', to='course.Course', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='instantflowrequest',
            name='course',
            field=models.ForeignKey(verbose_name='Course', to='course.Course', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='participation',
            name='course',
            field=models.ForeignKey(related_name='participations', verbose_name='Course', to='course.Course', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='participationpreapproval',
            name='course',
            field=models.ForeignKey(verbose_name='Course', to='course.Course', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='participationtag',
            name='course',
            field=models.ForeignKey(verbose_name='Course', to='course.Course', on_delete=models.CASCADE),
        ),
    ]
