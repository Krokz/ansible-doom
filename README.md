# 🔨 ansible-doom

Entertaining Ansible chaos engineering, deploy ansible configurations by killing DOOM enemies.

This is a Python fork of [kubedoom](https://github.com/storax/kubedoom), forked from [dockerdoom](https://github.com/gideonred/dockerdoom), forked from  **`psdoom`**. 
Also taken a bit of inspiration from [terraform-doom](https://github.com/theobori/terraform-doom).

![In game ( NOT UPDATED )](./assets/in-game.png)

## ℹ️ Usage ( NOT UPDATED )

An example with the Terraform project in `./examples`. Feel free to **`terraform apply`** before or after running the Docker container, both will work. This is a special case using the `local` Terraform provider with files, if you want them to get deleted, you must bind a volume into the Docker container. Otherwise it will work, but only the Terraform resources are going to be destroyed.

The Terraform project directory must be bound at `/terraform` inside the container (like below).

```bash
docker run \
    -itd \
    --rm=true \
    --name ansible-doom \
    -p 5900:5900 \
    -v $PWD/examples:/doomsible \

```

Now you can play DOOM through a VNC client. Example with `vnclient`:

```bash
vncviewer viewer localhost:5900
```

The default password is `1234` and the default terraform version is `1.4.6`.

You can change them by building the image yourself:

```bash
docker buildx build .\
    -t ansible-doom \
    --build-arg VNC_PASSWORD=custom_password \
    --build-arg TERRAFORM_VERSION=version
```

## 🔎 Cheat codes

There are some useful cheat codes in-game:
- **`idkfa`**: Get a weapon on slot 5
- **`idspispopd`**: No clip (useful to reach the mobs)
