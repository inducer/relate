from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AccountsConfig(AppConfig):
    name = "accounts"

    default_auto_field = "django.db.models.BigAutoField"

    # for translation of the name of "Accounts" app displayed in admin.
    verbose_name = _("Accounts")
