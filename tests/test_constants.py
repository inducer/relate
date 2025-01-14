from __future__ import annotations


__copyright__ = "Copyright (C) 2018 Dong Zhuang"

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

import unittest

from course import constants


class IsExpirationModeAllowedTest(unittest.TestCase):
    # test course.constants.is_expiration_mode_allowed
    def test_roll_over(self):
        expmode = constants.flow_session_expiration_mode.roll_over
        permissions = frozenset([])
        self.assertFalse(
            constants.is_expiration_mode_allowed(expmode, permissions))

        permissions = frozenset([
            constants.flow_permission.set_roll_over_expiration_mode
        ])
        self.assertTrue(
            constants.is_expiration_mode_allowed(expmode, permissions))

    def test_end(self):
        expmode = constants.flow_session_expiration_mode.end
        permissions = frozenset([constants.flow_permission.end_session])
        self.assertTrue(
            constants.is_expiration_mode_allowed(expmode, permissions))

        permissions = frozenset([
            constants.flow_permission.set_roll_over_expiration_mode
        ])
        self.assertTrue(
            constants.is_expiration_mode_allowed(expmode, permissions))

    def test_unknown_mode(self):
        expmode = "unknown_mode"
        permissions = frozenset([])

        expected_error_msg = "unknown expiration mode"

        with self.assertRaises(ValueError) as cm:
            self.assertTrue(
                constants.is_expiration_mode_allowed(expmode, permissions))

        self.assertEqual(expected_error_msg, str(cm.exception))

        permissions = frozenset([
            constants.flow_permission.set_roll_over_expiration_mode,
            constants.flow_permission.end_session
        ])

        with self.assertRaises(ValueError) as cm:
            self.assertTrue(
                constants.is_expiration_mode_allowed(expmode, permissions))

        self.assertEqual(expected_error_msg, str(cm.exception))
