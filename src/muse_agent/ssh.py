"""Thin SSH runner: run musegadget commands on the remote gadget host."""

from __future__ import annotations

import shlex
import subprocess


class SSHError(RuntimeError):
    """SSH failed (connection, auth, or remote command error)."""

    def __init__(self, message: str, returncode: int | None = None):
        super().__init__(message)
        self.returncode = returncode


def run_ssh(
    host: str,
    remote_args: list[str],
    *,
    timeout: int,
    connect_timeout: int = 10,
    stdin_text: str | None = None,
) -> str:
    """Run ``ssh host -- <remote_args>`` and return stdout.

    ``stdin_text`` is forwarded to the remote command's stdin.
    Raises SSHError on connection failure or non-zero exit (exit 3 kept as-is
    by callers that treat "no answer" separately).
    """
    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={connect_timeout}",
        "-o", "StrictHostKeyChecking=accept-new",
        host,
        "--",
        *remote_args,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            input=stdin_text,
            timeout=timeout + connect_timeout + 5,
        )
    except FileNotFoundError as exc:
        raise SSHError("ssh binary not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise SSHError(f"ssh timed out after {timeout + connect_timeout + 5}s: {shlex.join(remote_args[:3])} …") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        hint = detail[-1] if detail else f"exit {proc.returncode}"
        raise SSHError(f"remote command failed: {hint}", proc.returncode)
    return proc.stdout


def remote_quote(args: list[str]) -> str:
    return " ".join(shlex.quote(a) for a in args)
