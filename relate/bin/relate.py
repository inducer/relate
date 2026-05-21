from __future__ import annotations

import sys
from pathlib import Path

from pydantic import ValidationError
from typed_argparse import Parser, SubParser, SubParserGroup, TypedArgs, arg

from course.content import flow_desc_ta
from course.page.base import PageBase
from course.page.code import (
    PythonCodeQuestion,
    PythonCodeQuestionWithHumanTextFeedback as PythonCodeQuestionWHTF,
)
from course.page.code_run_backend import RunRequest
from course.repo import FileSystemFakeRepo
from course.validation import (
    ValidationContext,
)


CodeQuestion = PythonCodeQuestion | PythonCodeQuestionWHTF


class CommonArgs(TypedArgs):
    pass


class ValidateCourseArgs(CommonArgs):
    course_file: str = arg(default="course.yml")
    events_file: str = arg(default="events.yml")
    warn_error: bool = arg(
        help="Treat warnings as errors",
    )
    repo_root: str = arg(
        default=".",
        help="Root of the course repository",
        positional=True,
    )


class ValidatePageArgs(CommonArgs):
    warn_error: bool = arg(
        help="Treat warnings as errors",
    )
    repo_root: str = arg(
        default=".",
        help="Root of the course repository",
        positional=True,
    )
    problem_ymls: list[str] = arg(
        positional=True,
        nargs="+",
    )


class TestCodeArgs(CommonArgs):
    repo_root: str = arg(
        default=".",
        help="Root of the course repository",
    )
    flow_or_problem_ymls: list[str] = arg(
        positional=True,
        nargs="+",
    )


class ExpandYamlArgs(CommonArgs):
    repo_root: str = arg(
        default=".",
        help="Root of the course repository",
    )
    yaml_file: str = arg(positional=True)


class LintYamlArgs(CommonArgs):
    config_file: str = arg(default="./.yamllint")
    repo_root: str = arg(
        default=".",
        help="Root of the course repository",
    )
    files: list[str] = arg(
        positional=True,
        nargs="+",
        help="List of directories or files to lint",
    )


# {{{ expand YAML

def expand_yaml(yml_file: str, repo_root: Path):
    if yml_file == "-":
        data = sys.stdin.read()
    else:
        data = Path(yml_file).read_text()

    from course.content import (
        YamlBlockEscapingFileSystemLoader,
        process_yaml_for_expansion,
    )
    data = process_yaml_for_expansion(data)

    from minijinja import Environment
    jinja_env = Environment(
            loader=YamlBlockEscapingFileSystemLoader(repo_root),
            undefined_behavior="strict",
            auto_escape_callback=lambda fn: False,
        )

    return jinja_env.render_str(data)

# }}}


# {{{ validate_course

def validate_course(args: ValidateCourseArgs) -> None:
    from django.conf import settings
    settings.configure(DEBUG=True)

    import django
    django.setup()

    from course.validation import validate_course_on_filesystem
    has_warnings = validate_course_on_filesystem(Path(args.repo_root),
            course_file=args.course_file,
            events_file=args.events_file)

    sys.exit(int(has_warnings and args.warn_error))

# }}}


# {{{ validate_pages

def validate_pages(args: ValidatePageArgs) -> None:
    from django.conf import settings
    settings.configure(DEBUG=True)

    import django
    django.setup()

    fake_repo = FileSystemFakeRepo(Path(args.repo_root))
    vctx = ValidationContext(
            repo=fake_repo,
            commit_sha=fake_repo,  # type: ignore[arg-type]
            course=None)

    from yaml import safe_load
    for yaml_filename in args.problem_ymls:
        yaml_data = safe_load(expand_yaml(yaml_filename, Path(args.repo_root)))
        try:
            PageBase.model_validate(yaml_data, context=vctx)
        except ValidationError as e:
            raise RuntimeError(f"Validation error in {yaml_filename}: {e!s}") from e

    if vctx.warnings:
        print("WARNINGS: ")
        for w in vctx.warnings:
            print("***", w.location, w.text)

    sys.exit(int(bool(vctx.warnings) and args.warn_error))

# }}}


# {{{ lint YAML

def lint_yaml(args: LintYamlArgs) -> None:
    import os

    from yamllint import linter
    from yamllint.cli import show_problems
    from yamllint.config import YamlLintConfig

    conf = YamlLintConfig(file=args.config_file)

    had_problems = False

    def check_file(name):
        nonlocal had_problems

        # expanded yaml is missing a newline at the end of the
        # file which causes the linter to complain, so we add a
        # newline :)
        expanded_yaml = expand_yaml(name, Path(args.repo_root)) + "\n"

        problems = list(linter.run(expanded_yaml, conf))
        show_problems(problems, name, "auto", None)

        had_problems = had_problems or bool(problems)

    for item in args.files:
        if os.path.isdir(item):
            for root, _, filenames in os.walk(item):
                for f in filenames:
                    filepath = os.path.join(root, f)
                    if not conf.is_file_ignored(f) and conf.is_yaml_file(f):
                        check_file(filepath)
        else:
            check_file(item)

    sys.exit(int(had_problems))

# }}}


# {{{ code test

