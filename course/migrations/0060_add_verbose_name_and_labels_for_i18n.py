from django.db import models, migrations
import jsonfield.fields
import course.models
import django.utils.timezone
from django.conf import settings
import yamlfield.fields


class Migration(migrations.Migration):

    dependencies = [
        ('course', '0059_add_facility_ip_range_related_name'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='course',
            options={'verbose_name': 'Course', 'verbose_name_plural': 'Courses'},
        ),
        migrations.AlterModelOptions(
            name='event',
            options={'ordering': ('course', 'time'), 'verbose_name': 'Event', 'verbose_name_plural': 'Events'},
        ),
        migrations.AlterModelOptions(
            name='facility',
            options={'verbose_name': 'Facility', 'verbose_name_plural': 'Facilities'},
        ),
        migrations.AlterModelOptions(
            name='facilityiprange',
            options={'verbose_name': 'Facility IP range'},
        ),
        migrations.AlterModelOptions(
            name='flowaccessexceptionentry',
            options={'verbose_name_plural': 'Flow access exception entries'},
        ),
        migrations.AlterModelOptions(
            name='flowpagedata',
            options={'verbose_name': 'Flow page data', 'verbose_name_plural': 'Flow page data'},
        ),
        migrations.AlterModelOptions(
            name='flowpagevisit',
            options={'verbose_name': 'Flow page visit', 'verbose_name_plural': 'Flow page visits'},
        ),
        migrations.AlterModelOptions(
            name='flowpagevisitgrade',
            options={'ordering': ('visit', 'grade_time'), 'verbose_name': 'Flow page visit grade', 'verbose_name_plural': 'Flow page visit grades'},
        ),
        migrations.AlterModelOptions(
            name='flowruleexception',
            options={'verbose_name': 'Flow rule exception', 'verbose_name_plural': 'Flow rule exceptions'},
        ),
        migrations.AlterModelOptions(
            name='flowsession',
            options={'ordering': ('course', '-start_time'), 'verbose_name': 'Flow session', 'verbose_name_plural': 'Flow sessions'},
        ),
        migrations.AlterModelOptions(
            name='gradechange',
            options={'ordering': ('opportunity', 'participation', 'grade_time'), 'verbose_name': 'Grade change', 'verbose_name_plural': 'Grade changes'},
        ),
        migrations.AlterModelOptions(
            name='gradingopportunity',
            options={'ordering': ('course', 'due_time', 'identifier'), 'verbose_name': 'Grading opportunity', 'verbose_name_plural': 'Grading opportunities'},
        ),
        migrations.AlterModelOptions(
            name='instantflowrequest',
            options={'verbose_name': 'Instant flow request', 'verbose_name_plural': 'Instant flow requests'},
        ),
        migrations.AlterModelOptions(
            name='instantmessage',
            options={'ordering': ('participation__course', 'time'), 'verbose_name': 'Instant message', 'verbose_name_plural': 'Instant messages'},
        ),
        migrations.AlterModelOptions(
            name='participation',
            options={'ordering': ('course', 'user'), 'verbose_name': 'Participation', 'verbose_name_plural': 'Participations'},
        ),
        migrations.AlterModelOptions(
            name='participationpreapproval',
            options={'ordering': ('course', 'email'), 'verbose_name': 'Participation preapproval', 'verbose_name_plural': 'Participation preapprovals'},
        ),
        migrations.AlterModelOptions(
            name='participationtag',
            options={'ordering': ('course', 'name'), 'verbose_name': 'Participation tag', 'verbose_name_plural': 'Participation tags'},
        ),
        migrations.AlterModelOptions(
            name='userstatus',
            options={'ordering': ('key_time',), 'verbose_name': 'User status', 'verbose_name_plural': 'User statuses'},
        ),
        migrations.AlterField(
            model_name='course',
            name='accepts_enrollment',
            field=models.BooleanField(default=True, verbose_name='Accepts enrollment'),
        ),
        migrations.AlterField(
            model_name='course',
            name='active_git_commit_sha',
            field=models.CharField(max_length=200, verbose_name='Active git commit SHA'),
        ),
        migrations.AlterField(
            model_name='course',
            name='course_file',
            field=models.CharField(default='course.yml', help_text='Name of a YAML file in the git repository that contains the root course descriptor.', max_length=200, verbose_name='Course file'),
        ),
        migrations.AlterField(
            model_name='course',
            name='course_xmpp_id',
            field=models.CharField(help_text='(Required only if the instant message feature is desired.) The Jabber/XMPP ID (JID) the course will use to sign in to an XMPP server.', max_length=200, null=True, verbose_name='Course xmpp ID', blank=True),
        ),
        migrations.AlterField(
            model_name='course',
            name='course_xmpp_password',
            field=models.CharField(help_text='(Required only if the instant message feature is desired.) The password to go with the JID above.', max_length=200, null=True, verbose_name='Course xmpp password', blank=True),
        ),
        migrations.AlterField(
            model_name='course',
            name='enrollment_approval_required',
            field=models.BooleanField(default=False, help_text='If set, each enrolling student must be individually approved.', verbose_name='Enrollment approval required'),
        ),
        migrations.AlterField(
            model_name='course',
            name='enrollment_required_email_suffix',
            field=models.CharField(help_text="Enrollee's email addresses must end in the specified suffix, such as '@illinois.edu'.", max_length=200, null=True, verbose_name='Enrollment required email suffix', blank=True),
        ),
        migrations.AlterField(
            model_name='course',
            name='events_file',
            field=models.CharField(default='events.yml', help_text='Name of a YAML file in the git repository that contains calendar information.', max_length=200, verbose_name='Events file'),
        ),
        migrations.AlterField(
            model_name='course',
            name='from_email',
            field=models.EmailField(help_text="This email address will be used in the 'From' line of automated emails sent by RELATE.", max_length=254, verbose_name='From email'),
        ),
        migrations.AlterField(
            model_name='course',
            name='git_source',
            field=models.CharField(help_text="A Git URL from which to pull course updates. If you're just starting out, enter <tt>git://github.com/inducer/relate-sample</tt> to get some sample content.", max_length=200, verbose_name='git source', blank=True),
        ),
        migrations.AlterField(
            model_name='course',
            name='hidden',
            field=models.BooleanField(default=True, help_text='Is the course only accessible to course staff?', verbose_name='Hidden to student'),
        ),
        migrations.AlterField(
            model_name='course',
            name='identifier',
            field=models.CharField(help_text="A course identifier. Alphanumeric with dashes, no spaces. This is visible in URLs and determines the location on your file system where the course's git repository lives.", unique=True, max_length=200, verbose_name='Course identifier', db_index=True),
        ),
        migrations.AlterField(
            model_name='course',
            name='listed',
            field=models.BooleanField(default=True, help_text='Should the course be listed on the main page?', verbose_name='Listed on main page'),
        ),
        migrations.AlterField(
            model_name='course',
            name='notify_email',
            field=models.EmailField(help_text='This email address will receive notifications about the course.', max_length=254, verbose_name='Notify email'),
        ),
        migrations.AlterField(
            model_name='course',
            name='recipient_xmpp_id',
            field=models.CharField(help_text='(Required only if the instant message feature is desired.) The JID to which instant messages will be sent.', max_length=200, null=True, verbose_name='Recipient xmpp ID', blank=True),
        ),
        migrations.AlterField(
            model_name='course',
            name='ssh_private_key',
            field=models.TextField(help_text='An SSH private key to use for Git authentication. Not needed for the sample URL above.', verbose_name='SSH private key', blank=True),
        ),
        migrations.AlterField(
            model_name='course',
            name='valid',
            field=models.BooleanField(default=True, help_text='Whether the course content has passed validation.', verbose_name='Valid'),
        ),
        migrations.AlterField(
            model_name='event',
            name='all_day',
            field=models.BooleanField(default=False, help_text='Only affects the rendering in the class calendar, in that a start time is not shown', verbose_name='All day'),
        ),
        migrations.AlterField(
            model_name='event',
            name='course',
            field=models.ForeignKey(verbose_name='Course identifier', to='course.Course', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='event',
            name='end_time',
            field=models.DateTimeField(null=True, verbose_name='End time', blank=True),
        ),
        migrations.AlterField(
            model_name='event',
            name='kind',
            field=models.CharField(help_text='Should be lower_case_with_underscores, no spaces allowed.', max_length=50, verbose_name='Kind of event'),
        ),
        migrations.AlterField(
            model_name='event',
            name='ordinal',
            field=models.IntegerField(null=True, verbose_name='Ordinal of event', blank=True),
        ),
        migrations.AlterField(
            model_name='event',
            name='shown_in_calendar',
            field=models.BooleanField(default=True, verbose_name='Shown in calendar'),
        ),
        migrations.AlterField(
            model_name='event',
            name='time',
            field=models.DateTimeField(verbose_name='Start time'),
        ),
        migrations.AlterField(
            model_name='facility',
            name='description',
            field=models.CharField(max_length=100, verbose_name='Facility description'),
        ),
        migrations.AlterField(
            model_name='facility',
            name='identifier',
            field=models.CharField(help_text='Format is lower-case-with-hyphens. Do not use spaces.', unique=True, max_length=50, verbose_name='Facility ID'),
        ),
        migrations.AlterField(
            model_name='facilityiprange',
            name='description',
            field=models.CharField(max_length=100, verbose_name='IP range description'),
        ),
        migrations.AlterField(
            model_name='facilityiprange',
            name='ip_range',
            field=models.CharField(max_length=200, verbose_name='IP range'),
        ),
        migrations.AlterField(
            model_name='flowaccessexception',
            name='comment',
            field=models.TextField(null=True, verbose_name='Comment', blank=True),
        ),
        migrations.AlterField(
            model_name='flowaccessexception',
            name='creation_time',
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name='Creation time', db_index=True),
        ),
        migrations.AlterField(
            model_name='flowaccessexception',
            name='creator',
            field=models.ForeignKey(verbose_name='Creator', to=settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='flowaccessexception',
            name='expiration',
            field=models.DateTimeField(null=True, verbose_name='Expiration', blank=True),
        ),
        migrations.AlterField(
            model_name='flowaccessexception',
            name='flow_id',
            field=models.CharField(max_length=200, verbose_name='Flow ID'),
        ),
        migrations.AlterField(
            model_name='flowaccessexception',
            name='is_sticky',
            field=models.BooleanField(default=False, help_text='Check if a flow started under this exception rule set should stay under this rule set until it is expired.', verbose_name='Is sticky'),
        ),
        migrations.AlterField(
            model_name='flowaccessexception',
            name='participation',
            field=models.ForeignKey(verbose_name='Participation', to='course.Participation', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='flowaccessexception',
            name='stipulations',
            field=jsonfield.fields.JSONField(blank=True, help_text='A dictionary of the same things that can be added to a flow access rule, such as allowed_session_count or credit_percent. If not specified here, values will default to the stipulations in the course content.', null=True, verbose_name='Stipulations', validators=[course.models.validate_stipulations]),
        ),
        migrations.AlterField(
            model_name='flowaccessexceptionentry',
            name='exception',
            field=models.ForeignKey(related_name='entries', verbose_name='Exception', to='course.FlowAccessException', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='flowaccessexceptionentry',
            name='permission',
            field=models.CharField(max_length=50, verbose_name='Permission', choices=[('view', 'View the flow'), ('submit_answer', 'Submit answers'), ('end_session', 'End session'), ('change_answer', 'Change already-graded answer'), ('see_correctness', 'See whether an answer is correct'), ('see_answer_before_submission', 'See the correct answer before answering'), ('see_answer_after_submission', 'See the correct answer after answering'), ('set_roll_over_expiration_mode', "Set the session to 'roll over' expiration mode")]),
        ),
        migrations.AlterField(
            model_name='flowpagebulkfeedback',
            name='bulk_feedback',
            field=jsonfield.fields.JSONField(null=True, verbose_name='Bulk feedback', blank=True),
        ),
        migrations.AlterField(
            model_name='flowpagebulkfeedback',
            name='grade',
            field=models.ForeignKey(verbose_name='Grade', to='course.FlowPageVisitGrade', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='flowpagebulkfeedback',
            name='page_data',
            field=models.OneToOneField(verbose_name='Page data', to='course.FlowPageData', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='flowpagedata',
            name='data',
            field=jsonfield.fields.JSONField(null=True, verbose_name='Data', blank=True),
        ),
        migrations.AlterField(
            model_name='flowpagedata',
            name='flow_session',
            field=models.ForeignKey(related_name='page_data', verbose_name='Flow session', to='course.FlowSession', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='flowpagedata',
            name='group_id',
            field=models.CharField(max_length=200, verbose_name='Group ID'),
        ),
        migrations.AlterField(
            model_name='flowpagedata',
            name='ordinal',
            field=models.IntegerField(null=True, verbose_name='Ordinal', blank=True),
        ),
        migrations.AlterField(
            model_name='flowpagedata',
            name='page_id',
            field=models.CharField(max_length=200, verbose_name='Page ID'),
        ),
        migrations.AlterField(
            model_name='flowpagevisit',
            name='answer',
            field=jsonfield.fields.JSONField(null=True, verbose_name='Answer', blank=True),
        ),
        migrations.AlterField(
            model_name='flowpagevisit',
            name='flow_session',
            field=models.ForeignKey(verbose_name='Flow session', to='course.FlowSession', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='flowpagevisit',
            name='is_submitted_answer',
            field=models.NullBooleanField(verbose_name='Is submitted answer'),
        ),
        migrations.AlterField(
            model_name='flowpagevisit',
            name='is_synthetic',
            field=models.BooleanField(default=False, help_text='Synthetic flow page visits are generated for unvisited pages once a flow is finished. This is needed since grade information is attached to a visit, and it needs a place to go.', verbose_name='Is synthetic'),
        ),
        migrations.AlterField(
            model_name='flowpagevisit',
            name='page_data',
            field=models.ForeignKey(verbose_name='Page data', to='course.FlowPageData', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='flowpagevisit',
            name='remote_address',
            field=models.GenericIPAddressField(null=True, verbose_name='Remote address', blank=True),
        ),
        migrations.AlterField(
            model_name='flowpagevisit',
            name='visit_time',
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name='Visit time', db_index=True),
        ),
        migrations.AlterField(
            model_name='flowpagevisitgrade',
            name='correctness',
            field=models.FloatField(help_text='Real number between zero and one (inclusively) indicating the degree of correctness of the answer.', null=True, verbose_name='Correctness', blank=True),
        ),
        migrations.AlterField(
            model_name='flowpagevisitgrade',
            name='feedback',
            field=jsonfield.fields.JSONField(null=True, verbose_name='Feedback', blank=True),
        ),
        migrations.AlterField(
            model_name='flowpagevisitgrade',
            name='grade_data',
            field=jsonfield.fields.JSONField(null=True, verbose_name='Grade data', blank=True),
        ),
        migrations.AlterField(
            model_name='flowpagevisitgrade',
            name='grade_time',
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name='Grade time', db_index=True),
        ),
        migrations.AlterField(
            model_name='flowpagevisitgrade',
            name='graded_at_git_commit_sha',
            field=models.CharField(max_length=200, null=True, verbose_name='Graded at git commit SHA', blank=True),
        ),
        migrations.AlterField(
            model_name='flowpagevisitgrade',
            name='grader',
            field=models.ForeignKey(verbose_name='Grader', blank=True, to=settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='flowpagevisitgrade',
            name='max_points',
            field=models.FloatField(help_text='Point value of this question when receiving full credit.', null=True, verbose_name='Max points', blank=True),
        ),
        migrations.AlterField(
            model_name='flowpagevisitgrade',
            name='visit',
            field=models.ForeignKey(related_name='grades', verbose_name='Visit', to='course.FlowPageVisit', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='flowruleexception',
            name='active',
            field=models.BooleanField(default=True, verbose_name='Active'),
        ),
        migrations.AlterField(
            model_name='flowruleexception',
            name='comment',
            field=models.TextField(null=True, verbose_name='Comment', blank=True),
        ),
        migrations.AlterField(
            model_name='flowruleexception',
            name='creation_time',
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name='Creation time', db_index=True),
        ),
        migrations.AlterField(
            model_name='flowruleexception',
            name='creator',
            field=models.ForeignKey(verbose_name='Creator', to=settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='flowruleexception',
            name='expiration',
            field=models.DateTimeField(null=True, verbose_name='Expiration', blank=True),
        ),
        migrations.AlterField(
            model_name='flowruleexception',
            name='flow_id',
            field=models.CharField(max_length=200, verbose_name='Flow ID'),
        ),
        migrations.AlterField(
            model_name='flowruleexception',
            name='kind',
            field=models.CharField(max_length=50, verbose_name='Kind', choices=[('start', 'Session Start'), ('access', 'Session Access'), ('grading', 'Grading')]),
        ),
        migrations.AlterField(
            model_name='flowruleexception',
            name='participation',
            field=models.ForeignKey(verbose_name='Participation', to='course.Participation', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='flowruleexception',
            name='rule',
            field=yamlfield.fields.YAMLField(verbose_name='Rule'),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='access_rules_tag',
            field=models.CharField(max_length=200, null=True, verbose_name='Access rules tag', blank=True),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='active_git_commit_sha',
            field=models.CharField(max_length=200, verbose_name='Active git commit SHA'),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='completion_time',
            field=models.DateTimeField(null=True, verbose_name='Completition time', blank=True),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='course',
            field=models.ForeignKey(verbose_name='Course identifier', to='course.Course', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='expiration_mode',
            field=models.CharField(default='end', max_length=20, null=True, verbose_name='Expiration mode', choices=[('end', 'End session and grade'), ('roll_over', 'Keep session and apply new rules')]),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='flow_id',
            field=models.CharField(max_length=200, verbose_name='Flow ID', db_index=True),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='in_progress',
            field=models.BooleanField(default=None, verbose_name='In progress'),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='max_points',
            field=models.DecimalField(null=True, verbose_name='Max point', max_digits=10, decimal_places=2, blank=True),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='page_count',
            field=models.IntegerField(null=True, verbose_name='Page count', blank=True),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='participation',
            field=models.ForeignKey(verbose_name='Participation', blank=True, to='course.Participation', null=True, on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='points',
            field=models.DecimalField(null=True, verbose_name='Points', max_digits=10, decimal_places=2, blank=True),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='result_comment',
            field=models.TextField(null=True, verbose_name='Result comment', blank=True),
        ),
        migrations.AlterField(
            model_name='flowsession',
            name='start_time',
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name='Start time'),
        ),
        migrations.AlterField(
            model_name='gradechange',
            name='attempt_id',
            field=models.CharField(default='main', max_length=50, blank=True, help_text="Grade changes are grouped by their 'attempt ID' where later grades with the same attempt ID supersede earlier ones.", null=True, verbose_name='Attempt ID'),
        ),
        migrations.AlterField(
            model_name='gradechange',
            name='comment',
            field=models.TextField(null=True, verbose_name='Comment', blank=True),
        ),
        migrations.AlterField(
            model_name='gradechange',
            name='creator',
            field=models.ForeignKey(verbose_name='Creator', to=settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='gradechange',
            name='due_time',
            field=models.DateTimeField(default=None, null=True, verbose_name='Due time', blank=True),
        ),
        migrations.AlterField(
            model_name='gradechange',
            name='flow_session',
            field=models.ForeignKey(related_name='grade_changes', verbose_name='Flow session', blank=True, to='course.FlowSession', null=True, on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='gradechange',
            name='grade_time',
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name='Grade time', db_index=True),
        ),
        migrations.AlterField(
            model_name='gradechange',
            name='max_points',
            field=models.DecimalField(verbose_name='Max points', max_digits=10, decimal_places=2),
        ),
        migrations.AlterField(
            model_name='gradechange',
            name='opportunity',
            field=models.ForeignKey(verbose_name='Grading opportunity', to='course.GradingOpportunity', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='gradechange',
            name='participation',
            field=models.ForeignKey(verbose_name='Participation', to='course.Participation', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='gradechange',
            name='points',
            field=models.DecimalField(null=True, verbose_name='Points', max_digits=10, decimal_places=2, blank=True),
        ),
        migrations.AlterField(
            model_name='gradechange',
            name='state',
            field=models.CharField(max_length=50, verbose_name='State', choices=[('grading_started', 'Grading started'), ('graded', 'Graded'), ('retrieved', 'Retrieved'), ('unavailable', 'Unavailable'), ('extension', 'Extension'), ('report_sent', 'Report sent'), ('do_over', 'Do-over'), ('exempt', 'Exempt')]),
        ),
        migrations.AlterField(
            model_name='gradingopportunity',
            name='aggregation_strategy',
            field=models.CharField(max_length=20, verbose_name='Aggregation strategy', choices=[('max_grade', 'Use the max grade'), ('avg_grade', 'Use the avg grade'), ('min_grade', 'Use the min grade'), ('use_earliest', 'Use the earliest grade'), ('use_latest', 'Use the latest grade')]),
        ),
        migrations.AlterField(
            model_name='gradingopportunity',
            name='course',
            field=models.ForeignKey(verbose_name='Course identifier', to='course.Course', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='gradingopportunity',
            name='creation_time',
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name='Creation time'),
        ),
        migrations.AlterField(
            model_name='gradingopportunity',
            name='due_time',
            field=models.DateTimeField(default=None, null=True, verbose_name='Due time', blank=True),
        ),
        migrations.AlterField(
            model_name='gradingopportunity',
            name='flow_id',
            field=models.CharField(help_text='Flow identifier that this grading opportunity is linked to, if any', max_length=200, null=True, verbose_name='Flow ID', blank=True),
        ),
        migrations.AlterField(
            model_name='gradingopportunity',
            name='identifier',
            field=models.CharField(help_text='A symbolic name for this grade. lower_case_with_underscores, no spaces.', max_length=200, verbose_name='Grading opportunity ID'),
        ),
        migrations.AlterField(
            model_name='gradingopportunity',
            name='name',
            field=models.CharField(help_text='A human-readable identifier for the grade.', max_length=200, verbose_name='Grading opportunity name'),
        ),
        migrations.AlterField(
            model_name='gradingopportunity',
            name='shown_in_grade_book',
            field=models.BooleanField(default=True, verbose_name='Shown in grade book'),
        ),
        migrations.AlterField(
            model_name='gradingopportunity',
            name='shown_in_student_grade_book',
            field=models.BooleanField(default=True, verbose_name='Shown in student grade book'),
        ),
        migrations.AlterField(
            model_name='instantflowrequest',
            name='cancelled',
            field=models.BooleanField(default=False, verbose_name='Cancelled'),
        ),
        migrations.AlterField(
            model_name='instantflowrequest',
            name='course',
            field=models.ForeignKey(verbose_name='Course identifier', to='course.Course', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='instantflowrequest',
            name='end_time',
            field=models.DateTimeField(verbose_name='End time'),
        ),
        migrations.AlterField(
            model_name='instantflowrequest',
            name='flow_id',
            field=models.CharField(max_length=200, verbose_name='Flow ID'),
        ),
        migrations.AlterField(
            model_name='instantflowrequest',
            name='start_time',
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name='Start time'),
        ),
        migrations.AlterField(
            model_name='instantmessage',
            name='participation',
            field=models.ForeignKey(verbose_name='Participation', to='course.Participation', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='instantmessage',
            name='text',
            field=models.CharField(max_length=200, verbose_name='Text'),
        ),
        migrations.AlterField(
            model_name='instantmessage',
            name='time',
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name='Time'),
        ),
        migrations.AlterField(
            model_name='participation',
            name='course',
            field=models.ForeignKey(related_name='participations', verbose_name='Course identifier', to='course.Course', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='participation',
            name='enroll_time',
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name='Enroll time'),
        ),
        migrations.AlterField(
            model_name='participation',
            name='preview_git_commit_sha',
            field=models.CharField(max_length=200, null=True, verbose_name='Preview git commit SHA', blank=True),
        ),
        migrations.AlterField(
            model_name='participation',
            name='role',
            field=models.CharField(help_text='Instructors may update course content. Teaching assistants may access and change grade data. Observers may access analytics. Each role includes privileges from subsequent roles.', max_length=50, verbose_name='Participation role', choices=[('instructor', 'Instructor'), ('ta', 'Teaching Assistant'), ('student', 'Student'), ('observer', 'Observer'), ('auditor', 'Auditor')]),
        ),
        migrations.AlterField(
            model_name='participation',
            name='status',
            field=models.CharField(max_length=50, verbose_name='Participation status', choices=[('requested', 'Requested'), ('active', 'Active'), ('dropped', 'Dropped'), ('denied', 'Denied')]),
        ),
        migrations.AlterField(
            model_name='participation',
            name='tags',
            field=models.ManyToManyField(to='course.ParticipationTag', verbose_name='Tags', blank=True),
        ),
        migrations.AlterField(
            model_name='participation',
            name='time_factor',
            field=models.DecimalField(default=1, help_text='Multiplier for time available on time-limited flows (time-limited flows are currently unimplemented).', verbose_name='Time factor', max_digits=10, decimal_places=2),
        ),
        migrations.AlterField(
            model_name='participation',
            name='user',
            field=models.ForeignKey(verbose_name='User ID', to=settings.AUTH_USER_MODEL, on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='participationpreapproval',
            name='course',
            field=models.ForeignKey(verbose_name='Course identifier', to='course.Course', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='participationpreapproval',
            name='creation_time',
            field=models.DateTimeField(default=django.utils.timezone.now, verbose_name='Creation time', db_index=True),
        ),
        migrations.AlterField(
            model_name='participationpreapproval',
            name='creator',
            field=models.ForeignKey(verbose_name='Creator', to=settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='participationpreapproval',
            name='email',
            field=models.EmailField(max_length=254, verbose_name='Email'),
        ),
        migrations.AlterField(
            model_name='participationpreapproval',
            name='role',
            field=models.CharField(max_length=50, verbose_name='Role', choices=[('instructor', 'Instructor'), ('ta', 'Teaching Assistant'), ('student', 'Student'), ('observer', 'Observer'), ('auditor', 'Auditor')]),
        ),
        migrations.AlterField(
            model_name='participationtag',
            name='course',
            field=models.ForeignKey(verbose_name='Course identifier', to='course.Course', on_delete=models.CASCADE),
        ),
        migrations.AlterField(
            model_name='participationtag',
            name='name',
            field=models.CharField(help_text='Format is lower-case-with-hyphens. Do not use spaces.', unique=True, max_length=100, verbose_name='Name of participation tag'),
        ),
        migrations.AlterField(
            model_name='userstatus',
            name='editor_mode',
            field=models.CharField(default='default', max_length=20, verbose_name='Editor mode', choices=[('default', 'Default'), ('sublime', 'Sublime text'), ('emacs', 'Emacs'), ('vim', 'Vim')]),
        ),
        migrations.AlterField(
            model_name='userstatus',
            name='key_time',
            field=models.DateTimeField(default=django.utils.timezone.now, help_text='The time stamp of the sign in token.', verbose_name='Key time'),
        ),
        migrations.AlterField(
            model_name='userstatus',
            name='sign_in_key',
            field=models.CharField(null=True, max_length=50, blank=True, help_text='The sign in token sent out in email.', unique=True, verbose_name='Sign in key', db_index=True),
        ),
        migrations.AlterField(
            model_name='userstatus',
            name='status',
            field=models.CharField(max_length=50, verbose_name='User status', choices=[('unconfirmed', 'Unconfirmed'), ('active', 'Active')]),
        ),
        migrations.AlterField(
            model_name='userstatus',
            name='user',
            field=models.OneToOneField(related_name='user_status', verbose_name='User ID', to=settings.AUTH_USER_MODEL, on_delete=models.CASCADE),
        ),
    ]
