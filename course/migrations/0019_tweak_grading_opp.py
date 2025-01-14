import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0018_validate_stipulations'),
    ]

    operations = [
        migrations.AddField(
            model_name='gradingopportunity',
            name='creation_time',
            field=models.DateTimeField(default=django.utils.timezone.now),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='gradingopportunity',
            name='shown_in_grade_book',
            field=models.BooleanField(default=True),
            preserve_default=True,
        ),
    ]
