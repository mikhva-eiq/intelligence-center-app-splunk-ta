"""Create Sighting Workflow Action."""
import datetime
import json
import logging
import logging.handlers
import os
import sys
import traceback

import requests
import splunk
from splunk.clilib import cli_common as cli
from splunk.persistconn.application import PersistentServerConnectionApplication

(path, _) = os.path.split(os.path.realpath(__file__))
sys.path.insert(0, path)
import ta_eclecticiq_declare  # noqa pylint: disable=C0413,W0611
from constants.defaults import (  # pylint: disable=C0413
    ACCOUNTS_CONF,
    LOCAL_DIR,
    SETTINGS_CONF,
)  # pylint: disable=C0413
from constants.general import (  # pylint: disable=C0413
    AUTHORIZATION,
    CREDS,
    HEADERS,
    PAYLOAD,
    PROXY,
    PROXY_PASSWORD,
    STATUS_STR,
    URL,
)  # pylint: disable=C0413
from constants.messages import (
    API_ERROR,
    COULD_NOT_CREATE_SIGHTING,
    CREDS_NOT_FOUND,
    EVENTS_RESPONSE_ERROR_CODE,
    REQUEST_FAILED,
    SIGHTING_CREATED,
)  # pylint: disable=C0413
from constants.sighting_right_click import (
    CONFIDENCE,
    CONFIDENCE_LEVEL,
    CONTENT_TYPE,
    DATA_STR,
    DESCRIPTION,
    INGEST_TIME,
    INPUT_NAME,
    META,
    SECURITY_CONTROL,
    SIGHTING_DESC,
    SIGHTING_SCHEMA,
    SIGHTING_TAGS,
    SIGHTING_TITLE,
    SIGHTING_TYPE,
    SIGHTING_VALUE,
    START_TIME,
    TAGS,
    TEXT_PLAIN,
    TIME,
    TIME_FORMAT,
    TIMESTAMP_STR,
    TITLE,
    TYPE,
    VALUE,
)  # pylint: disable=C0413
from utils.formatters import format_proxy_uri  # pylint: disable=C0413

if sys.platform == "win32":
    import msvcrt

    # Binary mode is required for persistent mode on Windows.
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)  # pylint: disable=E1101
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)  # pylint: disable=E1101
    msvcrt.setmode(sys.stderr.fileno(), os.O_BINARY)  # pylint: disable=E1101

# Setup logging
logger = logging.getLogger("splunk.eiq")
SPLUNK_HOME = os.environ["SPLUNK_HOME"]

LOGGING_DEFAULT_CONFIG_FILE = os.path.join(SPLUNK_HOME, "etc", "log.cfg")
LOGGING_LOCAL_CONFIG_FILE = os.path.join(SPLUNK_HOME, "etc", "log-local.cfg")
LOGGING_STANZA_NAME = "python"
LOGGING_FILE_NAME = "ta_eclecticiq_create_sighting.log"
BASE_LOG_PATH = os.path.join("var", "log", "splunk")
LOGGING_FORMAT = "%(asctime)s %(levelname)-s\t%(module)s:%(lineno)d - %(message)s"
splunk_log_handler = logging.handlers.RotatingFileHandler(
    os.path.join(SPLUNK_HOME, BASE_LOG_PATH, LOGGING_FILE_NAME), mode="a"
)
splunk_log_handler.setFormatter(logging.Formatter(LOGGING_FORMAT))
logger.addHandler(splunk_log_handler)
splunk.setupSplunkLogger(
    logger, LOGGING_DEFAULT_CONFIG_FILE, LOGGING_LOCAL_CONFIG_FILE, LOGGING_STANZA_NAME
)


