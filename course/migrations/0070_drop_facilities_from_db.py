from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0069_exam_lockdown'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='facilityiprange',
            name='facility',
        ),
        migrations.DeleteModel(
            name='Facility',
        ),
        migrations.DeleteModel(
            name='FacilityIPRange',
        ),
    ]
