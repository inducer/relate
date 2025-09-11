from __future__ import annotations

from course.page.code_run_backend import RunRequest


def main():
    from course.page.code import request_run

    req = RunRequest(
        setup_code="a,b=5,2",
        names_for_user=["a", "b"],
        user_code="c = a+b",
        names_from_user=[],
        compile_only=False,
        )
    count = 0
    while True:
        print(count)
        count += 1
        res = request_run(req, 10)
        if res.result != "success":
            print(res)
            break


if __name__ == "__main__":
    main()
