import logging, yaml, requests, re
import paho.mqtt.client as mqtt
from random import choices
from string import ascii_letters, digits

# A mapping between user-provided mode and modes documented in the Netatmo
# Connect API specification (https://dev.netatmo.com/apidocumentation/control#homestatus)
mode_user_to_NA = {
    "AUTO": "home",
    "MANUAL": "manual",
    "BOOST": "max",
    "OFF": "hg"
}
mode_NA_to_user = {
    "home": "AUTO",
    "manual": "MANUAL",
    "max": "BOOST",
    "hg": "OFF"
}

# Load settings from file
settings_file = open("smarther2mqtt_settings.yml", mode="r")
settings = yaml.safe_load(settings_file)
settings_file.close()

# Set up logger
log = logging.getLogger('smarther2mqtt')
logging_level = logging.DEBUG if settings['debug'] else logging.INFO
logging.basicConfig(format="[%(asctime)s] %(levelname)s:%(name)s:%(funcName)s:%(lineno)d - %(message)s", datefmt="%Y/%m/%d %H:%M:%S", level = logging_level)

# A few ready-to-use classes that implement a
# "publish" method used to present messages that
# request user interaction
class LogRequester:
    def publish(self, message):
        log.info(message)

class TelegramRequester:
    def publish(self, message):
        telegram_base_url = "https://api.telegram.org/bot%s/sendMessage" %settings['telegram']['bot_token']
        message = re.sub("\.", "\\.", message)
        json_dict = {
            'chat_id': settings['telegram']['chat_id'],
            'parse_mode': 'MarkdownV2',
            'text': message
        }
        log.debug("Sending telegram message by using the following URL: %s and JSON data: %s" % (telegram_base_url, repr(json_dict)))
        requests.post(telegram_base_url, json=json_dict, timeout=20)

# Set up connection to the MQTT broker
def mqtt_init():
    log.debug("Initializing connection to the MQTT broker")
    # A client_id is required in order to preserve topic subscriptions in case
    # connection with the broker is lost and restored. To limit the likeliness
    # of collision with other instances of smarther2mqtt, a random client_id is
    # generated here
    mqttc = mqtt.Client(client_id = 'smarther2mqtt_' + ''.join(choices(ascii_letters + digits, k=10)), clean_session = False)
    mqttc.enable_logger(log)
    mqttc.connect(settings['mqtt']['broker']['ipaddress'], port=(settings['mqtt']['broker']['port'] if 'port' in settings['mqtt']['broker'] else 1883))
    return mqttc

# Raise a KeyboardInterrupt. This is a utility function
# that can be used as signal handler to convert a received
# signal to a KeyboardInterrupt exception
def signal_to_interrupt(*args):
    raise KeyboardInterrupt
