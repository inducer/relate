from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0025_add_more_permission_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='gradingopportunity',
            name='shown_in_student_grade_book',
            field=models.BooleanField(default=True),
            preserve_default=True,
        ),
    ]
