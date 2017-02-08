# -*- coding: utf-8 -*-

from __future__ import division, print_function

__copyright__ = "Copyright (C) 2014 Andreas Kloeckner"

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


class GradingComplete(Exception):
    pass


class Feedback:
    def __init__(self):
        self.points = None
        self.feedback_items = []

    def set_points(self, points):
        self.points = points

    def add_feedback(self, text):
        self.feedback_items.append(text)

    def finish(self, points, fb_text):
        self.add_feedback(fb_text)
        self.set_points(points)
        raise GradingComplete()

    def check_numpy_array_sanity(self, name, num_axes, data):
        import numpy as np
        if not isinstance(data, np.ndarray):
            self.finish(0, "'%s' is not a numpy array" % name)

        if isinstance(data, np.matrix):
            self.finish(0, "'%s' is a numpy matrix. Do not use those. "
                    "bit.ly/array-vs-matrix" % name)

        if len(data.shape) != num_axes:
            self.finish(
                    0, "'%s' does not have the correct number of axes--"
                    "got: %d, expected: %d" % (
                        name, len(data.shape), num_axes))

        if data.dtype.kind not in "fc":
            self.finish(
                    0, "'%s' does not consist of floating point numbers--"
                    "got: '%s'" % (name, data.dtype))

    def check_numpy_array_features(self, name, ref, data, report_failure=True):
        import numpy as np
        assert isinstance(ref, np.ndarray)

        def bad(msg):
            if report_failure:
                self.finish(0, msg)
            else:
                return False

        if not isinstance(data, np.ndarray):
            return bad("'%s' is not a numpy array" % name)

        if isinstance(data, np.matrix):
            return bad("'%s' is a numpy matrix. Do not use those. "
                    "bit.ly/array-vs-matrix" % name)

        if ref.shape != data.shape:
            return bad(
                    "'%s' does not have correct shape--"
                    "got: '%s', expected: '%s'" % (
                        name, data.shape, ref.shape))

        if ref.dtype.kind != data.dtype.kind:
            return bad(
                    "'%s' does not have correct data type--"
                    "got: '%s', expected: '%s'" % (
                        name, data.dtype.kind, ref.dtype.kind))

        return True

    def check_numpy_array_allclose(self, name, ref, data, accuracy_critical=True,
            rtol=1e-05, atol=1e-08, report_success=True, report_failure=True):
        import numpy as np

        if not self.check_numpy_array_features(name, ref, data, report_failure):
            return False

        good = np.allclose(ref, data, rtol=rtol, atol=atol)

        if not good:
            if report_failure:
                self.add_feedback("'%s' is inaccurate" % name)
        else:
            if report_success:
                self.add_feedback("'%s' looks good" % name)

        if accuracy_critical and not good:
            self.set_points(0)
            raise GradingComplete()

        return good

    def check_list(self, name, ref, data, entry_type=None):
        assert isinstance(ref, list)
        if not isinstance(data, list):
            self.finish(0, "'%s' is not a list" % name)

        if len(ref) != len(data):
            self.finish(0, "'%s' has the wrong length--expected %d, got %d"
              % (name, len(ref), len(data)))

        if entry_type is not None:
            for i, entry in enumerate(data):
                if not isinstance(entry, entry_type):
                    self.finish(0, "'%s[%d]' has the wrong type" % (name, i))

    def check_scalar(self, name, ref, data, accuracy_critical=True,
            rtol=1e-5, atol=1e-8, report_success=True, report_failure=True):
        import numpy as np

        if not isinstance(data, (float, int, np.number)):
            try:
                if not data.is_number:
                    raise AttributeError
            except AttributeError:
                self.finish(0, "'%s' is not a number" % name)

        good = False

        if rtol is not None and abs(ref-data) < abs(ref)*rtol:
            good = True
        if atol is not None and abs(ref-data) < atol:
            good = True

        if not good:
            if report_failure:
                self.add_feedback("'%s' is inaccurate" % name)
        else:
            if report_success:
                self.add_feedback("'%s' looks good" % name)

        if accuracy_critical and not good:
            self.set_points(0)
            raise GradingComplete()

        return good

    def call_user(self, f, *args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            from traceback import format_exc
            self.add_feedback(
                    "<p>"
                    "The callable '%s' supplied in your code failed with "
                    "an exception while it was being called by the grading "
                    "code:"
                    "</p>"
                    "<pre>%s</pre>"
                    % (
                        f.__name__,
                        "".join(format_exc())))

            self.set_points(0)
            raise GradingComplete()
