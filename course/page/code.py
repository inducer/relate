# -*- coding: utf-8 -*-

from __future__ import division, print_function

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

import six

from course.validation import ValidationError
import django.forms as forms
from django.core.exceptions import ObjectDoesNotExist
from django.utils.html import escape
from django.utils.translation import ugettext as _, string_concat
from django.utils import translation
from django.conf import settings

from relate.utils import StyledForm
from course.page.base import (
        PageBaseWithTitle, markup_to_html, PageBaseWithValue,
        PageBaseWithHumanTextFeedback,
        AnswerFeedback, get_auto_feedback,

        get_editor_interaction_mode)
from course.constants import flow_permission


# {{{ python code question

class PythonCodeForm(StyledForm):
    # prevents form submission with codemirror's empty textarea
    use_required_attribute = False

    def __init__(self, read_only, interaction_mode, initial_code, *args, **kwargs):
        super(PythonCodeForm, self).__init__(*args, **kwargs)

        from course.utils import get_codemirror_widget
        cm_widget, cm_help_text = get_codemirror_widget(
                language_mode="python",
                interaction_mode=interaction_mode,
                read_only=read_only)

        self.fields["answer"] = forms.CharField(required=True,
            initial=initial_code,
            help_text=cm_help_text,
            widget=cm_widget,
            label=_("Answer"))

    def clean(self):
        # FIXME Should try compilation
        pass


RUNPY_PORT = 9941


class InvalidPingResponse(RuntimeError):
    pass


def request_python_run(run_req, run_timeout, image=None):
    import platform
    import json
    from six.moves import http_client
    import docker
    import socket
    import errno
    from docker.errors import APIError as DockerAPIError

    debug = False
    if debug:
        def debug_print(s):
            print(s)
    else:
        def debug_print(s):
            pass

    docker_timeout = 15

    # DEBUGGING SWITCH: 1 for 'spawn container', 0 for 'static container'
    if 1:
        docker_url = getattr(settings, "RELATE_DOCKER_URL",
                "unix://var/run/docker.sock")
        docker_tls = getattr(settings, "RELATE_DOCKER_TLS_CONFIG",
                None)

        if platform.system().lower().startswith("linux"):
            docker_cnx = docker.Client(
                    base_url=docker_url,
                    tls=docker_tls,
                    timeout=docker_timeout,
                    version="1.19")
        else:
            from docker.utils import kwargs_from_env
            docker_cnx = docker.Client(
                timeout=docker_timeout,
                **kwargs_from_env(assert_hostname=False)
            )

        if image is None:
            image = settings.RELATE_DOCKER_RUNPY_IMAGE

        dresult = docker_cnx.create_container(
                image=image,
                command=[
                    "/opt/runpy/runpy",
                    "-1"],
                host_config={
                    "Memory": 256*10**6,
                    "MemorySwap": -1,
                    "PublishAllPorts": True,
                    # Do not enable: matplotlib stops working if enabled.
                    # "ReadonlyRootfs": True,
                    },
                user="runpy")

        container_id = dresult["Id"]
    else:
        container_id = None

    connect_host_ip = 'localhost'

    try:
        # FIXME: Prohibit networking

        if container_id is not None:
            docker_cnx.start(container_id)

            container_props = docker_cnx.inspect_container(container_id)
            (port_info,) = (container_props
                    ["NetworkSettings"]["Ports"]["%d/tcp" % RUNPY_PORT])
            port_host_ip = port_info.get("HostIp")

            if platform.system().lower().startswith("linux"):
                if port_host_ip != "0.0.0.0":
                    connect_host_ip = port_host_ip
            else:
                connect_host_ip = getattr(settings, "RELATE_DOCKER_HOST_IP")

            port = int(port_info["HostPort"])
        else:
            port = RUNPY_PORT

        from time import time, sleep
        start_time = time()

        # {{{ ping until response received

        from traceback import format_exc

        def check_timeout():
                if time() - start_time < docker_timeout:
                    sleep(0.1)
                    # and retry
                else:
                    return {
                            "result": "uncaught_error",
                            "message": "Timeout waiting for container.",
                            "traceback": "".join(format_exc()),
                            "exec_host": connect_host_ip,
                            }

        while True:
            try:
                connection = http_client.HTTPConnection(connect_host_ip, port)

                connection.request('GET', '/ping')

                response = connection.getresponse()
                response_data = response.read().decode()

                if response_data != "OK":
                    raise InvalidPingResponse()

                break

            except (http_client.BadStatusLine, InvalidPingResponse):
                ct_res = check_timeout()
                if ct_res is not None:
                    return ct_res

            except socket.error as e:
                if e.errno in [errno.ECONNRESET, errno.ECONNREFUSED]:
                    ct_res = check_timeout()
                    if ct_res is not None:
                        return ct_res

                else:
                    raise

        # }}}

        debug_print("PING SUCCESSFUL")

        try:
            # Add a second to accommodate 'wire' delays
            connection = http_client.HTTPConnection(connect_host_ip, port,
                    timeout=1 + run_timeout)

            headers = {'Content-type': 'application/json'}

            json_run_req = json.dumps(run_req).encode("utf-8")

            from time import time
            start_time = time()

            debug_print("BEFPOST")
            connection.request('POST', '/run-python', json_run_req, headers)
            debug_print("AFTPOST")

            http_response = connection.getresponse()
            debug_print("GETR")
            response_data = http_response.read().decode("utf-8")
            debug_print("READR")

            end_time = time()

            result = json.loads(response_data)

            result["feedback"] = (result.get("feedback", [])
                    + ["Execution time: %.1f s -- Time limit: %.1f s"
                        % (end_time - start_time, run_timeout)])

            result["exec_host"] = connect_host_ip

            return result

        except socket.timeout:
            return {
                    "result": "timeout",
                    "exec_host": connect_host_ip,
                    }
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


