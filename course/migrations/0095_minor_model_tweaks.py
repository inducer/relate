# Generated by Django 1.10 on 2016-09-03 18:12

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0094_gradingopportunity_result_shown_in_participant_grade_book'),
    ]

    operations = [
        migrations.AlterField(
            model_name='gradingopportunity',
            name='hide_superseded_grade_history_before',
            field=models.DateTimeField(blank=True, help_text='Grade changes dated before this date that are superseded by later grade changes will not be shown to participants. This can help avoid discussions about pre-release grading adjustments. May be blank. In that case, the entire grade history is shown.', null=True, verbose_name='Hide superseded grade history before'),
        ),
        migrations.AlterField(
            model_name='participationpermission',
            name='participation',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='individual_permissions', to='course.Participation', verbose_name='Participation'),
        ),
    ]
