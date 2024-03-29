# Generated by Django 1.10.3 on 2016-11-27 20:45

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0100_add_exam_listed'),
    ]

    operations = [
        migrations.AddField(
            model_name='examticket',
            name='restrict_to_facility',
            field=models.CharField(blank=True, help_text='If not blank, this exam ticket may only be used in the given facility', max_length=200, null=True, verbose_name='Restrict to facility'),
        ),
        migrations.AddField(
            model_name='examticket',
            name='valid_end_time',
            field=models.DateTimeField(blank=True, help_text='If not blank, date and time at which this exam ticket stops being valid/usable', null=True, verbose_name='End valid period'),
        ),
        migrations.AddField(
            model_name='examticket',
            name='valid_start_time',
            field=models.DateTimeField(blank=True, help_text='If not blank, date and time at which this exam ticket starts being valid/usable', null=True, verbose_name='End valid period'),
        ),
        migrations.AlterField(
            model_name='examticket',
            name='usage_time',
            field=models.DateTimeField(blank=True, help_text='Date and time of first usage of ticket', null=True, verbose_name='Usage time'),
        ),
    ]
