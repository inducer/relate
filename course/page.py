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

from course.validation import validate_struct, ValidationError, validate_markup
from course.content import remove_prefix
from django.utils.safestring import mark_safe
import django.forms as forms

from codemirror import CodeMirrorTextarea
from courseflow.utils import StyledForm

import re
import sys


__doc__ = """

.. autoclass:: PageBase
.. autoclass:: AnswerFeedback
.. autoclass:: PageContext

"""


class PageContext(object):
    """
    .. attribute:: course
    .. attribute:: repo
    .. attribute:: commit_sha

    Note that this is different from :class:`course.utils.FlowPageContext`,
    which is used internally by the flow views.
    """

    def __init__(self, course, repo, commit_sha):
        self.course = course
        self.repo = repo
        self.commit_sha = commit_sha


def markup_to_html(page_context, text):
    from course.content import markup_to_html

    return markup_to_html(
            page_context.course,
            page_context.repo,
            page_context.commit_sha,
            text)


# {{{ answer feedback type

class NoNormalizedAnswerAvailable(object):
    pass


def get_auto_feedback(correctness):
    if correctness == 0:
        return "Your answer is not correct."
    elif correctness == 1:
        return "Your answer is correct."
    elif correctness > 0.5:
        return "Your answer is mostly correct. (%.1f %%)" \
                % (100*correctness)
    elif correctness is None:
        return "The correctness of your answer could not be determined."
    else:
        return "Your answer is somewhat correct. (%.1f %%)" \
                % (100*correctness)


class AnswerFeedback(object):
    """
    .. attribute:: correctness

        A :class:`float` between 0 and 1 (inclusive),
        indicating the degree of correctness of the
        answer. May be *None*.

    .. attribute:: correct_answer

        Text (as a full sentence) describing the correct answer.

    .. attribute:: feedback

        Text (at least as a full sentence, or even multi-paragraph HTML)
        providing feedback to the student about the provided answer. Should not
        reveal the correct answer.

        May be None, in which case generic feedback
        is generated from :attr:`correctness`.

    .. attribute:: normalized_answer

        An HTML-formatted answer to be shown in analytics,
        or a :class:`NoNormalizedAnswerAvailable`, or *None*
        if no answer was provided.
    """

    def __init__(self, correctness, correct_answer, feedback=None,
            normalized_answer=NoNormalizedAnswerAvailable()):
        if correctness is not None:
            if correctness < 0 or correctness > 1:
                raise ValueError("Invalid correctness value")

        if feedback is None:
            feedback = get_auto_feedback(correctness)

        self.correctness = correctness
        self.correct_answer = correct_answer
        self.feedback = feedback
        self.normalized_answer = normalized_answer

    def as_json(self):
        result = {
                "correctness": self.correctness,
                "correct_answer": self.correct_answer,
                "feedback": self.feedback,
                }

        if not isinstance(self.normalized_answer, NoNormalizedAnswerAvailable):
            result["normalized_answer"] = self.normalized_answer

        return result

    @staticmethod
    def from_json(json):
        return AnswerFeedback(
                correctness=json["correctness"],
                correct_answer=json["correct_answer"],
                feedback=json["feedback"],
                normalized_answer=json.get("normalized_answer",
                    NoNormalizedAnswerAvailable())
                )

# }}}


# {{{ abstract page base class

