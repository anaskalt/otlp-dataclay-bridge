FROM python:3.11

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /usr/src/app
COPY ./model /usr/src/app/model
COPY ./bridgeConfig.py /usr/src/app

CMD ["python", "bridgeConfig.py"]