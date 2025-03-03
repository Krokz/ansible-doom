import asyncio
import configparser
import tempfile
import os
import asyncio.subprocess

### GLOBALS ###

hosts_filename = os.environ.get('HOSTS_FILENAME', 'hosts.ini')
playbook_filename = os.environ.get('ANSIBLE_FILENAME', 'ansible-playbook.yml')

# Paths for config files and socket.
SOCKET_PATH = '/dockerdoom.socket'
INVENTORY_FILE = f'/doomsible/conf/{hosts_filename}'         # Mounted inventory file (Ansible ini format)
PLAYBOOK_FILE = f'/doomsible/conf/{playbook_filename}' # Mounted playbook file


deployment_semaphore = asyncio.Semaphore(3)

deployed_hosts = set()

################

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

    if hostname in deployed_hosts:
        print(f"Deployment for {hostname} already triggered. Ignoring subsequent kill.")
        return

    async with deployment_semaphore:
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
            deployed_hosts.add(hostname)
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
        elif command == 'reload':
            deployed_hosts.clear()
            writer.write(b"Deployed hosts cleared.\n")
            await writer.drain()
            print("Deployed hosts have been re-initialized.")
        else:
            writer.write(b"Unknown command\n")
            await writer.drain()
    except Exception as e:
        print(f"Error handling client: {e}")
    finally:
        writer.close()
        await writer.wait_closed()


async def monitor_process(cmd, name, env=None):
    """
    Starts a process with the given command and monitors it.
    If the process terminates unexpectedly, it waits 5 seconds and tries restarting it.
    """
    while True:
        print(f"Starting {name}...")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env=env
        )
        return_code = await proc.wait()
        print(f"{name} terminated unexpectedly with code {return_code}. Restarting in 5 seconds...")
        await asyncio.sleep(5)

async def start_doom_environment():
    """
    Spawns and monitors background processes for Xvfb (X virtual framebuffer), x11vnc (VNC client for x11), and DOOM.
    """
    # Start Xvfb
    xvfb_cmd = ["/usr/bin/Xvfb", ":99", "-ac", "-screen", "0", "640x480x24"]
    task_xvfb = asyncio.create_task(monitor_process(xvfb_cmd, "Xvfb"))
    
    # Give Xvfb time to initialize.
    await asyncio.sleep(2)
    
    # Start x11vnc
    x11vnc_cmd = ["x11vnc", "-geometry", "640x480", "-forever", "-usepw", "-create", "-display", ":99"]
    task_x11vnc = asyncio.create_task(monitor_process(x11vnc_cmd, "x11vnc"))
    
    # Start DOOM (psdoom)
    print("Preparing to start DOOM...")
    env = os.environ.copy()
    env["DISPLAY"] = ":99"
    doom_cmd = ["/usr/local/games/psdoom", "-warp", "-E1M1", "-nomouse", "-iwad", "/doom1.wad"]
    task_doom = asyncio.create_task(monitor_process(doom_cmd, "DOOM", env=env))
    
    # Optionally, wait a bit before returning to ensure everything is up.
    await asyncio.sleep(2)
    print("DOOM environment is running and being monitored.")

async def main():
    await start_doom_environment()

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