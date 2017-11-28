import os
import sys
from django.core.management.base import CommandError


# {{{ for mypy

if False:
    from typing import Any, Text, Optional, Any, List, Callable  # noqa

# }}}


def is_program_accessible(program):
    return False if which(program) is None else True


def which(program):
    # https://stackoverflow.com/a/377028/3437454
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if sys.platform.startswith('win'):
                # Add .exe extension for windows executables
                exe_file += '.exe'
            if is_exe(exe_file):
                return exe_file

    return None


def get_docker_program_version(program, print_output=False):
    # type: (Text, bool) -> Optional[Text]
    assert program in ["docker", "docker-machine"]
    args = [program, '--version']
    try:
        version_str = run_cmd_line(args, print_output=print_output)
    except (OSError, CommandError):
        return None

    # version_str examples:
    # for docker: "Docker version 1.11.2, build b9f10c9"
    # version_str for docker-machine: "docker-machine version 0.11.0, build 5b27455"
    assert version_str
    return version_str.split()[2].strip(',')


def run_cmd_line(args, output_process_func=None,
                 raise_error=True, print_output=True):
    # type: (Any, Optional[Callable], Optional[bool], Optional[bool]) -> Optional[Text]  # noqa
    from subprocess import Popen, PIPE, STDOUT
    process = Popen(args, stdout=PIPE, stderr=STDOUT)

    output_list = []  # type: List[Text]
    for line in iter(process.stdout.readline, b''):
        line_str = line.decode('utf-8')
        if line_str != os.linesep:
            if print_output:
                sys.stdout.write(line_str)
                sys.stdout.flush()

        output_list.append(line_str)

    process.stdout.close()
    process.wait()

    returncode = process.returncode
    error_msg = 'Exited with return code %s' % returncode
    if output_process_func:
        output_list = output_process_func(output_list)
    output_str = ''.join(output_list)

    if returncode and raise_error:
        raise CommandError(error_msg, output_str, returncode)

    return output_str
