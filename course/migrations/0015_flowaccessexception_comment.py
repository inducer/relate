from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0014_course_events_file'),
    ]

    operations = [
        migrations.AddField(
            model_name='flowaccessexception',
            name='comment',
            field=models.TextField(null=True, blank=True),
            preserve_default=True,
        ),
    ]