class PageBase(object):
    """The abstract interface of a flow page.

    .. attribute:: location

        A string 'location' for reporting errors.

    .. attribute:: id

        The page identifier.

    .. automethod:: make_page_data
    .. automethod:: title
    .. automethod:: body
    .. automethod:: expects_answer
    .. automethod:: max_points
    .. automethod:: answer_data
    .. automethod:: make_form
    .. automethod:: post_form
    .. automethod:: grade
    """

    def __init__(self, vctx, location, id):
        """
        :arg vctx: a :class:`course.validation.ValidationContext`, or None
            if no validation is desired
        """

        self.location = location
        self.id = id

    def make_page_data(self):
        """Return (possibly randomly generated) data that is used to generate
        the content on this page. This is passed to methods below as the *page_data*
        argument. One possible use for this argument would be a random permutation
        of choices that is generated once (at flow setup) and then used whenever
        this page is shown.
        """
        return {}

    def title(self, page_context, page_data):
        """Return the (non-HTML) title of this page."""

        raise NotImplementedError()

    def body(self, page_context, page_data):
        """Return the (HTML) body of the page."""

        raise NotImplementedError()

    def expects_answer(self):
        """
        :return: a :class:`bool` indicating whether this page lets the
            user provide an answer of some type.
        """
        raise NotImplementedError()

    def max_points(self, page_data):
        """
        :return: a :class:`int` or :class:`float` indicating how many points
            are achievable on this page.
        """
        raise NotImplementedError()

    def answer_data(self, page_context, page_data, form):
        raise NotImplementedError()
        """Return a JSON-persistable object reflecting the user's answer on the
        form. This will be passed to methods below as *answer_data*.
        """

    def make_form(self, page_context, page_data,
            answer_data, answer_is_final):
        """
        :arg answer_data: value returned by :meth:`answer_data`.
             May be *None*.
        :return: a tuple (form, form_html), where *form* is a
            :class:`django.forms.Form` instance with *answer_data* prepopulated.
            If *answer_is_final* is *True*, the form should be read-only.

            *form_html* is the HTML of the rendered form. If *None*, the form
            will automatically be rendered using
            :func:`crispy_forms.utils.render_crispy_form`.
        """

        raise NotImplementedError()

    def post_form(self, page_context, page_data, post_data, files_data):
        """Return a form with the POST response from *post_data* and *files_data*
        filled in.

        :return: a tuple (form, form_html), where *form* is a
            :class:`django.forms.Form` instance with *answer_data* prepopulated.
            If *answer_is_final* is *True*, the form should be read-only.

            *form_html* is the HTML of the rendered form. It should not include
            a ``<form>`` HTML tag or a Django CSRF token. If *None*, the form
            will automatically be rendered using
            :func:`crispy_forms.utils.render_crispy_form`.
        """
        raise NotImplementedError()

    def grade(self, page_context, page_data, answer_data, grade_data):
        """Grade the answer contained in *answer_data*.

        :arg answer_data: value returned by :meth:`answer_data`,
            or *None*, which means that no answer was supplied.
        :arg grade_data: is a (currently unimplemented) interface to
            feed in persisted information from deferred/human grading.
        :return: a :class:`AnswerFeedback` instanstance, or *None* if the
            grade is not yet available.
        """

        raise NotImplementedError()

# }}}


class Page(PageBase):
    """A page showing static content."""

    def __init__(self, vctx, location, page_desc):
        validate_struct(
                location,
                page_desc,
                required_attrs=[
                    ("type", str),
                    ("id", str),
                    ("content", str),
                    ("title", str),
                    ],
                allowed_attrs=[],
                )

        PageBase.__init__(self, vctx, location, page_desc.id)
        self.page_desc = page_desc

        if vctx is not None:
            validate_markup(vctx, location, page_desc.content)

    def title(self, page_context, page_data):
        return self.page_desc.title

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.content)

    def expects_answer(self):
        return False


# {{{ text question

class TextAnswerForm(StyledForm):
    answer = forms.CharField(required=True)

    def __init__(self, matchers, *args, **kwargs):
        super(TextAnswerForm, self).__init__(*args, **kwargs)

        self.matchers = matchers

        self.fields["answer"].widget.attrs["autofocus"] = None

    def clean(self):
        cleaned_data = super(TextAnswerForm, self).clean()

        answer = cleaned_data.get("answer", "")
        for matcher in self.matchers:
            matcher.validate(answer)


# {{{ matchers

