from django.db import models, migrations


def set_notify_email(apps, schema_editor):
    Course = apps.get_model("course", "Course")
    for course in Course.objects.all():
        if course.notify_email is None:
            course.notify_email = course.from_email
            course.save()


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0042_rename_from_email'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='notify_email',
            field=models.EmailField(help_text='This email address will receive notifications about the course.', max_length=75, null=True),
            preserve_default=True,
        ),
        migrations.AlterField(
            model_name='course',
            name='from_email',
            field=models.EmailField(help_text="This email address will be used in the 'From' line of automated emails sent by RELATE.", max_length=75),
            preserve_default=True,
        ),
        migrations.RunPython(set_notify_email),
    ]
