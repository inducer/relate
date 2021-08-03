from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0045_add_course_listed'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flowpagedata',
            name='ordinal',
            field=models.IntegerField(null=True, blank=True),
            preserve_default=True,
        ),
    ]
