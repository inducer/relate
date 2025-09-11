from __future__ import annotations


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
import threading
import traceback
from types import TracebackType
from typing import TYPE_CHECKING, ClassVar, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field


if TYPE_CHECKING:
    from .code_feedback import Feedback, GradingComplete
else:
    try:
        from .code_feedback import Feedback, GradingComplete
    except SystemError:
        from code_feedback import Feedback, GradingComplete
    except ImportError:
        from code_feedback import Feedback, GradingComplete


ExcInfo: TypeAlias = tuple[type[BaseException], BaseException, TracebackType]

ResultType: TypeAlias = Literal[
                "success",
                "uncaught_error",
                "setup_compile_error",
                "setup_error",
                "test_compile_error",
                "test_error",
                "timeout",
                "user_compile_error",
                "user_error",
                "unknown_error",
        ]


# {{{ protocol

class RunRequest(BaseModel):
    compile_only: bool = False
    setup_code: str | None = None
    user_code: str
    test_code: str | None = None
    data_files: dict[str, str] = Field(default_factory=dict)
    names_from_user: list[str] = Field(default_factory=list)
    names_for_user: list[str] = Field(default_factory=list)


class RunResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    result: ResultType

    points: float | None = None

    feedback: list[str] = Field(default_factory=list)
    stdout: str | None = None
    stderr: str | None = None
    figures: list[tuple[int, str, str]] = Field(default_factory=list)
    html: list[str] = Field(default_factory=list)
    exec_host: str | None = None

    traceback: str | None = None
    message: str | None = None

# }}}


def substitute_correct_code_into_test_code(
            test_code: str,
            correct_code: str | None
        ) -> str:
    if correct_code is None:
        return test_code

    import re
    CORRECT_CODE_TAG = re.compile(r"^(\s*)###CORRECT_CODE###\s*$")  # noqa

    new_test_code_lines: list[str] = []
    for line in test_code.split("\n"):
        match = CORRECT_CODE_TAG.match(line)
        if match is not None:
            prefix = match.group(1)
            for cc_l in correct_code.split("\n"):
                new_test_code_lines.append(prefix+cc_l)
        else:
            new_test_code_lines.append(line)

    return "\n".join(new_test_code_lines)


def package_exception(
            what: ResultType,
            exc_info: ExcInfo | None = None
        ) -> RunResponse:
    if exc_info is None:
        tp, val, tb = sys.exc_info()
    else:
        tp, val, tb = exc_info

    assert tp is not None
    return RunResponse(
        result=what,
        message=f"{tp.__name__}: {val!s}",
        traceback="".join(
            traceback.format_exception(tp, val, tb))
    )


def user_code_thread(
            user_code: str,
            user_ctx: dict[str, object],
            exc_info: list[ExcInfo]) -> None:
    try:
        exec(user_code, user_ctx)
    except BaseException:
        tp, val, tb = sys.exc_info()
        assert tp is not None
        assert val is not None
        assert tb is not None
        exc_info.append((tp, val, tb))


def run_code(run_req: RunRequest) -> RunResponse:
    # {{{ silence matplotlib warnings

    import warnings
    warnings.filterwarnings(
            "ignore", message="Matplotlib is building the font cache.*")
    import os
    os.environ["MPLCONFIGDIR"] = "/tmp"

    # }}}

    # {{{ compile code

    if run_req.setup_code:
        try:
            setup_code = compile(
                    run_req.setup_code, "[setup code]", "exec")
        except Exception:
            return package_exception("setup_compile_error")
    else:
        setup_code = None

    try:
        user_code = compile(run_req.user_code, "[user code]", "exec")
    except Exception:
        return package_exception("user_compile_error")

    if run_req.test_code is not None:
        try:
            test_code = compile(run_req.test_code, "[test code]", "exec")
        except Exception:
            return package_exception("test_compile_error")
    else:
        test_code = None

    # Test code often contains the sample solution. Protect it from
    # access in user code via stack traversal.
    run_req.test_code = "# (removed)"

    # }}}

    if run_req.compile_only:
        return RunResponse(result="success")

    # {{{ run code

    data_files = {}
    if run_req.data_files:
        from base64 import b64decode
        for name, contents in run_req.data_files.items():
            data_files[name] = b64decode(contents.encode())

    generated_html: list[str] = []

    def output_html(s: str):
        generated_html.append(s)

    maint_ctx: dict[str, object] = {
            "user_code": run_req.user_code,
            "data_files": data_files,
            "output_html": output_html,
            "GradingComplete": GradingComplete,
            }

    if setup_code is not None:
        try:
            exec(setup_code, maint_ctx)
        except BaseException:
            return package_exception("setup_error")

    user_ctx: dict[str, object] = {}
    for name in run_req.names_for_user:
        if name not in maint_ctx:
            return RunResponse(
                result="setup_error",
                message=f"Setup code did not define '{name}'.",
                )

        user_ctx[name] = maint_ctx[name]

    from copy import deepcopy
    user_ctx = deepcopy(user_ctx)

    user_ctx["_MODULE_SOURCE_CODE"] = run_req.user_code

    # Running user code in a thread makes it harder for it to get at the (sensitive)
    # data held in this stack frame. Hiding sys._current_frames adds more difficulty.
    old_scf = sys._current_frames  # pyright: ignore[reportPrivateUsage]
    sys._current_frames = lambda: {}  # pyright: ignore[reportPrivateUsage]

    exc_info: list[ExcInfo] = []
    user_thread = threading.Thread(
            target=user_code_thread, args=(user_code, user_ctx, exc_info))
    user_thread.start()
    user_thread.join()

    sys._current_frames = old_scf  # pyright: ignore[reportPrivateUsage]

    if exc_info:
        return package_exception("user_error", exc_info[0])

    # It's harder for user code to get at the feedback object if it doesn't
    # yet exist while user code runs.
    feedback = maint_ctx["feedback"] = Feedback()

    # {{{ export plots

    figures: list[tuple[int, str, str]] = []
    if "matplotlib" in sys.modules:
        from base64 import b64encode
        from io import BytesIO

        import matplotlib.pyplot as pt

        format = "png"
        mime = "image/png"

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

    # }}}

    for name in run_req.names_from_user:
        if name not in user_ctx:
            feedback.add_feedback(
                    f"Required answer variable '{name}' is not defined.")
            maint_ctx[name] = None
        else:
            maint_ctx[name] = user_ctx[name]

    if test_code is not None:
        try:
            exec(test_code, maint_ctx)
        except GradingComplete:
            pass
        except BaseException:
            return package_exception("test_error")

    return RunResponse(
        result="success",
        points=feedback.points,
        feedback=feedback.feedback_items,
        figures=figures,
        html=generated_html,
    )


# vim: foldmethod=marker
