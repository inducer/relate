from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0070_drop_facilities_from_db'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='examticket',
            options={'ordering': ('exam__course', 'exam', 'usage_time'), 'verbose_name': 'Exam ticket', 'verbose_name_plural': 'Exam tickets', 'permissions': (('can_issue_exam_tickets', 'Can issue exam tickets to student'),)},
        ),
    ]
