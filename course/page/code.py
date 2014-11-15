# -*- coding: utf-8 -*-

from __future__ import division

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


from course.validation import ValidationError
import django.forms as forms
from django.core.exceptions import ObjectDoesNotExist
from django.utils.html import escape

from courseflow.utils import StyledForm
from course.page.base import (
        PageBaseWithTitle, markup_to_html, PageBaseWithValue,
        PageBaseWithHumanTextFeedback,
        AnswerFeedback, get_auto_feedback)


# {{{ python code question

class PythonCodeForm(StyledForm):
    def __init__(self, read_only, initial_code, *args, **kwargs):
        super(PythonCodeForm, self).__init__(*args, **kwargs)

        from codemirror import CodeMirrorTextarea, CodeMirrorJavascript

        self.fields["answer"] = forms.CharField(required=True,
            initial=initial_code,
            help_text="Hit F9 to toggle full screen mode.",
            widget=CodeMirrorTextarea(
                mode="python",
                theme="default",
                addon_css=(
                    "dialog/dialog",
                    "display/fullscreen",
                    ),
                addon_js=(
                    "search/searchcursor",
                    "dialog/dialog",
                    "search/search",
                    "edit/matchbrackets",
                    "comment/comment",
                    "display/fullscreen",
                    "selection/active-line",
                    ),
                config={
                    "fixedGutter": True,
                    "indentUnit": 4,
                    "matchBrackets": True,
                    "styleActiveLine": True,
                    "readOnly": read_only,
                    # "autofocus": not read_only,
                    "extraKeys": CodeMirrorJavascript("""
                        {
                          "Ctrl-/": "toggleComment",
                          "Tab": function(cm)
                          {
                            var spaces = \
                                    Array(cm.getOption("indentUnit") + 1).join(" ");
                            cm.replaceSelection(spaces);
                          },
                          "F9": function(cm) {
                              cm.setOption("fullScreen",
                                !cm.getOption("fullScreen"));
                          }
                        }
                    """)
                    }),
                )

    def clean(self):
        # FIXME Should try compilation
        pass


CFRUNPY_PORT = 9941


class InvalidPingResponse(RuntimeError):
    pass


def request_python_run(run_req, run_timeout, image=None):
    import json
    import httplib
    from django.conf import settings
    import docker
    import socket
    import errno
    from httplib import BadStatusLine
    from docker.errors import APIError as DockerAPIError

    debug = False
    if debug:
        def debug_print(s):
            print s
    else:
        def debug_print(s):
            pass

    docker_timeout = 15

    # DEBUGGING SWITCH: 1 for 'spawn container', 0 for 'static container'
    if 1:
        docker_cnx = docker.Client(
                base_url='unix://var/run/docker.sock',
                version='1.12', timeout=docker_timeout)

        if image is None:
            image = settings.CF_DOCKER_CFRUNPY_IMAGE

        dresult = docker_cnx.create_container(
                image=image,
                command=[
                    "/opt/cfrunpy/cfrunpy",
                    "-1"],
                mem_limit=256e6,
                user="cfrunpy")

        container_id = dresult["Id"]
    else:
        container_id = None

    try:
        # FIXME: Prohibit networking

        if container_id is not None:
            docker_cnx.start(
                    container_id,
                    port_bindings={CFRUNPY_PORT: ('127.0.0.1',)})

            port_info, = docker_cnx.port(container_id, CFRUNPY_PORT)
            port = int(port_info["HostPort"])
        else:
            port = CFRUNPY_PORT

        from time import time, sleep
        start_time = time()

        # {{{ ping until response received

        from traceback import format_exc

        while True:
            try:
                connection = httplib.HTTPConnection('localhost', port)

                connection.request('GET', '/ping')

                response = connection.getresponse()
                response_data = response.read().decode("utf-8")

                if response_data != b"OK":
                    raise InvalidPingResponse()

                break

            except socket.error as e:
                if e.errno in [errno.ECONNRESET, errno.ECONNREFUSED]:
                    if time() - start_time < docker_timeout:
                        sleep(0.1)
                        # and retry
                    else:
                        return {
                                "result": "uncaught_error",
                                "message": "Timeout waiting for container.",
                                "traceback": "".join(format_exc()),
                                }
                else:
                    raise

            except (BadStatusLine, InvalidPingResponse):
                if time() - start_time < docker_timeout:
                    sleep(0.1)
                    # and retry
                else:
                    return {
                            "result": "uncaught_error",
                            "message": "Timeout waiting for container.",
                            "traceback": "".join(format_exc()),
                            }

        # }}}

        debug_print("PING SUCCESSFUL")

        try:
            # Add a second to accommodate 'wire' delays
            connection = httplib.HTTPConnection('localhost', port,
                    timeout=1 + run_timeout)

            headers = {'Content-type': 'application/json'}

            json_run_req = json.dumps(run_req).encode("utf-8")

            debug_print("BEFPOST")
            connection.request('POST', '/run-python', json_run_req, headers)
            debug_print("AFTPOST")

            http_response = connection.getresponse()
            debug_print("GETR")
            response_data = http_response.read().decode("utf-8")
            debug_print("READR")
            return json.loads(response_data)

        except socket.timeout:
            return {"result": "timeout"}

    finally:
        if container_id is not None:
            debug_print("-----------BEGIN DOCKER LOGS for %s" % container_id)
            debug_print(docker_cnx.logs(container_id))
            debug_print("-----------END DOCKER LOGS for %s" % container_id)

            try:
                docker_cnx.remove_container(container_id, force=True)
            except DockerAPIError:
                # Oh well. No need to bother the students with this nonsense.
                pass


