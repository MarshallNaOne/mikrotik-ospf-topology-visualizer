"""SSH client to connect to MikroTik RouterOS and fetch LSDB."""

from __future__ import annotations

import logging
from typing import Optional, Tuple
import paramiko

logger = logging.getLogger(__name__)


class MikroTikSSHClient:
    """Connects via SSH to MikroTik RouterOS and fetches LSA output."""

    DEFAULT_COMMAND = "/routing/ospf/lsa/print detail without-paging"

    def __init__(self):
        pass

    def fetch_lsa(
        self,
        host: str,
        port: int = 22,
        username: str = "admin",
        password: str = "",
        timeout: float = 15.0,
        command: str = DEFAULT_COMMAND
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Executes LSA print command over SSH.
        Returns: (success: bool, output_or_error_msg: str, sanitized_log: Optional[str])
        Password is never logged.
        """
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        log_msg = f"Connecting to {host}:{port} as user '{username}'"
        logger.info(log_msg)

        try:
            client.connect(
                hostname=host,
                port=port,
                username=username,
                password=password,
                timeout=timeout,
                allow_agent=False,
                look_for_keys=False,
                banner_timeout=timeout
            )

            logger.info("Executing command: %s", command)
            # MikroTik RouterOS 7 supports exec_command for '/routing/ospf/lsa/print detail without-paging'
            try:
                stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
                out = stdout.read().decode("utf-8", errors="replace")
                err = stderr.read().decode("utf-8", errors="replace")
            except Exception as ex:
                logger.warning("Standard exec_command threw %s, trying interactive channel...", ex)
                out, err = "", ""

            # If exec_command returned empty, use open_session with pty or invoke_shell
            if not out.strip():
                logger.info("Standard exec was empty, using interactive shell...")
                try:
                    shell = client.invoke_shell(term="vt100", width=300, height=1000)
                    shell.settimeout(timeout)
                    import time
                    time.sleep(0.5)
                    if shell.recv_ready():
                        shell.recv(65535)
                    shell.send(command + "\r\n")
                    time.sleep(1.0)
                    shell_chunks = []
                    start_t = time.time()
                    while time.time() - start_t < timeout:
                        if shell.recv_ready():
                            data = shell.recv(65535).decode("utf-8", errors="replace")
                            shell_chunks.append(data)
                            time.sleep(0.2)
                        elif shell_chunks:
                            time.sleep(0.4)
                            if not shell.recv_ready():
                                break
                        else:
                            time.sleep(0.1)
                    out = "".join(shell_chunks)
                except Exception as sh_ex:
                    logger.warning("Shell session threw %s", sh_ex)

            client.close()

            if not out.strip() and err:
                return False, f"Command execution error: {err}", log_msg

            return True, out, log_msg

        except paramiko.AuthenticationException:
            err = f"Authentication failed for user '{username}' on {host}:{port}."
            logger.error(err)
            return False, err, log_msg
        except paramiko.SSHException as e:
            err = f"SSH Protocol error connecting to {host}:{port}: {e}"
            logger.error(err)
            return False, err, log_msg
        except TimeoutError:
            err = f"Connection timed out while connecting to {host}:{port} ({timeout}s)."
            logger.error(err)
            return False, err, log_msg
        except Exception as e:
            err = f"Connection error: {e}"
            logger.error(err)
            return False, err, log_msg
        finally:
            try:
                client.close()
            except Exception:
                pass
