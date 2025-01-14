from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0050_userstatus_editor_mode'),
    ]

    operations = [
        migrations.CreateModel(
            name='ParticipationTag',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(help_text='Format is lower-case-with-hyphens. Do not use spaces.', unique=True, max_length=100)),
                ('course', models.ForeignKey(to='course.Course', on_delete=models.CASCADE)),
            ],
            options={
                'ordering': ('course', 'name'),
            },
            bases=(models.Model,),
        ),
        migrations.AlterUniqueTogether(
            name='participationtag',
            unique_together={('course', 'name')},
        ),
        migrations.AddField(
            model_name='participation',
            name='tags',
            field=models.ManyToManyField(to='course.ParticipationTag'),
            preserve_default=True,
        ),
    ]
