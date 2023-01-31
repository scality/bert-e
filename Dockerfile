FROM python:3.10-slim-bullseye

RUN apt-get update && apt-get install git -y && rm -rf /var/cache/apt

COPY requirements.txt /app/

ENV PYTHON_PIP_VERSION 22.3.1
RUN pip install pip==$PYTHON_PIP_VERSION
RUN pip install -r /app/requirements.txt

VOLUME '/tmp'
VOLUME '/root/.bert-e'
WORKDIR /app/

COPY . /app/
RUN pip install --no-deps /app

ENTRYPOINT ["bert-e-serve"]
