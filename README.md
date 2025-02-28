# 🔨 ansible-doom

Entertaining Ansible chaos engineering, deploy ansible configurations by killing DOOM enemies.

This is a Python fork of [kubedoom](https://github.com/storax/kubedoom), forked from [dockerdoom](https://github.com/gideonred/dockerdoom), forked from  **`psdoom`**.

Also taken great inspiration from [terraform-doom](https://github.com/theobori/terraform-doom).

![In game ( NOT UPDATED )](./assets/ansible-doom.png)

## ℹ️ Usage ( NOT UPDATED )

An example with the Ansible project in `examples` folder. This example is a special testing-only case using 10 Ansible hosts which are all defined to localhost, while the playbook itself only pings each host it is given..

The Ansible project directory ( **Must include `hosts.ini` & `playbook.yml` files** ) must be bound at `/doomsible/conf` inside the container (like below).

```bash
docker run \
    -itd \
    --rm=true \
    --name ansible-doom \
    -p 5900:5900 \
    -v $PWD/example:/doomsible/conf \

```

Now you can play DOOM through a VNC client. Example with `vnclient`:

```bash
vncviewer viewer localhost:5900
```

The default password is `1234`

You can change that by building the image yourself:

```bash
docker buildx build .\
    -t ansible-doom \
    --build-arg VNC_PASSWORD=custom_password \
```

## 🔎 Cheat codes

There are some useful cheat codes in-game:
- **`idkfa`**: Get a weapon on slot 5
- **`idspispopd`**: No clip (useful to reach the mobs)
