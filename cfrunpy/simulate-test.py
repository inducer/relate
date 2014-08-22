#! /usr/bin/env python3

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

import io
import sys
from cfrunpy_backend import dict_to_struct, run_code, package_exception


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('yaml', help='The YAML problem definition')
    parser.add_argument('user_code', help='The user code to be tested')

    args = parser.parse_args()

    import yaml

    with open(args.yaml, "r") as inf:
        run_req = dict_to_struct(yaml.load(inf))

    with open(args.user_code, "r") as inf:
        run_req.user_code = inf.read()

    prev_stdout = sys.stdout
    prev_stderr = sys.stderr

    result = {}
    try:
        stdout = io.StringIO()
        stderr = io.StringIO()

        sys.stdin = None
        sys.stdout = stdout
        sys.stderr = stderr

        run_code(result, run_req)

        result["stdout"] = stdout.getvalue()
        result["stderr"] = stderr.getvalue()
    except:
        result = {}
        package_exception(result, "uncaught_error")

    sys.stdout = prev_stdout
    sys.stderr = prev_stderr

    print("RESULT: ", result.pop("result"))

    for key, val in sorted(result.items()):
        if val:
            print("-------------------------------------")
            print(key)
            print("-------------------------------------")
            print(val)


if __name__ == "__main__":
    main()
