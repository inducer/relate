from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0066_fix_course_identifier_usage'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flowaccessexceptionentry',
            name='permission',
            field=models.CharField(max_length=50, verbose_name='Permission', choices=[(b'view', 'View the flow'), (b'submit_answer', 'Submit answers'), (b'end_session', 'End session'), (b'change_answer', 'Change already-graded answer'), (b'see_correctness', 'See whether an answer is correct'), (b'see_answer_before_submission', 'See the correct answer before answering'), (b'see_answer_after_submission', 'See the correct answer after answering'), (b'set_roll_over_expiration_mode', "Set the session to 'roll over' expiration mode"), (b'see_session_time', 'See session time')]),
        ),
        migrations.AlterField(
            model_name='participation',
            name='time_factor',
            field=models.DecimalField(default=1, help_text='Multiplier for time available on time-limited flows', verbose_name='Time factor', max_digits=10, decimal_places=2),
        ),
    ]
