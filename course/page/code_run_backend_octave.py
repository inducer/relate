# -*- coding: utf-8 -*-

from __future__ import absolute_import

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

try:
    from .code_feedback import Feedback, GradingComplete
except SystemError:
    from code_feedback import Feedback, GradingComplete  # type: ignore
except ImportError:
    from code_feedback import Feedback, GradingComplete  # type: ignore


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

    .. attribute:: html

        A list of HTML strings generated. These are aggressively sanitized
        before being rendered.

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


def substitute_correct_code_into_test_code(test_code, correct_code):
    import re
    CORRECT_CODE_TAG = re.compile(r"^(\s*)###CORRECT_CODE###\s*$")  # noqa

    new_test_code_lines = []
    for line in test_code.split("\n"):
        match = CORRECT_CODE_TAG.match(line)
        if match is not None:
            prefix = match.group(1)
            for cc_l in correct_code.split("\n"):
                new_test_code_lines.append(prefix+cc_l)
        else:
            new_test_code_lines.append(line)

    return "\n".join(new_test_code_lines)


def package_exception(result, what):
    tp, val, tb = sys.exc_info()
    result["result"] = what
    result["message"] = "%s: %s" % (tp.__name__, str(val))
    result["traceback"] = "".join(
            traceback.format_exception(tp, val, tb))


def run_code(result, run_req):
    # {{{ set up octave process

    import oct2py

    oc = oct2py.Oct2Py()

    # }}}

    # {{{ run code

    data_files = {}
    if hasattr(run_req, "data_files"):
        from base64 import b64decode
        for name, contents in run_req.data_files.items():
            # This part "cheats" a litle, since Octave lets us evaluate functions
            # in the same context as the main code.  (MATLAB segregates these.)
            data_files[name] = b64decode(contents.encode())
            oc.eval(b64decode(contents.encode()).decode("utf-8"))

    generated_html = []
    result["html"] = generated_html

    def output_html(s):
        generated_html.append(s)

    feedback = Feedback()
    maint_ctx = {
            "feedback": feedback,
            "user_code": run_req.user_code,
            "data_files": data_files,
            "output_html": output_html,
            "GradingComplete": GradingComplete,
            }

    if getattr(run_req, "setup_code", None):
        try:
            oc.eval(run_req.setup_code)
            # put variables from user in main context
            for name in run_req.names_for_user:
                try:
                    maint_ctx[name] = oc.pull(name)
                except oct2py.Oct2PyError:
                    maint_ctx[name] = None
        except Exception:
            package_exception(result, "setup_error")
            return

    if getattr(run_req, "test_code", None):
        try:
            test_code = compile(
                    run_req.test_code, "[test code]", "exec")
        except Exception:
            package_exception(result, "test_compile_error")
            return
    else:
        test_code = None

    if hasattr(run_req, "compile_only") and run_req.compile_only:
        result["result"] = "success"
        return

    """
    user_ctx = {}
    if hasattr(run_req, "names_for_user"):  #XXX unused for Octave context currently
        for name in run_req.names_for_user:
            if name not in maint_ctx:
                result["result"] = "setup_error"
                result["message"] = "Setup code did not define \'%s\'." % name

            user_ctx[name] = maint_ctx[name]

    from copy import deepcopy
    user_ctx = deepcopy(user_ctx)
    """

    try:
        #user_ctx["_MODULE_SOURCE_CODE"] = run_req.user_code
        oc.eval(run_req.user_code)
    except Exception:
        package_exception(result, "user_error")
        return

    # {{{ export plots

    """
    if 'matplotlib' in sys.modules:
        import matplotlib.pyplot as pt
        from io import BytesIO
        from base64 import b64encode

        format = 'png'
        mime = 'image/png'
        figures = []

        for fignum in pt.get_fignums():
            pt.figure(fignum)
            bio = BytesIO()
            try:
                pt.savefig(bio, format=format)
            except Exception:
                pass
            else:
                figures.append(
                    (fignum, mime, b64encode(bio.getvalue()).decode()))

        result['figures'] = figures
    """
    # }}}

    if hasattr(run_req, "names_from_user"):
        for name in run_req.names_from_user:
            try:
                maint_ctx[name] = oc.pull(name)
            except oct2py.Oct2PyError:
                feedback.add_feedback(
                        "Required answer variable '%s' is not defined."
                        % name)
                maint_ctx[name] = None

    if test_code is not None:  # XXX test code is written in Python
        try:
            maint_ctx["_MODULE_SOURCE_CODE"] = run_req.test_code
            exec(test_code, maint_ctx)
        except GradingComplete:
            pass
        except Exception:
            package_exception(result, "test_error")
            return

    result["points"] = feedback.points
    result["feedback"] = feedback.feedback_items

    # }}}

    result["result"] = "success"

# vim: foldmethod=marker
