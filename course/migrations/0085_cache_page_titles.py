# Generated by Django 1.9.1 on 2016-02-07 18:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0084_flowsession_page_data_at_course_revision'),
    ]

    operations = [
        migrations.RenameField(
            model_name='flowsession',
            old_name='page_data_at_course_revision',
            new_name='page_data_at_revision_key',
        ),
        migrations.AddField(
            model_name='flowpagedata',
            name='title',
            field=models.CharField(blank=True, max_length=1000, null=True, verbose_name='Page Title'),
        ),
        migrations.AlterField(
            model_name='flowaccessexceptionentry',
            name='permission',
            field=models.CharField(choices=[(b'view', 'View the flow'), (b'submit_answer', 'Submit answers'), (b'end_session', 'End session'), (b'change_answer', 'Change already-graded answer'), (b'see_correctness', 'See whether an answer is correct'), (b'see_answer_before_submission', 'See the correct answer before answering'), (b'see_answer_after_submission', 'See the correct answer after answering'), (b'cannot_see_flow_result', 'Cannot see flow result'), (b'set_roll_over_expiration_mode', "Set the session to 'roll over' expiration mode"), (b'see_session_time', 'See session time'), (b'lock_down_as_exam_session', 'Lock down as exam session')], max_length=50, verbose_name='Permission'),
        ),
    ]