class Send(PersistentServerConnectionApplication):  # type: ignore
    """Sends the sighting to EclecticIQ Platform."""

    def __init__(self, command_line, command_arg):  # pylint: disable=W0613
        PersistentServerConnectionApplication.__init__(self)

    @staticmethod
    def parse_form_data(form_data):
        """Parse the payload.

        :param form_data: payload of the request
        :type form_data: dict
        """
        parsed = {}
        for [key, value] in form_data:
            parsed[key] = value
        return parsed

    @staticmethod
    def send_request(url, headers, proxy, sighting):
        """Send an API request to the URL provided with headers and parameters.

        :param url: API URL to send request
        :type url: str
        :param headers: Headers to be included in the request
        :type headers: dict
        :param proxy: proxy details to be included in the request
        :type proxy: dict
        :param sighting: payload of sighting
        :type sighting: dict
        :return: API response
        :rtype: dict
        """
        if proxy.get("proxy_enabled") == "1":
            proxy_settings = format_proxy_uri(proxy)
        else:
            proxy_settings = None
        try:
            response = requests.request(
                "post",
                url,
                headers=headers,
                data=json.dumps(sighting),
                verify=True,
                timeout=50,
                proxies=proxy_settings,
            )
            response.raise_for_status()
        except requests.exceptions.HTTPError as err:
            if str(response.status_code).startswith("5"):
                logger.critical(API_ERROR.format(input=INPUT_NAME, err=err))
                logger.critical(
                    EVENTS_RESPONSE_ERROR_CODE.format(
                        input=INPUT_NAME,
                        code=response.status_code,
                        error=str(response.content),
                    )
                )
            else:
                logger.error(API_ERROR.format(input=INPUT_NAME, err=err))
                logger.error(
                    EVENTS_RESPONSE_ERROR_CODE.format(
                        input=INPUT_NAME,
                        code=response.status_code,
                        error=str(response.content),
                    )
                )
            raise err
        except requests.exceptions.ConnectionError as err:
            logger.error(API_ERROR.format(input=INPUT_NAME, err=err))
            raise err
        except requests.exceptions.Timeout as err:
            logger.error(API_ERROR.format(input=INPUT_NAME, err=err))
            raise err
        except requests.exceptions.RequestException as err:
            logger.error(API_ERROR.format(input=INPUT_NAME, err=err))
            logger.error(
                EVENTS_RESPONSE_ERROR_CODE.format(
                    input=INPUT_NAME,
                    code=response.status_code,
                    error=str(response.content),
                )
            )
            raise err
        except Exception as err:
            logger.error(traceback.format_exc())
            raise err
        return response

    @staticmethod
    def create_response(status, message):
        """Create response to send back to JS.

        :param status: status code
        :type status: int
        :param message: message to send
        :type message: str
        :return: response dict
        :rtype: dict
        """
        return {
            PAYLOAD: message,
            STATUS_STR: status,
            HEADERS: {CONTENT_TYPE: TEXT_PLAIN},
        }

    @staticmethod
    def get_url(api_conf_path):
        """Get the URL from accounts.conf.

        :param api_conf_path: path to the conf file
        :type api_conf_path: str
        :return: URL value from the conf
        :rtype: str
        """
        apikeyconf = {}
        if os.path.exists(api_conf_path):
            localconf = cli.readConfFile(api_conf_path)
            for name, content in localconf.items():
                if name != "default":
                    account_name = name
                if name in apikeyconf:
                    apikeyconf[name].update(content)
                else:
                    apikeyconf[name] = content
            return apikeyconf[account_name][URL]

    @staticmethod
    def get_proxy(settings_conf_path):
        """Get the proxy from settings.conf.

        :param settings_conf_path: path to the conf file
        :type settings_conf_path: str
        :return: proxy information from the conf
        :rtype: dict
        """
        if os.path.exists(settings_conf_path):
            localsettingsconf = cli.readConfFile(settings_conf_path)
            for stanza, fields in localsettingsconf.items():
                if stanza == PROXY:
                    return fields

    @staticmethod
    def handle(in_string):
        """Handle request made to the endpoint services/create_sighting.

        :param self: Object of the class
        :type in_string: Send
        :param in_string: Payload of the request in string
        :type in_string: str
        :return: Response to be send
        :rtype: dict
        """
        logger.info("Request received.")
        in_dict = json.loads(in_string)
        appdir = os.path.dirname(os.path.dirname(__file__))
        localconfpath = os.path.join(appdir, LOCAL_DIR, ACCOUNTS_CONF)
        url = Send.get_url(localconfpath)
        localsettings_conf = os.path.join(appdir, LOCAL_DIR, SETTINGS_CONF)
        settingsconf = {}
        settingsconf[PROXY] = Send.get_proxy(localsettings_conf)
        payload = Send.parse_form_data(in_dict["form"])
        today = datetime.datetime.utcnow().date()
        sighting = SIGHTING_SCHEMA
        time = datetime.datetime.utcnow()
        api_key = payload.get(CREDS)
        if not api_key:
            return Send.create_response(401, CREDS_NOT_FOUND)
        proxy_pass = payload.get("proxy_pass") if payload.get("proxy_pass") else ""
        if settingsconf[PROXY]:
            settingsconf[PROXY][PROXY_PASSWORD] = proxy_pass
        sighting[DATA_STR][DATA_STR][VALUE] = payload[SIGHTING_VALUE]
        sighting[DATA_STR][DATA_STR][DESCRIPTION] = payload[SIGHTING_DESC]
        sighting[DATA_STR][DATA_STR][TIMESTAMP_STR] = datetime.datetime.strftime(
            time, TIME_FORMAT
        )
        sighting[DATA_STR][DATA_STR][CONFIDENCE] = payload[CONFIDENCE_LEVEL]
        sighting[DATA_STR][DATA_STR][TITLE] = payload[SIGHTING_TITLE]
        sighting[DATA_STR][META][TAGS] = [
            "".join(i for i in list(payload[SIGHTING_TAGS]))
        ]
        sighting[DATA_STR][DATA_STR][SECURITY_CONTROL][TYPE] = payload[SIGHTING_TYPE]
        sighting[DATA_STR][DATA_STR][SECURITY_CONTROL][TIME][
            START_TIME
        ] = datetime.datetime.strftime(
            datetime.datetime(today.year, today.month, today.day, 0, 0, 0),
            TIME_FORMAT,
        )
        sighting[DATA_STR][META][INGEST_TIME] = datetime.datetime.strftime(
            time, TIME_FORMAT
        )
        headers = {AUTHORIZATION: f"Bearer {api_key}"}
        try:
            response = Send.send_request(
                url + "/entities", headers, settingsconf[PROXY], sighting
            )
        except Exception as err:
            return Send.create_response(500, err)
        if not (str(response.status_code)).startswith("2"):
            logger.info(REQUEST_FAILED)
            return Send.create_response(response.status_code, COULD_NOT_CREATE_SIGHTING)
        content = json.loads(response.content)
        message = SIGHTING_CREATED.format(url, content[DATA_STR]["id"])
        logger.info(message)
        return Send.create_response(response.status_code, message)
