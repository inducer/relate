from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0071_add_issue_ticket_permission'),
    ]

    operations = [
        migrations.AlterField(
            model_name='course',
            name='course_root_path',
            field=models.CharField(help_text='Subdirectory *within* the git repository to use as course root directory. Not required, and usually blank. Use only if your course content lives in a subdirectory of your git repository. Should not include trailing slash.', max_length=200, verbose_name='Course root in repository', blank=True),
        ),
        migrations.AlterField(
            model_name='examticket',
            name='usage_time',
            field=models.DateTimeField(null=True, verbose_name='Date and time of first usage of ticket', blank=True),
        ),
    ]
