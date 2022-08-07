"""
markdowns for page sandbox tests
"""

# {{{


# }}}

# {{{ code questions

CODE_MARKDWON = """
type: PythonCodeQuestion
access_rules:
    add_permissions:
        - change_answer
id: addition
value: 1
timeout: 10
prompt: |

    # Adding 1 and 2, and assign it to c

names_from_user: [c]

initial_code: |
    c =

test_code: |
    if not isinstance(c, float):
        feedback.finish(0, "Your computed c is not a float.")

    correct_c = 3
    rel_err = abs(correct_c-c)/abs(correct_c)

    if rel_err < 1e-7:
        feedback.finish(1, "Your computed c was correct.")
    else:
        feedback.finish(0, "Your computed c was incorrect.")

correct_code: |

    c = 2 + 1

correct_code_explanation: This is the [explanation](http://example.com/1).
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

CODE_MARKDWON_WITH_DATAFILES_BAD_FORMAT = """
type: PythonCodeQuestion
id: addition
value: 1
timeout: 10
data_files:
    - question-data/random-data.npy
    - - foo
      - bar
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


CODE_MARKDWON_NOT_EXPLICITLY_NOT_ALLOW_MULTI_SUBMIT1 = """
type: PythonCodeQuestion
access_rules:
    add_permissions:
        - see_answer_after_submission
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

CODE_MARKDWON_NOT_EXPLICITLY_NOT_ALLOW_MULTI_SUBMIT2 = """
type: PythonCodeQuestion
access_rules:
    remove_permissions:
        - see_answer_after_submission
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

CODE_WITH_HUMAN_FEEDBACK_MARKDWON_PATTERN = """
type: PythonCodeQuestionWithHumanTextFeedback
id: pymult
access_rules:
    add_permissions:
        - change_answer
value: %(value)s
%(human_feedback)s
%(extra_attribute)s
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

rubric: |

    The code has to be squeaky-clean.

"""  # noqa

# }}}

# {{{ octave code questions

OCTAVE_CODE_MARKDWON = """
type: OctaveCodeQuestion
access_rules:
    add_permissions:
        - change_answer
id: addition
value: 1
timeout: 10
prompt: |
    # Adding 1 and 2, and assign it to c
names_from_user: [c]
initial_code: |
    c =
test_code: |
    if not isinstance(c, float):
        feedback.finish(0, "Your computed c is not a float.")
    correct_c = 3
    rel_err = abs(correct_c-c)/abs(correct_c)
    if rel_err < 1e-7:
        feedback.finish(1, "Your computed c was correct.")
    else:
        feedback.finish(0, "Your computed c was incorrect.")
correct_code: |
    c = 2 + 1
correct_code_explanation: This is the [explanation](http://example.com/1).
"""

OCTAVE_CODE_MARKDWON_PATTERN_WITH_DATAFILES = """
type: OctaveCodeQuestion
id: addition
value: 1
timeout: 10
data_files:
    - question-data/random-data.m
    %(extra_data_file)s
prompt: |
    # Adding two numbers in Octave
setup_code: |
    pkg load statistics
    a = unifrnd(-10,10)
    b = unifrnd(-10,10)
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

OCTAVE_CODE_MARKDWON_WITH_DATAFILES_BAD_FORMAT = """
type: OctaveCodeQuestion
id: addition
value: 1
timeout: 10
data_files:
    - question-data/random-data.m
    - - foo
      - bar
prompt: |
    # Adding two numbers in Octave
setup_code: |
    pkg load statistics
    a = unifrnd(-10,10)
    b = unifrnd(-10,10)
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

OCTAVE_CODE_MARKDWON_NOT_EXPLICITLY_NOT_ALLOW_MULTI_SUBMIT1 = """
type: OctaveCodeQuestion
access_rules:
    add_permissions:
        - see_answer_after_submission
id: addition
value: 1
timeout: 10
prompt: |
    # Adding two numbers in Octave
setup_code: |
    pkg load statistics
    a = unifrnd(-10,10)
    b = unifrnd(-10,10)
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

OCTAVE_CODE_MARKDWON_NOT_EXPLICITLY_NOT_ALLOW_MULTI_SUBMIT2 = """
type: OctaveCodeQuestion
access_rules:
    remove_permissions:
        - see_answer_after_submission
id: addition
value: 1
timeout: 10
prompt: |
    # Adding two numbers in Octave
setup_code: |
    pkg load statistics
    a = unifrnd(-10,10)
    b = unifrnd(-10,10)
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

OCTAVE_CODE_MARKDWON_PATTERN_EXPLICITLY_NOT_ALLOW_MULTI_SUBMIT = """
type: OctaveCodeQuestion
id: addition
value: 1
timeout: 10
single_submission: True
prompt: |
    # Adding two numbers in Octave
setup_code: |
    pkg load statistics
    a = unifrnd(-10,10)
    b = unifrnd(-10,10)
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

OCTAVE_CODE_MARKDWON_PATTERN_WITHOUT_TEST_CODE = """
type: OctaveCodeQuestion
id: addition
value: 1
timeout: 10
single_submission: True
prompt: |
    # Adding two numbers in Octave
setup_code: |
    pkg load statistics
    a = unifrnd(-10,10)
    b = unifrnd(-10,10)
names_for_user: [a, b]
names_from_user: [c]
correct_code: |
    c = a + b
"""

OCTAVE_CODE_MARKDWON_PATTERN_WITHOUT_CORRECT_CODE = """
type: OctaveCodeQuestion
id: addition
value: 1
timeout: 10
single_submission: True
prompt: |
    # Adding two numbers in Octave
setup_code: |
    pkg load statistics
    a = unifrnd(-10,10)
    b = unifrnd(-10,10)
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

OCTAVE_FEEDBACK_POINTS_CODE_MARKDWON_PATTERN = """
type: OctaveCodeQuestion
id: addition
value: 1
timeout: 10
prompt: |
    # Adding two numbers in Octave
setup_code: |
    pkg load statistics
    a = unifrnd(-10,10)
    b = unifrnd(-10,10)
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

OCTAVE_FEEDBACK_POINTS_CODE_MARKDWON_PATTERN = """
type: OctaveCodeQuestion
id: addition
value: 1
timeout: 10
prompt: |
    # Adding two numbers in Octave
setup_code: |
    pkg load statistics
    a = unifrnd(-10,10)
    b = unifrnd(-10,10)
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

# }}}

# vim: fdm=marker
