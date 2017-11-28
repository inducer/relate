from django.apps import AppConfig
from django.utils.translation import ugettext_lazy as _
from relate.checks import register_startup_checks_extra, register_startup_checks
from course.docker.checks import register_docker_client_config_checks


class CourseConfig(AppConfig):
    name = 'course'
    # for translation of the name of "Course" app displayed in admin.
    verbose_name = _("Course module")

    def ready(self):
        import course.receivers  # noqa

        # register all checks
        register_startup_checks()
        register_docker_client_config_checks()
        register_startup_checks_extra()
