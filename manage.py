#!/usr/bin/env python
from __future__ import annotations

import os
import sys


def get_local_test_settings_file(argv):
    assert argv[1] == "test"
    assert "manage.py" in argv[0]

    local_settings_dir = os.path.split(argv[0])[0]
    assert os.path.isfile(os.path.join(local_settings_dir, "manage.py"))

    from django.core.management import CommandError, CommandParser

    parser = CommandParser(
            usage="%(prog)s subcommand [options] [args]",
            add_help=False)

    parser.add_argument("--local_test_settings",
                        dest="local_test_settings")

    options, _args = parser.parse_known_args(argv)

    if options.local_test_settings is None:
        local_settings_file = "local_settings_example.py"
    else:
        local_settings_file = options.local_test_settings

    if os.path.split(local_settings_file)[0] == "":
        local_settings_file = os.path.join(
            local_settings_dir, local_settings_file)

    if os.path.abspath(local_settings_file) == os.path.abspath(
            os.path.join(local_settings_dir, "local_settings.py")):
        raise CommandError(
            "Using production local_settings for tests is not "
            "allowed due to security reason."
        )

    if not os.path.isfile(local_settings_file):
        raise CommandError(
            "file '%s' does not exist" % local_settings_file
        )

    return local_settings_file


if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "relate.settings")

    from django.core.management import execute_from_command_line

    if sys.argv[1] == "test":
        local_settings_file = get_local_test_settings_file(sys.argv)
        os.environ["RELATE_LOCAL_TEST_SETTINGS"] = local_settings_file

    execute_from_command_line(sys.argv)
