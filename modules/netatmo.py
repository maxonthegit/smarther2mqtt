import os, sys, json, threading, requests, signal
from http.server import HTTPServer, BaseHTTPRequestHandler
from queue import Queue
from threading import Timer, Lock
from modules.utilities import log, settings, LogRequester, signal_to_interrupt

def MinimalHTTPRequestHandler(redirect_url, msg_queue):
    class HTTPRequestHandler(BaseHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            self.redirect_url = redirect_url
            self.msg_queue = msg_queue
            super().__init__(*args, **kwargs)

        def do_GET(self):
            log.debug("Serving web page %s" % self.path)
            if self.path == "/authorize":
                log.debug("Redirecting to Netatmo authorization page %s" % self.redirect_url)
                self.send_response_only(301)
                self.send_header("Location", self.redirect_url)
                self.end_headers()
                log.debug("HTTP 301 code returned to client")
            elif self.path[:12] == "/token?code=":
                # The user has granted the application access to the Netatmo API,
                # and an authorization code has been returned.

                # Skip the /token?code= portion of the URL
                netatmo_grant_code = self.path[12:]
                log.debug("Acquired Netatmo code \"%s\"" % netatmo_grant_code)

                # Acquire and return the code
                self.send_response_only(200)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                self.wfile.write("<html><head><title>smarther2-mqtt</title></head><body><p>Authorization successfully acquired. You can now close this tab/window.</p></body></html>".encode("utf-8"))
                log.debug("Success page sent to HTTP client")
                self.msg_queue.put(netatmo_grant_code)
            else:
                log.debug("Unexpected URL: %s - No actions taken" % self.path)
            
    return HTTPRequestHandler

class NetatmoToken:
    # Load last used token from a file, whose
    # name is defined in the settings. This
    # method is silently ineffective in case
    # the file does not exist or does not
    # contain a valid token.
    def load_token_from_file(self):
        if os.path.isfile(self.TOKEN_FILE):
            log.debug("Token file found. Attempting to open it")

            try: 
                f = open(self.TOKEN_FILE, mode="r")
            except OSError as e:
                log.warning("Error while attempting to open token file \"%s\": %s", self.TOKEN_FILE, e.strerror)
                return
            
            try:
                token = json.load(f)
            except json.JSONDecodeError as e:
                log.warning("Invalid syntax in token file \"%s\": %s at line %i", self.TOKEN_FILE, e.msg, e.lineno)
                f.close()
                return
            f.close()

            if 'access_token' not in token.keys():
                log.warning("Ignoring token file \"%s\" as it does not seem to contain any valid tokens", self.TOKEN_FILE)
                return
            
            self.token = token
            f.close()
        else:
            log.debug("Token file not found")
    
    # Save current token to file. Whatever the
    # contents of self.token, it writes them
    # to the token file.
    def write_token_to_file(self):
        try:
            f = open(self.TOKEN_FILE, mode="w")
        except OSError as e:
            log.warning("Error while attempting to save token to file \"%s\": %s", self.TOKEN_FILE, e.strerror)
            return
    
        f.write(json.dumps(self.token))
        f.close()

    
    # Return token stored in the current NetatmoToken instance
    def current_token(self):
        return self.token

    # Check whether a valid token is loaded in
    # memory and return true or false accordingly
    def token_exists(self):
        return self.token is not None

    # Parse JSON structure of a token and return a corresponding Python
    # data structure
    def parse_json_token(self, token_string):
        temp_token = None
        try:
            log.debug("Attempting to decode token %s" % token_string)
            temp_token = json.loads(token_string)
        except json.JSONDecodeError as e:
            log.error("Failure while decoding token: %s - Token dump:%s" % (repr(e), token_string))

        if 'access_token' not in temp_token or \
            'refresh_token' not in temp_token:
            log.error("Token is invalid: %s" % token_string)
            return None

        return temp_token

    # Do whatever is required to obtain a new token from the Netatmo API cloud.
    # This is different from refreshing a token. The only optional argument is a
    # list of classes which implement a "publish" method that is used to present
    # a message to the user, requesting to access a specified URL.
    # This method implements the Authorization code OAuth2 grant type flow for
    # the Home+Control Netatmo API. The obtained token is automatically saved
    # to file. The method returns True in case the token is successfully
    # obtained; False otherwise
    def get_new_token(self, channels_list = [LogRequester]):
        # This step requires user interaction, so a request
        # to access the URL is published on all applicable
        # communication channels
        for c in channels_list:
            c().publish("The *Netatmo Smarther2* tool requires authorization. Please grant it by accessing this web page: http://%s:%i/authorize" % (self.HTTP_SERVER_IPADDRESS, self.HTTP_SERVER_PORT))

        # Run a temporary web server to receive the OAuth2
        # authorization code. This is also used to serve a
        # convenience web page with a simple URL that eases
        # redirection to the Netatmo API authorization page
        log.debug("Expecting Netatmo authorization code via HTTP on %s:%i" % (self.HTTP_SERVER_IPADDRESS, self.HTTP_SERVER_PORT))
        temp_http_server = HTTPServer((self.HTTP_SERVER_IPADDRESS, self.HTTP_SERVER_PORT), MinimalHTTPRequestHandler(self.AUTHORIZE_URL, self.msg_queue))
        # The web server is executed in a separate thread,
        # so that it can be later stopped by this (main)
        # thread 
        temp_http_server_thread = threading.Thread(target=temp_http_server.serve_forever)
        temp_http_server_thread.start()
        
        # Suspend this thread and wait until an authorization
        # code is received or the process is interrupted by
        # Ctrl+C or SIGTERM
        signal.signal(signal.SIGTERM, signal_to_interrupt)
        try:
            netatmo_grant_code = self.msg_queue.get()
        except KeyboardInterrupt:
            temp_http_server.shutdown()
            sys.exit(0)
        log.debug("Received authorization code: \"%s\"" % netatmo_grant_code)
        temp_http_server.shutdown()
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

        # Request token using the authorization code just
        # obtained
        try:
            token_request_data = {
                'grant_type': 'authorization_code',
                'client_id': self.CLIENT_ID,
                'client_secret': self.CLIENT_SECRET,
                'code': netatmo_grant_code,
                'redirect_uri': self.TOKEN_CONFIRMATION_URL,
                'scope': 'read_smarther write_smarther'
            }
            log.debug("Requesting token from %s with data: %s" % (self.NETATMO_TOKEN_URL, repr(token_request_data)))
            r = requests.post(self.NETATMO_TOKEN_URL, data=token_request_data)
            # Raise exception in case something went wrong
            r.raise_for_status()
        except requests.ConnectionError as e:
            log.error("Error while contacting %s to obtain a token: %s" % (self.NETATMO_TOKEN_URL, repr(e)))
            raise
        except requests.HTTPError as e:
            log.error("HTTP error %i while contacting %s to obtain a token: %s" % (r.status_code, self.NETATMO_TOKEN_URL, repr(e)))
            raise

        temp_token = self.parse_json_token(r.text)
        if temp_token is None:
            raise Exception("Failed to receive token: invalid JSON format in %s" % r.text)
        log.info("New token successfully obtained")
        self.token = temp_token
        self.write_token_to_file()

    # Refresh an existing token. The method returns True if the
    # token is successfully refreshed; False otherwise.
    def refresh_token(self):
        try:
            token_refresh_data = {
                'grant_type': 'refresh_token',
                'refresh_token': self.token['refresh_token'],
                'client_id': self.CLIENT_ID,
                'client_secret': self.CLIENT_SECRET
            }
            log.debug("Refreshing token from %s with data: %s" % (self.NETATMO_TOKEN_URL, repr(token_refresh_data)))
            r = requests.post(self.NETATMO_TOKEN_URL, data=token_refresh_data)
            # Raise exception in case something went wrong
            r.raise_for_status()
        except requests.ConnectionError as e:
            log.error("Error while contacting %s to refresh token: %s" % (self.NETATMO_TOKEN_URL, repr(e)))
            raise
        except requests.HTTPError as e:
            log.error("HTTP error %i while contacting %s to refresh token: %s" % (r.status_code, self.NETATMO_TOKEN_URL, repr(e)))
            raise
        
        temp_token = self.parse_json_token(r.text)
        if temp_token is None:
            raise Exception("Failed to refresh token: invalid JSON format in %s" % r.text)
        log.info("Token successfully refreshed")
        self.token = temp_token
        self.write_token_to_file()
        

    # Invoke a Netatmo API call. Grant token is automatically
    # refreshed in case it has expired
    def netatmo_api_call(self, url, request_parameters=None, second_attempt=False):
        request_headers = {
            'accept': 'application/json',
            'Authorization': 'Bearer ' + self.token['access_token']
        }

        try:
            if request_parameters:
                log.debug("Sending request to %s with headers %s and parameters %s" % (url, request_headers, repr(request_parameters)))
                r = requests.post(url, headers=request_headers, json=request_parameters)
            else:
                log.debug("Sending request to %s with headers %s" % (url, request_headers))
                r = requests.get(url, headers=request_headers)
            r.raise_for_status()
        except requests.ConnectionError as e:
            log.error("Error while performing API call %s: %s" % (url, repr(e)))
            raise
        except requests.HTTPError as e:
            log.warn("HTTP error %i while performing API call %s: %s, details: %s" % (r.status_code, url, repr(e), r.text))
            if not second_attempt:
                if r.status_code == 403:
                    j = json.loads(r.text)
                    if j['error']['code'] == 3:
                        log.warn("Access token expired")
                        self.refresh_token()
                        log.info("Token successfully refreshed. Attempting to repeat last HTTP request")
                        return self.netatmo_api_call(url, second_attempt=True)
                if r.status_code >= 500 and r.status_code <=599:
                    # Likely a temporary server error
                    log.warn("Possible server error: failing silently")
                    return r.text
                log.error("This error cannot be handled")
                raise
            else:
                log.error("HTTP error %i while performing API call %s: %s" % (r.status_code, url, repr(e)))
                raise
        return r.text

    # Methods for specific API calls follow

    # Get information about all homes, rooms and modules
    def query_homesdata(self):
        request_url = self.BASE_URL + self.HOMESDATA
        return self.netatmo_api_call(request_url)
    
    # Get information about a specific home
    def query_homestatus(self, home_id):
        request_url = self.BASE_URL + self.HOMESTATUS + "?home_id=" + home_id
        return self.netatmo_api_call(request_url)


    # Convenience function to wrap parameters in a proper JSON
    # data structure that is expected by the Netatmo Connect API
    def prepare_room_request(self, home_id, room_id, parameters_dict):
        return {
            "home": {
                "id": home_id,
                "rooms": [
                    {
                        "id": room_id,
                        **parameters_dict
                    }
                ]
            }
        }
    

    # In order to rate limit the requests sent to the Netatmo Connect cloud, the
    # following requests are deferred to a moment when no new parameter
    # changes are received.
    # Once a long enough period of silence is detected, a request is issued that
    # integrates all required status changes that have been gathered in the meantime.

    # Utility method to commit a thermostat status change. This method is
    # meant to be invoked by a Timer object
    def send_thermostat_update(self):
        with self.lock:
            log.debug("Sending thermostat update")
            request_url = self.BASE_URL + self.SETSTATE

            request_parameters_data = {}
            if self.target_temperature:
                request_parameters_data["therm_setpoint_temperature"] = self.target_temperature
            if self.target_mode:
                request_parameters_data["therm_setpoint_mode"] = self.target_mode
            request_parameters = self.prepare_room_request(settings['netatmo']['homeid'], settings['netatmo']['roomid'], request_parameters_data)

            self.netatmo_api_call(request_url, request_parameters)

            self.scheduled_request = None
            self.target_temperature = None
            self.target_mode = None
    
    # Schedule a thermostat status update for a later time.
    # Cancel an already scheduled update, if any
    def schedule_thermostat_update(self):
        if self.scheduled_request:
            log.debug("Canceling pending thermostat update")
            self.scheduled_request.cancel()
        self.scheduled_request = Timer(settings['netatmo']['min_request_idle_time'], self.send_thermostat_update)
        log.debug("Scheduling thermostat update within %i seconds" % settings['netatmo']['min_request_idle_time'])
        self.scheduled_request.start()

    # Change the thermostat's setpoint temperature and
    # automatically set "manual" mode
    def set_temperature(self, temp):
        with self.lock:
            target_temperature = float(temp)
            # Check if temperature has really changed since the last time it
            # has been set. This is useful to avoid publish/subscribe loops
            if target_temperature != self.last_set_temperature:
                self.target_temperature = target_temperature
                self.last_set_temperature = self.target_temperature
                self.target_mode = "manual"
                self.schedule_thermostat_update()

    # Change the thermostat's operational mode.
    # According to the schema of the /homestatus API call
    # (https://dev.netatmo.com/apidocumentation/control#homestatus),
    # allowed modes are: home, manual, max, hg (anti-frost mode)
    def set_mode(self, mode):
        if (self.last_set_mode is None or self.last_set_mode.lower() == "hg") and mode.lower() == "max":
            # Changing from the OFF to the BOOST status requires a transition through an
            # intermediate mode
            log.debug("BOOST mode requested. Setting intermediate MANUAL mode first")
            if self.scheduled_request:
                self.scheduled_request.cancel()
            self.target_mode = "manual"
            self.target_temperature = 18.0
            self.send_thermostat_update()
        with self.lock:
            # Check if mode has really changed since the last time it
            # has been set. This is useful to avoid publish/subscribe loops
            if mode.lower() != self.last_set_mode:
                self.target_mode = mode.lower()
                self.last_set_mode = self.target_mode
                # When mode is set to "manual", a temperature setpoint must
                # be included in the next call to the Netatmo API, otherwise
                # the call will be ineffective
                if mode.lower() == "manual":
                    # Check if there already is a temperature setpoint pending
                    # application
                    if not self.target_temperature:
                        # Try to re-apply a recently set temperature setting
                        if self.last_set_temperature:
                            self.target_temperature = self.last_set_temperature
                        else:
                            # Last resort: apply a (supposedly) safe temperature
                            self.target_temperature = 18.0
                            self.last_set_temperature = self.target_temperature
                        log.debug("Manual mode was requested and no temperature setpoint pending: applying one now (%.1f°)" % self.target_temperature)
                self.schedule_thermostat_update()
    
    # Check if there are temperature or mode updates pending
    def temperature_update_pending(self):
        return not (self.target_temperature is None)
    def mode_update_pending(self):
        return not (self.target_mode is None)




    def __init__(self):
        # Initialize constants
        self.settings = settings
        self.token = None
        self.msg_queue = Queue()
        self.lock = Lock()
        self.scheduled_request = None
        self.target_mode = None
        self.target_temperature = None
        self.last_set_temperature = None
        self.last_set_mode = None

        self.TOKEN_FILE = settings['netatmo']['token_file']
        self.CLIENT_ID = settings['netatmo']['clientid']
        self.CLIENT_SECRET = settings['netatmo']['clientsecret']
        self.HTTP_SERVER_IPADDRESS = settings['oauth_code_endpoint']['ipaddress']
        self.HTTP_SERVER_PORT = settings['oauth_code_endpoint']['port']
        self.NETATMO_TOKEN_URL = "https://api.netatmo.com/oauth2/token"
        self.TOKEN_CONFIRMATION_URL = "http://%s:%i/token" % (self.HTTP_SERVER_IPADDRESS, self.HTTP_SERVER_PORT)
        self.AUTHORIZE_URL = "https://api.netatmo.com/oauth2/authorize?client_id=%s&scope=read_smarther%%20write_smarther&redirect_uri=%s" % (self.CLIENT_ID, self.TOKEN_CONFIRMATION_URL)

        self.BASE_URL = "https://api.netatmo.com/api/"
        self.HOMESDATA = "homesdata"
        self.HOMESTATUS = "homestatus"
        self.SETSTATE = "setstate"

        self.load_token_from_file()
