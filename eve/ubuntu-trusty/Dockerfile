FROM ubuntu:trusty

ENV HOME_BUILDBOT /var/lib/buildbot

RUN apt-get --assume-yes update
RUN DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends --assume-yes \
    openssh-client \
    build-essential \
    ca-certificates \
    python \
    python-pip \
    python-dev \
    wget \
    git

RUN wget --no-verbose --tries=3 --timeout=30 https://bootstrap.pypa.io/get-pip.py

COPY requirements.txt /tmp/

RUN /usr/bin/pip2 install pip==8.1.2 \
 && pip2 install -r /tmp/requirements.txt \
 && /usr/local/bin/pip install buildbot-worker==0.9.0rc1 \
 && git config --global credential.helper store \
 && adduser -u 1042 --home /home/eve --disabled-password --gecos "" eve \
 && adduser eve sudo \
 && echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers

USER eve
WORKDIR /home/eve

ENV LANG=C.UTF-8 \
    BUILD_DISTRO=trusty \
    JOB_NAME=walle_trusty_docker

CMD buildbot-worker create-worker . "$BUILDMASTER:$BUILDMASTER_PORT" "$WORKERNAME" "$WORKERPASS" \
    && buildbot-worker start --nodaemon
