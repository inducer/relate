from django.core.management.commands.test import Command as DjangoTestCommand


class Command(DjangoTestCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--local_test_settings", action="store",
            dest="local_test_settings",
            help=("Overrides the default local test setting file path. "
                  "The default value is 'local_settings_example.py' in "
                  "project root. Note that local settings for production "
                  '("local_settings.py") is not allowed to be used '
                  "for unit tests for security reason.")
        )

    def handle(self, *test_labels, **options):
        del options["local_test_settings"]
        super().handle(*test_labels, **options)
