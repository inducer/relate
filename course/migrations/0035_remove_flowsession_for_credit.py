from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0034_help_text_changes'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='flowsession',
            name='for_credit',
        ),
    ]
