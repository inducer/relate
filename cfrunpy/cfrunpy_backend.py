# -*- coding: utf-8 -*-

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

import sys
import traceback


__doc__ = """
PROTOCOL
========

.. class:: Request

    .. attribute:: setup_code

    .. attribute:: names_for_user

    .. attribute:: user_code

    .. attribute:: names_from_user

    .. attribute:: test_code

    .. attribute:: data_files

        A dictionary from data file names to their
        base64-cencoded contents.
        Optional.

    .. attribute:: compile_only

        :class:`bool`

.. class Response::
    .. attribute:: result

        One of

        * ``success``
        * ``timeout``
        * ``uncaught_error``
        * ``setup_compile_error``
        * ``setup_error``,
        * ``user_compile_error``
        * ``user_error``
        * ``test_compile_error``
        * ``test_error``

        Always present.

    .. attribute:: message

        Optional.

    .. attribute:: traceback

        Optional.

    .. attribute:: stdout

        Whatever came out of stdout.

        Optional.

    .. attribute:: stderr

        Whatever came out of stderr.

        Optional.

    .. attribute:: figures

        A list of ``(index, mime_type, string)``, where *string* is a
        base64-encoded representation of the figure. *index* will usually
        correspond to the matplotlib figure number.

        Optional.

    .. attribute:: points

        A number between 0 and 1 (inclusive).

        Present on ``success`` if :attr:`Request.compile_only` is *False*.

    .. attribute:: feedback

        A list of strings.

        Present on ``success`` if :attr:`Request.compile_only` is *False*.
"""


# {{{ tools

class Struct(object):
    def __init__(self, entries):
        for name, val in entries.items():
            self.__dict__[name] = val

    def __repr__(self):
        return repr(self.__dict__)

# }}}


def package_exception(result, what):
    tp, val, tb = sys.exc_info()
    result["result"] = what
    result["message"] = "%s: %s" % (tp.__name__, str(val))
    result["traceback"] = "".join(
            traceback.format_exception(tp, val, tb))


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

    def check_numpy_array_features(self, name, ref, data):
        import numpy as np
        assert isinstance(ref, np.ndarray)

        if not isinstance(data, np.ndarray):
            self.finish(0, "'%s' is not a numpy array" % name)

        if ref.shape != data.shape:
            self.finish(
                    0, "'%s' does not have correct shape--"
                    "got: '%s', expected: '%s'" % (
                        name, data.shape, ref.shape))

        if ref.dtype.kind != data.dtype.kind:
            self.finish(
                    0, "'%s' does not have correct data type--"
                    "got: '%s', expected: '%s'" % (
                        name, data.dtype.kind, ref.dtype.kind))

    def check_numpy_array_allclose(self, name, ref, data, accuracy_critical=True,
            rtol=1e-05, atol=1e-08):
        import numpy as np

        self.check_numpy_array_features(name, ref, data)
        good = np.allclose(ref, data, rtol=rtol, atol=atol)

        if not good:
            self.add_feedback("'%s' is inaccurate" % name)

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


def run_code(result, run_req):
    # {{{ compile code

    if getattr(run_req, "setup_code", None):
        try:
            setup_code = compile(
                    run_req.setup_code, "<setup code>", 'exec')
        except:
            package_exception(result, "setup_compile_error")
            return
    else:
        setup_code = None

    try:
        user_code = compile(
                run_req.user_code, "<user code>", 'exec')
    except:
        package_exception(result, "user_compile_error")
        return

    if getattr(run_req, "test_code", None):
        try:
            test_code = compile(
                    run_req.test_code, "<test code>", 'exec')
        except:
            package_exception(result, "test_compile_error")
            return
    else:
        test_code = None

    # }}}

    if hasattr(run_req, "compile_only") and run_req.compile_only:
        result["result"] = "success"
        return

    # {{{ run code

    data_files = {}
    if hasattr(run_req, "data_files"):
        from base64 import b64decode
        for name, contents in run_req.data_files.items():
            data_files[name] = b64decode(contents.encode())

    feedback = Feedback()
    maint_ctx = {
            "feedback": feedback,
            "user_code": user_code,
            "data_files": data_files,
            "GradingComplete": GradingComplete,
            }

    if setup_code is not None:
        try:
            exec(setup_code, maint_ctx)
        except:
            package_exception(result, "setup_error")
            return

    user_ctx = {}
    from copy import deepcopy
    if hasattr(run_req, "names_for_user"):
        for name in run_req.names_for_user:
            if name not in maint_ctx:
                result["result"] = "setup_error"
                result["message"] = "Setup code did not define '%s'." % name

            user_ctx[name] = deepcopy(maint_ctx[name])

    try:
        exec(user_code, user_ctx)
    except:
        package_exception(result, "user_error")
        return

    # {{{ export plots

    if "matplotlib" in sys.modules:
        import matplotlib.pyplot as pt
        from io import BytesIO
        from base64 import b64encode

        format = "png"
        mime = "image/png"
        figures = []

        for fignum in pt.get_fignums():
            pt.figure(fignum)
            bio = BytesIO()
            try:
                pt.savefig(bio, format=format)
            except:
                pass
            else:
                figures.append(
                    (fignum, mime, b64encode(bio.getvalue()).decode()))

        result["figures"] = figures

    # }}}

    if hasattr(run_req, "names_from_user"):
        for name in run_req.names_from_user:
            if name not in user_ctx:
                feedback.add_feedback(
                        "Required answer variable '%s' is not defined."
                        % name)
                maint_ctx[name] = None
            else:
                maint_ctx[name] = user_ctx[name]

    if test_code is not None:
        try:
            exec(test_code, maint_ctx)
        except GradingComplete:
            pass
        except:
            package_exception(result, "test_error")
            return

    if not (feedback.points is None or 0 <= feedback.points <= 1):
        raise ValueError("grade point value is invalid: %s"
                % feedback.points)

    result["points"] = feedback.points
    result["feedback"] = feedback.feedback_items

    # }}}

    result["result"] = "success"

# vim: foldmethod=marker
