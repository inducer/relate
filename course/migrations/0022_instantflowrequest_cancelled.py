from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0021_gradechange_attempt_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='instantflowrequest',
            name='cancelled',
            field=models.BooleanField(default=False),
            preserve_default=True,
        ),
    ]
