from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0013_rename_time_label'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='events_file',
            field=models.CharField(default='events.yml', help_text='Name of a YAML file in the git repository that contains calendar information.', max_length=200),
            preserve_default=True,
        ),
    ]
