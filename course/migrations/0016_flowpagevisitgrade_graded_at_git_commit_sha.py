from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0015_flowaccessexception_comment'),
    ]

    operations = [
        migrations.AddField(
            model_name='flowpagevisitgrade',
            name='graded_at_git_commit_sha',
            field=models.CharField(max_length=200, null=True, blank=True),
            preserve_default=True,
        ),
    ]
