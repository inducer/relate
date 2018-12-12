# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0033_flowpagebulkfeedback'),
    ]

    operations = [
        migrations.AlterField(
            model_name='course',
            name='ssh_private_key',
            field=models.TextField(help_text='An SSH private key to use for Git authentication. Not needed for the sample URL above.', blank=True),
            preserve_default=True,
        ),
        migrations.AlterField(
            model_name='flowaccessexceptionentry',
            name='permission',
            field=models.CharField(max_length=50, choices=[(b'view', b'View the flow'), (b'modify', b'Submit answers'), (b'change_answer', b'Change already-graded answer'), (b'see_correctness', b'See whether an answer is correct'), (b'see_answer', b'See the correct answer'), (b'set_roll_over_expiration_mode', b"Set the session to 'roll over' expiration mode")]),
            preserve_default=True,
        ),
    ]
