from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0047_remove_page_data_ordinal_uniqueness'),
    ]

    operations = [
        migrations.AlterField(
            model_name='course',
            name='listed',
            field=models.BooleanField(default=True, help_text='Should the course be listed on the main page?'),
            preserve_default=True,
        ),
    ]
