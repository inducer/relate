from __future__ import annotations

import os
from collections import namedtuple

from relate.utils import (
    HTML5_DATETIME_FORMAT as DATE_TIME_PICKER_TIME_FORMAT,  # noqa: F401
)


QUIZ_FLOW_ID = "quiz-test"
MESSAGE_ANSWER_SAVED_TEXT = "Answer saved."
MESSAGE_ANSWER_FAILED_SAVE_TEXT = "Failed to submit answer."

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "resource")
CSV_PATH = os.path.join(FIXTURE_PATH, "csv")
FAKED_YAML_PATH = os.path.join(FIXTURE_PATH, "faked_yamls")


def get_upload_file_path(file_name, fixture_path=FIXTURE_PATH):
    return os.path.join(fixture_path, file_name)


TEST_TEXT_FILE_PATH = get_upload_file_path("test_file.txt")
TEST_PDF_FILE_PATH = get_upload_file_path("test_file.pdf")

TEST_HGTEXT_MARKDOWN_ANSWER = """
type: ChoiceQuestion
id: myquestion
shuffle: True
prompt: |

    # What is a quarter?

choices:

  - "1"
  - "2"
  - ~CORRECT~ 1/4
  - ~CORRECT~ $\\frac{1}{4}$
  - 四分之三
"""

TEST_HGTEXT_MARKDOWN_ANSWER_WRONG = """
type: ChoiceQuestion
id: myquestion
shuffle: True
prompt: |

    # What is a quarter?

choices:

  - "1"
  - "2"
  - 1/4
  - $\\frac{1}{4}$
  - 四分之三
"""

TEST_HGTEXT_MARKDOWN_ANSWER_TYPE_WRONG = """
type: Page
id: myquestion
content: |

    # Title
    content
"""

PageTuple = namedtuple(
    "PageTuple", [
        "page_id",
        "group_id",
        "need_human_grade",
        "expecting_grade",
        "need_runpy",
        "correct_answer",
        "grade_data",
        "full_points",
        "dl_file_extension",
    ]
)
TEST_AUDIO_OUTPUT_ANSWER = """
import numpy as np
t = np.linspace(0, 1, sample_rate, endpoint=False)
signal = np.sin(2*np.pi*t * 440)

output_audio(signal)
"""
TEST_PAGE_TUPLE = (
    PageTuple("welcome", "intro", False, False, False, None, {}, None, None),
    PageTuple("half", "quiz_start", False, True, False, {"answer": "0.5"}, {}, 5,
              ".txt"),
    PageTuple("krylov", "quiz_start", False, True, False, {"choice": ["0"]}, {}, 2,
              ".json"),
    PageTuple("ice_cream_toppings", "quiz_start", False, True, False,
              {"choice": ["0", "1", "4"]}, {}, 1, ".json"),
    PageTuple("matrix_props", "quiz_start", False, True, False,
              {"choice": ["0", "3"]}, {}, 1, ".json"),
    PageTuple("inlinemulti", "quiz_start", False, True, False,
              {"blank1": "Bar", "blank_2": "0.2", "blank3": "1",
               "blank4": "5", "blank5": "Bar", "choice2": "0",
               "choice_a": "0"}, {}, 10, ".json"),
    PageTuple("fear", "quiz_start", False, False, False, {"answer": "NOTHING!!!"},
              {}, 0, ".txt"),
    PageTuple("age_group", "quiz_start", False, False, False, {"choice": 3},
              {}, 0, ".json"),
    PageTuple("hgtext", "quiz_tail", True, True, False,
              {"answer": TEST_HGTEXT_MARKDOWN_ANSWER},
              {"grade_percent": "100", "released": "on"}, 5, ".txt"),
    PageTuple("addition", "quiz_tail", False, True, True, {"answer": "c = b + a\r"},
              {"grade_percent": "100", "released": "on"}, 1, ".py"),
    PageTuple("pymult", "quiz_tail", True, True, True, {"answer": "c = a * b\r"},
              {"grade_percent": "100", "released": "on"}, 4, ".py"),
    PageTuple("neumann", "quiz_tail", False, True, False, {"answer": "1/(1-A)"}, {},
              5, ".txt"),
    PageTuple("py_simple_list", "quiz_tail", True, True, True,
              {"answer": "b = [a] * 50\r"},
              {"grade_percent": "100", "released": "on"}, 4, ".py"),

    # Skipped
    # PageTuple("test_audio_output", "quiz_tail", True, True, True,
    #           {"answer": TEST_AUDIO_OUTPUT_ANSWER}, {}, 1),

    PageTuple("quarter", "quiz_tail", False, True, False, {"answer": ["0.25"]},
              {}, 0, ".txt"),
    PageTuple("anyup", "quiz_tail", True, False, False,
              {"uploaded_file": TEST_TEXT_FILE_PATH},
              {"grade_percent": "100", "released": "on"}, 5, None),
    PageTuple("proof", "quiz_tail", True, False, False,
              {"uploaded_file": TEST_PDF_FILE_PATH},
              {"grade_percent": "100", "released": "on"}, 5, ".pdf"),
    PageTuple("eigvec", "quiz_tail", False, True, False, {"answer": "matrix"}, {},
              2, ".txt"),
    PageTuple("lsq", "quiz_tail", False, True, False, {"choice": ["2"]}, {}, 1,
              ".json"),
)
PAGE_WARNINGS = "page_warnings"
PAGE_ERRORS = "page_errors"
HAVE_VALID_PAGE = "have_valid_page"

