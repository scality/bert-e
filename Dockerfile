FROM python:3.6.6-slim-stretch

RUN apt-get update && apt-get install git -y && rm -rf /var/cache/apt

COPY constraints.txt requirements.txt /app/

RUN pip install -r /app/requirements.txt

VOLUME '/tmp'
VOLUME '/root/.bert-e'
WORKDIR /app/

COPY . /app/
RUN pip install --no-deps /app

ENTRYPOINT ["bert-e-serve"]
