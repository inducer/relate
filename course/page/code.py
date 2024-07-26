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

import django.forms as forms
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.utils.html import escape
from django.utils.translation import gettext as _

from course.constants import flow_permission
from course.page.base import (
    AnswerFeedback,
    PageBaseWithHumanTextFeedback,
    PageBaseWithTitle,
    PageBaseWithValue,
    get_auto_feedback,
    get_editor_interaction_mode,
    markup_to_html,
)
from course.validation import ValidationError
from relate.utils import StyledForm, string_concat


# DEBUGGING SWITCH:
# True for 'spawn containers' (normal operation)
# False for 'just connect to localhost:CODE_QUESTION_CONTAINER_PORT' as runcode'
SPAWN_CONTAINERS = True


# {{{ html sanitization helper

def is_allowed_data_uri(allowed_mimetypes, uri):
    import re
    m = re.match(r"^data:([-a-z0-9]+/[-a-z0-9]+);base64,", uri)
    if not m:
        return False

    mimetype = m.group(1)
    return mimetype in allowed_mimetypes


def filter_audio_attributes(tag, name, value):
    if name in ["controls"]:
        return True
    else:
        return False


def filter_source_attributes(tag, name, value):
    if name in ["type"]:
        return True
    elif name == "src":
        if is_allowed_data_uri([
                "audio/wav",
                ], value):
            return True
        else:
            return False
    else:
        return False


def filter_img_attributes(tag, name, value):
    if name in ["alt", "title"]:
        return True
    elif name == "src":
        return is_allowed_data_uri([
            "image/png",
            "image/jpeg",
            ], value)
    else:
        return False


def filter_attributes(tag, name, value):
    from bleach.sanitizer import ALLOWED_ATTRIBUTES

    allowed_attrs = ALLOWED_ATTRIBUTES.get(tag, [])
    result = name in allowed_attrs

    if tag == "audio":
        result = result or filter_audio_attributes(tag, name, value)
    elif tag == "source":
        result = result or filter_source_attributes(tag, name, value)
    elif tag == "img":
        result = result or filter_img_attributes(tag, name, value)

    # {{{ prohibit data URLs anywhere not allowed above

    # Follows approach suggested in
    # https://github.com/mozilla/bleach/issues/348#issuecomment-359484660

    from html5lib.filters.sanitizer import attr_val_is_uri

    if (None, name) in attr_val_is_uri or (tag, name) in attr_val_is_uri:
        from urllib.parse import urlparse
        try:
            parsed_url = urlparse(value)
        except ValueError:
            # could not parse URL: tough beans
            return False

        if parsed_url.scheme == "data" and not result:
            return False

    # }}}

    return result


def sanitize_from_code_html(s):
    import bleach

    if not isinstance(s, str):
        return _("(Non-string in 'HTML' output filtered out)")

    return bleach.clean(s,
            tags=[*bleach.ALLOWED_TAGS, "audio", "video", "source"],
            protocols=[*bleach.ALLOWED_PROTOCOLS, "data"],
            attributes=filter_attributes)

# }}}


# {{{ base code question

class CodeForm(StyledForm):
    # prevents form submission with codemirror's empty textarea
    use_required_attribute = False

    def __init__(self, read_only, interaction_mode, initial_code,
            language_mode, data=None, *args, **kwargs):
        super().__init__(data, *args, **kwargs)

        from course.utils import get_codemirror_widget
        cm_widget, cm_help_text = get_codemirror_widget(
                language_mode=language_mode,
                interaction_mode=interaction_mode,
                read_only=read_only,

                # Automatically focus the text field once there has
                # been some input.
                autofocus=(
                    not read_only
                    and (data is not None and "answer" in data)))

        self.fields["answer"] = forms.CharField(required=True,
            initial=initial_code,
            help_text=cm_help_text,
            widget=cm_widget,
            label=_("Answer"))

        self.style_codemirror_widget()

    def clean(self):
        # FIXME Should try compilation
        pass


CODE_QUESTION_CONTAINER_PORT = 9941
DOCKER_TIMEOUT = 15


class InvalidPingResponse(RuntimeError):
    pass


