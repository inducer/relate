from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0031_event_shown_in_calendar'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flowsession',
            name='access_rules_id',
            field=models.CharField(max_length=200, null=True, blank=True),
        ),
    ]
