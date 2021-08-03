from django.db import models, migrations


def set_course_metadata(apps, schema_editor):
    Course = apps.get_model("course", "Course")  # noqa
    for course in Course.objects.all():
        from course.content import (
                get_course_repo, get_course_desc,
                get_course_commit_sha)

        repo = get_course_repo(course)
        course_desc = get_course_desc(
                repo, course,
                get_course_commit_sha(course, participation=None))

        course.name = course_desc.name
        course.number = course_desc.number
        course.time_period = course_desc.run

        repo.close()
        course.save()


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0074_flowpagedata_page_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='end_date',
            field=models.DateField(null=True, verbose_name='End date', blank=True),
        ),
        migrations.AddField(
            model_name='course',
            name='name',
            field=models.CharField(help_text="A human-readable name for the course. (e.g. 'Numerical Methods')", max_length=200, null=True),
        ),
        migrations.AddField(
            model_name='course',
            name='number',
            field=models.CharField(help_text="A human-readable course number/IDfor the course (e.g. 'CS123')", max_length=200, null=True),
        ),
        migrations.AddField(
            model_name='course',
            name='start_date',
            field=models.DateField(null=True, verbose_name='Start date', blank=True),
        ),
        migrations.AddField(
            model_name='course',
            name='time_period',
            field=models.CharField(help_text="A human-readable description of the time period for the course (e.g. 'Fall 2014')", max_length=200, null=True),
        ),
        migrations.RemoveField(
            model_name='course',
            name='valid',
        ),
        migrations.RunPython(set_course_metadata),
    ]
