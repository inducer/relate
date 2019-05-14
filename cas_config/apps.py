from django.apps import AppConfig
from django.utils.translation import ugettext_lazy as _
from django_cas_ng.signals import cas_user_authenticated

from cas_config.receivers import cas_attribute_callback_manager


class CasConfig(AppConfig):
    name = 'cas_config'
    verbose_name = _("CAS attribute callback shim")

    def ready(self):
        cas_user_authenticated.connect(
            cas_attribute_callback_manager,
            dispatch_uid="cas-attribute-callback-manager-init")
