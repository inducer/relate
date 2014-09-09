# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0022_instantflowrequest_cancelled'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='flowsession',
            options={'ordering': ('course', '-start_time')},
        ),
        migrations.AlterField(
            model_name='flowaccessexceptionentry',
            name='permission',
            field=models.CharField(max_length=50, choices=[(b'view', b'View the flow'), (b'view_past', b'Review past attempts'), (b'start_credit', b'Start a for-credit session'), (b'start_no_credit', b'Start a not-for-credit session'), (b'change_answer', b'Change already-graded answer'), (b'see_correctness', b'See whether an answer is correct'), (b'see_correctness_after_completion', b'See whether an answer is correct after completing the flow'), (b'see_answer', b'See the correct answer')]),
        ),
    ]
