# piplayer4 - Qudio
# http://www.tilman.de/projekte/qudio

import RPi.GPIO as GPIO
import logging
import time
import subprocess
import select  # for polling zbarcam, see http://stackoverflow.com/a/10759061/3761783
from socketIO_client import SocketIO, LoggingNamespace # see https://gist.github.com/ivesdebruycker/4b08bdd5415609ce95e597c1d28e9b9e
from threading import Thread


logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s - %(message)s')
logging.info('Initializing')

# Configuration
MUSIC_BASE_DIRECTORY = "mnt/"
SOUND_SCANNING = "mnt/INTERNAL/qudio/sounds/scanning.mp3"
SOUND_SCAN_FAIL = "mnt/INTERNAL/qudio/sounds/fail-05.mp3"
QR_SCANNER_TIMEOUT = 4

# photo sensor on PIN 5
PIN_SENSOR = 5

# LED on PIN 22
PIN_LED = 22

# Buttons on PINs 9, 10 and 11
PIN_PREV = 10
PIN_PLAY = 9
PIN_NEXT = 11


GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_SENSOR, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(PIN_LED, GPIO.OUT)
GPIO.output(PIN_LED, GPIO.LOW)
GPIO.setup(PIN_PREV, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(PIN_PLAY, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(PIN_NEXT, GPIO.IN, pull_up_down=GPIO.PUD_UP)


status_is_playing = False # for toggling play/pause (stores the current status from the pushState events)
status_seek_pos = 0       # for seek +/- 10
status_duration = 0       # for maximum seek

socketIO = SocketIO('localhost', 3000)


def play(uri, service = 'mpd'):
    socketIO.emit('replaceAndPlay', {'service':service,'uri':uri})

def button_play_callback(channel):
    if GPIO.input(channel) == GPIO.LOW: # ignore spurious triggers that seem to happen after a long press
        time_button_pressed = time.time()
        while GPIO.input(channel) == GPIO.LOW:
            if time.time() - time_button_pressed > 1:
                logging.info("STOP")
                socketIO.emit('stop')
                break
            time.sleep(0.1)
        duration_pressed = time.time() - time_button_pressed
        if duration_pressed > 0.2 and duration_pressed < 1:
            if status_is_playing:
                logging.info("PAUSE")
                socketIO.emit('pause')
            else:
                logging.info("PLAY")
                socketIO.emit('play')

def button_prev_next_callback(channel):
    if GPIO.input(channel) == GPIO.LOW: # ignore spurious triggers that seem to happen after a long press
        time_button_pressed = time.time()
        time_seek = time_button_pressed
        while GPIO.input(channel) == GPIO.LOW:
            if time.time() - time_seek > 1:
                if channel == PIN_PREV:
                    new_pos = status_seek_pos - 10
                elif channel == PIN_NEXT:
                    new_pos = status_seek_pos + 10
                if new_pos >= 0 and new_pos <= status_duration:
                    logging.info("seek {}".format(new_pos))
                    socketIO.emit('seek', new_pos)
                time_seek = time.time()
            time.sleep(0.1)
        if time.time() - time_button_pressed < 1:
            if channel == PIN_PREV:
                logging.info("PREV")
                socketIO.emit('prev')
            elif (channel == PIN_NEXT):
                logging.info("NEXT")
                socketIO.emit('next')

def on_pushState(*args):
    logging.debug(args[0])
    global status_is_playing
    if args[0]['status'] == 'play':
        status_is_playing = True
    else:
        status_is_playing = False
    global status_seek_pos
    if isinstance(args[0]['seek'], int):
        status_seek_pos = args[0]['seek'] / 1000
    global status_duration
    if isinstance(args[0]['duration'], int):
        status_duration = args[0]['duration']

def events_thread():
    socketIO.wait()


GPIO.add_event_detect(PIN_PLAY, GPIO.FALLING, callback=button_play_callback, bouncetime=400)
GPIO.add_event_detect(PIN_PREV, GPIO.FALLING, callback=button_prev_next_callback, bouncetime=400)
GPIO.add_event_detect(PIN_NEXT, GPIO.FALLING, callback=button_prev_next_callback, bouncetime=400)


try:
    socketIO.on('pushState', on_pushState)
    listener_thread = Thread(target=events_thread)
    listener_thread.daemon = True
    listener_thread.start()

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
