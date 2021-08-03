from django.db import models, migrations


def forwards(apps, schema_editor):
    fix_contenttype(apps, schema_editor,
                    "auth", "User",
                    "accounts", "User")


def backwards(apps, schema_editor):
    fix_contenttype(apps, schema_editor,
                    "accounts", "User",
                    "auth", "User")


def fix_contenttype(apps, schema_editor, from_app, from_model, to_app, to_model):
    from_model, to_model = from_model.lower(), to_model.lower()
    schema_editor.execute("UPDATE django_content_type SET app_label=%s, model=%s WHERE app_label=%s AND model=%s;",
                          [to_app, to_model, from_app, from_model])



class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_user_schema_migration'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
