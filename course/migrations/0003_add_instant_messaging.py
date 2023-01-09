import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0002_allow_graded_answer_resubmission'),
    ]

    operations = [
        migrations.CreateModel(
            name='InstantMessage',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('text', models.CharField(max_length=200)),
                ('time', models.DateTimeField(default=django.utils.timezone.now)),
                ('participation', models.ForeignKey(to='course.Participation', on_delete=models.CASCADE)),
            ],
            options={
                'ordering': ('participation__course', 'time'),
            },
            bases=(models.Model,),
        ),
        migrations.AddField(
            model_name='course',
            name='recipient_xmpp_id',
            field=models.CharField(help_text='(Required only if the instant message feature is desired.) The JID to which instant messages will be sent.', max_length=200, null=True, blank=True),
            preserve_default=True,
        ),
        migrations.AlterField(
            model_name='course',
            name='course_xmpp_id',
            field=models.CharField(help_text='(Required only if the instant message feature is desired.) The Jabber/XMPP ID (JID) the course will use to sign in to an XMPP server.', max_length=200, null=True, blank=True),
        ),
        migrations.AlterField(
            model_name='course',
            name='course_xmpp_password',
            field=models.CharField(help_text='(Required only if the instant message feature is desired.) The password to go with the JID above.', max_length=200, null=True, blank=True),
        ),
    ]
