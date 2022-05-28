# Script used to test the Adafruit Bonnet motor driver
# NOTE: This script includes code for both the DC motor and stepper motors
# Comment out the right script for any tests

# import relevant libraries
import time
import board
from adafruit_motorkit import MotorKit

#----- Code for the DC motor ---------#
# create driver object
kit = MotorKit(i2c=board.I2C())

# run motor at full speed for 0.5 seconds
kit.motor1.throttle = 1.0
time.sleep(0.5)

# stop the motor
kit.motor1.throttle = 0
#-------------------------------------#

# TODO: Include the stepper motor test code 