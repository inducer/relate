from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AccountsConfig(AppConfig):
    name = 'accounts'
    # for translation of the name of "Accounts" app displayed in admin.
    verbose_name = _("Accounts")
