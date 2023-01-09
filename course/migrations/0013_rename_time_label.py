from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0012_timelabel_end_time'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='TimeLabel',
            new_name='Event')
    ]
