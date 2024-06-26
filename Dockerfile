FROM alpine

RUN apk update
RUN apk add python3 py3-requests py3-yaml openssl py3-paho-mqtt

ADD smarther2mqtt.py /
ADD modules/ /modules/

CMD ["/smarther2mqtt.py"]
HEALTHCHECK CMD pgrep smarther2mqtt >/dev/null && openssl s_client -connect api.netatmo.com:443 -brief </dev/null 2>&1 | grep -q ESTABLISHED