def is_nuisance_failure(result):
    if result["result"] != "uncaught_error":
        return False

    if ("traceback" in result
            and "BadStatusLine" in result["traceback"]):

        # Occasionally, we fail to send a POST to the container, even after
        # the inital ping GET succeeded, for (for now) mysterious reasons.
        # Just try again.

        return True

    if ("traceback" in result
            and "bind: address already in use" in result["traceback"]):

        # https://github.com/docker/docker/issues/8714

        return True

    return False


def request_python_run_with_retries(run_req, run_timeout, image=None, retry_count=3):
    while True:
        result = request_python_run(run_req, run_timeout, image=image)

        if retry_count and is_nuisance_failure(result):
            retry_count -= 1
            continue

        return result


class PythonCodeQuestion(PageBaseWithTitle, PageBaseWithValue):
    """
    An auto-graded question allowing an answer consisting of Python code.
    All user code as well as all code specified as part of the problem
    is in Python 3.

    If you are not including the
    :attr:`course.constants.flow_permission.change_answer`
    permission for your entire flow, you likely want to
    include this snippet in your question definition:

    .. code-block:: yaml

        access_rules:
            add_permissions:
                - change_answer

    This will allow participants multiple attempts at getting
    the right answer.

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

        This may contain the marker "###CORRECT_CODE###", which will
        be replaced with the contents of :attr:`correct_code`, with
        each line indented to the same depth as where the marker
        is found. The line with this marker is only allowed to have
        white space and the marker on it.

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

    .. attribute:: single_submission

        Optional, a Boolean. If the question does not allow multiple submissions
        based on its :attr:`access_rules` (not the ones of the flow), a warning
        is shown. Setting this attribute to True will silence the warning.

    The following symbols are available in :attr:`setup_code` and :attr:`test_code`:

    * ``GradingComplete``: An exception class that can be raised to indicated
      that the grading code has concluded.

    * ``feedback``: A class instance with the following interface::

          feedback.set_points(0.5) # 0<=points<=1 (usually)
          feedback.add_feedback("This was wrong")

          # combines the above two and raises GradingComplete
          feedback.finish(0, "This was wrong")

          feedback.check_numpy_array_sanity(name, num_axes, data)

          feedback.check_numpy_array_features(name, ref, data, report_failure=True)

          feedback.check_numpy_array_allclose(name, ref, data,
                  accuracy_critical=True, rtol=1e-5, atol=1e-8,
                  report_success=True, report_failure=True)
              # If report_failure is True, this function will only return
              # if *data* passes the tests. It will return *True* in this
              # case.
              #
              # If report_failure is False, this function will always return,
              # and the return value will indicate whether *data* passed the
              # accuracy/shape/kind checks.

          feedback.check_list(name, ref, data, entry_type=None)

          feedback.check_scalar(name, ref, data, accuracy_critical=True,
              rtol=1e-5, atol=1e-8, report_success=True, report_failure=True)
          # returns True if accurate

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

        if not getattr(page_desc, "single_submission", False) and vctx is not None:
            is_multi_submit = False

            if hasattr(page_desc, "access_rules"):
                if hasattr(page_desc.access_rules, "add_permissions"):
                    if (flow_permission.change_answer
                            in page_desc.access_rules.add_permissions):
                        is_multi_submit = True

            if not is_multi_submit:
                vctx.add_warning(location, _("code question does not explicitly "
                    "allow multiple submission. Either add "
                    "access_rules/add_permssions/change_answer "
                    "or add 'single_submission: True' to confirm that you intend "
                    "for only a single submission to be allowed. "
                    "While you're at it, consider adding "
                    "access_rules/add_permssions/see_correctness."))

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
                ("single_submission", bool),
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
            answer_data, page_behavior):

        if answer_data is not None:
            answer = {"answer": answer_data["answer"]}
            form = PythonCodeForm(
                    not page_behavior.may_change_answer,
                    get_editor_interaction_mode(page_context),
                    self._initial_code(),
                    answer)
        else:
            answer = None
            form = PythonCodeForm(
                    not page_behavior.may_change_answer,
                    get_editor_interaction_mode(page_context),
                    self._initial_code(),
                    )

        return form

    def process_form_post(
            self, page_context, page_data, post_data, files_data, page_behavior):
        return PythonCodeForm(
                not page_behavior.may_change_answer,
                get_editor_interaction_mode(page_context),
                self._initial_code(),
                post_data, files_data)

    def answer_data(self, page_context, page_data, form, files_data):
        return {"answer": form.cleaned_data["answer"].strip()}

    def get_test_code(self):
        test_code = getattr(self.page_desc, "test_code", None)
        if test_code is None:
            return test_code

        correct_code = getattr(self.page_desc, "correct_code", None)
        if correct_code is None:
            correct_code = ""

        from .code_runpy_backend import substitute_correct_code_into_test_code
        return substitute_correct_code_into_test_code(test_code, correct_code)

    def grade(self, page_context, page_data, answer_data, grade_data):
        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback=_("No answer provided."))

        user_code = answer_data["answer"]

        # {{{ request run

        run_req = {"compile_only": False, "user_code": user_code}

        def transfer_attr(name):
            if hasattr(self.page_desc, name):
                run_req[name] = getattr(self.page_desc, name)

        transfer_attr("setup_code")
        transfer_attr("names_for_user")
        transfer_attr("names_from_user")

        if hasattr(self.page_desc, "test_code"):
            run_req["test_code"] = self.get_test_code()

        if hasattr(self.page_desc, "data_files"):
            run_req["data_files"] = {}

            from course.content import get_repo_blob

            for data_file in self.page_desc.data_files:
                from base64 import b64encode
                run_req["data_files"][data_file] = \
                        b64encode(
                                get_repo_blob(
                                    page_context.repo, data_file,
                                    page_context.commit_sha).data).decode()

        try:
            response_dict = request_python_run_with_retries(run_req,
                    run_timeout=self.page_desc.timeout)
        except:
            from traceback import format_exc
            response_dict = {
                    "result": "uncaught_error",
                    "message": "Error connecting to container",
                    "traceback": "".join(format_exc()),
                    }

        # }}}

        feedback_bits = []

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
                        and isinstance(val, six.string_types)):
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

            with translation.override(settings.RELATE_ADMIN_EMAIL_LOCALE):
                from django.template.loader import render_to_string
                message = render_to_string("course/broken-code-question-email.txt", {
                    "page_id": self.page_desc.id,
                    "course": page_context.course,
                    "error_message": error_msg,
                    })

                if (
                        not page_context.in_sandbox
                        and
                        not is_nuisance_failure(response_dict)):
                    try:
                        from django.core.mail import EmailMessage
                        msg = EmailMessage("".join(["[%s:%s] ",
                            _("code question execution failed")])
                            % (
                                page_context.course.identifier,
                                page_context.flow_session.flow_id
                                if page_context.flow_session is not None
                                else _("<unknown flow>")),
                            message,
                            settings.ROBOT_EMAIL_FROM,
                            [page_context.course.notify_email])

                        from relate.utils import get_connection
                        msg.connection = get_connection("robot")
                        msg.send()

                    except Exception:
                        from traceback import format_exc
                        feedback_bits.append(
                            six.text_type(string_concat(
                                "<p>",
                                _(
                                    "Both the grading code and the attempt to "
                                    "notify course staff about the issue failed. "
                                    "Please contact the course or site staff and "
                                    "inform them of this issue, mentioning this "
                                    "entire error message:"),
                                "</p>",
                                "<p>",
                                _(
                                    "Sending an email to the course staff about the "
                                    "following failure failed with "
                                    "the following error message:"),
                                "<pre>",
                                "".join(format_exc()),
                                "</pre>",
                                _("The original failure message follows:"),
                                "</p>")))

        # }}}

        from relate.utils import dict_to_struct
        response = dict_to_struct(response_dict)

        bulk_feedback_bits = []
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
            feedback_bits.append("".join([
                "<p>",
                _(
                    "The grading code failed. Sorry about that. "
                    "The staff has been informed, and if this problem is "
                    "due to an issue with the grading code, "
                    "it will be fixed as soon as possible. "
                    "In the meantime, you'll see a traceback "
                    "below that may help you figure out what went wrong."
                    ),
                "</p>"]))
        elif response.result == "timeout":
            feedback_bits.append("".join([
                "<p>",
                _(
                    "Your code took too long to execute. The problem "
                    "specifies that your code may take at most %s seconds "
                    "to run. "
                    "It took longer than that and was aborted."
                    ),
                "</p>"])
                    % self.page_desc.timeout)

            correctness = 0
        elif response.result == "user_compile_error":
            feedback_bits.append("".join([
                "<p>",
                _("Your code failed to compile. An error message is "
                    "below."),
                "</p>"]))

            correctness = 0
        elif response.result == "user_error":
            feedback_bits.append("".join([
                "<p>",
                _("Your code failed with an exception. "
                    "A traceback is below."),
                "</p>"]))

            correctness = 0
        else:
            raise RuntimeError("invalid runpy result: %s" % response.result)

        if hasattr(response, "feedback") and response.feedback:
            feedback_bits.append("".join([
                "<p>",
                _("Here is some feedback on your code"),
                ":"
                "<ul>%s</ul></p>"]) %
                        "".join(
                            "<li>%s</li>" % escape(fb_item)
                            for fb_item in response.feedback))
        if hasattr(response, "traceback") and response.traceback:
            feedback_bits.append("".join([
                "<p>",
                _("This is the exception traceback"),
                ":"
                "<pre>%s</pre></p>"]) % escape(response.traceback))
        if hasattr(response, "exec_host") and response.exec_host != "localhost":
            import socket
            try:
                exec_host_name, dummy, dummy = socket.gethostbyaddr(
                        response.exec_host)
            except socket.error:
                exec_host_name = response.exec_host

            feedback_bits.append("".join([
                "<p>",
                _("Your code ran on %s.") % exec_host_name,
                "</p>"]))

        if hasattr(response, "stdout") and response.stdout:
            bulk_feedback_bits.append("".join([
                "<p>",
                _("Your code printed the following output"),
                ":"
                "<pre>%s</pre></p>"])
                    % escape(response.stdout))
        if hasattr(response, "stderr") and response.stderr:
            bulk_feedback_bits.append("".join([
                "<p>",
                _("Your code printed the following error messages"),
                ":"
                "<pre>%s</pre></p>"]) % escape(response.stderr))
        if hasattr(response, "figures") and response.figures:
            fig_lines = ["".join([
                "<p>",
                _("Your code produced the following plots"),
                ":</p>"]),
                '<dl class="result-figure-list">',
                ]

            for nr, mime_type, b64data in response.figures:
                if mime_type in ["image/jpeg", "image/png"]:
                    fig_lines.extend([
                        "".join([
                            "<dt>",
                            _("Figure"), "%d<dt>"]) % nr,
                        '<dd><img alt="Figure %d" src="data:%s;base64,%s"></dd>'
                        % (nr, mime_type, b64data)])

            fig_lines.append("</dl>")
            bulk_feedback_bits.extend(fig_lines)

        # {{{ html output / santization

        if hasattr(response, "html") and response.html:
            def is_allowed_data_uri(allowed_mimetypes, uri):
                import re
                m = re.match(r"^data:([-a-z0-9]+/[-a-z0-9]+);base64,", uri)
                if not m:
                    return False

                mimetype = m.group(1)
                return mimetype in allowed_mimetypes

            def sanitize(s):
                import bleach

                def filter_audio_attributes(name, value):
                    if name in ["controls"]:
                        return True
                    else:
                        return False

                def filter_source_attributes(name, value):
                    if name in ["type"]:
                        return True
                    elif name == "src":
                        return is_allowed_data_uri([
                            "audio/wav",
                            ], value)
                    else:
                        return False

                def filter_img_attributes(name, value):
                    if name in ["alt", "title"]:
                        return True
                    elif name == "src":
                        return is_allowed_data_uri([
                            "image/png",
                            "image/jpeg",
                            ], value)
                    else:
                        return False

                return bleach.clean(s,
                        tags=bleach.ALLOWED_TAGS + ["audio", "video", "source"],
                        attributes={
                            "audio": filter_audio_attributes,
                            "source": filter_source_attributes,
                            "img": filter_img_attributes,
                            })

            bulk_feedback_bits.extend(
                    sanitize(snippet) for snippet in response.html)

        # }}}

        return AnswerFeedback(
                correctness=correctness,
                feedback="\n".join(feedback_bits),
                bulk_feedback="\n".join(bulk_feedback_bits))

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        result = ""

        if hasattr(self.page_desc, "correct_code_explanation"):
            result += markup_to_html(
                    page_context,
                    self.page_desc.correct_code_explanation)

        if hasattr(self.page_desc, "correct_code"):
            result += ("".join([
                _("The following code is a valid answer"),
                ": <pre>%s</pre>"])
                % escape(self.page_desc.correct_code))

        return result

    def normalized_answer(self, page_context, page_data, answer_data):
        if answer_data is None:
            return None

        normalized_answer = answer_data["answer"]

        from django.utils.html import escape
        return "<pre>%s</pre>" % escape(normalized_answer)

    def normalized_bytes_answer(self, page_context, page_data, answer_data):
        if answer_data is None:
            return None

        return (".py", answer_data["answer"].encode("utf-8"))

# }}}


# {{{ python code question with human feedback

class PythonCodeQuestionWithHumanTextFeedback(
        PythonCodeQuestion, PageBaseWithHumanTextFeedback):
    """
    A question allowing an answer consisting of Python code.
    This page type allows both automatic grading and grading
    by a human grader.

    If you are not including the
    :attr:`course.constants.flow_permission.change_answer`
    permission for your entire flow, you likely want to
    include this snippet in your question definition:

    .. code-block:: yaml

        access_rules:
            add_permissions:
                - change_answer

    This will allow participants multiple attempts at getting
    the right answer.

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
            raise ValidationError("".join([
                "%s: ",
                _("human_feedback_value greater than overall "
                    "value of question")])
                % location)

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
        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback=_("No answer provided."))

        if grade_data is not None and not grade_data["released"]:
            grade_data = None

        code_feedback = PythonCodeQuestion.grade(self, page_context,
                page_data, answer_data, grade_data)

        human_points = self.page_desc.human_feedback_value
        code_points = self.page_desc.value - human_points

        correctness = None
        percentage = None
        if (code_feedback is not None
                and code_feedback.correctness is not None
                and grade_data is not None
                and grade_data["grade_percent"] is not None):
            correctness = (
                    code_feedback.correctness * code_points

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

        human_feedback_points = None
        if grade_data is not None:
            if grade_data["feedback_text"] is not None:
                human_feedback_text = markup_to_html(
                        page_context, grade_data["feedback_text"])

            human_feedback_percentage = grade_data["grade_percent"]
            if human_feedback_percentage is not None:
                human_feedback_points = (human_feedback_percentage/100.
                        * human_points)

        code_feedback_points = None
        if (code_feedback is not None
                and code_feedback.correctness is not None):
            code_feedback_points = code_feedback.correctness*code_points

        from django.template.loader import render_to_string
        feedback = render_to_string(
                "course/feedback-code-with-human.html",
                {
                    "percentage": percentage,
                    "code_feedback": code_feedback,
                    "code_feedback_points": code_feedback_points,
                    "code_points": code_points,
                    "human_feedback_text": human_feedback_text,
                    "human_feedback_points": human_feedback_points,
                    "human_points": human_points,
                    })

        return AnswerFeedback(
                correctness=correctness,
                feedback=feedback,
                bulk_feedback=code_feedback.bulk_feedback)

# }}}
