from django.db import models, migrations
import django.utils.timezone
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('course', '0006_flowpagevisit_remote_address'),
    ]

    operations = [
        migrations.CreateModel(
            name='ParticipationPreapproval',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('email', models.EmailField(max_length=254)),
                ('role', models.CharField(max_length=50, choices=[('instructor', 'Instructor'), ('ta', 'Teaching Assistant'), ('student', 'Student')])),
                ('creation_time', models.DateTimeField(default=django.utils.timezone.now, db_index=True)),
                ('course', models.ForeignKey(to='course.Course', on_delete=models.CASCADE)),
                ('creator', models.ForeignKey(to=settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE)),
            ],
            options={
                'ordering': ('course', 'email'),
            },
            bases=(models.Model,),
        ),
        migrations.AlterUniqueTogether(
            name='participationpreapproval',
            unique_together={('course', 'email')},
        ),
    ]
