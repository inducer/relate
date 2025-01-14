from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0046_allow_null_page_data_ordinals'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='flowpagedata',
            unique_together=set(),
        ),
    ]
