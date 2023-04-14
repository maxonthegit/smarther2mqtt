#!/usr/bin/python3

import time, json, requests, signal
from threading import Thread, Event
from modules.utilities import log, settings, mqtt_init, mode_user_to_NA, mode_NA_to_user, LogRequester, TelegramRequester, signal_to_interrupt
from modules.netatmo import NetatmoToken


def obtain_netatmo_token(netatmo):
    notification_channels = [LogRequester]
    if 'telegram' in settings:
        if len(settings['telegram']['bot_token']) > 0:
            notification_channels += [TelegramRequester]
    netatmo.get_new_token(notification_channels)

def get_room_in_home(home_json, room_id):
    for r in home_json['rooms']:
        if r['id'] == room_id:
            return r
    return None

def handle_received_command(client, userdata, message):
    try:
        msg = message.payload.decode().upper()
        log.debug("Received MQTT command %s with topic %s" % (msg, message.topic))
        base_topic = settings['mqtt']['subscribe_topics']['base_topic']
        if message.topic == base_topic + '/' + settings['mqtt']['subscribe_topics']['temperature_setpoint']:
            netatmo.set_temperature(msg)
        elif message.topic == base_topic + '/' + settings['mqtt']['subscribe_topics']['mode']:
            if msg in mode_user_to_NA:
                netatmo.set_mode(mode_user_to_NA[msg])
            else:
                log.warning("Invalid mode received: %s", msg)
    except:
        # According to https://github.com/eclipse/paho.mqtt.python/issues/365,
        # exceptions in the callback function are always raised. On the
        # other hand, in https://stackoverflow.com/questions/66933791/why-my-mqtt-client-cannot-reconnect-when-an-exception-occurs
        # is explained that the callback function itself is the correct
        # (and, possibly, only) place where such exceptions should be
        # catched
        pass

def subscriber_loop(mqttc, stop):
    while not stop.is_set():
        try:
            log.debug("(Re)starting subscriber thread loop")
            while not stop.is_set():
                # Process incoming messages (loop() is a blocking function)
                mqttc.loop()
        except Exception:
            mqttc.reconnect()
        

def main():
    log.debug("Netatmo token exists: %s", netatmo.token_exists())
    if not netatmo.token_exists():
        obtain_netatmo_token(netatmo)

    stop_thread = Event()

    # Subscribe to selected MQTT topics for which messages are expected from
    # the broker
    base_topic = settings['mqtt']['subscribe_topics']['base_topic']
    mqttc = mqtt_init()
    mqttc.subscribe(base_topic + '/+', 0)
    mqttc.message_callback_add(base_topic + '/+', handle_received_command)

    log.debug("Initializing subscriber thread")

    sub_thread = Thread(target=subscriber_loop, args=[mqttc, stop_thread])
    sub_thread.start()  

    log.info("Starting polling cycle")
    while True:
        signal.signal(signal.SIGTERM, signal_to_interrupt)
        try:
            # Start polling cycle
            log.debug("(Re)starting polling cycle")
            while True:
                # Get information about the whole home
                home_status_string = netatmo.query_homestatus(settings['netatmo']['homeid'])
                log.debug("Received home status: %s" % home_status_string)
                home_status = json.loads(home_status_string)
                log.debug("JSON-decoded home status: %s" % json.dumps(home_status))

                # Retrieve information about the room of interest
                room_status = get_room_in_home(home_status['body']['home'], settings['netatmo']['roomid'])
                log.debug("Room status: %s" % room_status)
                
                # Publish data to the MQTT broker
                log.debug("Publishing information to the MQTT broker")
                base_topic = settings['mqtt']['publish_topics']['base_topic']
                mqttc.publish(base_topic + '/' + settings['mqtt']['publish_topics']['temperature'], payload = room_status['therm_measured_temperature'], retain = True)
                mqttc.publish(base_topic + '/' + settings['mqtt']['publish_topics']['humidity'], payload = room_status['humidity'], retain = True)
                if not netatmo.temperature_update_pending():
                    mqttc.publish(base_topic + '/' + settings['mqtt']['publish_topics']['temperature_setpoint'], payload = room_status['therm_setpoint_temperature'], retain = True)
                if not netatmo.mode_update_pending():
                    mqttc.publish(base_topic + '/' + settings['mqtt']['publish_topics']['mode'], payload = mode_NA_to_user[room_status['therm_setpoint_mode']], retain = True)

                time.sleep(settings['netatmo']['polling_interval'])
        except requests.ConnectionError as e:
            log.error("Error while connecting to server: %s. Restarting polling cycle" % repr(e))
            pass
        except requests.HTTPError as e:
            log.error("HTTP exception in polling cycle: %s" % repr(e))
            log.debug("Obtaining a new token and restarting the loop")
            obtain_netatmo_token(netatmo)
        except KeyboardInterrupt:
            stop_thread.set()
            mqttc.disconnect()
            return



netatmo = NetatmoToken()
main()
