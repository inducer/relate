from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0038_add_participations_related_name_on_course'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flowruleexception',
            name='kind',
            field=models.CharField(max_length=50, choices=[(b'start', b'Session Start'), (b'access', b'Session Access'), (b'grading', b'Grading')]),
            preserve_default=True,
        ),
    ]
