import RPi.GPIO as GPIO
import time

GPIO.setmode(GPIO.BCM)

# Buttons on PINs 9, 10 and 11
GPIO.setup(9, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(10, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(11, GPIO.IN, pull_up_down=GPIO.PUD_UP)

try:
    print('Start button test - End with Ctrl-C')
    
    while True:
        if (GPIO.input(10) == False):
            print('Button 1 (PREV)')
    
        if (GPIO.input(9) == False):
            print('Button 2 (PLAY/PAUSE)')
    
        if (GPIO.input(11) == False):
            print('Button 3 (NEXT)')
    
        time.sleep(0.25)
    
except KeyboardInterrupt:
    print('bye')
    GPIO.cleanup()

