from django.db import models, migrations
import django.utils.timezone
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('course', '0067_flow_time_limits'),
    ]

    operations = [
        migrations.CreateModel(
            name='Exam',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('description', models.CharField(max_length=200, verbose_name='Description')),
                ('flow_id', models.CharField(max_length=200, verbose_name='Flow ID')),
                ('active', models.BooleanField(default=True, verbose_name='Currently active')),
                ('no_exams_before', models.DateTimeField(verbose_name='No exams before')),
                ('no_exams_after', models.DateTimeField(null=True, verbose_name='No exams after', blank=True)),
                ('course', models.ForeignKey(verbose_name='Course', to='course.Course', on_delete=models.CASCADE)),
            ],
            options={
                'ordering': ('course', 'no_exams_before'),
                'verbose_name': 'Exam',
                'verbose_name_plural': 'Exams',
            },
        ),
        migrations.CreateModel(
            name='ExamTicket',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('creation_time', models.DateTimeField(default=django.utils.timezone.now, verbose_name='Creation time')),
                ('usage_time', models.DateTimeField(null=True, verbose_name='Usage time', blank=True)),
                ('state', models.CharField(max_length=50, verbose_name='Exam ticket state', choices=[(b'valid', 'Valid'), (b'used', 'Used'), (b'revoked', 'Revoked')])),
                ('code', models.CharField(unique=True, max_length=50, db_index=True)),
                ('creator', models.ForeignKey(verbose_name='Creator', to=settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE)),
                ('exam', models.ForeignKey(verbose_name='Exam', to='course.Exam', on_delete=models.CASCADE)),
                ('participation', models.ForeignKey(verbose_name='Participation', to='course.Participation', on_delete=models.CASCADE)),
            ],
            options={
                'ordering': ('exam__course', 'exam', 'usage_time'),
                'verbose_name': 'Exam ticket',
                'verbose_name_plural': 'Exam tickets',
            },
        ),
        migrations.AddField(
            model_name='facility',
            name='exams_only',
            field=models.BooleanField(default=True, verbose_name='Only allow exam logins and related flows'),
        ),
    ]
