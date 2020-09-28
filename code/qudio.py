# piplayer4 - Qudio
# http://www.tilman.de/projekte/qudio

import RPi.GPIO as GPIO
import logging
import time
import subprocess
import select  # for polling zbarcam, see http://stackoverflow.com/a/10759061/3761783
from socketIO_client import SocketIO, LoggingNamespace # see https://gist.github.com/ivesdebruycker/4b08bdd5415609ce95e597c1d28e9b9e
from threading import Thread
import os
import fcntl


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s - %(message)s')
logging.info('Initializing')

# Configuration
MUSIC_BASE_DIRECTORY = "mnt/"
this_dir = os.path.dirname(__file__)
if this_dir.startswith("/data/"): this_dir = MUSIC_BASE_DIRECTORY + this_dir[6:]
SOUND_SCANNING = os.path.join(this_dir, "sounds/scanning.mp3")
SOUND_SCAN_FAIL = os.path.join(this_dir, "sounds/fail-05.mp3")
QR_SCANNER_TIMEOUT = 4

# photo sensor on PIN 5
PIN_SENSOR = 5

# LED on PIN 22
PIN_LED = 22

# Buttons on PINs 9, 10 and 11
PIN_PREV = 10
PIN_PLAY = 9
PIN_NEXT = 11


status_is_playing = False # for toggling play/pause (stores the current status from the pushState events)
status_seek_pos = 0       # for seek +/- 10
status_duration = 0       # for maximum seek

socketIO = SocketIO('localhost', 3000)


def send_to_volumio(*args):
    logging.info("Sending to Volumio: {}".format(args))
    socketIO.emit(*args)

def play(uri, service = 'mpd', startPlaying = True):
    if startPlaying:
        send_to_volumio('replaceAndPlay', {'service':service,'uri':uri})
    else:
        send_to_volumio('clearQueue')
        send_to_volumio('addToQueue', {'service':service,'uri':uri})


def seek(step_seconds):
    # nanosound_cd will not accept fractions of seconds
    new_pos = round(status_seek_pos + step_seconds)
    if 0 <= new_pos <= status_duration:
        send_to_volumio('seek', new_pos)


GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_SENSOR, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(PIN_LED, GPIO.OUT)
GPIO.output(PIN_LED, GPIO.LOW)

button_short_press_commands = {
    PIN_PREV: lambda: send_to_volumio('prev'),
    PIN_PLAY: lambda: send_to_volumio('pause' if status_is_playing else 'play'),
    PIN_NEXT: lambda: send_to_volumio('next')
}
button_long_press_commands = {
    PIN_PREV: lambda down_secs: seek(-5 * down_secs),
    PIN_PLAY: lambda down_secs: send_to_volumio('stop'),
    PIN_NEXT: lambda down_secs: seek(5 * down_secs)
}

def button_callback(channel):
    time_button_down = time.time()
    # 0.5 + 0.5 = 1 second delay for first long action
    time_last_long_action = time_button_down + 0.5
    while GPIO.input(channel) == GPIO.LOW:
        # 0.5 seconds delay between subsequent long actons
        if time.time() - time_last_long_action > 0.5:
            button_long_press_commands.get(channel)(time.time() - time_button_down)
            time_last_long_action = time.time()
        time.sleep(0.1)
    # also ignore spurious triggers that sometimes seem to happen after a long press
    if 0.2 <= time.time() - time_button_down < 1:
        button_short_press_commands.get(channel)()

for pin in (PIN_PLAY, PIN_PREV, PIN_NEXT):
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(pin, GPIO.FALLING, callback=button_callback, bouncetime=400)


def on_pushState(*args):
    if len(args) == 1:
        volumio_status = args[0]
        logging.debug(volumio_status)
        try:
            global status_is_playing
            status_is_playing = volumio_status['status'] == 'play'
            logging.debug("status_is_playing: {}".format(status_is_playing))
        except Exception as e: logging.debug(e)
        try:
            global status_seek_pos
            status_seek_pos = volumio_status['seek'] / 1000
            logging.debug("status_seek_pos: {}".format(status_seek_pos))
        except Exception as e: logging.debug(e)
        try:
            global status_duration
            status_duration = volumio_status['duration']
            logging.debug("status_duration: {}".format(status_duration))
        except Exception as e: logging.debug(e)

def events_thread():
    socketIO.wait()


def cdrom_thread():

    def detect_tray():
        """
        detect_tray reads status of the first cd rom drive and returns:
        1 = no disk in tray
        2 = tray open
        3 = reading tray
        4 = disk in tray
        """
        try:
            fd = os.open('/dev/sr0', os.O_RDONLY | os.O_NONBLOCK)
            rv = fcntl.ioctl(fd, 0x5326)
            os.close(fd)
        except:
            rv = 0
        return rv

    """
    regularily check cd rom and start playing if cd is inserted
    """
    dt_old = -1
    while True:
        dt = detect_tray()
        logging.debug("detect_tray() result: {}".format(dt))
        if dt != dt_old and dt == 4:
            # on first startup only queue but no auto play
            play('nanosound_cd/playall', 'nanosound_cd', startPlaying = dt_old != -1)
        time.sleep(1)
        dt_old = dt


try:
    socketIO.on('pushState', on_pushState)
    listener_thread = Thread(target=events_thread)
    listener_thread.daemon = True
    listener_thread.start()

    Thread(target=cdrom_thread, daemon=True).start()

    while True:
        logging.info('Wait for photo sensor')
        GPIO.wait_for_edge(PIN_SENSOR, GPIO.FALLING)
        
        logging.info('Photo sensor active, activating light and camera')
        play(SOUND_SCANNING)
        
        # turn LED on
        GPIO.output(PIN_LED, GPIO.HIGH)
        
        # scan QR code
        zbarcam = subprocess.Popen(['zbarcam', '--quiet', '--nodisplay', '--raw', '-Sdisable', '-Sqrcode.enable', '--prescale=320x240', '/dev/video0'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        poll_obj = select.poll()
        poll_obj.register(zbarcam.stdout, select.POLLIN)
        
        # wait for scan result (or timeout)
        start_time = time.time()
        poll_result = False
        while ((time.time() - start_time) < QR_SCANNER_TIMEOUT and (not poll_result)):
            poll_result = poll_obj.poll(100)

        if (poll_result):
            qr_code = zbarcam.stdout.readline().rstrip()
            qr_code = qr_code.decode("utf-8") # python3
            logging.info("QR Code: " + qr_code)
            
            if qr_code.startswith("http://") or qr_code.startswith("https://"):
                play(qr_code, 'webradio')
            elif qr_code.startswith("spotify:"):
                play(qr_code, 'spop')
            else:
                # create full path
                if (qr_code.startswith("/")):
                    qr_code = qr_code[1:]
                full_path = MUSIC_BASE_DIRECTORY + qr_code
                logging.debug("full_path: " + full_path)
                play(full_path)
            
        else:
            logging.warning('Timeout on zbarcam')
            play(SOUND_SCAN_FAIL)
            
        zbarcam.terminate()
        GPIO.output(PIN_LED, GPIO.LOW)

        # wait until sensor is not blocked anymore
        if (GPIO.input(PIN_SENSOR) == GPIO.LOW):
            GPIO.wait_for_edge(PIN_SENSOR, GPIO.RISING)
            time.sleep(1)

        
# Exit when Ctrl-C is pressed
except KeyboardInterrupt:
    logging.info('Shutdown')
    
finally:
    logging.info('Reset GPIO configuration and close')
    GPIO.cleanup()
