from __future__ import annotations


__copyright__ = "Copyright (C) 2026 University of Illinois Board of Trustees"

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


# These live in a separate module because they are used by grading
# functionality within a timeout. Placing them here allows them to
# be imported within the spawned interpreter without booting all
# of Django.

from typing import TYPE_CHECKING

from pymbolic.interop.sympy import PymbolicToSympyMapper
from pymbolic.mapper.dependency import DependencyMapper
from sympy import simplify, sympify


if TYPE_CHECKING:
    from pymbolic import Expression


def parse_expr(s: float | str):
    if isinstance(s, (complex, float, int)):
        return s

    # use pymbolic because it has a semi-secure parser
    from pymbolic import parse
    return parse(s)


def evaluates_to_constant(expr: Expression) -> bool:
    depmap = DependencyMapper[[]]()
    return not depmap(expr)


def parse_sympy(s: float | str):
    if isinstance(s, (complex, float, int)):
        return sympify(s)

    return PymbolicToSympyMapper()(parse_expr(s))


def sympy_check_equality(
        expr_str: str, ref_str: str,
    ) -> bool:
    # NOTE When working on untrusted data, only call this from
    # timeout-protected contexts.

    diff = parse_sympy(expr_str) - parse_sympy(ref_str)
    return simplify(diff) == 0


def float_or_sympy_evalf(s: str | float) -> float:
    # NOTE When working on untrusted data, only call this from
    # timeout-protected contexts.

    if isinstance(s, int | float):
        return s

    if not isinstance(s, str):
        raise TypeError("expected string, int or float for floating point "
                "literal")

    try:
        return float(s)
    except ValueError:
        pass

    if s == "":
        raise ValueError("floating point value expected, empty string found")

    # return a float type value, expression not allowed
    return float(parse_sympy(s).evalf())
