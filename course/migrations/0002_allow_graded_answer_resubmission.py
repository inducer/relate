# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(
            model_name='flowpagevisit',
            old_name='answer_is_final',
            new_name='is_graded_answer',
        ),
        migrations.AlterField(
            model_name='flowaccessexceptionentry',
            name='permission',
            field=models.CharField(max_length=50, choices=[(b'view', b'View flow'), (b'view_past', b'Review past attempts'), (b'start_credit', b'Start for-credit session'), (b'start_no_credit', b'Start not-for-credit session'), (b'change_answer', b'Change already-graded answer'), (b'see_correctness', b'See whether answer is correct'), (b'see_answer', b'See the correct answer')]),
        ),
    ]
