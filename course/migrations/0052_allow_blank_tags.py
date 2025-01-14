from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0051_add_participation_tags'),
    ]

    operations = [
        migrations.AlterField(
            model_name='participation',
            name='tags',
            field=models.ManyToManyField(to='course.ParticipationTag', blank=True),
            preserve_default=True,
        ),
    ]
