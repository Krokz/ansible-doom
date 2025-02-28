FROM ubuntu:22.04 AS build-doom

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -y && \
    apt-get install -y \
      build-essential \
      libsdl-mixer1.2-dev \
      libsdl-net1.2-dev \
      git \
      gcc \
      unzip \
      wget

# Copy dockerdoom locally (DOOM framework) and download the IWAD
COPY dockerdoom /dockerdoom
RUN wget http://distro.ibiblio.org/pub/linux/distributions/slitaz/sources/packages/d/doom1.wad

WORKDIR /dockerdoom/trunk
RUN ./configure && \
    make && \
    make install

######################################################################################################################    

FROM ubuntu:22.04 AS run-doom

ARG VNC_PASSWORD=1234
ENV DEBIAN_FRONTEND=noninteractive

# Install runtime dependencies: VNC server, virtual X (Xvfb), DOOM libraries, Python3, pip, and Ansible.
RUN apt-get update -y && \
    apt-get install -y \
      x11vnc \
      xvfb \
      libsdl-mixer1.2 \
      libsdl-net1.2 \
      netcat \
      python3 \
      ansible

# Copy the DOOM IWAD and DOOM binary (psdoom) from the build stage.
COPY --from=build-doom /doom1.wad /
COPY --from=build-doom /usr/local/games/psdoom /usr/local/games

# Setup a VNC password.
RUN mkdir /doomsible && \
    mkdir -p ~/.vnc && \
    x11vnc -storepasswd ${VNC_PASSWORD} ~/.vnc/passwd

WORKDIR /doomsible
COPY ./src/ansible_doom.py /doomsible/ansible_doom.py

# Expose the VNC port.
EXPOSE 5900

# Use the Python script as the container's entrypoint.
ENTRYPOINT [ "python3", "/doomsible/ansible_doom.py" ]
