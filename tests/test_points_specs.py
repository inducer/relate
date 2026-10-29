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


import json
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from course.grading import parse_points_specs, sum_points_specs


if TYPE_CHECKING:
    from collections.abc import Callable

    from course.grading import PointsSpec, PointsTotals


@pytest.fixture(scope="session", params=["python", "javascript"])
def points_implementation(request: pytest.FixtureRequest) -> str:
    return cast("str", request.param)


def run_points_javascript(text: str, operation: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.fail("Node.js is required for JavaScript points parser tests")

    runner = Path(__file__).parent / "js" / "parse_points_specs.mjs"

    completed = subprocess.run(
        [node, str(runner), operation],
        # JSON escapes preserve lone surrogates across the UTF-8 boundary.
        input=json.dumps(text, ensure_ascii=True),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    response = json.loads(completed.stdout)
    if "error" in response:
        raise ValueError(response["error"])
    return response["result"]


@pytest.fixture(scope="session")
def points_parser(points_implementation: str) -> Callable[[str], list[PointsSpec]]:
    if points_implementation == "python":
        return parse_points_specs

    def parse_javascript(text: str) -> list[PointsSpec]:
        return cast("list[PointsSpec]", run_points_javascript(text, "parse"))

    return parse_javascript


@pytest.fixture(scope="session")
def points_summer(points_implementation: str) -> Callable[[str], PointsTotals]:
    if points_implementation == "python":
        return lambda text: sum_points_specs(parse_points_specs(text))

    def sum_javascript(text: str) -> PointsTotals:
        return cast("PointsTotals", run_points_javascript(text, "sum"))

    return sum_javascript


@pytest.mark.parametrize("text", [
    "", "Plain feedback", "[pts: 2", "[PTS: 2]", "[points: 2]",
])
def test_parse_points_specs_no_matches(
        points_parser: Callable[[str], list[PointsSpec]], text: str):
    assert points_parser(text) == []


@pytest.mark.parametrize(("body", "points", "max_points", "identifier"), [
    ("", None, None, None),
    ("2", 2, None, None),
    ("-2.5", -2.5, None, None),
    (".5 / 4", 0.5, 4, None),
    ("/ 4", None, 4, None),
    ("#part_1", None, None, "#part_1"),
    ("2 / 4 #Part_1", 2, 4, "#Part_1"),
    ("/ .5 #_part", None, 0.5, "#_part"),
    (" \t-0.5\n/\t2.5\t#part \n", -0.5, 2.5, "#part"),
    ("1.2.3 / 4.5.6", 1.2, 4.5, None),
    ("1-2 / 3-4", 1, 3, None),
])
def test_parse_points_specs_fields(
        points_parser: Callable[[str], list[PointsSpec]],
        body: str, points: float | None, max_points: float | None,
        identifier: str | None):
    text = f"[pts:{body}]"
    assert points_parser(text) == [{
        "points": points,
        "maxPoints": max_points,
        "identifier": identifier,
        "matchStart": 0,
        "matchLength": len(text),
    }]


def test_parse_points_specs_multiple_utf16_offsets(
        points_parser: Callable[[str], list[PointsSpec]]):
    assert points_parser("😀 [pts: 2/3 #a] é🚀[pts: /4]") == [
        {
            "points": 2,
            "maxPoints": 3,
            "identifier": "#a",
            "matchStart": 3,
            "matchLength": 13,
        },
        {
            "points": None,
            "maxPoints": 4,
            "identifier": None,
            "matchStart": 20,
            "matchLength": 9,
        },
    ]


def test_parse_points_specs_lone_surrogate_offset(
        points_parser: Callable[[str], list[PointsSpec]]):
    assert points_parser("\ud800[pts: 1]") == [{
        "points": 1,
        "maxPoints": None,
        "identifier": None,
        "matchStart": 1,
        "matchLength": 8,
    }]


@pytest.mark.parametrize(("body", "error"), [
    ("abc", "Points spec not understood: 'abc'"),
    ("+1", "Points spec not understood: '+1'"),
    ("1e2", "Points spec not understood: '1e2'"),
    ("1 #1part", "Points spec not understood: '1 #1part'"),
    ("1 / 2 / 3", "Points spec not understood: '1 / 2 / 3'"),
    (".", "Numeral not understood: ."),
    ("-", "Numeral not understood: -"),
    ("1/", "Numeral not understood: "),
    ("1/.", "Numeral not understood: ."),
    ("1/0", "Point denominator must be positive: '1/0'"),
    ("1/-2", "Point denominator must be positive: '1/-2'"),
    ("1/-0.0", "Point denominator must be positive: '1/-0.0'"),
])
def test_parse_points_specs_errors(
        points_parser: Callable[[str], list[PointsSpec]], body: str, error: str):
    with pytest.raises(ValueError) as exc_info:
        points_parser(f"[pts: {body}]")
    assert str(exc_info.value) == error


@pytest.mark.parametrize(("text", "points", "max_points"), [
    ("", None, None),
    ("Plain feedback", None, None),
    ("[pts: 0]", 0, None),
    ("[pts: -2.5]", -2.5, None),
    ("[pts: 2] then [pts: 3]", 5, None),
    ("[pts: 2] [pts: -2]", 0, None),
    ("[pts: 0/4]", 0, 4),
    ("[pts: 2/4 #a] [pts: 3/6 #b]", 5, 10),
    ("[pts: 2/4 #a] [pts: -0.5]", 1.5, 4),
    ("[pts: -0.5] [pts: 2/4 #a]", 1.5, 4),
    ("[pts: 0.5/0.5] [pts: 1.5/2.5]", 2, 3),
    ("[pts: 2/4 #a] [pts: 2/4 #a]", 4, 8),
    ("😀 [pts: 2/4] 🚀[pts: -2/3]", 0, 7),
])
def test_sum_points_specs(
        points_summer: Callable[[str], PointsTotals],
        text: str, points: float | None, max_points: float | None):
    assert points_summer(text) == {"points": points, "maxPoints": max_points}


@pytest.mark.parametrize("text", [
    "[pts:]",
    "[pts: /4]",
    "[pts: #part]",
    "[pts: /4 #part]",
    "[pts: 2/3] [pts: /4]",
    "[pts: /4] [pts: 2/3]",
])
def test_sum_points_specs_missing_points(
        points_summer: Callable[[str], PointsTotals], text: str):
    with pytest.raises(ValueError) as exc_info:
        points_summer(text)
    assert str(exc_info.value) == (
        "Not applying points total when a pts spec is missing a point value.")


@pytest.mark.parametrize(("text", "error"), [
    ("[pts: 2] [pts: bad]", "Points spec not understood: 'bad'"),
    ("[pts: 1/0]", "Point denominator must be positive: '1/0'"),
    ("[pts:] [pts: bad]", "Points spec not understood: 'bad'"),
])
def test_sum_points_specs_parse_errors(
        points_summer: Callable[[str], PointsTotals], text: str, error: str):
    with pytest.raises(ValueError) as exc_info:
        points_summer(text)
    assert str(exc_info.value) == error


def test_parse_points_specs_invalid_after_valid(
        points_parser: Callable[[str], list[PointsSpec]]):
    with pytest.raises(ValueError) as exc_info:
        points_parser("[pts: 1] then [pts: bad]")
    assert str(exc_info.value) == "Points spec not understood: 'bad'"
