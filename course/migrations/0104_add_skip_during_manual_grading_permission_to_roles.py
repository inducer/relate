from django.db import migrations


def remove_mistakenly_added_individual_pperm(apps, schema_editor):
    from course.constants import participation_permission as pperm

    ParticipationPermission = apps.get_model("course", "ParticipationPermission")  # noqa
    Participation = apps.get_model("course", "Participation")  # noqa

    target_participations = Participation.objects.filter(
        individual_permissions__permission=(
            pperm.skip_during_manual_grading)
    )

    for participation in target_participations:
        ParticipationPermission.objects.filter(
            participation=participation,
            permission=pperm.skip_during_manual_grading).delete()


def add_skip_during_manual_grading_permission_to_roles(apps, schema_editor):
    from course.constants import participation_permission as pperm

    ParticipationRolePermission = apps.get_model("course", "ParticipationRolePermission")  # noqa

    roles_pks = (
        ParticipationRolePermission.objects.filter(
            permission=pperm.assign_grade)
        .values_list("role", flat=True)
    )

    if roles_pks.count():
        for pk in roles_pks:
            ParticipationRolePermission.objects.get_or_create(
                role_id=pk,
                permission=pperm.skip_during_manual_grading
            )


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0103_skip_during_manual_grading_permission'),
    ]

    operations = [
        migrations.RunPython(remove_mistakenly_added_individual_pperm),
        migrations.RunPython(add_skip_during_manual_grading_permission_to_roles)
    ]
