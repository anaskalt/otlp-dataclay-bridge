FROM python:3.11

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /usr/src/app
COPY ./icos_fl /usr/src/app/icos_fl
COPY ./bridgeConfig.py /usr/src/app

# Run configuration once then keep container alive
CMD python bridgeConfig.py && touch /tmp/config_done && tail -f /dev/null