class TextAnswerMatcher(object):
    """Abstract interface for matching text answers.

    .. attribute:: prefix
    .. attribute:: is_case_sensitive
    """

    def __init__(self, location, pattern):
        pass

    def validate(self, s):
        """Called to validate form input against simple input mistakes.

        Should raise :exc:`django.forms.ValidationError` on error.
        """

        pass

    def grade(self, s):
        raise NotImplementedError()

    def correct_answer_text(self):
        """May return *None* if not known."""
        raise NotImplementedError()


class CaseSensitivePlainMatcher(TextAnswerMatcher):
    prefix = "case_sens_plain"
    is_case_sensitive = True

    def __init__(self, location, pattern):
        self.pattern = pattern

    def grade(self, s):
        return int(self.pattern == s)

    def correct_answer_text(self):
        return self.pattern


class PlainMatcher(CaseSensitivePlainMatcher):
    prefix = "plain"
    is_case_sensitive = False

    def grade(self, s):
        return int(self.pattern.lower() == s.lower())


class RegexMatcher(TextAnswerMatcher):
    prefix = "regex"
    re_flags = re.I
    is_case_sensitive = False

    def __init__(self, location, pattern):
        try:
            self.pattern = re.compile(pattern, self.re_flags)
        except:
            tp, e, _ = sys.exc_info()

            raise ValidationError("%s: regex '%s' did not compile: %s: %s"
                    % (location, pattern, tp.__name__, str(e)))

    def grade(self, s):
        match = self.pattern.match(s)
        if match is not None:
            return 1
        else:
            return 0

    def correct_answer_text(self):
        return None


class CaseSensitiveRegexMatcher(RegexMatcher):
    prefix = "case_sens_regex"
    re_flags = 0
    is_case_sensitive = True


def parse_sympy(s):
    if isinstance(s, unicode):
        # Sympy is not spectacularly happy with unicode function names
        s = s.encode()

    from pymbolic import parse
    from pymbolic.sympy_interface import PymbolicToSympyMapper

    # use pymbolic because it has a semi-secure parser
    return PymbolicToSympyMapper()(parse(s))


class SymbolicExpressionMatcher(TextAnswerMatcher):
    prefix = "sym_expr"
    is_case_sensitive = True

    def __init__(self, location, pattern):
        self.pattern = pattern

        try:
            self.pattern_sym = parse_sympy(pattern)
        except:
            tp, e, _ = sys.exc_info()
            raise ValidationError("%s: %s: %s"
                    % (location, tp.__name__, str(e)))

    def validate(self, s):
        try:
            parse_sympy(s)
        except:
            tp, e, _ = sys.exc_info()
            raise forms.ValidationError("%s: %s"
                    % (tp.__name__, str(e)))

    def grade(self, s):
        from sympy import simplify
        answer_sym = parse_sympy(s)

        if simplify(answer_sym - self.pattern_sym) == 0:
            return 1
        else:
            return 0

    def correct_answer_text(self):
        return self.pattern


TEXT_ANSWER_MATCHER_CLASSES = [
        CaseSensitivePlainMatcher,
        PlainMatcher,
        RegexMatcher,
        CaseSensitiveRegexMatcher,
        SymbolicExpressionMatcher,
        ]


MATCHER_RE = re.compile(r"^\<([a-zA-Z0-9_:.]+)\>(.*)$")
MATCHER_RE_2 = re.compile(r"^([a-zA-Z0-9_.]+):(.*)$")


def parse_matcher(vctx, location, answer):
    match = MATCHER_RE.match(answer)

    if match is not None:
        matcher_prefix = match.group(1)
        pattern = match.group(2)
    else:
        match = MATCHER_RE_2.match(answer)

        if match is None:
            raise ValidationError("%s: does not specify match type"
                    % location)

        matcher_prefix = match.group(1)
        pattern = match.group(2)

        if vctx is not None:
            vctx.add_warning(location, "uses deprecated 'matcher:answer' style")

    for matcher_class in TEXT_ANSWER_MATCHER_CLASSES:
        if matcher_class.prefix == matcher_prefix:
            return matcher_class(location, pattern)

    raise ValidationError("%s: unknown match type '%s'"
            % (location, matcher_prefix))

