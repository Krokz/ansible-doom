from __future__ import annotations

import asyncio
import configparser
import logging
import os
import sys
import tempfile
from dataclasses import dataclass, field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ansible_doom")


@dataclass
class Config:
    socket_path: str = "/dockerdoom.socket"
    inventory_file: str = ""
    playbook_file: str = ""
    max_concurrent_deployments: int = 3

    def __post_init__(self) -> None:
        if not self.inventory_file:
            hosts_filename = os.environ.get("HOSTS_FILENAME", "hosts.ini")
            self.inventory_file = f"/doomsible/conf/{hosts_filename}"
        if not self.playbook_file:
            playbook_filename = os.environ.get("ANSIBLE_FILENAME", "ansible-playbook.yml")
            self.playbook_file = f"/doomsible/conf/{playbook_filename}"


@dataclass
class ServerState:
    deployed_hosts: set[str] = field(default_factory=set)
    host_map: dict[str, str] = field(default_factory=dict)

    def clear(self) -> None:
        self.deployed_hosts.clear()
        self.host_map.clear()


def _djb2_hash(name: str) -> str:
    """Reproduce the djb2 hash from pr_process.c for backward compatibility."""
    h = 5381
    for c in name.encode():
        h = ((h << 5) + h) + c
        h &= 0xFFFFFFFF  # keep within 32-bit range
    if h >= 0x80000000:
        h = 0x100000000 - h
    return str(h)


def get_hosts_from_inventory(inventory_file: str) -> list[str]:
    """
    Reads an Ansible inventory file and returns a list of hostnames.
    Supports INI format (skipping :vars sections) with a flat-file fallback.
    """
    config = configparser.ConfigParser(allow_no_value=True)
    config.optionxform = str

    try:
        config.read(inventory_file)
    except configparser.MissingSectionHeaderError:
        return _parse_flat_inventory(inventory_file)

    hosts: list[str] = []
    if config.sections():
        for section in config.sections():
            if ":vars" in section:
                continue
            for host in config.options(section):
                hostname = host.split()[0]
                hosts.append(hostname)
    else:
        return _parse_flat_inventory(inventory_file)
    return hosts


def _parse_flat_inventory(inventory_file: str) -> list[str]:
    """Parse a flat inventory file (one host per line, no INI sections)."""
    hosts: list[str] = []
    with open(inventory_file, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("["):
                hostname = line.split()[0]
                hosts.append(hostname)
    return hosts


def resolve_kill_target(token: str, state: ServerState) -> str | None:
    """
    Resolve a kill command token to an inventory hostname.
    With the C-side fix, token is already the hostname string.
    For backward compat, also check if it's a numeric hash and look it up.
    """
    if token in {h for h in state.host_map.values()}:
        return token

    if token in state.host_map:
        resolved = state.host_map[token]
        logger.info("Resolved hash %s to hostname %s", token, resolved)
        return resolved

    logger.warning("Kill target '%s' not found in host map; using as-is", token)
    return token


async def run_ansible_deployment(
    hostname: str, config: Config, state: ServerState
) -> None:
    """
    Creates a temporary inventory for a single host and runs ansible-playbook.
    """
    if hostname in state.deployed_hosts:
        logger.info("Deployment for %s already triggered, skipping", hostname)
        return

    semaphore = _get_semaphore(config)
    temp_inv_path: str | None = None
    async with semaphore:
        try:
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".ini") as temp_inv:
                temp_inv.write("[all]\n")
                temp_inv.write(f"{hostname}\n")
                temp_inv_path = temp_inv.name

            cmd = [
                "ansible-playbook",
                "-i", temp_inv_path,
                config.playbook_file,
                "--limit", hostname,
            ]
            logger.info("Starting deployment for %s", hostname)

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                logger.info("Deployment for %s succeeded:\n%s", hostname, stdout.decode())
                state.deployed_hosts.add(hostname)
            else:
                logger.error(
                    "Deployment for %s failed (code %d):\n%s",
                    hostname, process.returncode, stderr.decode(),
                )
        finally:
            if temp_inv_path:
                try:
                    os.remove(temp_inv_path)
                except OSError:
                    pass


_semaphores: dict[int, asyncio.Semaphore] = {}


