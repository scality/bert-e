FROM ubuntu:bionic

ENV HOME_BUILDBOT /var/lib/buildbot
ENV PYTHON_PIP_VERSION 21.0.1
# Set the desired version of Helm
ENV DESIRED_VERSION v3.5.4

#
# Install packages needed by the buildchain
#

RUN apt-get upgrade
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

RUN sudo apt-get install -y software-properties-common \
    && sudo apt-get update \
    && sudo add-apt-repository -y ppa:git-core/ppa \
    && sudo apt-get update \
    && sudo apt-get install -y git

COPY requirements.txt /tmp/

RUN pip3 install pip==$PYTHON_PIP_VERSION
RUN pip3 install -r /tmp/requirements.txt

# Install helm
RUN curl https://raw.githubusercontent.com/kubernetes/helm/master/scripts/get > /tmp/get_helm.sh && bash /tmp/get_helm.sh

ENV LANG=C.UTF-8 \
    BUILD_DISTRO=trusty