# }}}


class TextQuestion(PageBase):
    def __init__(self, vctx, location, page_desc):
        validate_struct(
                location,
                page_desc,
                required_attrs=[
                    ("type", str),
                    ("id", str),
                    ("value", (int, float)),
                    ("title", str),
                    ("answers", list),
                    ("prompt", str),
                    ],
                allowed_attrs=[],
                )

        if len(page_desc.answers) == 0:
            raise ValidationError("%s: at least one answer must be provided"
                    % location)

        self.matchers = [
                parse_matcher(
                    vctx,
                    "%s, answer %d" % (location, i+1),
                    answer)
                for i, answer in enumerate(page_desc.answers)]

        if not any(matcher.correct_answer_text() is not None
                for matcher in self.matchers):
            raise ValidationError("%s: no matcher is able to provide a plain-text "
                    "correct answer")

        if vctx is not None:
            validate_markup(vctx, location, page_desc.prompt)

        PageBase.__init__(self, vctx, location, page_desc.id)
        self.page_desc = page_desc

    def title(self, page_context, page_data):
        return self.page_desc.title

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    def expects_answer(self):
        return True

    def max_points(self, page_data):
        return self.page_desc.value

    def make_form(self, page_context, page_data,
            answer_data, answer_is_final):
        if answer_data is not None:
            answer = {"answer": answer_data["answer"]}
            form = TextAnswerForm(self.matchers, answer)
        else:
            answer = None
            form = TextAnswerForm(self.matchers)

        if answer_is_final:
            form.fields['answer'].widget.attrs['readonly'] = True

        return (form, None)

    def post_form(self, page_context, page_data, post_data, files_data):
        return (TextAnswerForm(self.matchers, post_data, files_data), None)

    def answer_data(self, page_context, page_data, form):
        return {"answer": form.cleaned_data["answer"].strip()}

    def grade(self, page_context, page_data, answer_data, grade_data):
        CA_PATTERN = "A correct answer is: '%s'."

        for matcher in self.matchers:
            unspec_correct_answer_text = matcher.correct_answer_text()
            if unspec_correct_answer_text is not None:
                break

        assert unspec_correct_answer_text

        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback="No answer provided.",
                    correct_answer=CA_PATTERN % unspec_correct_answer_text)

        answer = answer_data["answer"]

        correctness, correct_answer_text = max(
                (matcher.grade(answer), matcher.correct_answer_text())
                for matcher in self.matchers)

        if correct_answer_text is None:
            correct_answer_text = unspec_correct_answer_text

        normalized_answer = answer
        if not any(matcher.is_case_sensitive for matcher in self.matchers):
            normalized_answer = normalized_answer.lower()

        return AnswerFeedback(
                correctness=correctness,
                correct_answer=CA_PATTERN % correct_answer_text,
                normalized_answer=normalized_answer)

# }}}


# {{{ choice question

class ChoiceAnswerForm(StyledForm):
    def __init__(self, field, *args, **kwargs):
        super(ChoiceAnswerForm, self).__init__(*args, **kwargs)

        self.fields["choice"] = field