def request_run(run_req, run_timeout, image=None):
    import errno
    import http.client as http_client
    import json
    import socket

    import docker
    from docker.errors import APIError as DockerAPIError

    debug = False
    if debug:
        def debug_print(s):
            print(s)
    else:
        def debug_print(s):
            pass

    command_path = "/opt/runcode/runcode"
    user = "runcode"

    # The following is necessary because tests don't arise from a CodeQuestion
    # object, so we provide a fallback.
    debug_print("Image is %s." % repr(image))
    if image is None:
        image = settings.RELATE_DOCKER_RUNPY_IMAGE

    if SPAWN_CONTAINERS:
        docker_url = getattr(settings, "RELATE_DOCKER_URL",
                "unix://var/run/docker.sock")
        docker_tls = getattr(settings, "RELATE_DOCKER_TLS_CONFIG",
                None)
        docker_cnx = docker.DockerClient(
                base_url=docker_url,
                tls=docker_tls,
                timeout=DOCKER_TIMEOUT,
                version="1.24")

        mem_limit = 384*10**6
        container = docker_cnx.containers.create(
                image=image,
                command=[
                    command_path,
                    "-1"],
                mem_limit=mem_limit,
                memswap_limit=mem_limit,
                publish_all_ports=True,
                detach=True,
                # Do not enable: matplotlib stops working if enabled.
                # read_only=True,
                user=user)

    else:
        container = None

    connect_host_ip = "localhost"

    try:
        # FIXME: Prohibit networking

        if container is not None:
            container.start()

            port_infos = container.ports[f"{CODE_QUESTION_CONTAINER_PORT}/tcp"]
            if not port_infos:
                raise ValueError("got empty list of container ports")
            port_info = port_infos[0]

            port_host_ip = port_info.get("HostIp")

            if port_host_ip != "0.0.0.0":
                connect_host_ip = port_host_ip

            port = int(port_info["HostPort"])
        else:
            port = CODE_QUESTION_CONTAINER_PORT

        from time import sleep, time
        start_time = time()

        # {{{ ping until response received

        from traceback import format_exc

        def check_timeout():
            if time() - start_time < DOCKER_TIMEOUT:
                sleep(0.1)
                # and retry
            else:
                return {
                        "result": "uncaught_error",
                        "message": "Timeout waiting for container.",
                        "traceback": "".join(format_exc()),
                        "exec_host": connect_host_ip,
                        }

        if not connect_host_ip:
            # for compatibility with podman
            connect_host_ip = "localhost"

        while True:
            try:
                connection = http_client.HTTPConnection(connect_host_ip, port)

                connection.request("GET", "/ping")

                response = connection.getresponse()
                response_data = response.read().decode()

                if response_data != "OK":
                    raise InvalidPingResponse()

                break

            except (http_client.BadStatusLine, InvalidPingResponse):
                ct_res = check_timeout()
                if ct_res is not None:
                    return ct_res

            except OSError as e:
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

            headers = {"Content-type": "application/json"}

            json_run_req = json.dumps(run_req).encode("utf-8")

            from time import time
            start_time = time()

            debug_print("BEFPOST")
            connection.request("POST", "/run-python", json_run_req, headers)
            debug_print("AFTPOST")

            http_response = connection.getresponse()
            debug_print("GETR")
            response_data = http_response.read().decode("utf-8")
            debug_print("READR")

            end_time = time()

            result = json.loads(response_data)

            result["feedback"] = ([*result.get("feedback", []),
                "Execution time: %.1f s -- Time limit: %.1f s" % (
                    end_time - start_time, run_timeout)])

            result["exec_host"] = connect_host_ip

            return result

        except socket.timeout:
            return {
                    "result": "timeout",
                    "exec_host": connect_host_ip,
                    }
    finally:
        if container is not None:
            debug_print(f"-----------BEGIN DOCKER LOGS for {container.id}")
            debug_print(container.logs())
            debug_print(f"-----------END DOCKER LOGS for {container.id}")

            try:
                container.remove(force=True)
            except DockerAPIError:
                # Oh well. No need to bother the students with this nonsense.
                pass


