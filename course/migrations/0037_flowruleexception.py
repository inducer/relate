# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import django.utils.timezone
from django.conf import settings
import yamlfield.fields


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('course', '0036_rename_access_rules_id_to_tag'),
    ]

    operations = [
        migrations.CreateModel(
            name='FlowRuleException',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('flow_id', models.CharField(max_length=200)),
                ('expiration', models.DateTimeField(null=True, blank=True)),
                ('creation_time', models.DateTimeField(default=django.utils.timezone.now, db_index=True)),
                ('comment', models.TextField(null=True, blank=True)),
                ('kind', models.CharField(max_length=50, choices=[(b'new_session', b'New Session'), (b'access', b'Session Access'), (b'grading', b'Grading')])),
                ('rule', yamlfield.fields.YAMLField()),
                ('active', models.BooleanField(default=True)),
                ('creator', models.ForeignKey(to=settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE)),
                ('participation', models.ForeignKey(to='course.Participation', on_delete=models.CASCADE)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
    ]
