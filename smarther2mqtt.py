#!/usr/bin/python3

import time, json, requests, signal
from threading import Thread
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
    except Exception as e:
        # In recent releases of paho-mqtt, exceptions raised inside
        # callback functions may have two alternative effects:
        # a) if the exception is not handled in the callback function
        #    *and* is not suppressed using parameter suppress_exceptions
        #    (see https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html#callbacks),
        #    then it is raised and hangs the callback handler altogether
        #    (unfortunately it cannot be catched in the main thread)
        # b) if the exception is haneld in the callback function *or*
        #    is suppressed using parameter suppress_exceptions, then
        #    the callback handler remains valid (and, of course, the
        #    exception is not raised)
        # In this case option b) is applied.
        log.error("Exception raised while processing received message '%s': %s" % (message.payload, repr(e)))


def main():
    log.debug("Netatmo token exists: %s", netatmo.token_exists())
    if not netatmo.token_exists():
        obtain_netatmo_token(netatmo)

    mqttc = mqtt_init()

    base_topic = settings['mqtt']['subscribe_topics']['base_topic']
    # Subscribe to selected MQTT topics for which messages are expected from the broker
    mqttc.subscribe(base_topic + '/+', 0)
    # Set up a callback function to handle received messages
    mqttc.message_callback_add(base_topic + '/+', handle_received_command)

    mqttc.loop_start()

    log.info("Starting polling cycle")
    first_iteration = True
    while True:
        signal.signal(signal.SIGTERM, signal_to_interrupt)
        try:
            # Start polling cycle
            log.debug("(Re)starting polling cycle")
            while True:
                if not first_iteration:
                    log.debug("Waiting %i seconds" % settings['netatmo']['polling_interval'])
                    time.sleep(settings['netatmo']['polling_interval'])
                first_iteration = False

                # Get information about the whole home
                home_status_string = netatmo.query_homestatus(settings['netatmo']['homeid'])
                log.debug("Received home status: %s" % home_status_string)
                home_status = json.loads(home_status_string)
                log.debug("JSON-decoded home status: %s" % json.dumps(home_status))

                # Check whether global API rate limits (which may occasionally occur)
                # have been hit. This is signaled by the following response body in an
                # HTTP 429 error response:
                # {
                #   "error": {
                #     "code": 11,
                #     "message": "Failed to enter concurrency limited section"
                #   }
                # }
                if 'error' in home_status:
                    log.warning("API returned system-wide error: %i. Will try again at next polling cycle" % home_status['erorr']['message'])
                    continue
                else:
                    # The response is assumed to have a 'body' key at this point

                    # Check whether any application-level errors have been
                    # reported (see https://dev.netatmo.com/apidocumentation/general#status-ok)
                    if 'errors' in home_status['body']:
                        log.warning("API returned application-evel error code %i. Will try again at next polling cycle" % home_status['body']['errors'][0]['code'])
                        continue
                
                # Retrieve information about the room of interest
                room_status = get_room_in_home(home_status['body']['home'], settings['netatmo']['roomid'])
                log.debug("Room status: %s" % room_status)
                
                # Publish data to the MQTT broker
                log.debug("Publishing information to the MQTT broker")
                base_topic = settings['mqtt']['publish_topics']['base_topic']
                mqttc.publish(base_topic + '/' + settings['mqtt']['publish_topics']['temperature'], payload = room_status['therm_measured_temperature'], retain = True)
                mqttc.publish(base_topic + '/' + settings['mqtt']['publish_topics']['humidity'], payload = room_status['humidity'], retain = True)
                mqttc.publish(base_topic + '/' + settings['mqtt']['publish_topics']['setpoint_endtime'], payload = (room_status['therm_setpoint_end_time'] or "0"), retain = True)
                if not netatmo.temperature_update_pending():
                    mqttc.publish(base_topic + '/' + settings['mqtt']['publish_topics']['temperature_setpoint'], payload = room_status['therm_setpoint_temperature'], retain = True)
                    netatmo.update_temperature(room_status['therm_setpoint_temperature'])
                if not netatmo.mode_update_pending():
                    mqttc.publish(base_topic + '/' + settings['mqtt']['publish_topics']['mode'], payload = mode_NA_to_user[room_status['therm_setpoint_mode']], retain = True)
                    netatmo.update_mode(room_status['therm_setpoint_mode'])

        except requests.ConnectionError as e:
            log.error("Error while connecting to server: %s. Restarting polling cycle" % repr(e))
        except requests.HTTPError as e:
            log.error("HTTP exception in polling cycle: %s" % repr(e))
            log.debug("Obtaining a new token and restarting the loop")
            obtain_netatmo_token(netatmo)
        except KeyboardInterrupt:
            mqttc.loop_stop()
            return
        except Exception as e:
            log.error("Unknown exception occurred: %s" % repr(e))



netatmo = NetatmoToken()
main()
