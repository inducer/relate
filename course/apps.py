from django.apps import AppConfig
from django.utils.translation import ugettext_lazy as _


class CourseConfig(AppConfig):
    name = 'course'
    # for translation of the name of "Course" app displayed in admin.
    verbose_name = _("Course module")

    def ready(self):
        import course.receivers  # noqa
