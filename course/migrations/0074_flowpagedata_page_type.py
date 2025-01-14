from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0073_some_property_changes'),
    ]

    operations = [
        migrations.AddField(
            model_name='flowpagedata',
            name='page_type',
            field=models.CharField(max_length=200, null=True, verbose_name='Page type as indicated in course content', blank=True),
        ),
    ]
