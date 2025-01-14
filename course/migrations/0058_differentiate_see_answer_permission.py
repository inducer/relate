from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0057_default_attempt_id_to_main'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flowaccessexceptionentry',
            name='permission',
            field=models.CharField(max_length=50, choices=[(b'view', b'View the flow'), (b'submit_answer', b'Submit answers'), (b'end_session', b'End session'), (b'change_answer', b'Change already-graded answer'), (b'see_correctness', b'See whether an answer is correct'), (b'see_answer_before_submission', b'See the correct answer before answering'), (b'see_answer_after_submission', b'See the correct answer after answering'), (b'set_roll_over_expiration_mode', b"Set the session to 'roll over' expiration mode")]),
        ),
    ]
