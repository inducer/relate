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
            field=models.CharField(max_length=50, choices=[('view', 'View flow'), ('view_past', 'Review past attempts'), ('start_credit', 'Start for-credit session'), ('start_no_credit', 'Start not-for-credit session'), ('change_answer', 'Change already-graded answer'), ('see_correctness', 'See whether answer is correct'), ('see_answer', 'See the correct answer')]),
        ),
    ]
