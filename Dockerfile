ARG BASE_IMAGE=kicad/kicad:10.0

FROM $BASE_IMAGE

SHELL ["/bin/bash", "-c"]

USER root

RUN apt update \
    && apt -qqy install \
        python3 \
        python3-pip \
        python3-venv \
        gerbv \
        git \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m docker && echo "docker:docker" | chpasswd

USER docker

ENV HOME="/home/docker" \
    XDG_CONFIG_HOME="/home/docker/.config" \
    XDG_DATA_HOME="/home/docker/.local/share" \
    XDG_BIN_HOME="/home/docker/.local/bin" \
    VIRTUAL_ENV="/home/docker/venv" \
    PATH="/home/docker/venv/bin:$PATH"

WORKDIR /home/docker

RUN python3 -m venv --system-site-packages $VIRTUAL_ENV

COPY --chown=docker:docker . kicad-si-simulation-wrapper

RUN echo "Installing si-wrapper..." \
  && pushd ./kicad-si-simulation-wrapper \
  && pip install . \
  && popd
ENTRYPOINT ["si-wrapper"]
