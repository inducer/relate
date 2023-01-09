from django.db import migrations


def add_manage_auth_tokens_permission(apps, schema_editor):
    from course.constants import participation_permission as pperm

    ParticipationRolePermission = apps.get_model("course", "ParticipationRolePermission")  # noqa

    roles_pks = (
        ParticipationRolePermission.objects.filter(
            permission=pperm.edit_course)
        .values_list("role", flat=True)
    )

    if roles_pks.count():
        for pk in roles_pks:
            ParticipationRolePermission.objects.get_or_create(
                role_id=pk,
                permission=pperm.manage_authentication_tokens
            )


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0105_authenticationtoken'),
    ]

    operations = [
        migrations.RunPython(add_manage_auth_tokens_permission)
    ]
