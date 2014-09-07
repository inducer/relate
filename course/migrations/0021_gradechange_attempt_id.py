# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


def add_attempt_id_to_grade_change_from_flow_session(apps, schema_editor):
    GradeChange = apps.get_model("course", "GradeChange")

    for gchange in GradeChange.objects.all():
        if gchange.flow_session is not None:
            gchange.attempt_id = "flow-session-%d" % gchange.flow_session.id
            gchange.save()


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0020_tweak_field_access_exception'),
    ]

    operations = [
        migrations.AddField(
            model_name='gradechange',
            name='attempt_id',
            field=models.CharField(max_length=50, null=True, blank=True,
                help_text="Grade changes are grouped by their 'attempt ID' "
                "where later grades with the same attempt ID supersede earlier "
                "ones."),
            preserve_default=True,
        ),
        migrations.RunPython(add_attempt_id_to_grade_change_from_flow_session),
    ]
