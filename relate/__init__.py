from __future__ import annotations

import os


if "RELATE_COMMAND_LINE" not in os.environ:
    # This will make sure the app is always imported when
    # Django starts so that shared_task will use this app.
    from .celery import app as celery_app  # noqa