class PythonCodeQuestion(PageBaseWithTitle, PageBaseWithValue):
    """
    An auto-graded question allowing an answer consisting of Python code.
    All user code as well as all code specified as part of the problem
    is in Python 3.

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``PythonCodeQuestion``

    .. attribute:: access_rules

        |access-rules-page-attr|

    .. attribute:: title

        |title-page-attr|

    .. attribute:: value

        |value-page-attr|

    .. attribute:: prompt

        The page's prompt, written in :ref:`markup`.

    .. attribute:: timeout

        A number, giving the number of seconds for which setup code,
        the given answer code, and the test code (combined) will be
        allowed to run.

    .. attribute:: setup_code

        Optional.
        Python code to prepare the environment for the participants
        answer.

    .. attribute:: show_setup_code

        Optional. ``True`` or ``False``. If true, the :attr:`setup_code`
        will be shown to the participant.

    .. attribute:: names_for_user

        Optional.
        Symbols defined at the end of the :attr:`setup_code` that will be
        made available to the participant's code.

        A deep copy (using the standard library function :func:`copy.deepcopy`)
        of these values is made, to prevent the user from modifying trusted
        state of the grading code.

    .. attribute:: names_from_user

        Optional.
        Symbols that the participant's code is expected to define.
        These will be made available to the :attr:`test_code`.

    .. attribute:: test_code

        Optional.
        Symbols that the participant's code is expected to define.
        These will be made available to the :attr:`test_code`.

    .. attribute:: show_test_code

        Optional. ``True`` or ``False``. If true, the :attr:`test_code`
        will be shown to the participant.

    .. attribute:: correct_code_explanation

        Optional.
        Code that is revealed when answers are visible
        (see :ref:`flow-permissions`). This is shown before
        :attr:`correct_code` as an explanation.

    .. attribute:: correct_code

        Optional.
        Code that is revealed when answers are visible
        (see :ref:`flow-permissions`).

    .. attribute:: initial_code

        Optional.
        Code present in the code input field when the participant first starts
        working on their solution.

    .. attribute:: data_files

        Optional.
        A list of file names in the :ref:`git-repo` whose contents will be made
        available to :attr:`setup_code` and :attr:`test_code` through the
        ``data_files`` dictionary. (see below)

    The following symbols are available in :attr:`setup_code` and :attr:`test_code`:

    * ``GradingComplete``: An exception class that can be raised to indicated
      that the grading code has concluded.

    * ``feedback``: A class instance with three methods::

          feedback.set_points(0.5) # 0<=points<=1 (usually)
          feedback.add_feedback("This was wrong")

          # combines the above two and raises GradingComplete
          feedback.finish(0, "This was wrong")

    * ``data_files``: A dictionary mapping file names from :attr:`data_files`
      to :class:`bytes` instances with that file's contents.

    * ``user_code``: The user code being tested, as a string.
    """

    def __init__(self, vctx, location, page_desc):
        super(PythonCodeQuestion, self).__init__(vctx, location, page_desc)

        if vctx is not None and hasattr(page_desc, "data_files"):
            for data_file in page_desc.data_files:
                try:
                    if not isinstance(data_file, str):
                        raise ObjectDoesNotExist()

                    from course.content import get_repo_blob
                    get_repo_blob(vctx.repo, data_file, vctx.commit_sha)
                except ObjectDoesNotExist:
                    raise ValidationError("%s: data file '%s' not found"
                            % (location, data_file))

    def required_attrs(self):
        return super(PythonCodeQuestion, self).required_attrs() + (
                ("prompt", "markup"),
                ("timeout", (int, float)),
                )

    def allowed_attrs(self):
        return super(PythonCodeQuestion, self).allowed_attrs() + (
                ("setup_code", str),
                ("show_setup_code", bool),
                ("names_for_user", list),
                ("names_from_user", list),
                ("test_code", str),
                ("show_test_code", bool),
                ("correct_code_explanation", "markup"),
                ("correct_code", str),
                ("initial_code", str),
                ("data_files", list),
                )

    def _initial_code(self):
        result = getattr(self.page_desc, "initial_code", None)
        if result is not None:
            return result.strip()
        else:
            return result

    def markup_body_for_title(self):
        return self.page_desc.prompt

    def body(self, page_context, page_data):
        from django.template.loader import render_to_string
        return render_to_string(
                "course/prompt-code-question.html",
                {
                    "prompt_html":
                    markup_to_html(page_context, self.page_desc.prompt),
                    "initial_code": self._initial_code(),
                    "show_setup_code": getattr(
                        self.page_desc, "show_setup_code", False),
                    "setup_code": getattr(self.page_desc, "setup_code", ""),
                    "show_test_code": getattr(
                        self.page_desc, "show_test_code", False),
                    "test_code": getattr(self.page_desc, "test_code", ""),
                    })

    def make_form(self, page_context, page_data,
            answer_data, answer_is_final):
        if answer_data is not None:
            answer = {"answer": answer_data["answer"]}
            form = PythonCodeForm(
                    answer_is_final,
                    self._initial_code(),
                    answer)
        else:
            answer = None
            form = PythonCodeForm(
                    answer_is_final,
                    self._initial_code(),
                    )

        return form

    def post_form(self, page_context, page_data, post_data, files_data):
        return PythonCodeForm(
                False,
                self._initial_code(),
                post_data, files_data)

    def answer_data(self, page_context, page_data, form, files_data):
        return {"answer": form.cleaned_data["answer"].strip()}

    def grade(self, page_context, page_data, answer_data, grade_data):

        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback="No answer provided.",
                    normalized_answer=None)

        user_code = answer_data["answer"]

        # {{{ request run

        run_req = {"compile_only": False, "user_code": user_code}

        def transfer_attr(name):
            if hasattr(self.page_desc, name):
                run_req[name] = getattr(self.page_desc, name)

        transfer_attr("setup_code")
        transfer_attr("names_for_user")
        transfer_attr("names_from_user")
        transfer_attr("test_code")

        if hasattr(self.page_desc, "data_files"):
            run_req["data_files"] = {}

            from course.content import get_repo_blob

            for data_file in self.page_desc.data_files:
                from base64 import b64encode
                run_req["data_files"][data_file] = \
                        b64encode(
                                get_repo_blob(
                                    page_context.repo, data_file,
                                    page_context.commit_sha).data)

        try:
            response_dict = request_python_run(run_req,
                    run_timeout=self.page_desc.timeout)
        except:
            from traceback import format_exc
            response_dict = {
                    "result": "uncaught_error",
                    "message": "Error connecting to container",
                    "traceback": "".join(format_exc()),
                    }

        # }}}

        # {{{ send email if the grading code broke

        if response_dict["result"] in [
                "uncaught_error",
                "setup_compile_error",
                "setup_error",
                "test_compile_error",
                "test_error"]:
            error_msg_parts = ["RESULT: %s" % response_dict["result"]]
            for key, val in sorted(response_dict.items()):
                if (key not in ["result", "figures"]
                        and val
                        and isinstance(val, (str, unicode))):
                    error_msg_parts.append("-------------------------------------")
                    error_msg_parts.append(key)
                    error_msg_parts.append("-------------------------------------")
                    error_msg_parts.append(val)
            error_msg_parts.append("-------------------------------------")
            error_msg_parts.append("user code")
            error_msg_parts.append("-------------------------------------")
            error_msg_parts.append(user_code)
            error_msg_parts.append("-------------------------------------")

            error_msg = "\n".join(error_msg_parts)

            from django.template.loader import render_to_string
            message = render_to_string("course/broken-code-question-email.txt", {
                "page_id": self.page_desc.id,
                "course": page_context.course,
                "error_message": error_msg,
                })

            from django.core.mail import send_mail
            from django.conf import settings
            send_mail("[%s] code question execution failed"
                    % page_context.course.identifier,
                    message,
                    settings.ROBOT_EMAIL_FROM,
                    recipient_list=[page_context.course.email])

        # }}}

        from courseflow.utils import dict_to_struct
        response = dict_to_struct(response_dict)

        feedback_bits = []
        if hasattr(response, "points"):
            correctness = response.points
            feedback_bits.append(
                    "<p><b>%s</b></p>"
                    % get_auto_feedback(correctness))
        else:
            correctness = None

        if response.result == "success":
            pass
        elif response.result in [
                "uncaught_error",
                "setup_compile_error",
                "setup_error",
                "test_compile_error",
                "test_error"]:
            feedback_bits.append(
                    "<p>The grading code failed. Sorry about that. "
                    "The staff has been informed, and if this problem is due "
                    "to an issue with the grading code, "
                    "it will be fixed as soon as possible. "
                    "In the meantime, you'll see a traceback "
                    "below that may help you figure out what went wrong.</p>")
        elif response.result == "timeout":
            feedback_bits.append(
                    "<p>Your code took too long to execute. The problem "
                    "specifies that your code may take at most %s seconds to run. "
                    "It took longer than that and was aborted.</p>"
                    % self.page_desc.timeout)

            correctness = 0
        elif response.result == "user_compile_error":
            feedback_bits.append(
                    "<p>Your code failed to compile. An error message is below.</p>")

            correctness = 0
        elif response.result == "user_error":
            feedback_bits.append(
                    "<p>Your code failed with an exception. "
                    "A traceback is below.</p>")

            correctness = 0
        else:
            raise RuntimeError("invalid cfrunpy result: %s" % response.result)

        if hasattr(response, "feedback") and response.feedback:
            feedback_bits.append(
                    "<p>Here is some feedback on your code:"
                    "<ul>%s</ul></p>" % "".join(
                        "<li>%s</li>" % escape(fb_item)
                        for fb_item in response.feedback))
        if hasattr(response, "traceback") and response.traceback:
            feedback_bits.append(
                    "<p>This is the exception traceback:"
                    "<pre>%s</pre></p>" % escape(response.traceback))
            print repr(response.traceback)
        if hasattr(response, "stdout") and response.stdout:
            feedback_bits.append(
                    "<p>Your code printed the following output:<pre>%s</pre></p>"
                    % escape(response.stdout))
        if hasattr(response, "stderr") and response.stderr:
            feedback_bits.append(
                    "<p>Your code printed the following error messages:"
                    "<pre>%s</pre></p>" % escape(response.stderr))
        if hasattr(response, "figures") and response.figures:
            fig_lines = [
                    "<p>Your code produced the following plots:</p>",
                    '<dl class="result-figure-list">',
                    ]

            for nr, mime_type, b64data in response.figures:
                fig_lines.extend([
                        "<dt>Figure %d<dt>" % nr,
                        '<dd><img alt="Figure %d" src="data:%s;base64,%s"></dd>'
                        % (nr, mime_type, b64data)])

            fig_lines.append("</dl>")
            feedback_bits.extend(fig_lines)

        return AnswerFeedback(
                correctness=correctness,
                feedback="\n".join(feedback_bits),
                normalized_answer="<pre>%s</pre>" % user_code)

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        result = ""

        if hasattr(self.page_desc, "correct_code_explanation"):
            result += markup_to_html(
                    page_context,
                    self.page_desc.correct_code_explanation),

        if hasattr(self.page_desc, "correct_code"):
            result += (
                    "The following code is a valid answer:<pre>%s</pre>"
                    % escape(self.page_desc.correct_code))

        return result

