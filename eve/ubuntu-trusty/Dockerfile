FROM ubuntu:trusty

ENV HOME_BUILDBOT /var/lib/buildbot

RUN apt-get --assume-yes update
RUN DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends --assume-yes \
    openssh-client \
    build-essential \
    ca-certificates \
    python \
    python-dev \
    wget \
    git

RUN wget --no-verbose --tries=3 --timeout=30 https://bootstrap.pypa.io/get-pip.py
RUN python get-pip.py pip==8.1.2
RUN /usr/local/bin/pip install buildbot-worker==0.9.0b9
COPY requirements.txt requirements.txt
RUN /usr/local/bin/pip install -r requirements.txt

USER eve
WORKDIR /home/eve

ENV LANG=C.UTF-8 \
    BUILD_DISTRO=trusty \
    JOB_NAME=walle_trusty_docker

CMD  buildbot-worker create-worker . "$BUILDMASTER:$BUILDMASTER_PORT" "$WORKERNAME" "$WORKERPASS" && buildbot-worker start --nodaemon
