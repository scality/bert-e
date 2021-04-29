FROM python:3.6.6-slim-stretch

RUN apt-get update && apt-get install git -y && rm -rf /var/cache/apt

COPY constraints.txt requirements.txt /app/

ENV PYTHON_PIP_VERSION 21.0.1
RUN pip3 install pip==$PYTHON_PIP_VERSION
RUN pip install -r /app/requirements.txt

VOLUME '/tmp'
VOLUME '/root/.bert-e'
WORKDIR /app/

COPY . /app/
RUN pip install --no-deps /app

ENTRYPOINT ["bert-e-serve"]
