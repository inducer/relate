# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0052_allow_blank_tags'),
    ]

    operations = [
        migrations.AlterField(
            model_name='course',
            name='from_email',
            field=models.EmailField(help_text="This email address will be used in the 'From' line of automated emails sent by RELATE.", max_length=254),
        ),
        migrations.AlterField(
            model_name='course',
            name='notify_email',
            field=models.EmailField(help_text='This email address will receive notifications about the course.', max_length=254),
        ),
        migrations.AlterField(
            model_name='flowaccessexceptionentry',
            name='permission',
            field=models.CharField(max_length=50, choices=[(b'view', b'View the flow'), (b'submit_answer', b'Submit answers'), (b'end_session', b'End session'), (b'change_answer', b'Change already-graded answer'), (b'see_correctness', b'See whether an answer is correct'), (b'see_answer', b'See the correct answer'), (b'set_roll_over_expiration_mode', b"Set the session to 'roll over' expiration mode")]),
        ),
    ]
