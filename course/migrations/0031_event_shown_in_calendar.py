from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0030_change_expmode_descr'),
    ]

    operations = [
        migrations.AddField(
            model_name='event',
            name='shown_in_calendar',
            field=models.BooleanField(default=True),
            preserve_default=True,
        ),
    ]
