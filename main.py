import asyncio
import RPi.GPIO as GPIO
import glob
import os
import time
import logging
from datetime import datetime
from configuration.YamlConfigurationHelper import YamlConfigurationHelper
import paho.mqtt.client as mqtt
import json

# Create logger
logger = logging.getLogger(__name__)

shift_sleep = 5e-6

# Shift In - 74HC165
shift_in_data = 17  #  9 The serial data output QH (input to CPU)
shift_in_load = (
    11  #  1 Sift or Load flag 0 = load from parallel, 1 = load from serial (PL)
)
shift_in_clock = 9  #  2 Clock data through shift register (CP)
shift_in_clock_enable = (
    8  # 15 Set low to enable clocking, high to inhibit clocking (CE)
)
shift_in_serial_data = 10  # 10 Serial input (DS)

# Shift out - 74HC565

pb_1 = 7
shutdown = 21

status_led_1 = 19
status_led_2 = 16
status_led_3 = 20
status_led_4 = 26

# Set GPIO mode to use logical pin numbering
GPIO.setmode(GPIO.BCM)

# Disable warning, eg 'Pin already in use, assigned, etc)
GPIO.setwarnings(False)

# Init Shift In (74HC165)
GPIO.setup(shift_in_data, GPIO.IN)
GPIO.setup(shift_in_load, GPIO.OUT)
GPIO.setup(shift_in_clock, GPIO.OUT)
GPIO.setup(shift_in_clock_enable, GPIO.OUT)
GPIO.setup(shift_in_serial_data, GPIO.OUT)

# Load parallel inputs
GPIO.output(shift_in_load, GPIO.LOW)

# Disable clock
GPIO.output(shift_in_clock_enable, GPIO.LOW)

# Set clock low
GPIO.output(shift_in_clock, GPIO.LOW)

# Set serial data low (not used in this test)
GPIO.output(shift_in_serial_data, GPIO.LOW)

# Init Shift Out (74HC565)
shift_out_data = 4  # 14
shift_out_clock = 22  # 11
shift_out_latch = 27  # 12
shift_out_enable = 18  # 13

GPIO.setup(shift_out_data, GPIO.OUT)
GPIO.setup(shift_out_clock, GPIO.OUT)
GPIO.setup(shift_out_latch, GPIO.OUT)
GPIO.setup(shift_out_enable, GPIO.OUT)

GPIO.output(shift_out_data, GPIO.LOW)
GPIO.output(shift_out_clock, GPIO.LOW)
GPIO.output(shift_out_latch, GPIO.LOW)
GPIO.output(shift_out_enable, GPIO.HIGH)

GPIO.setup(pb_1, GPIO.IN)
GPIO.setup(shutdown, GPIO.IN)

GPIO.setup(status_led_1, GPIO.OUT)
GPIO.setup(status_led_2, GPIO.OUT)
GPIO.setup(status_led_3, GPIO.OUT)
GPIO.setup(status_led_4, GPIO.OUT)

GPIO.output(status_led_1, GPIO.HIGH)
GPIO.output(status_led_2, GPIO.HIGH)
GPIO.output(status_led_3, GPIO.HIGH)
GPIO.output(status_led_4, GPIO.HIGH)


# Enable 1 wire bus on GPIO 2
# nano /boot/config.txt
# [all]
# dtoverlay=w1-gpio,gpiopin=2

os.system("modprobe w1-gpio")
os.system("modprobe w1-therm")

base_dir = "/sys/bus/w1/devices/"
device_folder1 = glob.glob(base_dir + "28*")[0]
device_file1 = device_folder1 + "/w1_slave"
device_folder2 = glob.glob(base_dir + "28*")[1]
device_file2 = device_folder2 + "/w1_slave"

temp_1 = 0
temp_2 = 0
temp_avg = 0

temp_sp = 10
temp_pb = 1.5

heater_on = 0
heater_enabled = False

def init_mqtt(config) -> mqtt.Client:
    unacked_publish = set()
    mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    mqttc.user_data_set(unacked_publish)
    mqttc.username_pw_set(
        username=config["mqtt"]["user"], password=config["mqtt"]["password"]
    )
    
    # Assign the callback functions
    mqttc.on_connect = on_connect
    mqttc.on_message = on_message
        
    mqttc.connect(config["mqtt"]["host"], config["mqtt"]["port"])
        
    mqttc.loop_start()
    return mqttc

def read_temp_raw1():
    f = open(device_file1, "r")
    lines = f.readlines()
    f.close()
    return lines


def read_temp_raw2():
    f = open(device_file2, "r")
    lines = f.readlines()
    f.close()
    return lines


def read_temp1():
    lines = read_temp_raw1()
    while lines[0].strip()[-3:] != "YES":
        time.sleep(0.2)
        lines = read_temp_raw1()
    equals_pos = lines[1].find("t=")
    if equals_pos != -1:
        temp_string = lines[1][equals_pos + 2 :]
        temp_c = float(temp_string) / 1000.0
        return temp_c


def read_temp2():
    lines = read_temp_raw2()
    while lines[0].strip()[-3:] != "YES":
        time.sleep(0.2)
        lines = read_temp_raw2()
    equals_pos = lines[1].find("t=")
    if equals_pos != -1:
        temp_string = lines[1][equals_pos + 2 :]
        temp_c = float(temp_string) / 1000.0
        return temp_c


