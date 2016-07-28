FROM ubuntu:trusty

ENV HOME_BUILDBOT /var/lib/buildbot

RUN apt-get --assume-yes update
RUN DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends --assume-yes \
    python-dev \
    python-pip \
    wget \
    git

RUN wget --no-verbose --tries=3 --timeout=30 https://bootstrap.pypa.io/get-pip.py
RUN python get-pip.py pip==8.1.2
RUN /usr/local/bin/pip install buildbot-worker==0.9.0b9
COPY requirements.txt requirements.txt
RUN /usr/local/bin/pip install -r requirements.txt

# Create buildbot user
RUN groupadd -r buildbot
RUN useradd -r -m -d $HOME_BUILDBOT -g buildbot buildbot
COPY id_rsa $HOME_BUILDBOT/.ssh/id_rsa
RUN chmod 600 $HOME_BUILDBOT/.ssh/id_rsa
RUN ssh-keyscan bitbucket.org >> $HOME_BUILDBOT/.ssh/known_hosts
RUN chown -R buildbot:buildbot $HOME_BUILDBOT

# Switch to user
USER buildbot
WORKDIR $HOME_BUILDBOT


CMD  buildbot-worker create-worker . "$BUILDMASTER:$BUILDMASTER_PORT" "$WORKERNAME" "$WORKERPASS" && buildbot-worker start --nodaemon
