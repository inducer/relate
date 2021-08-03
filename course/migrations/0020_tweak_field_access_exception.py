from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0019_tweak_grading_opp'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flowaccessexceptionentry',
            name='permission',
            field=models.CharField(max_length=50, choices=[('view', 'View the flow'), ('view_past', 'Review past attempts'), ('start_credit', 'Start a for-credit session'), ('start_no_credit', 'Start a not-for-credit session'), ('change_answer', 'Change already-graded answer'), ('see_correctness', 'See whether an answer is correct'), ('see_answer', 'See the correct answer')]),
        ),
    ]
