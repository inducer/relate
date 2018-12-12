REST API
========

Data in RELATE can be accessed remotely and programmatically through a REST
API. To access the API, create an API token using functionality the
"Participant" menu.

An HTTP request like the following then suffices to access data::

    curl \
        -H "Authorization: Token 7_23acf8e6235ff332b186d6bc7848ce3a47c26991" \
        https://HOSTNAME/course/rsmp/api/v1/get-flow-sessions?flow_id=quiz-test

.. warning::

    RELATE uses plain text tokens for API authentication. Like passwords,
    transmitting tokens over plain HTTP is laughably insecure.

    DO NOT use RELATE's REST API via plain, unencrypted HTTP.

The following API endpoints exist:

* ``https://HOSTNAME/course/COURSE_IDENTIFIER/api/v1/get-flow-sessions?flow_id=FLOW_ID``

  Retrieves all flow sessions in a course for a given flow ID.

* ``https://HOSTNAME/course/COURSE_IDENTIFIER/api/v1/get-flow-session-content?flow_session_id=FSID``

  Retrieves all pages with answer and grade data for a given flow session with a numerical
  flow session ID ``FSID``. ``FSID`` can be obtained from ``get-flow-sessions``.

To see what data will be returned from these queries, examine the
`API source code <https://github.com/inducer/relate/blob/master/course/api.py>`_.
