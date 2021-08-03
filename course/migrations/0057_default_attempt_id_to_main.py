from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0056_facility_tweaks'),
    ]

    operations = [
        migrations.AlterField(
            model_name='gradechange',
            name='attempt_id',
            field=models.CharField(default='main', max_length=50, null=True, help_text="Grade changes are grouped by their 'attempt ID' where later grades with the same attempt ID supersede earlier ones.", blank=True),
            preserve_default=True,
        ),
    ]
