from django.test import SimpleTestCase
from django.apps import apps


class AdministrationAppSmokeTest(SimpleTestCase):
    def test_app_is_installed(self):
        self.assertTrue(apps.is_installed("apps.administration"))