def test_code_question(page: CodeQuestion) -> bool:
    import io

    from pytools import not_none
    print(75*"-")
    print("TESTING", page.id, "...", end=" ")
    sys.stdout.flush()

    test_code = page.test_code
    if test_code is not None:
        from course.page.code_run_backend import (
            substitute_correct_code_into_test_code,
        )
        test_code = substitute_correct_code_into_test_code(
                                            test_code, page.correct_code)

    from course.page.code_run_backend import package_exception, run_code

    data_files: dict[str, str] = {}

    for data_file_name in getattr(page, "data_files", []):
        from base64 import b64encode
        data_files[data_file_name] = b64encode(
                                Path(data_file_name).read_bytes()).decode()

    run_req = RunRequest(
            setup_code=page. setup_code,
            names_for_user=page. names_for_user,
            user_code=not_none(page.check_user_code or page.correct_code),
            names_from_user=page. names_from_user,
            test_code=test_code,
            data_files=data_files,
            compile_only=False,
            )

    prev_stdin = sys.stdin
    prev_stdout = sys.stdout
    prev_stderr = sys.stderr

    stdout = io.StringIO()
    stderr = io.StringIO()

    from time import time
    start = time()

    try:
        sys.stdin = None  # type: ignore[assignment]
        sys.stdout = stdout
        sys.stderr = stderr

        response = run_code(RunRequest.model_validate(run_req),
                            # allows matplotlib GUI to work
                            unsafely_skip_threading=True)

        response.stdout = stdout.getvalue()
        response.stderr = stderr.getvalue()

    except Exception:
        response = package_exception("uncaught_error")

    finally:
        sys.stdin = prev_stdin
        sys.stdout = prev_stdout
        sys.stderr = prev_stderr

    stop = time()
    response.feedback = [*response.feedback,
            f"Execution took {stop-start:.1f} seconds. "
            f"(Timeout is {page.timeout:.1f} seconds.)"]

    from colorama import Fore, Style
    if response.result == "success":
        points = response.points
        if points is None:
            print(Fore.RED
                    + "FAIL: no points value recorded"
                    + Style.RESET_ALL)
            success = False
        elif points < 1:
            print(Fore.RED
                    + "FAIL: code did not pass test"
                    + Style.RESET_ALL)
            success = False
        else:
            print(Fore.GREEN+response.result.upper()+Style.RESET_ALL)
            success = True
    else:
        print(Style.BRIGHT+Fore.RED
                + response.result.upper()+Style.RESET_ALL)
        success = False

    def print_response_aspect(s: str) -> None:
        val = getattr(response, s, None)
        if val is None:
            return
        if isinstance(val, list):
            response_s = "\n".join(str(s_i) for s_i in val)
        else:
            response_s = str(val).strip()

        if not response_s:
            return

        print(s, ":")
        indentation = 4*" "
        print(indentation + response_s.replace("\n", "\n"+indentation))

    print_response_aspect("points")
    print_response_aspect("feedback")
    print_response_aspect("traceback")
    print_response_aspect("stdout")
    print_response_aspect("stderr")
    print_response_aspect("timeout")

    return success


def test_code_yml(yml_file: str, repo_root: Path):
    from pydantic import TypeAdapter
    from yaml import safe_load
    data = safe_load(expand_yaml(yml_file, repo_root))

    if not isinstance(data, dict):
        raise ValueError("YAML file did not parse as a dict")

    vctx = ValidationContext(
                             repo=FileSystemFakeRepo(repo_root),
                             commit_sha=b"WORKINGDIR",
                             course=None,
                         ).with_location(yml_file)

    if "id" in data and "type" in data:
        adapter = TypeAdapter[CodeQuestion](CodeQuestion)
        page = adapter.validate_python(data, context=vctx)
        return test_code_question(page)

    else:
        flow = flow_desc_ta.validate_python(data, context=vctx)

        for group in flow.groups:
            for grp_page in group.pages:
                if not isinstance(grp_page, CodeQuestion):
                    continue
                res = test_code_question(grp_page)
                if not res:
                    return False

        return True


def test_code(args: TestCodeArgs) -> None:
    for yml_file in args.flow_or_problem_ymls:
        print(75*"=")
        print("EXAMINING", yml_file)
        if not test_code_yml(yml_file, repo_root=Path(args.repo_root)):
            sys.exit(1)

    sys.exit(0)

# }}}


def expand_yaml_ui(args: ExpandYamlArgs) -> None:
    print(expand_yaml(args.yaml_file, Path(args.repo_root)))


def main() -> None:
    import os

    os.environ["RELATE_COMMAND_LINE"] = "1"

    parser = Parser(
        SubParserGroup(
            SubParser("validate", ValidateCourseArgs),
            SubParser("validate-page", ValidatePageArgs),
            SubParser("test-code", TestCodeArgs),
            SubParser("expand-yaml", ExpandYamlArgs),
            SubParser("lint-yaml", LintYamlArgs),
            common_args=CommonArgs,
        ),
        description="RELATE course content command line tool",
    )

    parser.bind(
        validate_course,
        validate_pages,
        test_code,
        expand_yaml_ui,
        lint_yaml,
    ).run()


if __name__ == "__main__":
    main()

# vim: foldmethod=marker
