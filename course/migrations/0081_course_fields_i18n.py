from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0080_remove_userstatus'),
    ]

    operations = [
        migrations.AlterField(
            model_name='course',
            name='course_root_path',
            field=models.CharField(help_text='Subdirectory <em>within</em> the git repository to use as course root directory. Not required, and usually blank. Use only if your course content lives in a subdirectory of your git repository. Should not include trailing slash.', max_length=200, verbose_name='Course root in repository', blank=True),
        ),
        migrations.AlterField(
            model_name='course',
            name='identifier',
            field=models.CharField(max_length=200, validators=[django.core.validators.RegexValidator(b'^(?P<course_identifier>[-a-zA-Z0-9]+)$', message="Identifier may only contain letters, numbers, and hypens ('-').")], help_text="A course identifier. Alphanumeric with dashes, no spaces. This is visible in URLs and determines the location on your file system where the course's git repository lives. This should <em>not</em> be changed after the course has been created without also moving the course's git on the server.", unique=True, verbose_name='Course identifier', db_index=True),
        ),
        migrations.AlterField(
            model_name='course',
            name='name',
            field=models.CharField(help_text="A human-readable name for the course. (e.g. 'Numerical Methods')", max_length=200, null=True, verbose_name='Course name'),
        ),
        migrations.AlterField(
            model_name='course',
            name='number',
            field=models.CharField(help_text="A human-readable course number/ID for the course (e.g. 'CS123')", max_length=200, null=True, verbose_name='Course number'),
        ),
        migrations.AlterField(
            model_name='course',
            name='time_period',
            field=models.CharField(help_text="A human-readable description of the time period for the course (e.g. 'Fall 2014')", max_length=200, null=True, verbose_name='Time Period'),
        ),
    ]
