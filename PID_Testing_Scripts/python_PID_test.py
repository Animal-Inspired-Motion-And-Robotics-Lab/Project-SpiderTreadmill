# This script is a script that implements the PID control algorithm on the Raspberry Pi

# import required libraries
import time
import threading
import queue
import RPi.GPIO as GPIO
from math import pi
from single_tb9051ftg_rpi import Motor, Motors, MAX_SPEED

# Ensure the GPIO is using BCM numbering
GPIO.setmode(GPIO.BCM)

# Create the Motor and Motors objects
motor1 = Motor(pwm1_pin=12, pwm2_pin=13, en_pin=4, enb_pin=5, diag_pin=6)
motors = Motors(motor1)

# Define and set up pins for the encoder
ENCA = 23
ENCB = 24
GPIO.setup(ENCA, GPIO.IN)
GPIO.setup(ENCB, GPIO.IN)

# Create a queue to pass user-defined treadmill speeds to the main thread
q = queue.Queue()

# Create global variables required for the script
pos_i = 0                       # variable that stores the encoder position from the interrupt function
pos_prev = 0                    # variable that stores the previous position of the motor shaft (used to calculate motor vel)
time_prev = time.perf_counter() # variable that stores the previous time for the motor speed calculation
deltaT = 0                      # variable that stores the difference in time between two executions of the motor velocity calculation function
err_prev = 0                    # variable that stores the error from the previous iteration of PID function (used for the integral and derivative terms)
err_sum = 0                     # variable that stores the integral sum of the error for the integral term of the PID
u_prev = 0                      # variable that stores the previous control signal sent to the motor (used to generate new control signal)
speed_des = 0                   # variable that stores the desired speed from the user (default at 0 speed)

# Create function to calculate the motor velocity
def calcMotorVelocity():
    global pos_prev, pos_i, time_prev, deltaT

    # calculate motor velocity (in counts/second)
    pos_curr = pos_i
    time_curr = time.perf_counter()
    deltaT = time_curr - time_prev
    velocity = (pos_curr - pos_prev)/deltaT

    # change the velocity into RPM
    velocity = velocity/116.16*60.0

    # update the previous time and position variables
    pos_prev = pos_curr
    time_prev = time_curr

    return velocity

# Create function to execute the PID controller
def motorPID(desired_vel, meas_vel):
    global err_prev, err_sum, deltaT, u_prev

    # tuning constants
    # NOTE: from testing, it appears that having k_p as 0.1 as the only value works quite well
    k_p = 0.1
    k_i = 0
    k_d = 0

    # NOTE: there is a check for 0 m/s as an input speed because the PID will actually
    #       never send a control signal of "0" and will waste energy sending a voltage
    #       that is not enough to actually power the motor
    if not (desired_vel == 0):
        # calculate the current error between the desired and measured motor speeds
        err = desired_vel - meas_vel

        # calculate the sum of the error for the integral term for the PID
        err_sum = err_sum + (1/2)*(err + err_prev)*deltaT

        # calculate the change in error for the derivative term for the PID
        deltaErr = err - err_prev
    else:
        # here, we set the errors and previous control signal to zero so that we send a command of u = 0
        err = 0
        err_sum = 0
        deltaErr = 0
        u_prev = 0

    # calculate the control signal
    u = k_p*err + k_i*err_sum + k_d*(deltaErr/deltaT) + u_prev

    # update required global variables for the next iteration of the loop
    err_prev = err
    u_prev = u

    return u

# Callback function for the encoder
def readEncoder(channel):
    global pos_i

    # read ENCB when ENCA has been triggered with a rising signal
    b = GPIO.input(ENCB)
    increment = 0
    if (b > 0):
        # if ENCB is HIGH when ENCA is HIGH, motor is moving in negative (CCW) direction
        increment = -1
    else:
        # if ENCB is LOW when ENCA is HIGH, motor is moving in the positive (CW) direction
        increment = 1

    pos_i = pos_i + increment

