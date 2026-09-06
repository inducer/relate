"""
Tests for the runcode script's single-shot stdin/stdout mode (used by
course.page.code.request_run_in_container, where the run request and
response are exchanged over 'docker exec' stdin/stdout rather than HTTP).
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    import socket


def _runcode_path():
    return os.path.abspath(os.path.join(
            os.path.dirname(__file__), os.pardir,
            "docker-image-run-py", "runcode"))


def _python_executable() -> str:
    python_executable = os.getenv("PY_EXE")
    if not python_executable:
        python_executable = sys.executable
    return python_executable


def _frame_request(json_req: bytes) -> bytes:
    # Mirror the framing used by
    # course.page.code.request_run_in_container.
    return f"{len(json_req)}\n".encode("ascii") + json_req


def _run_runcode(stdin_data: bytes, timeout: float = 60) -> bytes:
    proc = subprocess.run(
            [_python_executable(), _runcode_path(), "-s"],
            input=stdin_data,
            capture_output=True,
            timeout=timeout,
            check=False)

    assert proc.returncode == 0, (
            f"runcode exited with {proc.returncode}:\n"
            f"{proc.stderr.decode()}")

    return proc.stdout


def test_runcode_stdin_stdout_success():
    from course.page.code_run_backend import RunRequest, RunResponse

    run_req = RunRequest(
            user_code="c = 2.0 + 1",
            test_code=(
                "if not isinstance(c, float):\n"
                "    feedback.finish(0, 'Your computed c is not a float.')\n"
                "\n"
                "correct_c = 3\n"
                "rel_err = abs(correct_c-c)/abs(correct_c)\n"
                "\n"
                "if rel_err < 1e-7:\n"
                "    feedback.finish(1, 'Your computed c was correct.')\n"
                "else:\n"
                "    feedback.finish(0, 'Your computed c was incorrect.')\n"),
            names_from_user=["c"],
            )

    response_data = _run_runcode(_frame_request(
            run_req.model_dump_json().encode("utf-8")))

    response = RunResponse.model_validate_json(response_data)
    assert response.result == "success"
    assert response.points == 1
    assert "Your computed c was correct." in response.feedback


def test_runcode_stdin_stdout_user_error():
    from course.page.code_run_backend import RunRequest, RunResponse

    run_req = RunRequest(
            user_code="raise ValueError('boom')",
            test_code="pass",
            )

    response_data = _run_runcode(_frame_request(
            run_req.model_dump_json().encode("utf-8")))

    response = RunResponse.model_validate_json(response_data)
    assert response.result == "user_error"
    assert "ValueError" in (response.traceback or "")


def test_runcode_stdin_stdout_stdout_capture():
    from course.page.code_run_backend import RunRequest, RunResponse

    run_req = RunRequest(
            user_code="print('hello from user code')",
            test_code="pass",
            )

    response_data = _run_runcode(_frame_request(
            run_req.model_dump_json().encode("utf-8")))

    response = RunResponse.model_validate_json(response_data)
    assert response.result == "success"
    assert "hello from user code" in (response.stdout or "")


def test_runcode_stdin_stdout_bad_request():
    from course.page.code_run_backend import RunResponse

    # A length-prefixed request whose payload is not valid JSON.
    response_data = _run_runcode(b"4\n1234")

    response = RunResponse.model_validate_json(response_data)
    assert response.result == "uncaught_error"


# {{{ host-side protocol tests

def _read_framed_request(sock: socket.socket) -> bytes:
    """
    Read a length-prefixed run request, as sent by
    course.page.code.request_run_in_container.

    Return the request with its length prefix intact, exactly as it
    arrived (the 'daemon' passes it through to the container's stdin).
    """
    line = b""
    while not line.endswith(b"\n"):
        nxt = sock.recv(1)
        if not nxt:
            raise ConnectionError("connection closed while reading length")
        line += nxt

    data = b""
    n = int(line)
    while len(data) < n:
        nxt = sock.recv(n - len(data))
        if not nxt:
            raise ConnectionError("connection closed while reading request")
        data += nxt

    return line + data


class _FakeContainer:
    id = "fake-container"

    def __init__(self) -> None:
        self.killed = False

    def start(self) -> None:
        pass

    def kill(self) -> None:
        self.killed = True

    def remove(self, force: bool = False) -> None:  # pyright: ignore[reportUnusedParameter]
        pass


class _FakeDockerCnx:
    """
    Emulates the Docker daemon's side of a hijacked 'exec' connection:
    the exec'd runcode process is run locally, and its stdout is
    delivered to the client as (multiplexed) frames.
    """

    def __init__(self, client_sock: socket.socket, server_sock: socket.socket,
            *, hang: bool = False) -> None:
        import threading

        self._client_sock = client_sock
        self._server_sock = server_sock
        self._hang = hang
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._daemon_side,
                                        daemon=True)

    def start(self) -> None:
        self._thread.start()

    def join(self) -> None:
        self._thread.join(timeout=30)

    def request_stop(self) -> None:
        # Emulate the daemon dropping the connection (e.g. because the
        # container was killed).
        self._stop.set()

    def _daemon_side(self) -> None:
        import struct
        import subprocess

        try:
            req = _read_framed_request(self._server_sock)

            if self._hang:
                # Emulate a hung run: never respond. Wait until
                # request_stop() is called, then drop the connection.
                while not self._stop.wait(0.2):
                    pass
                return

            proc = subprocess.run(
                    [_python_executable(), _runcode_path(), "-s"],
                    input=req,
                    capture_output=True,
                    timeout=60,
                    check=False)

            self._server_sock.sendall(
                    struct.pack(">BxxxL", 1, len(proc.stdout)) + proc.stdout)
        finally:
            self._server_sock.close()

    # The following emulate the docker-py API.

    @property
    def api(self):
        return self

    def exec_create(self, container_id: str, cmd: list[str],
            **kwargs: Any) -> dict[str, Any]:
        assert container_id == _FakeContainer.id
        assert cmd == ["/opt/runcode/runcode", "-s"]
        assert kwargs == {"stdin": True, "stdout": True, "stderr": True}
        return {"Id": "fake-exec"}

    def exec_start(self, exec_id: str, socket: bool = True):  # pyright: ignore[reportUnusedParameter]
        class _FakeRawSocket:
            # Emulate the read-only file-like wrapper that docker-py
            # returns on unix/TCP transports.
            _sock = self._client_sock

            def close(self) -> None:
                self._sock.close()

        return _FakeRawSocket()


def test_request_run_in_container_success():
    import socket as pysocket

    from course.page import code as code_page
    from course.page.code_run_backend import RunRequest

    client_sock, server_sock = pysocket.socketpair()

    cnx = _FakeDockerCnx(client_sock, server_sock)
    cnx.start()

    try:
        run_req = RunRequest(
                user_code="c = 2.0 + 1",
                test_code=(
                    "if not isinstance(c, float):\n"
                    "    feedback.finish(0, 'Your computed c is not a float.')\n"
                    "\n"
                    "correct_c = 3\n"
                    "rel_err = abs(correct_c-c)/abs(correct_c)\n"
                    "\n"
                    "if rel_err < 1e-7:\n"
                    "    feedback.finish(1, 'Your computed c was correct.')\n"
                    "else:\n"
                    "    feedback.finish(0, 'Your computed c was incorrect.')\n"),
                names_from_user=["c"],
                )

        result = code_page.request_run_in_container(
                cnx, _FakeContainer(), run_req, 30.0,
                command_path="/opt/runcode/runcode",
                debug_print=lambda s: None)
    finally:
        cnx.join()
        client_sock.close()

    assert result.result == "success"
    assert result.points == 1
    assert "Your computed c was correct." in result.feedback


def test_request_run_in_container_timeout():
    import socket as pysocket
    from unittest import mock

    from course.page import code as code_page
    from course.page.code_run_backend import RunRequest

    client_sock, server_sock = pysocket.socketpair()

    cnx = _FakeDockerCnx(client_sock, server_sock, hang=True)

    class _KillingContainer(_FakeContainer):
        def kill(self) -> None:
            super().kill()
            # Emulate the daemon dropping the connection when the
            # container is killed.
            cnx.request_stop()

    cnx.start()

    try:
        run_req = RunRequest(user_code="while True: pass")

        # Shrink the (module-global) startup allowance so that the
        # watchdog fires after a few seconds rather than ~16.
        with mock.patch.object(code_page, "DOCKER_TIMEOUT", 2):
            result = code_page.request_run_in_container(
                    cnx, _KillingContainer(), run_req, 1.0,
                    command_path="/opt/runcode/runcode",
                    debug_print=lambda s: None)
    finally:
        cnx.join()
        client_sock.close()

    assert result.result == "timeout"

# }}}
