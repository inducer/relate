from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0012_timelabel_end_time'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='TimeLabel',
            new_name='Event')
    ]
