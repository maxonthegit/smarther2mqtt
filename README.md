# About
`smarther2mqtt` is a Docker container that implements communication between a [BTicino][bticino] [Smarther2][smarther2] Wi-Fi thermostat and an [MQTT][mqtt] broker like [Mosquitto][mosquitto]. My primary use case is monitoring and controlling the thermostat from [openHAB][openhab] using the [MQTT binding][openhab-mqtt].

Here is an overview of the assumed architecture, where `◄════►` represents the data flow:
```
                         ┌────────────────────┐
                         │ Netatmo            │
   ┌────────────┐        │ Connect ┌───────┐  │      ╔═══════════════╗
   │ Smarther2  │        │  cloud  │Netatmo╞═◄╪════►═╣ smarther2mqtt ║
   │ thermostat ╞═◄════►═╡         │  API  │  │      ║  (this tool)  ║
   └────────────┘        │         └───────┘  │      ╚═══════╦═══════╝
                         └────────────────────┘              ▲
                                                             ║
                                                             ▼
                                                      ┌──────╨──────┐
                                                      │ MQTT broker │
                                                      └──────╥──────┘
                                                             ▲
                                                             ║
                                              ┌──────────────╫──────┐
                                              │ openHAB      ▼      │
    ┌──────┐                                  │          ┌───╨────┐ │
    │ User ╞═◄══════════════════════════════►═╡          │  MQTT  │ │
    └──────┘                                  │          │ add-on │ │
                                              │          └────────┘ │
                                              └─────────────────────┘
```

# Setup
Let **`HOST_IPADDRESS`** be the IP address of the host on which `smarther2mqtt` will be executed (this it the IP address on your LAN). Also, let **`WEBSERVER_PORT`** be the TCP port on which a temporary web server will be launched to obtain an OAuth2 token when required at a later step (this is the host-side published port of the Docker container).

> Take note of:
> * `HOST_IPADDRESS`
> * `WEBSERVER_PORT`

Setting up `smarther2mqtt` for exposing a [Smarther2][smarther2] thermostat in openHAB involves a few steps:

1. Register an app on the [Netatmo Connect][netatmo-developer] portal
2. Install an MQTT broker (or pick an existing one)
3. Configure `smarther2mqtt`
4. Run `smarther2mqtt`
5. Install the [MQTT binding][openhab-mqtt] in [openHAB][openhab]
6. Configure things and items in openHAB

These steps are illustrated in detail below.

## 1. Register an app on the Netatmo Connect portal
* If required, sign up for a new account on the [Netatmo Connect developer portal][netatmo-developer].
* [Create a new app][netatmo-newapp] that will be used by `smarther2mqtt` to communicate with the thermostat. At this stage only generic information are requested, so there are no constraints about what to indicate.
* Once your new app has been approved, get back to the [list of your apps][netatmo-applist].
* Take note of the **_Client ID_** and of the **_Client secret_**, as they will be required later on.
* Set `http://HOST_IPADDRESS:WEBSERVER_PORT/token` as _Redirect URI_. Be careful in respecting this exact syntax (e.g., do _not_ put a final `/` in the URI), as this URI will be used as part of the OAuth2 authentication process.
* Make sure that the app status is _Activated_.
* Switch to the [Netatmo Home + Control API documentation][netatmo-home+control] page, expand the `homesdata` section, click the _Try It Out_ button and then the _Execute /Homesdata_ button. From the resulting _Server response_, take note of the `id` of your home and of the room that contains the thermostat.

> Take note of:
> * _Client ID_
> * _Client secret_
> * `id` of your home
> * `id` of the room with the thermostat

## 2. Set up the MQTT broker
An MQTT broker is a software that acts as an "exchange point" for messages in the MQTT protocol which _subscriber_ applications receive from _publisher_ applications. `smarther2mqtt` relies on an MQTT broker which it will use as a _subscriber_ to receive thermostat commands (from openHAB) and as a _publisher_ to expose readings from the thermostat (to openHAB).

