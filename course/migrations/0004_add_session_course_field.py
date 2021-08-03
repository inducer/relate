from django.db import models, migrations


def set_course(apps, schema_editor):
    broken_anonymous_sessions = []

    FlowSession = apps.get_model("course", "FlowSession")
    for session in FlowSession.objects.all():
        if session.participation is not None:
            session.course = session.participation.course
            session.save()
        else:
            broken_anonymous_sessions.append(session)

    for session in broken_anonymous_sessions:
        session.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0003_add_instant_messaging'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='flowsession',
            options={'ordering': ('course', 'participation', '-start_time')},
        ),
        migrations.AddField(
            model_name='flowsession',
            name='course',
            field=models.ForeignKey(to='course.Course', null=True, on_delete=models.CASCADE),
            preserve_default=True,
        ),
        migrations.RunPython(set_course),
    ]
