"""
Shell Executor Module - Handles shell command execution with comprehensive logging
"""

import os
import subprocess
import time
import logging
import threading
from pathlib import Path
import shlex

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Known-harmless stderr noise filter
# ----------------------------------------------------------------------
# Some tools emit "error:" lines on stderr even when the command succeeded
# (e.g. pacman post-transaction hooks failing inside containers because
# systemd is not PID 1). When the process exit code is 0 and the *only*
# non-warning content on stderr consists of lines from this set, we treat
# the output as clean and log it at DEBUG level.
_HARMLESS_STDERR_LINES = frozenset({
    "error: command failed to execute correctly",  # pacman hook failure summary
})


def _is_harmless_stderr(stderr: str) -> bool:
    """
    Return True if stderr contains only:
      - empty lines
      - lines starting with 'warning:'
      - lines exactly matching a known-harmless entry

    Used together with returncode == 0 to downgrade log noise.
    """
    if not stderr:
        return True
    for line in stderr.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("warning:"):
            continue
        if stripped in _HARMLESS_STDERR_LINES:
            continue
        return False
    return True


class ShellExecutor:
    """Handles shell command execution with comprehensive logging and timeout"""

    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode

    def _run_streaming(self, actual_cmd, actual_shell, env, actual_cwd, timeout):
        """
        Run a command with streaming output: every line of stdout/stderr
        is logged immediately as it appears, while still being buffered
        for the caller's return value (CompletedProcess).

        This makes long-running builds observable in CI logs — you can
        distinguish "still compiling" from "stalled on something".

        Only supported for shell=True commands. Raises TimeoutExpired on
        timeout (caller handles).
        """
        process = subprocess.Popen(
            actual_cmd,
            shell=actual_shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
            cwd=actual_cwd,
        )

        stdout_lines = []
        stderr_lines = []

        def read_stream(pipe, lines, stream_name):
            try:
                for line in iter(pipe.readline, ''):
                    if not line:
                        break
                    lines.append(line)
                    stripped = line.rstrip('\n')
                    if stripped:
                        logger.info(f"[{stream_name}] {stripped}")
            except Exception as e:
                logger.warning(f"[{stream_name}] reader thread error: {e}")
            finally:
                try:
                    pipe.close()
                except Exception:
                    pass

        stdout_thread = threading.Thread(
            target=read_stream,
            args=(process.stdout, stdout_lines, 'STDOUT'),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=read_stream,
            args=(process.stderr, stderr_lines, 'STDERR'),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                process.kill()
            except Exception:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass

        # Give reader threads a moment to drain remaining buffered output
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

        stdout = ''.join(stdout_lines)
        stderr = ''.join(stderr_lines)

        if timed_out:
            raise subprocess.TimeoutExpired(
                cmd=actual_cmd if isinstance(actual_cmd, str) else ' '.join(actual_cmd),
                timeout=timeout,
                output=stdout,
                stderr=stderr,
            )

        return subprocess.CompletedProcess(
            args=actual_cmd,
            returncode=process.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    def run_command_with_retry(self, cmd, max_retries: int = 10, initial_delay: float = 2.0,
                             cwd=None, capture=True, check=True, shell=True, user=None,
                             log_cmd=False, timeout=1800, extra_env=None, retry_errors=None,
                             stream=False):
        """
        Run command with retry logic for transient failures.

        NEW: retries on TimeoutExpired as well (previously it propagated
        immediately and defeated the retry mechanism entirely).

        Args:
            cmd: Command to execute
            max_retries: Maximum number of retry attempts (default 10)
            initial_delay: Initial delay between retries (doubles each retry)
            retry_errors: List of error patterns to retry on (default: internal server errors)
            stream: If True, stream output line-by-line (requires shell=True)
            Other args: Same as run_command

        Returns:
            Command result
        """
        if retry_errors is None:
            retry_errors = ["500 Internal Server Error", "remote: Internal Server Error",
                           "fatal: the remote end hung up unexpectedly", "connection timed out",
                           "transfer closed with", "Connection reset by peer", "Recv failure",
                           "Operation too slow", "GnuTLS recv error", "OpenSSL SSL_read",
                           "HTTP/2 stream", "unexpected EOF", "error: failed retrieving file",
                           "==> ERROR: Failure while downloading", "failed to download sources"]

        last_exception = None
        delay = initial_delay

        for attempt in range(max_retries):
            if attempt > 0:
                logger.info(f"SRC_RETRY attempt={attempt}/{max_retries - 1} delay={delay:.1f}s")
                time.sleep(delay)
                delay *= 2  # Exponential backoff

            try:
                result = self.run_command(
                    cmd=cmd,
                    cwd=cwd,
                    capture=capture,
                    check=False,  # Don't raise on error for retry logic
                    shell=shell,
                    user=user,
                    log_cmd=log_cmd,
                    timeout=timeout,
                    extra_env=extra_env,
                    stream=stream,
                )

                # Check if we should retry based on output
                should_retry = False
                retry_reason = ""

                if result.returncode != 0:
                    # Check stderr for retryable errors
                    error_output = (result.stderr or "") + (result.stdout or "")
                    for error_pattern in retry_errors:
                        if error_pattern in error_output:
                            should_retry = True
                            retry_reason = error_pattern
                            break

                if not should_retry:
                    if check and result.returncode != 0:
                        # Final failure, raise exception
                        raise subprocess.CalledProcessError(
                            result.returncode, cmd, result.stdout, result.stderr
                        )
                    return result

                logger.warning(f"SRC_RETRY_REASON attempt={attempt} reason={retry_reason}")

                if attempt == max_retries - 1:
                    return result

            except subprocess.TimeoutExpired as e:
                # NEW: retry on timeout (previously not caught, so retries
                # silently never happened for timeout failures).
                if attempt == max_retries - 1:
                    logger.error(f"SRC_RETRY_EXHAUSTED reason=timeout attempts={max_retries}")
                    raise
                logger.warning(
                    f"SRC_RETRY_REASON attempt={attempt} reason=timeout timeout={timeout}s"
                )
                last_exception = e
                continue

            except subprocess.CalledProcessError as e:
                # Check if this is a retryable error
                error_output = (e.stderr or "") + (e.stdout or "")
                should_retry = False
                retry_reason = ""

                for error_pattern in retry_errors:
                    if error_pattern in error_output:
                        should_retry = True
                        retry_reason = error_pattern
                        break

                if not should_retry or attempt == max_retries - 1:
                    raise  # Re-raise non-retryable or final failure

                logger.warning(f"SRC_RETRY_REASON attempt={attempt} reason={retry_reason}")
                last_exception = e

        # Should never reach here
        raise last_exception or RuntimeError("Max retries exceeded")

    def _log_result(self, result, cmd):
        """
        Log a CompletedProcess result consistently.
        Downgrades harmless stderr noise to DEBUG when returncode == 0.
        """
        if self.debug_mode:
            if result.stdout:
                print(f"🔧 [SHELL DEBUG] STDOUT:\n{result.stdout}", flush=True)
            if result.stderr:
                print(f"🔧 [SHELL DEBUG] STDERR:\n{result.stderr}", flush=True)
            print(f"🔧 [SHELL DEBUG] EXIT CODE: {result.returncode}", flush=True)
            return

        if result.stdout:
            logger.info(f"STDOUT: {result.stdout[:500]}")

        if result.stderr:
            if result.returncode == 0 and _is_harmless_stderr(result.stderr):
                # Known-harmless noise (e.g. pacman hook failure in container)
                logger.debug(f"STDERR (harmless, suppressed): {result.stderr[:500]}")
            else:
                logger.info(f"STDERR: {result.stderr[:500]}")

        logger.info(f"EXIT CODE: {result.returncode}")

    def run_command(self, cmd, cwd=None, capture=True, check=True, shell=True, user=None,
                   log_cmd=False, timeout=1800, extra_env=None, stream=False):
        """
        Run command with comprehensive logging, timeout, and optional extra
        environment variables.

        If stream=True, output is logged line-by-line in real-time (useful
        for long-running builds where we want to distinguish a slow build
        from a stalled one). Streaming requires shell=True.
        """
        if log_cmd or self.debug_mode:
            if self.debug_mode:
                print(f"🔧 [SHELL DEBUG] RUNNING COMMAND: {cmd}", flush=True)
            else:
                logger.info(f"RUNNING COMMAND: {cmd}")

        if cwd is None:
            cwd = Path.cwd()

        # Prepare environment
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)

        # Build the actual command and its invocation context
        if user:
            env['HOME'] = f'/home/{user}'
            env['USER'] = user
            env['LC_ALL'] = 'C'

            if shell:
                env_prefix = ""
                if extra_env:
                    env_pairs = []
                    for k, v in extra_env.items():
                        env_pairs.append(f"{k}={shlex.quote(v)}")
                    if env_pairs:
                        env_prefix = "env " + " ".join(env_pairs) + " "

                actual_cmd = f'sudo -u {user} bash -c "cd {shlex.quote(str(cwd))} && {env_prefix}{cmd}"'
                actual_shell = True
                actual_cwd = None
            else:
                actual_cmd = ['sudo', '-u', user]
                actual_cmd.extend(cmd)
                actual_shell = False
                actual_cwd = None
        else:
            env['LC_ALL'] = 'C'
            actual_cmd = cmd
            actual_shell = shell
            actual_cwd = cwd

        # Streaming path (only for shell=True; list-form commands cannot
        # be run through a shell safely without re-quoting)
        if stream:
            if not actual_shell:
                logger.warning("STREAMING_FALLBACK shell=False -> buffered")
                stream = False
            else:
                try:
                    result = self._run_streaming(actual_cmd, actual_shell, env, actual_cwd, timeout)

                    # Debug output for streaming (full output already logged)
                    if result.returncode != 0 and self.debug_mode:
                        print(f"❌ [SHELL DEBUG] COMMAND FAILED: {cmd}", flush=True)

                    if check and result.returncode != 0:
                        raise subprocess.CalledProcessError(
                            result.returncode, cmd, result.stdout, result.stderr
                        )
                    return result

                except subprocess.TimeoutExpired:
                    error_msg = f"⚠️ Command timed out after {timeout} seconds: {cmd}"
                    if self.debug_mode:
                        print(f"❌ [SHELL DEBUG] {error_msg}", flush=True)
                    logger.error(error_msg)
                    raise

                except subprocess.CalledProcessError:
                    if self.debug_mode:
                        print(f"❌ [SHELL DEBUG] COMMAND FAILED: {cmd}", flush=True)
                    raise

        # Non-streaming (original) path
        try:
            result = subprocess.run(
                actual_cmd,
                shell=actual_shell,
                capture_output=capture,
                text=True,
                check=check,
                env=env,
                cwd=actual_cwd,
                timeout=timeout,
            )

            # Logging is centralized; harmless stderr is downgraded to DEBUG
            if log_cmd or self.debug_mode:
                self._log_result(result, cmd)

            # If command failed and we're in debug mode, print full output
            if result.returncode != 0 and self.debug_mode:
                print(f"❌ [SHELL DEBUG] COMMAND FAILED: {cmd}", flush=True)
                if result.stdout and len(result.stdout) > 500:
                    print(f"❌ [SHELL DEBUG] FULL STDOUT (truncated):\n{result.stdout[:2000]}", flush=True)
                if result.stderr and len(result.stderr) > 500:
                    print(f"❌ [SHELL DEBUG] FULL STDERR (truncated):\n{result.stderr[:2000]}", flush=True)

            return result

        except subprocess.TimeoutExpired as e:
            error_msg = f"⚠️ Command timed out after {timeout} seconds: {cmd}"
            if self.debug_mode:
                print(f"❌ [SHELL DEBUG] {error_msg}", flush=True)
            logger.error(error_msg)
            raise

        except subprocess.CalledProcessError as e:
            if log_cmd or self.debug_mode:
                error_msg = f"Command failed: {cmd}"
                if self.debug_mode:
                    print(f"❌ [SHELL DEBUG] {error_msg}", flush=True)
                    if hasattr(e, 'stdout') and e.stdout:
                        print(f"❌ [SHELL DEBUG] EXCEPTION STDOUT:\n{e.stdout}", flush=True)
                    if hasattr(e, 'stderr') and e.stderr:
                        print(f"❌ [SHELL DEBUG] EXCEPTION STDERR:\n{e.stderr}", flush=True)
                else:
                    logger.error(error_msg)
            if check:
                raise
            return e