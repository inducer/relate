from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0029_flowaccessexception_is_sticky'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flowsession',
            name='expiration_mode',
            field=models.CharField(default='end', max_length=20, null=True, choices=[(b'end', b'End session and grade'), (b'roll_over', b'Keep session and apply new rules')]),
        ),
    ]
