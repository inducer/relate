import os

import pytest


@pytest.mark.parametrize("yaml_file",
                         ["pass.yml",
                          pytest.param("fail.yml", marks=pytest.mark.xfail)])
def test_yaml_lint(yaml_file):
    cmd = 'relate lint_yaml --config_file=.yamllint.yml ' + yaml_file
    stream = os.popen(cmd)
    output = stream.read()

    if len(output) > 0 and yaml_file == 'pass.yml':
        raise Exception('File that was supposed to pass did not pass')
    elif len(output) == 0 and yaml_file == 'fail.yml':
        raise Exception('File that was supposed to fail did not fail')
