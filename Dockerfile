FROM python:2.7
ENV FLASK_APP webhook_listener.py
COPY . wall-e
WORKDIR wall-e
RUN pip install -rrequirements.txt
CMD python webhook_listener.py