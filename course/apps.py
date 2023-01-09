from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

from relate.checks import register_startup_checks, register_startup_checks_extra


class CourseConfig(AppConfig):
    name = "course"
    # for translation of the name of "Course" app displayed in admin.
    verbose_name = _("Course module")

    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        import course.receivers  # noqa

        # register all checks
        register_startup_checks()
        register_startup_checks_extra()
