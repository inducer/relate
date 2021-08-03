from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0004_add_session_course_field'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flowsession',
            name='course',
            field=models.ForeignKey(to='course.Course', on_delete=models.CASCADE),
        ),
    ]
