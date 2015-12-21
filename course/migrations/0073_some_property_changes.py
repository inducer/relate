# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0072_ui_updates'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flowaccessexceptionentry',
            name='permission',
            field=models.CharField(max_length=50, verbose_name='Permission', choices=[(b'view', 'View the flow'), (b'submit_answer', 'Submit answers'), (b'end_session', 'End session'), (b'change_answer', 'Change already-graded answer'), (b'see_correctness', 'See whether an answer is correct'), (b'see_answer_before_submission', 'See the correct answer before answering'), (b'see_answer_after_submission', 'See the correct answer after answering'), (b'cannot_see_flow_result', 'Cannot see flow result'), (b'set_roll_over_expiration_mode', "Set the session to 'roll over' expiration mode"), (b'see_session_time', 'See session time')]),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='completion_time',
            field=models.DateTimeField(null=True, verbose_name='Completion time', blank=True),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='expiration_mode',
            field=models.CharField(default=b'end', max_length=20, null=True, verbose_name='Expiration mode', choices=[(b'end', 'Submit session for grading'), (b'roll_over', 'Do not submit session for grading')]),
        ),
        migrations.AlterField(
            model_name='userstatus',
            name='editor_mode',
            field=models.CharField(default=b'default', help_text='Your favorite text editor mode for text block or code block.', max_length=20, verbose_name='Editor mode', choices=[(b'default', 'Default'), (b'sublime', b'Sublime text'), (b'emacs', b'Emacs'), (b'vim', b'Vim')]),
        ),
    ]
