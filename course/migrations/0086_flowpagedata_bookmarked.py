# Generated by Django 1.9.1 on 2016-02-13 00:59

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0085_cache_page_titles'),
    ]

    operations = [
        migrations.AddField(
            model_name='flowpagedata',
            name='bookmarked',
            field=models.BooleanField(default=False, help_text="A user-facing 'marking' feature to allow participants to easily return to pages that still need their attention.", verbose_name='Bookmarked'),
        ),
    ]
