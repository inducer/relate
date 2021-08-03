from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0027_flowsession_expiration_mode'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flowaccessexceptionentry',
            name='permission',
            field=models.CharField(max_length=50, choices=[(b'view', b'View the flow'), (b'view_past', b'Review past attempts'), (b'start_credit', b'Start a for-credit session'), (b'start_no_credit', b'Start a not-for-credit session'), (b'change_answer', b'Change already-graded answer'), (b'see_correctness', b'See whether an answer is correct'), (b'see_correctness_after_completion', b'See whether an answer is correct after completing the flow'), (b'see_answer', b'See the correct answer'), (b'see_answer_after_completion', b'See the correct answer after completing the flow'), (b'set_roll_over_expiration_mode', b"Set the session to 'roll over' expiration mode")]),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='expiration_mode',
            field=models.CharField(default='end', max_length=20, null=True, choices=[(b'end', b'End session and grade'), (b'roll_over', b'Roll over to new rules')]),
        ),
    ]