COMMIT_SHA_MAP = {
    # This didn't use os.path.join, because "get_flow_desc" used "flows/%s.yml" to
    # get the path.
    f"flows/{QUIZ_FLOW_ID}.yml": [

        # key: commit_sha, value: attributes
        {"my_fake_commit_sha_1": {"path": "fake-quiz-test1.yml"}},
        {"my_fake_commit_sha_2": {"path": "fake-quiz-test2.yml"}},

        {"my_fake_commit_sha_for_grades1": {
            "path": "fake-quiz-test-for-grade1.yml",
            "page_ids": ["half", "krylov", "quarter"]}},
        {"my_fake_commit_sha_for_grades2": {
            "path": "fake-quiz-test-for-grade2.yml",
            "page_ids": ["krylov", "quarter"]}},

        {"my_fake_commit_sha_for_finish_flow_session": {
            "path": "fake-quiz-test-for-finish_flow_session.yml",
            "page_ids": ["half", "krylov", "matrix_props", "age_group",
                         "anyup", "proof", "neumann"]
        }},

        {"my_fake_commit_sha_for_grade_flow_session": {
            "path": "fake-quiz-test-for-grade_flow_session.yml",
            "page_ids": ["anyup"]}},
        {"my_fake_commit_sha_for_view_flow_page": {
            "path": "fake-quiz-test-for-view_flow_page.yml",
            "page_ids": ["half", "half2"]}},
        {"my_fake_commit_sha_for_download_submissions": {
            "path": "fake-quiz-test-for-download-submissions.yml",
            "page_ids": ["half", "proof"]}},
        {"my_fake_commit_sha_for_flow_analytics": {
            "path": "fake-quiz-test-for-flow_analytics.yml"}},
        {"my_fake_commit_sha_for_page_analytics": {
            "path": "fake-quiz-test-for-page_analytics.yml"
        }}
    ],

    # This had to use path join
    os.path.join("images", ".attributes.yml"): [
        # faked commit sha for .attributes.yml
        {"abcdef001":
             {"path": "fake-images-attributes.yml"}},
    ],
    "questions/pdf-file-upload-example.yml": [
        {"my_fake_commit_sha_for_normalized_bytes_answer":
             {"path": "fake-pdf-file-upload-example.yml"}},
    ],
    "course.yml": [
        {"my_fake_commit_sha_for_course_desc": {
            "path":
                "fake-course-desc-for-page-chunk-tests.yml"}}
    ],
    "events.yml": [
        {"my_fake_commit_sha_for_events": {
            "path":
                "fake-events-desr-for-calendar-tests1.yml"}}
    ]

}
