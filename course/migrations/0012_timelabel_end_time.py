from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0011_flowsession_access_rules_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='timelabel',
            name='end_time',
            field=models.DateTimeField(null=True, blank=True),
            preserve_default=True,
        ),
    ]