def shift_in():
    # Latch parallel data into shift register
    GPIO.output(shift_in_load, GPIO.LOW)
    time.sleep(shift_sleep)
    GPIO.output(shift_in_load, GPIO.HIGH)

    val = 0
    for bit_number in range(8):
        # Sample bit value
        input_value = GPIO.input(shift_in_data)
        print("input_value: " + format(input_value, "b"))

        # Clock input value
        GPIO.output(shift_in_clock, GPIO.HIGH)

        # Let settle
        time.sleep(shift_sleep)

        # Set clock low again
        GPIO.output(shift_in_clock, GPIO.LOW)

        # Move bit to correct position
        val = val | input_value << (7 - bit_number)

    return val


def shift_out(data):
    GPIO.output(shift_out_latch, GPIO.LOW)

    for i in range(8):
        bit = (0x80 >> i) & data

        GPIO.output(shift_out_data, bit)
        GPIO.output(shift_out_clock, GPIO.HIGH)
        time.sleep(shift_sleep)
        GPIO.output(shift_out_clock, GPIO.LOW)

    GPIO.output(shift_out_latch, GPIO.HIGH)
    GPIO.output(shift_out_enable, GPIO.LOW)

    return


def on_connect(client, userdata, flags, reasonCode, properties):
    global config
    
    print(f'Connected to \'{config["mqtt"]["host"]}\' with result code: {reasonCode}')
    # Subscribe to the topic upon connecting
    client.subscribe("dog/settings")

# Callback when a PUBLISH message is received from the server
def on_message(client, userdata, msg):
    global temp_sp 
    global temp_pb
    global heater_enabled

    try:
        payload = msg.payload.decode('utf-8')
        data = json.loads(payload)
        temp_sp = data['temperatureSetpoint']
        temp_pb = data['temperatureProportionalBand']
        heater_enabled = data['enabled']
    except json.JSONDecodeError as e:
        print(f"Failed to decode JSON: {e}")
    except KeyError as e:
        print(f"Missing expected key: {e}")
    

async def mqtt_state_loop(mqttc: mqtt.Client):
    global temp_1
    global temp_2
    global temp_avg
    global heater_on
    global heater_enabled
    global temp_sp 
    global temp_pb

    while True:
        logger.debug('Posting MQTT')
        
        payload = {
            "temperature1": temp_1,
            "temperature2": temp_2,
            "temperatureAvgerage": temp_avg,
            "temperatureSetpoint": temp_sp,
            "temperatureProportionalBand": temp_pb,
            "heaterOn": True if heater_on == 1 else False,
            "enabled": heater_enabled
        }
        
        json_payload = json.dumps(payload)        
        msg_info = mqttc.publish(f"dog/status", json_payload, qos=0)
        unacked_publish = set()
        unacked_publish.add(msg_info.mid)
        msg_info.wait_for_publish()
        
        await asyncio.sleep(5)

async def heater_loop():
    global temp_1
    global temp_2
    global temp_avg
    global heater_on
    global heater_enabled
    global temp_sp 
    global temp_pb

    while True:

        while True:
            temp_1 = read_temp1()
            temp_2 = read_temp2()
            temp_avg = (temp_1 + temp_2) / 2

                
            # Make sure heater is off if disabled
            if(not heater_enabled):
                heater_on = 0
            elif temp_avg < temp_sp:
                heater_on = 1
            elif temp_avg >= (temp_sp + temp_pb):
                heater_on = 0

            shift_out(heater_on)

            GPIO.output(status_led_1, GPIO.HIGH)
            time.sleep(1)
            GPIO.output(status_led_1, GPIO.LOW)

            pb_1_val = GPIO.input(pb_1)

            if pb_1_val:
                GPIO.output(status_led_3, GPIO.LOW)
            else:
                GPIO.output(status_led_3, GPIO.HIGH)

            shutdown_val = GPIO.input(shutdown)

            if shutdown_val:
                GPIO.output(status_led_2, GPIO.LOW)
                GPIO.output(status_led_4, GPIO.LOW)
            else:
                GPIO.output(status_led_2, GPIO.HIGH)
                GPIO.output(status_led_4, GPIO.HIGH)

            await asyncio.sleep(5)


async def main():
    global config
    
    try:
        # Read configuration
        configHelper = YamlConfigurationHelper("config.yaml", "config.debug.yaml")
        config = await configHelper.read()

        # Configure logging
        # log_levels = logging.getLevelNamesMapping()
        # log_level = log_levels[config["logging"]["level"]]
        logging.basicConfig(filename=config["logging"]["file-name"], level="DEBUG")

        mqttc = init_mqtt(config)
        
        alarm_task = asyncio.create_task(heater_loop())
        mqtt_state_task = asyncio.create_task(mqtt_state_loop(mqttc))
               
        # Loop forever
        await asyncio.wait([alarm_task, mqtt_state_task])
    except Exception as e:
        logging.error("Error at %s", exc_info=e)
    finally:
        GPIO.cleanup()
        logger.debug("All tasks have completed")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as ex:
        logger.error(f"Exec error: '{ex}'")