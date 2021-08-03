from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0037_flowruleexception'),
    ]

    operations = [
        migrations.AlterField(
            model_name='participation',
            name='course',
            field=models.ForeignKey(related_name='participations', to='course.Course', on_delete=models.CASCADE),
            preserve_default=True,
        ),
    ]
