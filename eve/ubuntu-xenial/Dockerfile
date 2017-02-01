FROM ubuntu:xenial

ENV HOME_BUILDBOT /var/lib/buildbot

RUN apt-get --assume-yes update
RUN DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends --assume-yes \
    openssh-client \
    build-essential \
    ca-certificates \
    python \
    python-pkg-resources \
    python-setuptools \
    python-pip \
    python-dev \
    wget \
    git

COPY requirements.txt /tmp/

RUN pip2 install -r /tmp/requirements.txt \
 && pip2 install buildbot-worker==0.9.0rc1 \
 && git config --global credential.helper store \
 && adduser -u 1042 --home /home/eve --disabled-password --gecos "" eve \
 && adduser eve sudo \
 && echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers

USER eve

RUN mkdir -p /home/eve/workspace \
    && mkdir -p /home/eve/.ssh/ \
    && /bin/echo -e "Host bitbucket.org\n\tStrictHostKeyChecking no\n" >> /home/eve/.ssh/config

ENV LANG=C.UTF-8 \
    BUILD_DISTRO=trusty \
    JOB_NAME=walle_trusty_docker

WORKDIR /home/eve/workspace
CMD buildbot-worker create-worker . "$BUILDMASTER:$BUILDMASTER_PORT" "$WORKERNAME" "$WORKERPASS" \
    && buildbot-worker start --nodaemon
