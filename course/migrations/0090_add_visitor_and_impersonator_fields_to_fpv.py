# Generated by Django 1.9.2 on 2016-04-26 00:45

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('course', '0089_gradingopportunity_hide_superseded_grade_history_before'),
    ]

    operations = [
        migrations.AddField(
            model_name='flowpagevisit',
            name='impersonated_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='impersonator', to=settings.AUTH_USER_MODEL, verbose_name='Impersonated by'),
        ),
        migrations.AddField(
            model_name='flowpagevisit',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='visitor', to=settings.AUTH_USER_MODEL, verbose_name='User'),
        ),
    ]
