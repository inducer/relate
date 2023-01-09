from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0024_change_fae_entry_plural'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flowaccessexceptionentry',
            name='permission',
            field=models.CharField(max_length=50, choices=[('view', 'View the flow'), ('view_past', b'Review past attempts'), (b'start_credit', b'Start a for-credit session'), (b'start_no_credit', b'Start a not-for-credit session'), (b'change_answer', b'Change already-graded answer'), (b'see_correctness', b'See whether an answer is correct'), (b'see_correctness_after_completion', b'See whether an answer is correct after completing the flow'), (b'see_answer', b'See the correct answer'), (b'see_answer_after_completion', b'See the correct answer after completing the flow')]),
        ),
        migrations.AlterField(
            model_name='participation',
            name='role',
            field=models.CharField(max_length=50, choices=[(b'instructor', b'Instructor'), (b'ta', b'Teaching Assistant'), (b'student', b'Student'), (b'observer', b'Observer')]),
        ),
        migrations.AlterField(
            model_name='participation',
            name='temporary_role',
            field=models.CharField(blank=True, max_length=50, null=True, choices=[(b'instructor', b'Instructor'), (b'ta', b'Teaching Assistant'), (b'student', b'Student'), (b'observer', b'Observer')]),
        ),
        migrations.AlterField(
            model_name='participationpreapproval',
            name='role',
            field=models.CharField(max_length=50, choices=[(b'instructor', b'Instructor'), (b'ta', b'Teaching Assistant'), (b'student', b'Student'), (b'observer', b'Observer')]),
        ),
    ]
