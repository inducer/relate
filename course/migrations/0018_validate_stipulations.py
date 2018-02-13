# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import jsonfield.fields
import course.models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0017_event_all_day'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flowaccessexception',
            name='stipulations',
            field=jsonfield.fields.JSONField(blank=True, help_text='A dictionary of the same things that can be added to a flow access rule, such as allowed_session_count or credit_percent. If not specified here, values will default to the stipulations in the course content.', null=True, validators=[course.models.validate_stipulations]),
        ),
    ]
