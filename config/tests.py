import importlib
import os
import sys
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

REQUIRED = {
    "DJANGO_SECRET_KEY": "a-long-random-secret-for-tests",
    "DJANGO_ALLOWED_HOSTS": "example.com",
    "POSTGRES_DB": "oep",
    "POSTGRES_USER": "oep",
    "POSTGRES_PASSWORD": "s3cret",
    "POSTGRES_HOST": "db",
}


def load_prod(env):
    sys.modules.pop("config.settings.prod", None)
    with mock.patch.dict(os.environ, env, clear=True):
        return importlib.import_module("config.settings.prod")


class ProductionSettingsTest(SimpleTestCase):
    def test_loads_when_all_variables_are_set(self):
        prod = load_prod(REQUIRED)
        self.assertEqual(prod.SECRET_KEY, REQUIRED["DJANGO_SECRET_KEY"])
        self.assertEqual(prod.DATABASES["default"]["PASSWORD"], "s3cret")

    def test_each_missing_variable_fails_clearly(self):
        for name in REQUIRED:
            env = {k: v for k, v in REQUIRED.items() if k != name}
            with self.subTest(missing=name):
                with self.assertRaisesMessage(ImproperlyConfigured, name):
                    load_prod(env)

    def test_blank_database_password_is_rejected(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "POSTGRES_PASSWORD"):
            load_prod({**REQUIRED, "POSTGRES_PASSWORD": "   "})

    def test_allowed_hosts_with_only_commas_and_spaces_is_rejected(self):
        for value in [", , ", ",", ",,,", " , ,\t,"]:
            with self.subTest(value=value):
                with self.assertRaisesMessage(ImproperlyConfigured, "DJANGO_ALLOWED_HOSTS"):
                    load_prod({**REQUIRED, "DJANGO_ALLOWED_HOSTS": value})

    def test_allowed_hosts_ignores_empty_entries_and_spaces(self):
        prod = load_prod({**REQUIRED, "DJANGO_ALLOWED_HOSTS": " a.com, ,b.com ,"})
        self.assertEqual(prod.ALLOWED_HOSTS, ["a.com", "b.com"])

    def tearDown(self):
        sys.modules.pop("config.settings.prod", None)
