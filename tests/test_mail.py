from __future__ import annotations

from django.core import mail
from django.test import SimpleTestCase, override_settings

from relate.utils import get_outbound_mail_connection


LOCMEM_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


@override_settings(MAILERS={
    "default": {"BACKEND": LOCMEM_BACKEND},
    "robot": {"BACKEND": LOCMEM_BACKEND},
    "grader_feedback": {"BACKEND": "tests.resource.MyFakeEmailBackend"},
})
class MailerRoutingTest(SimpleTestCase):
    def test_purpose_specific_mailer(self):
        from tests.resource import MyFakeEmailBackend

        connection = get_outbound_mail_connection("grader_feedback")
        self.assertIsInstance(connection, MyFakeEmailBackend)
        connection.send_messages([mail.EmailMessage(to=["student@example.com"])])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].sent_using, "grader_feedback")

    def test_missing_purpose_uses_default(self):
        connection = get_outbound_mail_connection("enroll")
        connection.send_messages([mail.EmailMessage(to=["student@example.com"])])
        self.assertEqual(mail.outbox[0].sent_using, "default")

    def test_no_purpose_uses_default(self):
        self.assertEqual(get_outbound_mail_connection().alias, "default")

    @override_settings(MAILERS={
        "grader_feedback": {"BACKEND": "does.not.exist.EmailBackend"},
        "default": {"BACKEND": LOCMEM_BACKEND},
    })
    def test_invalid_purpose_mailer_does_not_silently_fall_back(self):
        with self.assertRaisesMessage(mail.InvalidMailer, "Could not find BACKEND"):
            get_outbound_mail_connection("grader_feedback")

    @override_settings(MAILERS={"robot": {"BACKEND": LOCMEM_BACKEND}})
    def test_missing_default_mailer_does_not_select_another_alias(self):
        with self.assertRaises(mail.MailerDoesNotExist):
            get_outbound_mail_connection("enroll")
