import os
import sys

import pytest


@pytest.mark.parametrize("yaml_file", ["pass.yml", "fail.yml"])
def test_yaml_lint(yaml_file):
    from subprocess import Popen
    thisdir = os.path.dirname(os.path.realpath(__file__))
    stream = Popen([sys.executable, "-m", "relate", "lint-yaml",
                    "--config-file",
                    os.path.join(thisdir, ".yamllint.yml"),
                    os.path.join(thisdir, yaml_file)])
    stream.wait()

    if stream.returncode and "pass" in yaml_file:
        raise Exception("File that was supposed to pass did not pass")
    elif stream.returncode == 0 and "fail" in yaml_file:
        raise Exception("File that was supposed to fail did not fail")
