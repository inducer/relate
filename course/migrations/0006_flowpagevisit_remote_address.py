from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0005_make_session_course_not_nullable'),
    ]

    operations = [
        migrations.AddField(
            model_name='flowpagevisit',
            name='remote_address',
            field=models.GenericIPAddressField(null=True, blank=True),
            preserve_default=True,
        ),
    ]
