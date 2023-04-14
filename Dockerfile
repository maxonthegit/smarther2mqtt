FROM alpine

RUN apk update
RUN apk add python3 py3-pip py3-requests py3-yaml
RUN pip install --upgrade pip wheel
RUN pip install --upgrade paho-mqtt

ADD smarther2mqtt.py /
ADD modules/ /modules/

CMD ["/smarther2mqtt.py"]
HEALTHCHECK CMD "ping -n 1 api.netatmo.com && pgrep smarther2mqtt >/dev/null"