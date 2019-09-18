def main():
    from course.page import request_run

    req = {
        "setup_code": "a,b=5,2",
        "names_for_user": ["a", "b"],
        "user_code": "c = a+b",
        "names_from_user": [],
        "test_from_user": [],
        "compile_only": False
        }
    count = 0
    while True:
        print count
        count += 1
        res = request_run(req, 5,
                image="inducer/runpy-i386")
        if res["result"] != "success":
            print res
            break

if __name__ == "__main__":
    main()
