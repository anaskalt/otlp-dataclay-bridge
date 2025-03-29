FROM python:3.11

COPY requirements.txt /tmp/requirements.txt

RUN pip install --no-cache-dir -r /tmp/requirements.txt

RUN mkdir -p /usr/src/app
WORKDIR /usr/src/app

COPY ./opentelemetry /usr/src/app/opentelemetry
COPY ./icos_fl /usr/src/app/icos_fl
COPY ./run_bridge.py /usr/src/app

CMD ["python", "run_bridge.py"]

