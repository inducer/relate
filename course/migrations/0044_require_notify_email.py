from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0043_add_notify_email'),
    ]

    operations = [
        migrations.AlterField(
            model_name='course',
            name='notify_email',
            field=models.EmailField(help_text='This email address will receive notifications about the course.', max_length=75),
            preserve_default=True,
        ),
    ]
