from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0026_gradingopportunity_shown_in_student_grade_book'),
    ]

    operations = [
        migrations.AddField(
            model_name='flowsession',
            name='expiration_mode',
            field=models.CharField(default='end', max_length=20, null=True, choices=[(b'end', b'End session'), (b'roll_over', b'Roll over to new rules')]),
            preserve_default=True,
        ),
    ]