def _get_semaphore(config: Config) -> asyncio.Semaphore:
    if config.max_concurrent_deployments not in _semaphores:
        _semaphores[config.max_concurrent_deployments] = asyncio.Semaphore(
            config.max_concurrent_deployments
        )
    return _semaphores[config.max_concurrent_deployments]


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    config: Config,
    state: ServerState,
) -> None:
    """
    Handles a connection on the UNIX socket.
    Protocol:
      - "list"            -> newline-separated host list
      - "kill <hostname>" -> trigger ansible deployment
      - "reload"          -> clear deployed hosts, re-read inventory
    """
    try:
        data = await reader.read(255)
        if not data:
            return

        message = data.decode("utf-8").strip()
        logger.info("Received command: %s", message)
        parts = message.split()
        if not parts:
            return

        command = parts[0].lower()

        if command == "list":
            hosts = get_hosts_from_inventory(config.inventory_file)
            state.host_map.clear()
            for h in hosts:
                state.host_map[_djb2_hash(h)] = h
                state.host_map[h] = h
            response = "\n".join(hosts) + "\n"
            writer.write(response.encode("utf-8"))
            await writer.drain()
        elif command == "kill" and len(parts) >= 2:
            token = parts[1]
            hostname = resolve_kill_target(token, state)
            if hostname:
                asyncio.create_task(run_ansible_deployment(hostname, config, state))
        elif command == "reload":
            state.clear()
            writer.write(b"Deployed hosts cleared.\n")
            await writer.drain()
            logger.info("Deployed hosts and host map cleared")
        else:
            writer.write(b"Unknown command\n")
            await writer.drain()
    except Exception:
        logger.exception("Error handling client")
    finally:
        writer.close()
        await writer.wait_closed()


async def monitor_process(
    cmd: list[str],
    name: str,
    env: dict[str, str] | None = None,
    forward_stderr: bool = False,
) -> None:
    """
    Starts a subprocess and restarts it if it terminates unexpectedly.
    When forward_stderr is True, the child's stderr is piped and
    logged line-by-line so it appears in ``docker logs``.
    """
    while True:
        logger.info("Starting %s...", name)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE if forward_stderr else asyncio.subprocess.DEVNULL,
            env=env,
        )
        if forward_stderr and proc.stderr:
            asyncio.create_task(_log_stream(proc.stderr, name))
        return_code = await proc.wait()
        logger.warning(
            "%s terminated with code %d, restarting in 5s...", name, return_code
        )
        await asyncio.sleep(5)


async def _log_stream(stream: asyncio.StreamReader, name: str) -> None:
    """Read lines from a subprocess stream and emit them via the logger."""
    while True:
        line = await stream.readline()
        if not line:
            break
        logger.info("[%s] %s", name, line.decode("utf-8", errors="replace").rstrip())


async def start_doom_environment() -> None:
    """
    Spawns Xvfb, x11vnc, and psDooM as monitored background tasks.
    """
    xvfb_cmd = ["/usr/bin/Xvfb", ":99", "-ac", "-screen", "0", "640x480x24"]
    asyncio.create_task(monitor_process(xvfb_cmd, "Xvfb"))
    await asyncio.sleep(2)

    x11vnc_cmd = [
        "x11vnc", "-geometry", "640x480", "-forever",
        "-usepw", "-create", "-display", ":99",
    ]
    asyncio.create_task(monitor_process(x11vnc_cmd, "x11vnc"))

    logger.info("Preparing to start DOOM...")
    env = os.environ.copy()
    env["DISPLAY"] = ":99"
    doom_cmd = [
        "/usr/local/games/psdoom", "-warp", "-E1M1",
        "-nomouse", "-iwad", "/doom1.wad",
    ]
    asyncio.create_task(monitor_process(doom_cmd, "DOOM", env=env, forward_stderr=True))

    await asyncio.sleep(2)
    logger.info("DOOM environment is running")


def validate_config(config: Config) -> None:
    """Check that required files exist before starting."""
    errors: list[str] = []
    if not os.path.isfile(config.inventory_file):
        errors.append(f"Inventory file not found: {config.inventory_file}")
    if not os.path.isfile(config.playbook_file):
        errors.append(f"Playbook file not found: {config.playbook_file}")
    if errors:
        for e in errors:
            logger.error(e)
        logger.error(
            "Mount your Ansible project to /doomsible/conf/ "
            "or set HOSTS_FILENAME / ANSIBLE_FILENAME env vars"
        )
        sys.exit(1)


async def main(config: Config | None = None) -> None:
    if config is None:
        config = Config()

    validate_config(config)

    state = ServerState()

    await start_doom_environment()

    if os.path.exists(config.socket_path):
        os.remove(config.socket_path)

    def client_handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> asyncio.coroutine:
        return handle_client(reader, writer, config, state)

    server = await asyncio.start_unix_server(client_handler, path=config.socket_path)
    logger.info("Server listening on %s", config.socket_path)

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server interrupted, shutting down")
