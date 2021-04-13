FROM ubuntu:bionic

ENV HOME_BUILDBOT /var/lib/buildbot
ENV PYTHON_PIP_VERSION 21.0.1

#
# Install packages needed by the buildchain
#

RUN apt-get --assume-yes update \
 && DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends --assume-yes \
    build-essential \
    ca-certificates \
    curl \
    git \
    libssl-dev \
    openssh-client \
    python \
    python3 \
    python3-dev \
    python3-pip \
    python3-pkg-resources \
    python3-setuptools \
    python-dev \
    python-pip \
    python-pkg-resources \
    python-setuptools \
    sudo \
    tox \
    wget

COPY requirements.txt /tmp/

RUN pip3 install pip==$PYTHON_PIP_VERSION
RUN pip3 install -r /tmp/requirements.txt

# Install helm
RUN curl https://raw.githubusercontent.com/kubernetes/helm/master/scripts/get > /tmp/get_helm.sh && bash /tmp/get_helm.sh

RUN git config --global credential.helper store

#
# Add user eve
#

RUN adduser -u 1042 --home /home/eve --disabled-password --gecos "" eve \
 && adduser eve sudo \
 && echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers

#
# Eve configuration
#

USER eve

RUN mkdir -p /home/eve/workspace \
    && mkdir -p /home/eve/.ssh/ \
    && /bin/echo -e "Host bitbucket.org\n\tStrictHostKeyChecking no\n" >> /home/eve/.ssh/config

ENV LANG=C.UTF-8 \
    BUILD_DISTRO=trusty

#
# Run buildbot-worker on startup
#

ARG BUILDBOT_VERSION
RUN sudo pip2 install buildbot-worker==$BUILDBOT_VERSION

WORKDIR /home/eve/workspace
CMD buildbot-worker create-worker . "$BUILDMASTER:$BUILDMASTER_PORT" "$WORKERNAME" "$WORKERPASS" \
    && buildbot-worker start --nodaemon
