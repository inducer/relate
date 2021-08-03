from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0041_remove_participation_temporary_role'),
    ]

    operations = [
        migrations.RenameField(
            model_name='course',
            old_name='email',
            new_name='from_email',
        ),
    ]