In case you already have an MQTT broker running somewhere in your network, it is enough to point `smarther2mqtt` to this broker by editing the configuration file (see step 3 below). Otherwise, you will need to set up a new MQTT broker.
In principle, it may even be possible to point `smarther2mqtt` to a free publicly available MQTT broker like [HiveMQ](https://www.hivemq.com/public-mqtt-broker/), but this is strongly discouraged for obvious security reasons.

In practice, it is enough to install an open source MQTT broker like [Mosquitto][mosquitto], which requires little to no configuration. Just make sure that:
* the broker is _not_ accessible from the Internet by setting up proper firewall rules
* `smarther2mqtt` is pointed to the correct broker, as no authentication is enforced
* the broker is reachable by the Docker container that runs `smarther2mqtt` (by default, some default Mosquitto installations listen on `127.0.0.1` only)

## 3. Configure `smarther2mqtt`
Copy file `smarther2mqtt_settings-template.yml` to `smarther2mqtt_settings.yml` and edit its contents to suit your setup.

Comments inside the provided template configuration file should be fairly self-explanatory about the semantic of each parameter. Most of the paramaters that you have taken note of will be required at this stage.

## 4. Run `smarther2mqtt`
Execute the following sequence of commands to build the container image, create a container and execute it.

_Note about network mode_ - The correct network mode to be used depends on your system settings:
* `bridge` ensures isolation, hence is deemed more safe (`smarther2mqtt` will be able to reach your whole network but prevented from exposing unintended services). It is fine to use as long as the MQTT broker listens on the host IP address (i.e., not just `127.0.0.1`) or is executed on a different host
* `host`, used in this example, is slightly less safe (`smarther2mqtt` does not normally expose any services anyway) but allows to reach a host-side MQTT broker listening on `127.0.0.1` only


```
sudo docker build --tag smarther2mqtt .
sudo docker container create --name smarther2mqtt --hostname smarther2mqtt --network host --mount type=bind,source=$PWD/smarther2mqtt_settings.yml,target=/smarther2mqtt_settings.yml --restart unless-stopped smarther2mqtt
sudo docker start smarther2mqtt
```

At the time of first execution, or if the OAuth2 token has somehow been invalidated, it is required to authorize access to the Netatmo Connect API. For this purpose, `smarther2mqtt` requires the user to access a specific URL from a web browser that can reach `HOST_IPADDRESS` and `WEBSERVER_PORT`. The need to perform this action, as well as the URL to contact are notified in the container log and, optionally (if set in the configuration file) through a Telegram bot. To check the container log:
```
sudo docker logs smarther2mqtt
```
The message that invites to contact the URL is similar to the following:
```
[2023/04/14 19:26:53] INFO:smarther2-mqtt:publish:34 - The *Netatmo Smarther2* tool requires authorization. Please grant it by accessing this web page: http://192.168.10.150:9090/authorize
```
Just access the URL, authenticate yourself on the Netatmo Connect cloud, grant the requested access and you are done.

## 5. Install the [MQTT binding][openhab-mqtt] in [openHAB][openhab]
From the _Settings_/_Bindings_ menu of openHAB, install the [MQTT binding][openhab-mqtt].

## 6. Configure things and items in openHAB
Configure things and item as follows:
* Add a new `mqtt:broker` thing (bridge) and configure it to point to the IP address (and, if required, port) of your MQTT broker. Review and tune the other parameters to make sure that the thing status is _Online_. Unless explicitly required, it should be perfectly fine to use QoS `0` here, especially if the MQTT broker is running on the same host.
* Add another _Generic MQTT_ thing (`mqtt:topic`) and configure it to use the _MQTT broker_ added above as bridge.
* Edit the freshly added _Generic MQTT_ thing and open its _Channels_ tab (see also the [applicable section of the MQTT Things and Channels Binding guide](https://www.openhab.org/addons/bindings/mqtt.generic/#supported-things)). For each topic in the `smarther2mqtt` configuration file (both `publish_topics` and `subscribe_topics`) add a new _Channel_, picking its parameters as follows:
  * identifiers and labels can be arbitrary, but pick ones that will be easy to recognize later on
  * channel types should be quite obvious: temperature and humidity topics will use numbers, whereas mode will use strings
  * for each of the temperature and humidity topics just indicate the corresponding `publish_topic` from the `smarther2mqtt` configuration file as _status_ topic in each channel's settings
  * for each of the temperature setpoint and mode topics indicate the corresponding pair of `publish_topic` and `subscribe_topic` from the `smarther2mqtt` configuration file as _status_ and _command_ topics, respectively, in each channel's settings: for example, create a single channel to represent the temperature setpoint where you set `smarther2/thermostat1/sensors/temperature_setpoint` as _status_ topic and `smarther2/thermostat1/commands/temperature_setpoint` as _command_ topic
  * optionally, for the channel that represents the thermostat's operational mode you can indicate the following list of _Allowed states_ in the _Advanced options_ section: `AUTO,MANUAL,BOOST,OFF`. This will allow to easily set the state from the openHAB GUI
  * always indicate the full topic path (e.g., `smarther2/thermostat1/sensors/temperature`) in each channel
  * it is perfectly fine _not_ to set any `qos` value for the channel, thus letting the default one from the broker thing be applied
  * do _not_ set the `retained` flag on any of the created channels: it is pointless for channels used to get readings from the thermostat, and it may have adverse effects for channels used to send commands to the thermostat (see [Synchronization Logic](#synchronization-logic) below)
* Create a new item for each of the channels created above. For convenience, it is possible to use the _Create Points from Thing_ button to accomplish this. Item types should be selected according to the corresponding channels (for example, temperature setpoint must be a setpoint, while mode must be a string).

### Synchronization logic
Once this setup stage is reached, the [Smarther2][smarther2] thermostat can be controlled and its status be monitored through 3 different interfaces:
1. the Legrand/Netatmo/BTicino Home+Control mobile app
2. Apple HomeKit (or, possibly, Google Home)
3. the MQTT topics exposed by `smarther2mqtt`

While interfaces 1 and 2 are natively paired, it is natural to wonder how `smarther2mqtt` is expected to interact with them.

#### Status Readings
All thermostat readings are made available through all the three aforementioned interfaces: they should all return the same readings at any time, regardless of which one is queried. \
As a minor exception, status information published by `smarther2mqtt` via MQTT may be refreshed with a slight delay due to the setting of its internal parameter `netatmo`/`polling_interval`.

#### Commands
As a general rule, the latest requested (temperature/mode) change is always applied, regardless of the interface it was received through. \
However, a couple of additional mechanisms should be considered:
* Messages published on the MQTT topics used to receive temperature/mode commands (`subscribe_topics`) need not and should _never_ have the [retained](https://www.hivemq.com/blog/mqtt-essentials-part-8-retained-messages/) flag set; channels of the openHAB thing should be configured accordingly. \
In fact, if a retained message is published on any of the `subscribe_topics`, this message becomes "sticky" and is sent to any new subscribers, even if they connect to the MQTT broker after the message has been sent. Although in principle this is not harmful, the retained message would be fetched by `smarther2mqtt` every time it starts up (for example, in the event of a reboot of the device that `smarther2mqtt` is executed on), causing unintentional overrides of the current thermostat operational mode. \
Checking whether a retained message exists can be accomplished by simply subscribing to a topic with an appropriate filter: if a message is immediately received, then that message was set to be retained. For example:
  ```
  mosquitto_sub --retained-only -t smarther2/thermostat1/commands/temperature_setpoint
  13.5 <===== retained message
  ```
  In case a retained message has been mistakenly sent to one of the `subscribe_topics`, it can be cleared by using a command similar to the following:
  ```
  mosquitto_pub -n -r -t smarther2/thermostat1/commands/TOPIC_TO_BE_CLEARED
  ```
* Similarly to environmental readings, also the last issued command is always synchronized among the 3 aforementioned interfaces. Therefore, changes requested via the Home+Control app are also reflected in the temperature setpoint item in openHAB. \
Also in this case, the refresh may take a short time due to the `polling_interval` setting.


# Testing and troubleshooting
Assuming that the [Mosquitto][mosquitto] MQTT broker is being used, it is possible to verify which messages are exchanged by `smarther2mqtt` by installing the `mosquitto-clients` package and running commands similar to the following:
```
# To verify information published by smarther2mqtt (i.e., thermostat sensor readings)
for SENSOR in temperature humidity temperature_setpoint mode; do echo -n "-t smarther2/thermostat1/sensors/$SENSOR "; done | xargs mosquitto_sub

# To verify commands issued by smarther2mqtt
echo auto | mosquitto_pub -t smarther2/thermostat1/commands/mode -l
echo 18   | mosquitto_pub -t smarther2/thermostat1/commands/temperature_setpoint -l
```


----

# Background
[BTicino S.p.A.][bticino] is a renowned italian manufacturer of electrical components for home and industry use. Its product range includes a family of thermostats called _Smarther_ that can drive heating or cooling home systems: they have a built-in Wi-Fi connection for being managed from the cloud and support being controlled by the user from a mobile app.

There exist two generations of such thermostats:
* the earlier [_Smarther_][smarther], which can be controlled using the companion BTicino _Thermostat_ app ([Apple App Store][thermostat-ios], [Google Play Store][thermostat-android]), relies on the [Works with Legrand][legrand-developer] cloud platform, implements the [Smarther legacy v2.0 API specification][smarther-api] and is fully supported by the [BTicinoSmarther][openhab-bticinosmarther] openHAB binding
* the later [Smarther2][smarther2], which can be controlled using the companion Legrand/Netatmo/BTicino _Home + Control_ app ([Apple App Store][home+control-ios], [Google Play Store][home+control-android]) as well as through the Apple Homekit framework (Apple Home), relies on the [Netatmo Connect][netatmo-developer] cloud platform, implements the [Netatmo Home+Control API specification][natatmo-api] and, although a [Netatmo][openhab-netatmo] binding exists in openHAB, as of April 2023 is not among the device types it supports

Here is a summary of the picture:

| Generation | Cloud Platform | Mobile App | Apple Homekit | Implemented API | openHAB Binding |
| ---------- | -------------- | ---------- | :-----------: | --------------- | --------------- |
| [_Smarther_][smarther] | [Works with Legrand][legrand-developer] | BTicino _Thermostat_<br/>[Apple App Store][thermostat-ios]<br/>[Google Play Store][thermostat-android] | No | [Smarther legacy v2.0][smarther-api] | [BTicinoSmarther][openhab-bticinosmarther] |
| [Smarther2][smarther2] | [Netatmo Connect][netatmo-developer] | Legrand/Netatmo/BTicino _Home + Control_<br/>[Apple App Store][home+control-ios]<br/>[Google Play Store][home+control-android] | Yes | [Netatmo Connect Home+Control][natatmo-api] | ~~[Netatmo][openhab-netatmo]~~ |

To the best of my knowledge, each thermostat generation is meant to work with the control chain (cloud platform, app, API) it was designed for, therefore the two openHAB bindings are not interchangeable.
`smarther2mqtt` specifically addresses the Smarther2 generation, and implements a simple a link between the Netatmo Connect cloud and openHAB, in a way that does not require any integrations to openHAB itself.

# Additional notes
## Features
* The following functions of the [Smarther2][smarther2] thermostat are supported:
  * Room temperature reading
  * Room humidity reading
  * Temperature setpoint reading
  * Current operational mode reading (`AUTO`/`MANUAL`/`BOOST`/`OFF`)
  * Temperature setpoint setting
  * Operational mode setting (`AUTO`/`MANUAL`/`BOOST`/`OFF`)
* `smarther2mqtt` includes an implementation of the Netatmo Connect API [Authorization code grant type][netatmo-oauth2]. For this purpose, it temporarily runs a web server that is used to serve a callback URL where the authorization token is received. This service _never_ needs to be exposed on the Internet and terminates as soon as the grant is obtained.
* Changing the temperature setpoint automatically switches the operational mode of the thermostat to `MANUAL`. Moreover, this change may expire according to the _default duration_ of manual settings that has been configured in the Home + Control app: after expiry, the previous operational mode should be automatically restored.

## Requirements
* Excerpts from the [Smarther2 FAQ][smarther2] claim that the Smarther2 thermostat can be controlled from the local Wi-Fi network even in the absence of a working Internet connection. In practice, the native Legrand/Netatmo/BTicino Home + Control app refuses to start or fails to reach any thermostats without an Internet connection. The "local" operational mode, which may therefore only be supported via Apple Home (again, I don't know about Google Home) is anyway out of the scope of this tool: **`smarther2mqtt` requires an Internet connection and _always_ relies on it to control a thermostat** by leveraging the API from the Netatmo Connect cloud.

## Scope and limitations
* This tool is _not_ meant to replace the companion Legrand/Netatmo/BTicino Home + Control app, which remains the only tool for first-time setup of a thermostat and for accessing its full feature set.
* This tool is also _not_ meant to enable exposing the Smarther2 thermostat on the Apple Homekit system via the [openHAB Homekit add-on][openhab-homekit]: in fact, the unit is already supposed to be natively added in Apple Home at the time of first setup. A similar point may apply to Google Home.
* This tool only supports a **single instance of a [Smarther2][smarther2] thermostat**. However, in principle it should be possible to run multiple instances of the container, provided that each uses a different configuration file and a different `WEBSERVER_PORT`.
* Thermostat readings are queried by periodical polling: there is **no support for** proactive event (status change) notifications from the Netatmo Connect cloud via a **webhook URI**.


[bticino]: https://www.bticino.com
[smarther2]: https://www.bticino.it/termostati/smarther-termostato-wifi
[mqtt]: https://mqtt.org/
[mosquitto]: https://mosquitto.org/
[openhab]: https://www.openhab.org/
[openhab-mqtt]: https://www.openhab.org/addons/bindings/mqtt/
[smarther]: https://catalogo.bticino.it/BTI-X8000-IT
[thermostat-ios]: https://apps.apple.com/it/app/bticino-thermostat/id1082977357
[thermostat-android]: https://play.google.com/store/apps/details?id=it.bticino.thermostat&hl=it&gl=US
[legrand-developer]: https://developer.legrand.com
[smarther-api]: https://portal.developer.legrand.com/reference#api=smartherV2&operation=Chronothermostat-Measures
[openhab-bticinosmarther]: https://www.openhab.org/addons/bindings/bticinosmarther/
[home+control-ios]: https://apps.apple.com/it/app/home-control/id1188809809
[home+control-android]: https://play.google.com/store/apps/details?id=com.legrand.homecontrol&hl=it&pli=1
[netatmo-developer]: https://dev.netatmo.com
[natatmo-api]: https://dev.netatmo.com/apidocumentation/control
[openhab-netatmo]: https://www.openhab.org/addons/bindings/netatmo/
[netatmo-newapp]: https://dev.netatmo.com/apps/createanapp#form
[netatmo-applist]: https://dev.netatmo.com/apps/
[netatmo-oauth2]: https://dev.netatmo.com/apidocumentation/oauth#authorization-code
[openhab-homekit]: https://www.openhab.org/addons/integrations/homekit/
[netatmo-home+control]: https://dev.netatmo.com/apidocumentation/control#homesdata