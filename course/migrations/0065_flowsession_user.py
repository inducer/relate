from django.db import models, migrations
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('course', '0064_link_to_keygen_tool'),
    ]

    operations = [
        migrations.AddField(
            model_name='flowsession',
            name='user',
            field=models.ForeignKey(verbose_name='User', blank=True, to=settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE),
        ),
    ]
