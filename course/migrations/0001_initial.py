# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import jsonfield.fields
import django.utils.timezone
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Course',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('identifier', models.CharField(help_text=b"A course identifier. Alphanumeric with dashes, no spaces. This is visible in URLs and determines the location on your file system where the course's git repository lives.", unique=True, max_length=200, db_index=True)),
                ('hidden', models.BooleanField(default=True, help_text=b'Is the course only visible to course staff?')),
                ('valid', models.BooleanField(default=True, help_text=b'Whether the course content has passed validation.')),
                ('git_source', models.CharField(help_text=b"A Git URL from which to pull course updates. If you're just starting out, enter <tt>git://github.com/inducer/relate-sample</tt> to get some sample content.", max_length=200, blank=True)),
                ('ssh_private_key', models.TextField(help_text=b'An SSH private key to use for Git authentication', blank=True)),
                ('course_file', models.CharField(default=b'course.yml', help_text=b'Name of a YAML file in the git repository that contains the root course descriptor.', max_length=200)),
                ('enrollment_approval_required', models.BooleanField(default=False, help_text=b'If set, each enrolling student must be individually approved.')),
                ('enrollment_required_email_suffix', models.CharField(help_text=b"Enrollee's email addresses must end in the specified suffix, such as '@illinois.edu'.", max_length=200, null=True, blank=True)),
                ('email', models.EmailField(help_text=b"This email address will be used in the 'From' line of automated emails sent by RELATE. It will also receive notifications about required approvals.", max_length=75)),
                ('course_xmpp_id', models.CharField(max_length=200, blank=True)),
                ('course_xmpp_password', models.CharField(max_length=200, blank=True)),
                ('active_git_commit_sha', models.CharField(max_length=200)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='FlowAccessException',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('flow_id', models.CharField(max_length=200)),
                ('expiration', models.DateTimeField(null=True, blank=True)),
                ('stipulations', jsonfield.fields.JSONField(help_text=b'A dictionary of the same things that can be added to a flow access rule, such as allowed_session_count or credit_percent. If not specified here, values will default to the stipulations in the course content.', null=True, blank=True)),
                ('creation_time', models.DateTimeField(default=django.utils.timezone.now, db_index=True)),
                ('creator', models.ForeignKey(to=settings.AUTH_USER_MODEL, null=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='FlowAccessExceptionEntry',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('permission', models.CharField(max_length=50, choices=[(b'view', b'View flow'), (b'view_past', b'Review past attempts'), (b'start_credit', b'Start for-credit session'), (b'start_no_credit', b'Start not-for-credit session'), (b'see_correctness', b'See whether answer is correct'), (b'see_answer', b'See the correct answer')])),
                ('exception', models.ForeignKey(to='course.FlowAccessException')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='FlowPageData',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('ordinal', models.IntegerField()),
                ('group_id', models.CharField(max_length=200)),
                ('page_id', models.CharField(max_length=200)),
                ('data', jsonfield.fields.JSONField(null=True, blank=True)),
            ],
            options={
                'verbose_name_plural': b'flow page data',
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='FlowPageVisit',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('visit_time', models.DateTimeField(default=django.utils.timezone.now, db_index=True)),
                ('answer', jsonfield.fields.JSONField(null=True, blank=True)),
                ('answer_is_final', models.NullBooleanField()),
                ('grade_data', jsonfield.fields.JSONField(null=True, blank=True)),
                ('page_data', models.ForeignKey(to='course.FlowPageData')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='FlowSession',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('active_git_commit_sha', models.CharField(max_length=200)),
                ('flow_id', models.CharField(max_length=200)),
                ('start_time', models.DateTimeField(default=django.utils.timezone.now)),
                ('completion_time', models.DateTimeField(null=True, blank=True)),
                ('page_count', models.IntegerField(null=True, blank=True)),
                ('in_progress', models.BooleanField(default=None)),
                ('for_credit', models.BooleanField(default=None)),
                ('points', models.DecimalField(null=True, max_digits=10, decimal_places=2, blank=True)),
                ('max_points', models.DecimalField(null=True, max_digits=10, decimal_places=2, blank=True)),
                ('result_comment', models.TextField(null=True, blank=True)),
            ],
            options={
                'ordering': (b'participation', b'-start_time'),
            },
            bases=(models.Model,),
        ),
        migrations.AddField(
            model_name='flowpagevisit',
            name='flow_session',
            field=models.ForeignKey(to='course.FlowSession'),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='flowpagevisit',
            unique_together=set([(b'page_data', b'visit_time')]),
        ),
        migrations.AddField(
            model_name='flowpagedata',
            name='flow_session',
            field=models.ForeignKey(to='course.FlowSession'),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='flowpagedata',
            unique_together=set([(b'flow_session', b'ordinal')]),
        ),
        migrations.CreateModel(
            name='GradeChange',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('state', models.CharField(max_length=50, choices=[(b'grading_started', b'Grading started'), (b'graded', b'Graded'), (b'retrieved', b'Retrieved'), (b'unavailable', b'Unavailable'), (b'extension', b'Extension'), (b'report_sent', b'Report sent'), (b'do_over', b'Do-over'), (b'exempt', b'Exempt')])),
                ('points', models.DecimalField(null=True, max_digits=10, decimal_places=2, blank=True)),
                ('max_points', models.DecimalField(max_digits=10, decimal_places=2)),
                ('comment', models.TextField(null=True, blank=True)),
                ('due_time', models.DateTimeField(default=None, null=True, blank=True)),
                ('grade_time', models.DateTimeField(default=django.utils.timezone.now, db_index=True)),
                ('creator', models.ForeignKey(to=settings.AUTH_USER_MODEL, null=True)),
                ('flow_session', models.ForeignKey(blank=True, to='course.FlowSession', null=True)),
            ],
            options={
                'ordering': (b'opportunity', b'participation', b'grade_time'),
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='GradingOpportunity',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('identifier', models.CharField(help_text=b'A symbolic name for this grade. lower_case_with_underscores, no spaces.', max_length=200)),
                ('name', models.CharField(help_text=b'A human-readable identifier for the grade.', max_length=200)),
                ('flow_id', models.CharField(help_text=b'Flow identifier that this grading opportunity is linked to, if any', max_length=200, null=True, blank=True)),
                ('aggregation_strategy', models.CharField(max_length=20, choices=[(b'max_grade', b'Use the max grade'), (b'avg_grade', b'Use the avg grade'), (b'min_grade', b'Use the min grade'), (b'use_earliest', b'Use the earliest grade'), (b'use_latest', b'Use the latest grade')])),
                ('due_time', models.DateTimeField(default=None, null=True, blank=True)),
                ('course', models.ForeignKey(to='course.Course')),
            ],
            options={
                'ordering': (b'course', b'due_time', b'identifier'),
                'verbose_name_plural': b'grading opportunities',
            },
            bases=(models.Model,),
        ),
        migrations.AddField(
            model_name='gradechange',
            name='opportunity',
            field=models.ForeignKey(to='course.GradingOpportunity'),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='gradingopportunity',
            unique_together=set([(b'course', b'identifier')]),
        ),
        migrations.CreateModel(
            name='InstantFlowRequest',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('flow_id', models.CharField(max_length=200)),
                ('start_time', models.DateTimeField(default=django.utils.timezone.now)),
                ('end_time', models.DateTimeField()),
                ('course', models.ForeignKey(to='course.Course')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='Participation',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('enroll_time', models.DateTimeField(default=django.utils.timezone.now)),
                ('role', models.CharField(max_length=50, choices=[(b'instructor', b'Instructor'), (b'ta', b'Teaching Assistant'), (b'student', b'Student')])),
                ('temporary_role', models.CharField(blank=True, max_length=50, null=True, choices=[(b'instructor', b'Instructor'), (b'ta', b'Teaching Assistant'), (b'student', b'Student')])),
                ('status', models.CharField(max_length=50, choices=[(b'requested', b'Requested'), (b'active', b'Active'), (b'dropped', b'Dropped'), (b'denied', b'Denied')])),
                ('time_factor', models.DecimalField(default=1, max_digits=10, decimal_places=2)),
                ('preview_git_commit_sha', models.CharField(max_length=200, null=True, blank=True)),
            ],
            options={
                'ordering': (b'course', b'user'),
            },
            bases=(models.Model,),
        ),
        migrations.AddField(
            model_name='gradechange',
            name='participation',
            field=models.ForeignKey(to='course.Participation'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='flowsession',
            name='participation',
            field=models.ForeignKey(blank=True, to='course.Participation', null=True),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='flowaccessexception',
            name='participation',
            field=models.ForeignKey(to='course.Participation'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='course',
            name='participants',
            field=models.ManyToManyField(to=settings.AUTH_USER_MODEL, through='course.Participation'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='participation',
            name='course',
            field=models.ForeignKey(to='course.Course'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='participation',
            name='user',
            field=models.ForeignKey(to=settings.AUTH_USER_MODEL),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='participation',
            unique_together=set([(b'user', b'course')]),
        ),
        migrations.CreateModel(
            name='TimeLabel',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('kind', models.CharField(help_text=b'Should be lower_case_with_underscores, no spaces allowed.', max_length=50)),
                ('ordinal', models.IntegerField(null=True, blank=True)),
                ('time', models.DateTimeField()),
                ('course', models.ForeignKey(to='course.Course')),
            ],
            options={
                'ordering': (b'course', b'time'),
            },
            bases=(models.Model,),
        ),
        migrations.AlterUniqueTogether(
            name='timelabel',
            unique_together=set([(b'course', b'kind', b'ordinal')]),
        ),
        migrations.CreateModel(
            name='UserStatus',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('status', models.CharField(max_length=50, choices=[(b'unconfirmed', b'Unconfirmed'), (b'active', b'Active')])),
                ('sign_in_key', models.CharField(db_index=True, max_length=50, unique=True, null=True, blank=True)),
                ('key_time', models.DateTimeField(default=django.utils.timezone.now)),
                ('user', models.OneToOneField(to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': (b'key_time',),
                'verbose_name_plural': b'user statuses',
            },
            bases=(models.Model,),
        ),
    ]
