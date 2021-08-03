from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0081_course_fields_i18n'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='preapproval_require_verified_inst_id',
            field=models.BooleanField(default=True, help_text='If set, students cannot get particiaption preapproval using institutional ID if institutional ID they provided are not verified.', verbose_name='None preapproval by institutional ID if not verified?'),
        ),
        migrations.AddField(
            model_name='participationpreapproval',
            name='institutional_id',
            field=models.CharField(max_length=254, null=True, verbose_name='Institutional ID', blank=True),
        ),
        migrations.AlterField(
            model_name='participationpreapproval',
            name='email',
            field=models.EmailField(max_length=254, null=True, verbose_name='Email', blank=True),
        ),
    ]
