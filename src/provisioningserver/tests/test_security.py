# Copyright 2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for MAAS's cluster security module."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = []

from os import (
    chmod,
    stat,
    )
from os.path import dirname

from fixtures import EnvironmentVariableFixture
import lockfile
from maastesting.factory import factory
from maastesting.matchers import MockCalledOnceWith
from maastesting.testcase import MAASTestCase
from mock import ANY
from provisioningserver import security
from provisioningserver.utils.fs import (
    ensure_dir,
    read_text_file,
    write_text_file,
    )


class TestGetSharedSecretFromFilesystem(MAASTestCase):

    def setUp(self):
        super(TestGetSharedSecretFromFilesystem, self).setUp()
        self.useFixture(EnvironmentVariableFixture(
            "MAAS_ROOT", self.make_dir()))

    def write_secret(self):
        secret = factory.make_bytes()
        secret_path = security.get_shared_secret_filesystem_path()
        ensure_dir(dirname(secret_path))
        write_text_file(secret_path, security.to_hex(secret))
        return secret

    def test__returns_None_when_no_secret_exists(self):
        self.assertIsNone(security.get_shared_secret_from_filesystem())

    def test__returns_secret_when_one_exists(self):
        secret = self.write_secret()
        self.assertEqual(
            secret, security.get_shared_secret_from_filesystem())

    def test__same_secret_is_returned_on_subsequent_calls(self):
        self.write_secret()
        self.assertEqual(
            security.get_shared_secret_from_filesystem(),
            security.get_shared_secret_from_filesystem())

    def test__errors_reading_file_are_raised(self):
        self.write_secret()
        secret_path = security.get_shared_secret_filesystem_path()
        self.addCleanup(chmod, secret_path, 0o600)
        chmod(secret_path, 0o000)
        self.assertRaises(IOError, security.get_shared_secret_from_filesystem)

    def test__errors_when_filesystem_value_cannot_be_decoded(self):
        self.write_secret()
        write_text_file(security.get_shared_secret_filesystem_path(), "_")
        self.assertRaises(
            TypeError, security.get_shared_secret_from_filesystem)

    def test__deals_fine_with_whitespace_in_filesystem_value(self):
        secret = self.write_secret()
        write_text_file(
            security.get_shared_secret_filesystem_path(),
            " %s\n" % security.to_hex(secret))
        self.assertEqual(secret, security.get_shared_secret_from_filesystem())

    def test__reads_with_lock(self):
        lock = lockfile.FileLock(security.get_shared_secret_filesystem_path())
        self.assertFalse(lock.is_locked())

        def check_lock(path):
            self.assertTrue(lock.is_locked())
            return "12"  # Two arbitrary hex characters.

        read_text_file = self.patch_autospec(security, "read_text_file")
        read_text_file.side_effect = check_lock
        security.get_shared_secret_from_filesystem()
        self.assertThat(read_text_file, MockCalledOnceWith(ANY))
        self.assertFalse(lock.is_locked())


class TestSetSharedSecretOnFilesystem(MAASTestCase):

    def setUp(self):
        super(TestSetSharedSecretOnFilesystem, self).setUp()
        self.useFixture(EnvironmentVariableFixture(
            "MAAS_ROOT", self.make_dir()))

    def read_secret(self):
        secret_path = security.get_shared_secret_filesystem_path()
        secret_hex = read_text_file(secret_path)
        return security.to_bin(secret_hex)

    def test__writes_secret(self):
        secret = factory.make_bytes()
        security.set_shared_secret_on_filesystem(secret)
        self.assertEqual(secret, self.read_secret())

    def test__writes_with_lock(self):
        lock = lockfile.FileLock(security.get_shared_secret_filesystem_path())
        self.assertFalse(lock.is_locked())

        def check_lock(path, data):
            self.assertTrue(lock.is_locked())

        write_text_file = self.patch_autospec(security, "write_text_file")
        write_text_file.side_effect = check_lock
        security.set_shared_secret_on_filesystem(b"foo")
        self.assertThat(write_text_file, MockCalledOnceWith(ANY, ANY))
        self.assertFalse(lock.is_locked())

    def test__writes_with_secure_permissions(self):
        secret = factory.make_bytes()
        security.set_shared_secret_on_filesystem(secret)
        secret_path = security.get_shared_secret_filesystem_path()
        perms_observed = stat(secret_path).st_mode & 0o777
        perms_expected = 0o640
        self.assertEqual(
            perms_expected, perms_observed,
            "Expected %04o, got %04o." % (perms_expected, perms_observed))
