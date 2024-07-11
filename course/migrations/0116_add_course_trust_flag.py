# Generated by Django 3.0.14 on 2021-04-16 00:27

from django.db import migrations, models


def trust_existing_courses_for_markup(apps, schema_editor):
    Course = apps.get_model("course", "Course")
    for course in Course.objects.all():
        # Existing courses are grandfathered in.
        course.trusted_for_markup = True
        course.save()


class Migration(migrations.Migration):

    dependencies = [
        ("course", "0115_catch_up"),
    ]

    operations = [
        migrations.AddField(
            model_name="course",
            name="trusted_for_markup",
            field=models.BooleanField(
                default=False,
                verbose_name="May present arbitrary HTML to course participants",
            ),
        ),
        migrations.RunPython(trust_existing_courses_for_markup),
    ]