class ChoiceQuestion(PageBase):
    CORRECT_TAG = "~CORRECT~"

    @classmethod
    def process_choice_string(cls, page_context, s):
        s = remove_prefix(cls.CORRECT_TAG, s)
        s = markup_to_html(page_context, s)
        # allow HTML in option
        s = mark_safe(s)

        return s

    def __init__(self, vctx, location, page_desc):
        validate_struct(
                location,
                page_desc,
                required_attrs=[
                    ("type", str),
                    ("id", str),
                    ("value", (int, float)),
                    ("title", str),
                    ("choices", list),
                    ("prompt", str),
                    ],
                allowed_attrs=[
                    ("shuffle", bool),
                    ],
                )

        correct_choice_count = 0
        for choice in page_desc.choices:
            if choice.startswith(self.CORRECT_TAG):
                correct_choice_count += 1

            if vctx is not None:
                validate_markup(vctx, location,
                        remove_prefix(self.CORRECT_TAG, choice))

        if correct_choice_count < 1:
            raise ValidationError("%s: one or more correct answer(s) "
                    "expected, %d found" % (location, correct_choice_count))

        if vctx is not None:
            validate_markup(vctx, location, page_desc.prompt)

        PageBase.__init__(self, vctx, location, page_desc.id)
        self.page_desc = page_desc
        self.shuffle = getattr(self.page_desc, "shuffle", False)

    def title(self, page_context, page_data):
        return self.page_desc.title

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    def expects_answer(self):
        return True

    def max_points(self, page_data):
        return self.page_desc.value

    def make_page_data(self):
        import random
        perm = range(len(self.page_desc.choices))
        if self.shuffle:
            random.shuffle(perm)

        return {"permutation": perm}

    def make_choice_form(self, page_context, page_data, *args, **kwargs):
        permutation = page_data["permutation"]

        choices = tuple(
                (i,  self.process_choice_string(
                    page_context, self.page_desc.choices[src_i]))
                for i, src_i in enumerate(permutation))

        return ChoiceAnswerForm(
            forms.TypedChoiceField(
                choices=tuple(choices),
                coerce=int,
                widget=forms.RadioSelect()),
            *args, **kwargs)

    def make_form(self, page_context, page_data,
            answer_data, answer_is_final):
        if answer_data is not None:
            form_data = {"choice": answer_data["choice"]}
            form = self.make_choice_form(page_context, page_data, form_data)
        else:
            form = self.make_choice_form(page_context, page_data)

        if answer_is_final:
            form.fields['choice'].widget.attrs['disabled'] = True

        return (form, None)

    def post_form(self, page_context, page_data, post_data, files_data):
        return (
                self.make_choice_form(
                    page_context, page_data, post_data, files_data),
                None)

    def answer_data(self, page_context, page_data, form):
        return {"choice": form.cleaned_data["choice"]}

    def grade(self, page_context, page_data, answer_data, grade_data):
        unpermuted_correct_indices = []
        for i, choice_text in enumerate(self.page_desc.choices):
            if choice_text.startswith(self.CORRECT_TAG):
                unpermuted_correct_indices.append(i)

        correct_answer_text = ("A correct answer is:%s"
                % self.process_choice_string(
                    page_context,
                    self.page_desc.choices[unpermuted_correct_indices[0]]).lstrip())

        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback="No answer provided.",
                    correct_answer=correct_answer_text,
                    normalized_answer=None)

        permutation = page_data["permutation"]
        choice = answer_data["choice"]

        if permutation[choice] in unpermuted_correct_indices:
            correctness = 1
        else:
            correctness = 0

        return AnswerFeedback(correctness=correctness,
                correct_answer=correct_answer_text,
                normalized_answer=self.process_choice_string(
                    page_context,
                    self.page_desc.choices[permutation[choice]]))

# }}}


# {{{ python code question

class PythonCodeForm(StyledForm):
    def __init__(self, read_only, *args, **kwargs):
        super(PythonCodeForm, self).__init__(*args, **kwargs)

        self.fields["answer"] = forms.CharField(required=True,
            widget=CodeMirrorTextarea(
                mode="python",
                theme="default",
                config={
                    "fixedGutter": True,
                    "indentUnit": 4,
                    "readOnly": read_only,
                    }))

    def clean(self):
        # FIXME Should try compilation
        pass


CFRUNPY_PORT = 9941


class InvalidPingResponse(RuntimeError):
    pass


