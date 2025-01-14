from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0035_remove_flowsession_for_credit'),
    ]

    operations = [
        migrations.RenameField(
            model_name='flowsession',
            old_name='access_rules_id',
            new_name='access_rules_tag',
        ),
    ]
