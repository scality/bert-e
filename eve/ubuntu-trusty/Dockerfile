FROM ubuntu:trusty

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

# Create workdir
RUN mkdir /worker
WORKDIR /worker

# Copy over private key, and set permissions
RUN mkdir /root/.ssh/
COPY id_rsa /root/.ssh/id_rsa
RUN ssh-keyscan bitbucket.org >> /root/.ssh/known_hosts

CMD  buildbot-worker create-worker . "$BUILDMASTER:$BUILDMASTER_PORT" "$WORKERNAME" "$WORKERPASS" && buildbot-worker start --nodaemon
