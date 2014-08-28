# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import jsonfield.fields
from django.conf import settings
import django.utils.timezone


def store_grading_results(apps, schema_editor):
    FlowPageVisit = apps.get_model("course", "FlowPageVisit")
    FlowPageVisitGrade = apps.get_model("course", "FlowPageVisitGrade")

    qset = FlowPageVisit.objects.all()
    qset = qset.prefetch_related("page_data")
    qset = qset.prefetch_related("flow_session")

    count = qset.count()
    for i, visit in enumerate(qset):
        import sys
        if i % 10 == 0:
            sys.stderr.write("%d/%d...\n" % (i, count))
            sys.stderr.flush()

        if not visit.is_graded_answer:
            continue

        from course.flow import grade_page_visit
        grade_page_visit(visit, visit_grade_model=FlowPageVisitGrade,
                grade_data=visit.grade_data)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('course', '0007_add_participation_preapproval'),
    ]

    operations = [
        migrations.CreateModel(
            name='FlowPageVisitGrade',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False,
                    auto_created=True, primary_key=True)),
                ('grade_time', models.DateTimeField(db_index=True,
                    default=django.utils.timezone.now)),
                ('grade_data', jsonfield.fields.JSONField(null=True, blank=True)),
                ('max_points', models.FloatField(null=True, blank=True,
                    help_text="Point value of this question when receiving "
                    "full credit.")),
                ('correctness', models.FloatField(null=True, blank=True,
                    help_text="Real number between zero and one (inclusively) "
                    "indicating the degree of correctness of the answer.")),
                ('feedback', jsonfield.fields.JSONField(null=True, blank=True)),
                ('grader', models.ForeignKey(blank=True,
                    to=settings.AUTH_USER_MODEL, null=True)),
                ('visit', models.ForeignKey(to='course.FlowPageVisit')),
            ],
            options={
                'ordering': (b'visit', b'grade_time'),
            },
            bases=(models.Model,),
        ),
        migrations.AddField(
            model_name='flowpagevisit',
            name='is_synthetic',
            field=models.BooleanField(default=False),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='flowpagevisitgrade',
            unique_together=set([(b'visit', b'grade_time')]),
        ),
        migrations.RunPython(store_grading_results),
        migrations.RemoveField(
            model_name='flowpagevisit',
            name='grade_data',
        ),
    ]
