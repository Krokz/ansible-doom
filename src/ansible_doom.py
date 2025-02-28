import asyncio
import configparser
import tempfile
import os
import asyncio.subprocess

# Paths for config files and socket.
SOCKET_PATH = '/dockerdoom.socket'
INVENTORY_FILE = '/doomsible/conf/hosts.ini'         # Mounted inventory file (Ansible ini format)
PLAYBOOK_FILE = '/doomsible/conf/ansible-playbook.yml' # Mounted playbook file

async def get_hosts_from_inventory(inventory_file):
    """
    Reads the inventory file and returns a list of hosts,
    ignoring any sections with names containing ':vars'.
    """
    config = configparser.ConfigParser(allow_no_value=True)
    config.optionxform = str  # Preserve case
    config.read(inventory_file)
    hosts = []
    
    if config.sections():
        for section in config.sections():
            # Skip variable sections (e.g., "group:vars")
            if ':vars' in section:
                continue
            # Add each key in the section as a host.
            for host in config.options(section):
                hosts.append(host)
    else:
        # Fallback: treat each non-empty, non-comment line as a host.
        with open(inventory_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    hosts.append(line)
    return hosts

async def run_ansible_deployment(hostname):
    """
    Creates a temporary inventory file containing only the target host,
    then asynchronously invokes ansible-playbook with --limit to target that host.
    """
    # Create temporary inventory file content.
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_inv:
        temp_inv.write("[all]\n")
        temp_inv.write(f"{hostname}\n")
        temp_inv_path = temp_inv.name

    # The --limit flag targets a specific host, as an extra safety measure.
    cmd = [
        "ansible-playbook", "-i", temp_inv_path,
        PLAYBOOK_FILE, "--limit", hostname
    ]
    print(f"Starting ansible deployment for {hostname} using inventory {temp_inv_path}")
    
    # Launch ansible-playbook asynchronously.
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    
    if process.returncode == 0:
        print(f"Deployment for {hostname} succeeded:\n{stdout.decode()}")
    else:
        print(f"Deployment for {hostname} failed (code {process.returncode}):\n{stderr.decode()}")
    
    # Clean up the temporary inventory file.
    os.remove(temp_inv_path)

async def handle_client(reader, writer):
    """
    Handles an incoming connection on the UNIX socket.
    Expects commands in the form:
      - "list"              -> Respond with the list of hosts.
      - "kill <hostname>"   -> Asynchronously deploy to the specified host.
    """
    try:
        data = await reader.read(255)
        if not data:
            writer.close()
            await writer.wait_closed()
            return

        message = data.decode('utf-8').strip()
        print(f"Received command: {message}")
        parts = message.split()
        if not parts:
            writer.close()
            await writer.wait_closed()
            return

        command = parts[0].lower()

        if command == 'list':
            hosts = await get_hosts_from_inventory(INVENTORY_FILE)
            response = "\n".join(hosts) + "\n"
            writer.write(response.encode('utf-8'))
            await writer.drain()
        elif command == 'kill' and len(parts) >= 2:
            hostname = parts[1]
            # Start the deployment asynchronously.
            asyncio.create_task(run_ansible_deployment(hostname))
        else:
            writer.write(b"Unknown command\n")
            await writer.drain()
    except Exception as e:
        print(f"Error handling client: {e}")
    finally:
        writer.close()
        await writer.wait_closed()

async def start_doom_environment():
    """
    Spawns background processes for Xvfb, x11vnc, and DOOM.
    """
    # Start Xvfb
    print("Starting Xvfb...")
    xfvb_proc = await asyncio.create_subprocess_exec(
        "/usr/bin/Xvfb", ":99", "-ac", "-screen", "0", "640x480x24",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )
    # Wait a couple seconds to allow Xvfb to initialize.
    await asyncio.sleep(2)

    # Start x11vnc
    print("Starting x11vnc...")
    x11vnc_proc = await asyncio.create_subprocess_exec(
        "x11vnc", "-geometry", "640x480", "-forever", "-usepw", "-create", "-display", ":99",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )

    # Start DOOM (psdoom)
    print("Starting DOOM...")
    # Set the DISPLAY environment variable for DOOM.
    env = os.environ.copy()
    env["DISPLAY"] = ":99"
    doom_proc = await asyncio.create_subprocess_exec(
        "/usr/local/games/psdoom", "-warp", "-E1M1", "-nomouse", "-iwad", "/doom1.wad",
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )
    # Optionally, you could store these process handles if you need to manage them later.
    print("DOOM environment started.")

async def main():
    # Launch DOOM environment processes.
    await start_doom_environment()

    # Remove the socket file if it already exists.
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    # Start the UNIX socket server.
    server = await asyncio.start_unix_server(handle_client, path=SOCKET_PATH)
    print(f"Server listening on {SOCKET_PATH}")

    async with server:
        await server.serve_forever()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Server interrupted. Shutting down.")