def is_nuisance_failure(result):
    if result["result"] != "uncaught_error":
        return False

    if "traceback" in result:
        if "BadStatusLine" in result["traceback"]:

            # Occasionally, we fail to send a POST to the container, even after
            # the inital ping GET succeeded, for (for now) mysterious reasons.
            # Just try again.

            return True

        if "bind: address already in use" in result["traceback"]:
            # https://github.com/docker/docker/issues/8714

            return True

        if ("requests.packages.urllib3.exceptions.NewConnectionError"
                in result["traceback"]):
            return True

        if "http.client.RemoteDisconnected" in result["traceback"]:
            return True

        if "[Errno 113] No route to host" in result["traceback"]:
            return True

    return False


def request_run_with_retries(run_req, run_timeout, image=None, retry_count=3):
    while True:
        result = request_run(run_req, run_timeout, image=image)

        if retry_count and is_nuisance_failure(result):
            retry_count -= 1
            continue

        return result


class CodeQuestion(PageBaseWithTitle, PageBaseWithValue):
    """
    An auto-graded question allowing an answer consisting of code.
    All user code as well as all code specified as part of the problem
    is in the specified language.  This class should be treated as an
    interface and used only as a superclass.

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

        ``CodeQuestion``

    .. attribute:: is_optional_page

        |is-optional-page-attr|

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
        Language-specific code to prepare the environment for the participant's
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
        Code that will be run to determine the correctness of a
        student-provided solution. Will have access to variables in
        :attr:`names_from_user` (which will be *None*) if not provided. Should
        never raise an exception.

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

    .. attribute:: docker_image

        Optional.
        Specific Docker image within which to run code for the participants
        answer.  This overrides the image set in the `local_settings.py`
        configuration.  The Docker image should provide two files; these are
        supplied in RELATE's standard Python Docker image by `course/page/
        code_run_backend_python.py` and `course/page/code_feedback.py`, for
        instance.  Consult `docker-image-run-py/docker-build.sh` for one
        example of a local build.  The Docker image should already be loaded
        on the system (RELATE does not pull the image automatically).

    * ``data_files``: A dictionary mapping file names from :attr:`data_files`
      to :class:`bytes` instances with that file's contents.

    * ``user_code``: The user code being tested, as a string.
    """

    def __init__(self, vctx, location, page_desc, language_mode):
        super().__init__(vctx, location, page_desc)

        if vctx is not None and hasattr(page_desc, "data_files"):
            for data_file in page_desc.data_files:
                try:
                    if not isinstance(data_file, str):
                        raise ObjectDoesNotExist()

                    from course.content import get_repo_blob
                    get_repo_blob(vctx.repo, data_file, vctx.commit_sha)
                except ObjectDoesNotExist:
                    raise ValidationError(
                        string_concat(
                            "%(location)s: ",
                            _("data file '%(file)s' not found"))
                        % {"location": location, "file": data_file})

        if hasattr(page_desc, "docker_image"):
            self.container_image = page_desc.docker_image

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
        return (
            *super().required_attrs(),
            ("prompt", "markup"),
            ("timeout", (int, float)))

    def allowed_attrs(self):
        return (
            *super().allowed_attrs(),
            ("setup_code", str),
            ("show_setup_code", bool),
            ("names_for_user", list),
            ("names_from_user", list),
            ("test_code", str),
            ("show_test_code", bool),
            ("correct_code_explanation", "markup"),
            ("correct_code", str),
            ("initial_code", str),
            ("docker_image", str),
            ("data_files", list),
            ("single_submission", bool))

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
            answer = {"answer": self.get_code_from_answer_data(answer_data)}
            form = CodeForm(
                    not page_behavior.may_change_answer,
                    get_editor_interaction_mode(page_context),
                    self._initial_code(),
                    self.language_mode,
                    answer)
        else:
            answer = None
            form = CodeForm(
                    not page_behavior.may_change_answer,
                    get_editor_interaction_mode(page_context),
                    self._initial_code(),
                    self.language_mode
                    )

        return form

    def process_form_post(
            self, page_context, page_data, post_data, files_data, page_behavior):
        return CodeForm(
                not page_behavior.may_change_answer,
                get_editor_interaction_mode(page_context),
                self._initial_code(),
                self.language_mode,
                post_data, files_data)

    def get_submission_filename_pattern(self, page_context):
        username = "anon"
        flow_id = "unk_flow"
        if page_context.flow_session is not None:
            if page_context.flow_session.participation is not None:
                username = page_context.flow_session.participation.user.username
            if page_context.flow_session.flow_id:
                flow_id = page_context.flow_session.flow_id

        return (
                "submission/"
                f"{page_context.course.identifier}/"
                "code/"
                f"{flow_id}/"
                f"{self.page_desc.id}/"
                f"{username}"
                f"{self.suffix}")

    def code_to_answer_data(self, page_context, code):
        # Linux sector size is 512. Anything below a half-full
        # sector is probably inefficient.
        if len(code) <= 256:
            return {"answer": code}

        from django.core.files.base import ContentFile
        saved_name = settings.RELATE_BULK_STORAGE.save(
                self.get_submission_filename_pattern(page_context),
                ContentFile(code))

        return {"storage_filename": saved_name}

    def answer_data(self, page_context, page_data, form, files_data):
        code = form.cleaned_data["answer"].strip()
        return self.code_to_answer_data(page_context, code)

    def get_test_code(self):
        test_code = getattr(self.page_desc, "test_code", None)
        if test_code is None:
            return test_code

        correct_code = getattr(self.page_desc, "correct_code", None)
        if correct_code is None:
            correct_code = ""

        from .code_run_backend import substitute_correct_code_into_test_code
        return substitute_correct_code_into_test_code(test_code, correct_code)

    @staticmethod
    def get_code_from_answer_data(answer_data):
        if "storage_filename" in answer_data:
            bulk_storage = settings.RELATE_BULK_STORAGE
            with bulk_storage.open(answer_data["storage_filename"]) as inf:
                return inf.read().decode("utf-8")

        elif "answer" in answer_data:
            return answer_data["answer"]

        else:
            raise ValueError("could not get submitted data from answer_data JSON")

    def grade(self, page_context, page_data, answer_data, grade_data):
        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback=_("No answer provided."))

        user_code = self.get_code_from_answer_data(answer_data)

        # {{{ request run

        run_req = {"compile_only": False, "user_code": user_code}

        def transfer_attr(name):
            if hasattr(self.page_desc, name):
                run_req[name] = getattr(self.page_desc, name)

        transfer_attr("setup_code")
        transfer_attr("names_for_user")
        transfer_attr("names_from_user")

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
            response_dict = request_run_with_retries(run_req,
                    run_timeout=self.page_desc.timeout,
                    image=self.container_image)
        except Exception:
            from traceback import format_exc
            response_dict = {
                    "result": "uncaught_error",
                    "message": "Error connecting to container",
                    "traceback": "".join(format_exc()),
                    }

        # }}}

        feedback_bits = []

        correctness = None

        if "points" in response_dict:
            correctness = response_dict["points"]
            try:
                feedback_bits.append(
                        "<p><b>%s</b></p>"
                        % _(get_auto_feedback(correctness)))
            except Exception as e:
                correctness = None
                response_dict["result"] = "setup_error"
                response_dict["message"] = (
                    "{}: {}".format(type(e).__name__, str(e))
                )

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
                        and isinstance(val, str)):
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

            from course.utils import LanguageOverride
            from relate.utils import format_datetime_local, local_now
            with LanguageOverride(page_context.course):
                from relate.utils import render_email_template
                message = render_email_template(
                    "course/broken-code-question-email.txt", {
                        "site": settings.RELATE_BASE_URL,
                        "page_id": self.page_desc.id,
                        "course": page_context.course,
                        "error_message": error_msg,
                        "review_uri": page_context.page_uri,
                        "time": format_datetime_local(local_now())
                    })

                if (
                        not page_context.in_sandbox
                        and not is_nuisance_failure(response_dict)):
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

                        from relate.utils import get_outbound_mail_connection
                        msg.connection = get_outbound_mail_connection("robot")
                        msg.send()

                    except Exception:
                        from traceback import format_exc
                        feedback_bits.append(
                            str(string_concat(
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

        if hasattr(self.page_desc, "correct_code"):
            def normalize_code(s):
                return (s
                        .replace(" ", "")
                        .replace("\r", "")
                        .replace("\n", "")
                        .replace("\t", ""))

            if (normalize_code(user_code)
                    == normalize_code(self.page_desc.correct_code)):
                feedback_bits.append(
                        "<p><b>%s</b></p>"
                        % _("It looks like you submitted code that is identical to "
                            "the reference solution. This is not allowed."))

        from relate.utils import dict_to_struct
        response = dict_to_struct(response_dict)

        bulk_feedback_bits = []

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
            raise RuntimeError("invalid run result: %s" % response.result)

        if hasattr(response, "feedback") and response.feedback:
            def sanitize(s):
                import bleach
                return bleach.clean(s, tags=["p", "pre"])
            feedback_bits.append("".join([
                "<p>",
                _("Here is some feedback on your code"),
                ":"
                "<ul>%s</ul></p>"]) %
                        "".join(
                            "<li>%s</li>" % sanitize(fb_item)
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
                exec_host_name, _dummy, _dummy = socket.gethostbyaddr(
                        response.exec_host)
            except OSError:
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

        # {{{ html output / sanitization

        if hasattr(response, "html") and response.html:
            if (page_context.course is None
                    or not page_context.course.trusted_for_markup):
                bulk_feedback_bits.extend(
                        sanitize_from_code_html(snippet)
                        for snippet in response.html)
            else:
                bulk_feedback_bits.extend(response.html)

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

        normalized_answer = self.get_code_from_answer_data(answer_data)

        from django.utils.html import escape
        return "<pre>%s</pre>" % escape(normalized_answer)

    def normalized_bytes_answer(self, page_context, page_data, answer_data):
        if answer_data is None:
            return None

        suffix = self.suffix
        return (suffix, self.get_code_from_answer_data(answer_data).encode("utf-8"))

# }}}


# {{{ python code question

class PythonCodeQuestion(CodeQuestion):
    """
    An auto-graded question allowing an answer consisting of Python code.
    All user code as well as all code specified as part of the problem
    is in Python 3.

    Example:

    .. code-block:: yaml

        type: PythonCodeQuestion
        id: addition
        access_rules:
            add_permissions:
                - change_answer
        value: 1
        timeout: 10
        prompt: |
            # Adding two numbers in Python
            Your code will receive two variables, *a* and *b*. Compute their sum and
            assign it to *c*.
        setup_code: |
            import random
            a = random.uniform(-10, 10)
            b = random.uniform(-10, 10)
        names_for_user: [a, b]

        correct_code: |
            c = a + b
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

    .. attribute:: is_optional_page

        |is-optional-page-attr|

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
        Code that will be run to determine the correctness of a
        student-provided solution. Will have access to variables in
        :attr:`names_from_user` (which will be *None*) if not provided. Should
        never raise an exception.

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

          feedback.call_user(f, *args, **kwargs)
          # Calls a user-supplied function and prints an appropriate
          # feedback message in case of failure.

    * ``data_files``: A dictionary mapping file names from :attr:`data_files`
      to :class:`bytes` instances with that file's contents.

    * ``user_code``: The user code being tested, as a string.
    """

    @property
    def language_mode(self):
        return "python"

    @property
    def container_image(self):
        return settings.RELATE_DOCKER_RUNPY_IMAGE

    @property
    def suffix(self):
        return ".py"

    def __init__(self, vctx, location, page_desc, language_mode="python"):
        super().__init__(vctx, location, page_desc,
        language_mode)

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

    Besides those defined in :class:`PythonCodeQuestion`, the
    following additional, allowed/required attribute are introduced:

    Supports automatic computation of point values from textual feedback.
    See :ref:`points-from-feedback`.

    .. attribute:: human_feedback_value

        Optional (deprecated).
        A number. The point value of the feedback component
        by the human grader (who will grade on a 0-100 scale,
        which is scaled to yield :attr:`human_feedback_value`
        at 100).

    .. attribute:: human_feedback_percentage

        Optional.
        A number. The percentage the feedback by the human
        grader takes in the overall grade. Noticing that
        either this attribute or :attr:`human_feedback_value`
        must be included. `

    .. attribute:: rubric

        Required.
        The grading guideline for this question (for the human-graded component
        of the question), in :ref:`markup`.
    """

    def __init__(self, vctx, location, page_desc):
        super().__init__(
                vctx, location, page_desc)

        if vctx is not None:
            if (
                    hasattr(self.page_desc, "human_feedback_value")
                    and hasattr(self.page_desc, "human_feedback_percentage")):
                raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("'human_feedback_value' and "
                          "'human_feedback_percentage' are not "
                          "allowed to coexist"))
                    % {"location": location}
                )
            if not (hasattr(self.page_desc, "human_feedback_value")
                    or hasattr(self.page_desc, "human_feedback_percentage")):
                raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("expecting either 'human_feedback_value' "
                          "or 'human_feedback_percentage', found neither."))
                    % {"location": location}
                )
            if hasattr(self.page_desc, "human_feedback_value"):
                vctx.add_warning(
                    location,
                    _("Used deprecated 'human_feedback_value' attribute--"
                      "use 'human_feedback_percentage' instead."))
                if self.page_desc.value == 0:
                    raise ValidationError("".join([
                        "%s: ",
                        _("'human_feedback_value' attribute is not allowed "
                          "if value of question is 0, use "
                          "'human_feedback_percentage' instead")])
                        % location)
                if self.page_desc.human_feedback_value > self.page_desc.value:
                    raise ValidationError("".join([
                        "%s: ",
                        _("human_feedback_value greater than overall "
                            "value of question")])
                        % location)
            if hasattr(self.page_desc, "human_feedback_percentage"):
                if not (
                        0 <= self.page_desc.human_feedback_percentage <= 100):
                    raise ValidationError("".join([
                        "%s: ",
                        _("the value of human_feedback_percentage "
                          "must be between 0 and 100")])
                        % location)

        if hasattr(self.page_desc, "human_feedback_value"):
            self.human_feedback_percentage = (
                self.page_desc.human_feedback_value * 100 / self.page_desc.value)
        else:
            self.human_feedback_percentage = (
                self.page_desc.human_feedback_percentage)

    def required_attrs(self):
        return (
            *super().required_attrs(),
            # value is otherwise optional, but we require it here
            ("value", (int, float)),
            )

    def allowed_attrs(self):
        return (
            *super().allowed_attrs(),
            ("human_feedback_value", (int, float)),
            ("human_feedback_percentage", (int, float)))

    def human_feedback_point_value(self, page_context, page_data):
        return self.page_desc.value * self.human_feedback_percentage / 100

    def grade(self, page_context, page_data, answer_data, grade_data):
        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback=_("No answer provided."))

        if grade_data is not None and not grade_data["released"]:
            grade_data = None

        code_feedback = PythonCodeQuestion.grade(self, page_context,
                page_data, answer_data, grade_data)

        human_points = self.human_feedback_point_value(page_context, page_data)
        code_points = self.page_desc.value - human_points

        correctness = None
        percentage = None
        if (code_feedback is not None
                and code_feedback.correctness is not None
                and grade_data is not None
                and grade_data["grade_percent"] is not None):
            code_feedback_percentage = 100 - self.human_feedback_percentage
            percentage = (
                    code_feedback.correctness * code_feedback_percentage

                    + grade_data["grade_percent"] / 100
                    * self.human_feedback_percentage
                    )
            correctness = percentage / 100
        elif (self.human_feedback_percentage == 100
                and grade_data is not None
                and grade_data["grade_percent"] is not None):
            correctness = grade_data["grade_percent"] / 100
            percentage = correctness * 100
        elif (self.human_feedback_percentage == 0
                and code_feedback.correctness is not None):
            correctness = code_feedback.correctness
            percentage = correctness * 100

        human_feedback_text = None

        human_feedback_points = None
        if grade_data is not None:
            assert grade_data["feedback_text"] is not None
            if grade_data["feedback_text"].strip():
                human_feedback_text = markup_to_html(
                        page_context, grade_data["feedback_text"])

            human_graded_percentage = grade_data["grade_percent"]
            if human_graded_percentage is not None:
                human_feedback_points = (human_graded_percentage/100.
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

# vim: foldmethod=marker