def request_python_run(run_req, run_timeout):
    import json
    import httplib
    from django.conf import settings
    import docker
    import socket
    import errno
    from httplib import BadStatusLine

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

        dresult = docker_cnx.create_container(
                image=settings.CF_DOCKER_CFRUNPY_IMAGE,
                command=["/opt/cfrunpy/cfrunpy", "-1"],
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
                from traceback import format_exc

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

            docker_cnx.stop(container_id, timeout=3)
            docker_cnx.remove_container(container_id)


class PythonCodeQuestion(PageBase):
    def __init__(self, vctx, location, page_desc):
        validate_struct(
                location,
                page_desc,
                required_attrs=[
                    ("type", str),
                    ("id", str),
                    ("value", (int, float)),
                    ("title", str),
                    ("prompt", str),
                    ("timeout", (int, float)),
                    ],
                allowed_attrs=[
                    ("setup_code", str),
                    ("names_for_user", list),
                    ("names_from_user", list),
                    ("test_code", str),
                    ("correct_code", str),
                    ],
                )

        if vctx is not None:
            validate_markup(vctx, location, page_desc.prompt)

        PageBase.__init__(self, vctx, location, page_desc.id)
        self.page_desc = page_desc

    def title(self, page_context, page_data):
        return self.page_desc.title

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    def expects_answer(self):
        return True

    def max_points(self, page_data):
        return self.page_desc.value

    def make_form(self, page_context, page_data,
            answer_data, answer_is_final):
        if answer_data is not None:
            answer = {"answer": answer_data["answer"]}
            form = PythonCodeForm(answer_is_final, answer)
        else:
            answer = None
            form = PythonCodeForm(answer_is_final)

        return (form, None)

    def post_form(self, page_context, page_data, post_data, files_data):
        return (PythonCodeForm(False, post_data, files_data), None)

    def answer_data(self, page_context, page_data, form):
        return {"answer": form.cleaned_data["answer"].strip()}

    def grade(self, page_context, page_data, answer_data, grade_data):
        from courseflow.utils import html_escape

        if hasattr(self.page_desc, "correct_code"):
            correct_answer = (
                    "The following code is a valid answer:<pre>%s</pre>"
                    % html_escape(self.page_desc.correct_code))
        else:
            correct_answer = ""

        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback="No answer provided.",
                    correct_answer=correct_answer,
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
                if key != "result" and val:
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
        elif response.result == "user_compile_error":
            feedback_bits.append(
                    "<p>Your code failed to compile. An error message is below.</p>")
        elif response.result == "user_error":
            feedback_bits.append(
                    "<p>Your code failed with an exception. "
                    "A traceback is below.</p>")
        else:
            raise RuntimeError("invalid cfrunpy result: %s" % response.result)

        if hasattr(response, "points"):
            correctness = response.points
            feedback_bits.append(
                    "<p><b>%s</b></p>"
                    % get_auto_feedback(correctness))
        else:
            correctness = None

        if hasattr(response, "feedback") and response.feedback:
            feedback_bits.append(
                    "<p>Here is some feedback on your code:"
                    "<ul>%s</ul></p>" % "".join(
                        "<li>%s</li>" % html_escape(fb_item)
                        for fb_item in response.feedback))
        if hasattr(response, "traceback") and response.traceback:
            feedback_bits.append(
                    "<p>This is the exception traceback:"
                    "<pre>%s</pre></p>" % html_escape(response.traceback))
            print repr(response.traceback)
        if hasattr(response, "stdout") and response.stdout:
            feedback_bits.append(
                    "<p>Your code printed the following output:<pre>%s</pre></p>"
                    % html_escape(response.stdout))
        if hasattr(response, "stderr") and response.stderr:
            feedback_bits.append(
                    "<p>Your code printed the following error messages:"
                    "<pre>%s</pre></p>" % html_escape(response.stderr))

        return AnswerFeedback(
                correctness=correctness,
                correct_answer=correct_answer,
                feedback="\n".join(feedback_bits))

# }}}


# vim: foldmethod=marker
