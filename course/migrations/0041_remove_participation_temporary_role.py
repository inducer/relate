from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0040_rename_is_submitted_answer'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='participation',
            name='temporary_role',
        ),
    ]
