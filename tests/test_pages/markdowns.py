"""
markdowns for page sandbox tests
"""

CODE_MARKDWON = """
type: PythonCodeQuestion
id: addition
value: 1
timeout: 10
prompt: |

    # Adding two numbers in Python

setup_code: |
    import random

    a = random.uniform(-10, 10)
    b = random.uniform(-10, 10)

names_for_user: [a, b]

names_from_user: [c]

test_code: |
    if not isinstance(c, float):
        feedback.finish(0, "Your computed c is not a float.")

    correct_c = a + b
    rel_err = abs(correct_c-c)/abs(correct_c)

    if rel_err < 1e-7:
        feedback.finish(1, "Your computed c was correct.")
    else:
        feedback.finish(0, "Your computed c was incorrect.")

correct_code: |

    c = a + b
"""

CODE_MARKDWON_PATTERN_WITH_DATAFILES = """
type: PythonCodeQuestion
id: addition
value: 1
timeout: 10
data_files:
    - question-data/random-data.npy
    %(extra_data_file)s
prompt: |

    # Adding two numbers in Python

setup_code: |
    import random

    a = random.uniform(-10, 10)
    b = random.uniform(-10, 10)

names_for_user: [a, b]

names_from_user: [c]

test_code: |
    if not isinstance(c, float):
        feedback.finish(0, "Your computed c is not a float.")

    correct_c = a + b
    rel_err = abs(correct_c-c)/abs(correct_c)

    if rel_err < 1e-7:
        feedback.finish(1, "Your computed c was correct.")
    else:
        feedback.finish(0, "Your computed c was incorrect.")

correct_code: |

    c = a + b
"""

CODE_MARKDWON_PATTERN_EXPLICITLY_NOT_ALLOW_MULTI_SUBMIT = """
type: PythonCodeQuestion
id: addition
value: 1
timeout: 10
single_submission: True
prompt: |

    # Adding two numbers in Python

setup_code: |
    import random

    a = random.uniform(-10, 10)
    b = random.uniform(-10, 10)

names_for_user: [a, b]

names_from_user: [c]

test_code: |
    if not isinstance(c, float):
        feedback.finish(0, "Your computed c is not a float.")

    correct_c = a + b
    rel_err = abs(correct_c-c)/abs(correct_c)

    if rel_err < 1e-7:
        feedback.finish(1, "Your computed c was correct.")
    else:
        feedback.finish(0, "Your computed c was incorrect.")

correct_code: |
    c = a + b
"""

CODE_MARKDWON_PATTERN_WITHOUT_TEST_CODE = """
type: PythonCodeQuestion
id: addition
value: 1
timeout: 10
single_submission: True
prompt: |

    # Adding two numbers in Python

setup_code: |
    import random

    a = random.uniform(-10, 10)
    b = random.uniform(-10, 10)

names_for_user: [a, b]

names_from_user: [c]

correct_code: |
    c = a + b
"""

CODE_MARKDWON_PATTERN_WITHOUT_CORRECT_CODE = """
type: PythonCodeQuestion
id: addition
value: 1
timeout: 10
single_submission: True
prompt: |

    # Adding two numbers in Python

setup_code: |
    import random

    a = random.uniform(-10, 10)
    b = random.uniform(-10, 10)

names_for_user: [a, b]

names_from_user: [c]

test_code: |
    if not isinstance(c, float):
        feedback.finish(0, "Your computed c is not a float.")

    correct_c = a + b
    rel_err = abs(correct_c-c)/abs(correct_c)

    if rel_err < 1e-7:
        feedback.finish(1, "Your computed c was correct.")
    else:
        feedback.finish(0, "Your computed c was incorrect.")

"""

FEEDBACK_POINTS_CODE_MARKDWON_PATTERN = """
type: PythonCodeQuestion
id: addition
value: 1
timeout: 10
prompt: |

    # Adding two numbers in Python

setup_code: |
    import random

    a = random.uniform(-10, 10)
    b = random.uniform(-10, 10)

names_for_user: [a, b]

names_from_user: [c]

test_code: |
    if not isinstance(c, float):
        feedback.finish(0, "Your computed c is not a float.")

    correct_c = a + b
    rel_err = abs(correct_c-c)/abs(correct_c)

    if rel_err < 1e-7:
        feedback.finish(%(full_points)s, "Your computed c was correct.")
    else:
        feedback.finish(%(min_points)s, "Your computed c was incorrect.")

correct_code: |

    c = a + b
"""  # noqa

FEEDBACK_POINTS_CODE_MARKDWON_PATTERN = """
type: PythonCodeQuestion
id: addition
value: 1
timeout: 10
prompt: |

    # Adding two numbers in Python

setup_code: |
    import random

    a = random.uniform(-10, 10)
    b = random.uniform(-10, 10)

names_for_user: [a, b]

names_from_user: [c]

test_code: |
    if not isinstance(c, float):
        feedback.finish(0, "Your computed c is not a float.")

    correct_c = a + b
    rel_err = abs(correct_c-c)/abs(correct_c)

    if rel_err < 1e-7:
        feedback.finish(%(full_points)s, "Your computed c was correct.")
    else:
        feedback.finish(%(min_points)s, "Your computed c was incorrect.")

correct_code: |

    c = a + b
"""  # noqa
