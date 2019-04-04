from django.apps import AppConfig
from django.utils.translation import ugettext_lazy as _


class CasConfig(AppConfig):
    name = 'cas-config'
    verbose_name = _("CAS attribute callback shim")
