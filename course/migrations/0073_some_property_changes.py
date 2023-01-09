from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0072_ui_updates'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flowaccessexceptionentry',
            name='permission',
            field=models.CharField(max_length=50, verbose_name='Permission', choices=[('view', 'View the flow'), ('submit_answer', 'Submit answers'), ('end_session', 'End session'), ('change_answer', 'Change already-graded answer'), ('see_correctness', 'See whether an answer is correct'), ('see_answer_before_submission', 'See the correct answer before answering'), ('see_answer_after_submission', 'See the correct answer after answering'), ('cannot_see_flow_result', 'Cannot see flow result'), ('set_roll_over_expiration_mode', "Set the session to 'roll over' expiration mode"), ('see_session_time', 'See session time')]),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='completion_time',
            field=models.DateTimeField(null=True, verbose_name='Completion time', blank=True),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='expiration_mode',
            field=models.CharField(default='end', max_length=20, null=True, verbose_name='Expiration mode', choices=[('end', 'Submit session for grading'), ('roll_over', 'Do not submit session for grading')]),
        ),
        migrations.AlterField(
            model_name='userstatus',
            name='editor_mode',
            field=models.CharField(default='default', help_text='Your favorite text editor mode for text block or code block.', max_length=20, verbose_name='Editor mode', choices=[('default', 'Default'), ('sublime', 'Sublime text'), ('emacs', 'Emacs'), ('vim', 'Vim')]),
        ),
    ]
