FROM ubuntu:22.04 AS build-doom

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
      build-essential \
      libsdl-mixer1.2-dev \
      libsdl-net1.2-dev \
      git \
      gcc \
      unzip \
      wget && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY dockerdoom /dockerdoom

# Download and verify the shareware IWAD
# doom1.wad v1.9 shareware -- verify integrity after download
RUN wget -q http://distro.ibiblio.org/pub/linux/distributions/slitaz/sources/packages/d/doom1.wad && \
    echo "f0cefca49926d00903cf57551d901abe  doom1.wad" | md5sum -c -

WORKDIR /dockerdoom/trunk
RUN ./configure && \
    make && \
    make install

######################################################################################################################    

FROM ubuntu:22.04 AS run-doom

ARG VNC_PASSWORD=1234
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
      x11vnc \
      xvfb \
      libsdl-mixer1.2 \
      libsdl-net1.2 \
      netcat \
      python3 \
      ansible && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=build-doom /doom1.wad /
COPY --from=build-doom /usr/local/games/psdoom /usr/local/games

RUN mkdir /doomsible && \
    mkdir -p ~/.vnc && \
    x11vnc -storepasswd ${VNC_PASSWORD} ~/.vnc/passwd

WORKDIR /doomsible
COPY ./src/ansible_doom.py /doomsible/ansible_doom.py

EXPOSE 5900

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD echo "list" | nc -U /dockerdoom.socket || exit 1

ENTRYPOINT [ "python3", "/doomsible/ansible_doom.py" ]
