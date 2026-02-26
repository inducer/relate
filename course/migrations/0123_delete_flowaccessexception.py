from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("course", "0122_alter_authenticationtoken_id_alter_course_id_and_more"),
    ]

    operations = [
        migrations.DeleteModel(
            name="FlowAccessExceptionEntry",
        ),
        migrations.DeleteModel(
            name="FlowAccessException",
        ),
    ]
