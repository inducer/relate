# -*- coding: utf-8 -*-

from __future__ import unicode_literals

from django.db import migrations

def add_direct_git_endpoint_permission(apps, schema_editor):
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
                permission=pperm.direct_git_endpoint
            )


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0111_alter_git_source_in_course_to_a_required_field'),
    ]

    operations = [
        migrations.RunPython(add_direct_git_endpoint_permission)
    ]
