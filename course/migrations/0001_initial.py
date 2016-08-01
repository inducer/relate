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
                ('hidden', models.BooleanField(default=True, help_text='Is the course only visible to course staff?')),
                ('valid', models.BooleanField(default=True, help_text='Whether the course content has passed validation.')),
                ('git_source', models.CharField(help_text=b"A Git URL from which to pull course updates. If you're just starting out, enter <tt>git://github.com/inducer/relate-sample</tt> to get some sample content.", max_length=200, blank=True)),
                ('ssh_private_key', models.TextField(help_text='An SSH private key to use for Git authentication', blank=True)),
                ('course_file', models.CharField(default='course.yml', help_text='Name of a YAML file in the git repository that contains the root course descriptor.', max_length=200)),
                ('enrollment_approval_required', models.BooleanField(default=False, help_text='If set, each enrolling student must be individually approved.')),
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
                ('stipulations', jsonfield.fields.JSONField(help_text='A dictionary of the same things that can be added to a flow access rule, such as allowed_session_count or credit_percent. If not specified here, values will default to the stipulations in the course content.', null=True, blank=True)),
                ('creation_time', models.DateTimeField(default=django.utils.timezone.now, db_index=True)),
                ('creator', models.ForeignKey(to=settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='FlowAccessExceptionEntry',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('permission', models.CharField(max_length=50, choices=[('view', 'View flow'), ('view_past', 'Review past attempts'), ('start_credit', 'Start for-credit session'), ('start_no_credit', 'Start not-for-credit session'), ('see_correctness', 'See whether answer is correct'), ('see_answer', 'See the correct answer')])),
                ('exception', models.ForeignKey(to='course.FlowAccessException', on_delete=models.CASCADE)),
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
                'verbose_name_plural': 'flow page data',
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
                ('page_data', models.ForeignKey(to='course.FlowPageData', on_delete=models.CASCADE)),
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
                'ordering': ('participation', '-start_time'),
            },
            bases=(models.Model,),
        ),
        migrations.AddField(
            model_name='flowpagevisit',
            name='flow_session',
            field=models.ForeignKey(to='course.FlowSession', on_delete=models.CASCADE),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='flowpagevisit',
            unique_together=set([('page_data', 'visit_time')]),
        ),
        migrations.AddField(
            model_name='flowpagedata',
            name='flow_session',
            field=models.ForeignKey(to='course.FlowSession', on_delete=models.CASCADE),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='flowpagedata',
            unique_together=set([('flow_session', 'ordinal')]),
        ),
        migrations.CreateModel(
            name='GradeChange',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('state', models.CharField(max_length=50, choices=[('grading_started', 'Grading started'), ('graded', 'Graded'), ('retrieved', 'Retrieved'), ('unavailable', 'Unavailable'), ('extension', 'Extension'), ('report_sent', 'Report sent'), ('do_over', 'Do-over'), ('exempt', 'Exempt')])),
                ('points', models.DecimalField(null=True, max_digits=10, decimal_places=2, blank=True)),
                ('max_points', models.DecimalField(max_digits=10, decimal_places=2)),
                ('comment', models.TextField(null=True, blank=True)),
                ('due_time', models.DateTimeField(default=None, null=True, blank=True)),
                ('grade_time', models.DateTimeField(default=django.utils.timezone.now, db_index=True)),
                ('creator', models.ForeignKey(to=settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE)),
                ('flow_session', models.ForeignKey(blank=True, to='course.FlowSession', null=True, on_delete=models.CASCADE)),
            ],
            options={
                'ordering': ('opportunity', 'participation', 'grade_time'),
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='GradingOpportunity',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('identifier', models.CharField(help_text='A symbolic name for this grade. lower_case_with_underscores, no spaces.', max_length=200)),
                ('name', models.CharField(help_text='A human-readable identifier for the grade.', max_length=200)),
                ('flow_id', models.CharField(help_text='Flow identifier that this grading opportunity is linked to, if any', max_length=200, null=True, blank=True)),
                ('aggregation_strategy', models.CharField(max_length=20, choices=[('max_grade', 'Use the max grade'), ('avg_grade', 'Use the avg grade'), ('min_grade', 'Use the min grade'), ('use_earliest', 'Use the earliest grade'), ('use_latest', 'Use the latest grade')])),
                ('due_time', models.DateTimeField(default=None, null=True, blank=True)),
                ('course', models.ForeignKey(to='course.Course', on_delete=models.CASCADE)),
            ],
            options={
                'ordering': ('course', 'due_time', 'identifier'),
                'verbose_name_plural': 'grading opportunities',
            },
            bases=(models.Model,),
        ),
        migrations.AddField(
            model_name='gradechange',
            name='opportunity',
            field=models.ForeignKey(to='course.GradingOpportunity', on_delete=models.CASCADE),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='gradingopportunity',
            unique_together=set([('course', 'identifier')]),
        ),
        migrations.CreateModel(
            name='InstantFlowRequest',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('flow_id', models.CharField(max_length=200)),
                ('start_time', models.DateTimeField(default=django.utils.timezone.now)),
                ('end_time', models.DateTimeField()),
                ('course', models.ForeignKey(to='course.Course', on_delete=models.CASCADE)),
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
                ('role', models.CharField(max_length=50, choices=[('instructor', 'Instructor'), ('ta', 'Teaching Assistant'), ('student', 'Student')])),
                ('temporary_role', models.CharField(blank=True, max_length=50, null=True, choices=[('instructor', 'Instructor'), ('ta', 'Teaching Assistant'), ('student', 'Student')])),
                ('status', models.CharField(max_length=50, choices=[('requested', 'Requested'), ('active', 'Active'), ('dropped', 'Dropped'), ('denied', 'Denied')])),
                ('time_factor', models.DecimalField(default=1, max_digits=10, decimal_places=2)),
                ('preview_git_commit_sha', models.CharField(max_length=200, null=True, blank=True)),
            ],
            options={
                'ordering': ('course', 'user'),
            },
            bases=(models.Model,),
        ),
        migrations.AddField(
            model_name='gradechange',
            name='participation',
            field=models.ForeignKey(to='course.Participation', on_delete=models.CASCADE),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='flowsession',
            name='participation',
            field=models.ForeignKey(blank=True, to='course.Participation', null=True, on_delete=models.CASCADE),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='flowaccessexception',
            name='participation',
            field=models.ForeignKey(to='course.Participation', on_delete=models.CASCADE),
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
            field=models.ForeignKey(to='course.Course', on_delete=models.CASCADE),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='participation',
            name='user',
            field=models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=models.CASCADE),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='participation',
            unique_together=set([('user', 'course')]),
        ),
        migrations.CreateModel(
            name='TimeLabel',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('kind', models.CharField(help_text='Should be lower_case_with_underscores, no spaces allowed.', max_length=50)),
                ('ordinal', models.IntegerField(null=True, blank=True)),
                ('time', models.DateTimeField()),
                ('course', models.ForeignKey(to='course.Course', on_delete=models.CASCADE)),
            ],
            options={
                'ordering': ('course', 'time'),
            },
            bases=(models.Model,),
        ),
        migrations.AlterUniqueTogether(
            name='timelabel',
            unique_together=set([('course', 'kind', 'ordinal')]),
        ),
        migrations.CreateModel(
            name='UserStatus',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('status', models.CharField(max_length=50, choices=[('unconfirmed', 'Unconfirmed'), ('active', 'Active')])),
                ('sign_in_key', models.CharField(db_index=True, max_length=50, unique=True, null=True, blank=True)),
                ('key_time', models.DateTimeField(default=django.utils.timezone.now)),
                ('user', models.OneToOneField(to=settings.AUTH_USER_MODEL, on_delete=models.CASCADE)),
            ],
            options={
                'ordering': ('key_time',),
                'verbose_name_plural': 'user statuses',
            },
            bases=(models.Model,),
        ),
    ]
