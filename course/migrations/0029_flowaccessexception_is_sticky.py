from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0028_more_expiration_mode_changes'),
    ]

    operations = [
        migrations.AddField(
            model_name='flowaccessexception',
            name='is_sticky',
            field=models.BooleanField(default=False, help_text='Check if a flow started under this exception rule set should stay under this rule set until it is expired.'),
            preserve_default=True,
        ),
    ]
