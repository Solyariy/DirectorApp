import os

from dotenv import load_dotenv

load_dotenv()

INVERTER_LOGGER_IP = os.getenv("INVERTER_LOGGER_IP")
INVERTER_LOGGER_SERIAL = int(os.getenv("INVERTER_LOGGER_SERIAL"))
