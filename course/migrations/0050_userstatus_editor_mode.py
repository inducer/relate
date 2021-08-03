from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0049_course_accepts_enrollment'),
    ]

    operations = [
        migrations.AddField(
            model_name='userstatus',
            name='editor_mode',
            field=models.CharField(default='default', max_length=20, choices=[(b'default', b'Default'), (b'sublime', b'Sublime text'), (b'emacs', b'Emacs'), (b'vim', b'Vim')]),
            preserve_default=True,
        ),
    ]