# }}}


# {{{ python code question with human feedback

class PythonCodeQuestionWithHumanTextFeedback(
        PythonCodeQuestion, PageBaseWithHumanTextFeedback):
    """
    A question allowing an answer consisting of Python code.
    This page type allows both automatic grading and grading
    by a human grader.

    The allowed attributes are the same as those of
    :class:`PythonCodeQuestion`, with the following additional,
    required attribute:

    .. attribute:: human_feedback_value

        Required.
        A number. The point value of the feedback component
        by the human grader (who will grade on a 0-100 scale,
        which is scaled to yield :attr:`human_feedback_value`
        at 100).

    .. attribute:: rubric

        Required.
        The grading guideline for this question (for the human-graded component
        of the question), in :ref:`markup`.
    """

    def __init__(self, vctx, location, page_desc):
        super(PythonCodeQuestionWithHumanTextFeedback, self).__init__(
                vctx, location, page_desc)

        if (vctx is not None
                and self.page_desc.human_feedback_value > self.page_desc.value):
            raise ValidationError(
                    "%s: human_feedback_value greater than overall "
                    "value of question" % location)

    def required_attrs(self):
        return super(
                PythonCodeQuestionWithHumanTextFeedback, self).required_attrs() + (
                        # value is otherwise optional, but we require it here
                        ("value", (int, float)),
                        ("human_feedback_value", (int, float)),
                        )

    def human_feedback_point_value(self, page_context, page_data):
        return self.page_desc.human_feedback_value

    def grade(self, page_context, page_data, answer_data, grade_data):
        """This method is appropriate if the grade consists *only* of the
        feedback provided by humans. If more complicated/combined feedback
        is desired, a subclass would likely override this.
        """

        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback="No answer provided.")

        if grade_data is not None and not grade_data["released"]:
            grade_data = None

        code_feedback = PythonCodeQuestion.grade(self, page_context,
                page_data, answer_data, grade_data)

        correctness = None
        percentage = None
        if (code_feedback is not None
                and code_feedback.correctness is not None
                and grade_data is not None
                and grade_data["grade_percent"] is not None):
            correctness = (
                    code_feedback.correctness
                    * (self.page_desc.value - self.page_desc.human_feedback_value)

                    + grade_data["grade_percent"] / 100
                    * self.page_desc.human_feedback_value
                    ) / self.page_desc.value
            percentage = correctness * 100
        elif (self.page_desc.human_feedback_value == self.page_desc.value
                and grade_data is not None
                and grade_data["grade_percent"] is not None):
            correctness = grade_data["grade_percent"] / 100
            percentage = correctness * 100

        human_feedback_percentage = None
        human_feedback_text = None

        if grade_data is not None:
            if grade_data["feedback_text"] is not None:
                human_feedback_text = markup_to_html(
                        page_context, grade_data["feedback_text"])

            human_feedback_percentage = grade_data["grade_percent"]

        from django.template.loader import render_to_string
        feedback = render_to_string(
                "course/feedback-code-with-human.html",
                {
                    "percentage": percentage,
                    "code_feedback": code_feedback,
                    "human_feedback_text": human_feedback_text,
                    "human_feedback_percentage": human_feedback_percentage,
                    })

        return AnswerFeedback(
                correctness=correctness,
                feedback=feedback)

# }}}
