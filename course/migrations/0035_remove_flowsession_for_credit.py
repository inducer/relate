from django.db import models, migrations


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
