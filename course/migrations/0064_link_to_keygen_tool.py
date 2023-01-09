from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0063_tweak_hidden_field_descr'),
    ]

    operations = [
        migrations.AlterField(
            model_name='course',
            name='ssh_private_key',
            field=models.TextField(help_text="An SSH private key to use for Git authentication. Not needed for the sample URL above.You may use <a href='/generate-ssh-key'>this tool</a> to generate a key pair.", verbose_name='SSH private key', blank=True),
        ),
    ]
