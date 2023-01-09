import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0060_add_verbose_name_and_labels_for_i18n'),
    ]

    operations = [
        migrations.AlterField(
            model_name='course',
            name='identifier',
            field=models.CharField(max_length=200, validators=[django.core.validators.RegexValidator(b'^(?P<course_identifier>[-a-zA-Z0-9]+)$', message="Identifier may only contain letters, numbers, and hypens ('-').")], help_text="A course identifier. Alphanumeric with dashes, no spaces. This is visible in URLs and determines the location on your file system where the course's git repository lives.", unique=True, verbose_name='Course identifier', db_index=True),
        ),
    ]
