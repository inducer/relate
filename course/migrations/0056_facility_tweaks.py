from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0055_facility_facilityiprange'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='facility',
            options={'verbose_name_plural': 'facilities'},
        ),
        migrations.AlterModelOptions(
            name='facilityiprange',
            options={'verbose_name': 'Facility IP Range'},
        ),
        migrations.RenameField(
            model_name='facilityiprange',
            old_name='ip_range_description',
            new_name='description',
        ),
        migrations.AlterField(
            model_name='facilityiprange',
            name='ip_range',
            field=models.CharField(max_length=200, verbose_name='IP Range'),
        ),
    ]