# function used to change the motor velocity based on the user input and current velocity
def changeMotorVelocity():
    global speed_des

    # NOTE: built into this function is the ability to "ramp" from the current velocity
    #       to the desired velocity to provide smoother transitions between velocities
    #       that also minimize strain of sharp fluctuations of speed on the motor and
    #       the motor driver

    # number of loop iterations for the ramp signal
    iter = 10

    # obtain the current velocity from the motor
    m_vel = calcMotorVelocity()

    # create a variable to store the ramp speed in the loop (starts at the current speed)
    ramp_vel = m_vel

    # determine the increment for the ramp for a loop of 10 iterations
    signal_increment = (speed_des - m_vel)/iter

    # ramp the function from the current m_vel to the desired velocity via a for loop
    for i in range(iter):
        # obtain the ramp velocities
        ramp_vel = ramp_vel + signal_increment

        # use PID function to determine speed to be sent to controller and set that speed
        control_sig = motorPID(ramp_vel, m_vel)

        # send the motor speed
        motor1.setSpeed(control_sig)

        # wait for the motor to react to the control signal
        time.sleep(0.1)

        # reobtain the current speed of the motor for the next iteration of the loop
        m_vel = calcMotorVelocity()

    return control_sig, m_vel           # return final control signal and motor velocity

# Create interrupt to ENCA
GPIO.add_event_detect(ENCA, GPIO.RISING, callback = readEncoder)

# Create function running in child thread that waits for user inputs for speeds
def getUserInput(q):
    # loop that is always waiting for a user input for the speed (running on a separate thread)
    while True:
        try:
            # obtain the user input for the motor speed
            user_input = input('Enter a motor speed in meters/second (range from [-1.5, 1.5] m/s): ')

            # try to turn the input into a float (will throw an exception if it doesn't work)
            user_input = float(user_input)

            # check the number to see if it is in the correct range (0 m/s to 1.5 m/s)
            if not ((user_input >= -1.5) and (user_input <= 1.5)):
                print("The speed you entered is not within the specified range. Please enter a new speed.")
            else:
                q.put(user_input)       # put the user-defined speed on the queue in m/s
                print(f'Current desired speed updated to: {user_input} m/s')

        except ValueError:
            print("You did not enter a number in the correct format (check for any unwanted characters, spaces, etc).")
            print("Please enter your speed again.")

# Create a function that reads the user input from the queue in the main thread and updates the speed_des variable
def readUserInput():
    global speed_des, q

    # determine the desired speed from the user (in m/s) and covert it to RPM
    try:
        speed_des = q.get(block=False)                  # False used to prevent code on waiting for info
        speed_des = speed_des*(60/pi)/(2/39.3701)       # conversion to RPM

    except queue.Empty:
        pass

# Define a custom exception to raise if a fault is detected.
class DriverFault(Exception):
    def __init__(self, driver_num):
        self.driver_num = driver_num

def raiseIfFault():
    if motors.motor1.getFault():
        raise DriverFault(1)

# Main execution loop for the motor
if __name__ == '__main__':

    # create a thread that runs the user input function (obtain user defined speeds)
    # NOTE: This is a daemon thread which allows the thread to be killed when the main program is killed,
    #       or else main thread will not be killed
    user_in_thread = threading.Thread(target=getUserInput, args=(q,), daemon=True)

    # start the user input thread
    user_in_thread.start()

    try:
        while True:
            # test for driver faults
            raiseIfFault()

            # obtain user input for desired velocity if available from the queue
            readUserInput()

            # set the motor speed determined from user input and current motor speeds (ramping included)
            control_sig, m_vel = changeMotorVelocity()

            # print useful information about motor speeds
            print(control_sig, "|", speed_des, "|", m_vel)

    except KeyboardInterrupt:
        print("\nKeyboard Interrupt")

    except DriverFault as e:
        print("Driver %s fault!" % e.driver_num)

    finally:
        GPIO.cleanup()
        print("GPIO pins cleaned up")
        motors.forceStop()
        print("Motors stopped")
        print("Program exited")
