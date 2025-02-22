import time
import serial.tools.list_ports
from threading import Event
import matplotlib.pyplot as plt
import math
import yaml


def load_config(config_path, model_name):
    """Load configuration for a specific machine model"""
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    return config['machines'][model_name]
    print(f"Configuration loaded for {model_name}.")


def find_port():
    # Get list of available serial ports
    ports = serial.tools.list_ports.comports()

    if not ports:
        raise Exception("No serial ports found! Check your connection.")

    if len(ports) == 1:
        print(f"Automatically selected only available port: {ports[0].device}")
        return ports[0].device

    # If multiple ports found, try to identify the CNC
    print("Found multiple ports. Attempting to detect CNC...")
    for port in ports:
        try:
            # Try to communicate with CNC
            with serial.Serial(port.device, baudrate=115200, timeout=0.5) as ser:
                ser.write(b"\r\n\r\n")  # Wake up command
                time.sleep(1)
                ser.write(b"$$\n")  # Request settings (common CNC command)
                response = ser.read_all().decode()

                if 'ok' in response.lower() or 'grbl' in response.lower():
                    print(f"CNC detected on port: {port.device}")
                    return port.device
        except Exception as e:
            continue

    raise Exception("Could not automatically detect CNC port. Please check connections.")


class CNC_Simulator:
    def __init__(self, config):
        sim_config = config['simulator']
        self.MIN_X = sim_config['min_x']
        self.MAX_X = sim_config['max_x']
        self.MIN_Y = sim_config['min_y']
        self.MAX_Y = sim_config['max_y']
        self.figure_size = sim_config['figure_size']
        plt.figure(figsize=self.figure_size)
        plt.xlim((self.MIN_X, self.MAX_X))
        plt.ylim((self.MIN_Y, self.MAX_Y))
        self.current_x = 0
        self.current_y = 0
        self.MARKER_UP = True

    def move_to_point(self, X, Y):
        if self.MIN_X <= X <= self.MAX_X and self.MIN_Y <= Y <= self.MAX_Y:
            if not self.MARKER_UP:
                plt.plot([self.current_x, X], [self.current_y, Y], 'bo', linestyle="--")
            self.current_x = X
            self.current_y = Y
        else:
            print("Point out of bounds")

    def move_down(self):
        self.MARKER_UP = False

    def move_up(self):
        self.MARKER_UP = True

    def render_drawing(self):
        plt.show()


class CNC_Controller:
    def __init__(self, port, config):
        ctrl_config = config['controller']
        self.BAUD_RATE = ctrl_config['baud_rate']
        self.SERIAL_PORT_PATH = port
        self.X_LOW_BOUND = ctrl_config['x_low_bound']
        self.X_HIGH_BOUND = ctrl_config['x_high_bound']
        self.Y_LOW_BOUND = ctrl_config['y_low_bound']
        self.Y_HIGH_BOUND = ctrl_config['y_high_bound']
        self.Z_LOW_BOUND = ctrl_config['z_low_bound']
        self.Z_HIGH_BOUND = ctrl_config['z_high_bound']
        self.X_OFFSET = ctrl_config['x_offset']
        self.Y_OFFSET = ctrl_config['y_offset']
        self.gcode = ""

    def home_xyz(self):
        """Home all axes using machine's homing cycle"""
        with serial.Serial(self.SERIAL_PORT_PATH, self.BAUD_RATE) as ser:
            self.wake_up(ser)
            # Send homing command (Grbl-specific: $H)
            ser.write(b"$H\n")
            self.wait_for_movement_completion(ser, "$H")
            print("Homing completed")

    def read_coordinates(self):
        """Read current machine coordinates"""
        with serial.Serial(self.SERIAL_PORT_PATH, self.BAUD_RATE) as ser:
            self.wake_up(ser)
            ser.reset_input_buffer()
            ser.write(b"?\n")
            time.sleep(0.1)  # Wait for response
            response = ser.readline().decode().strip()

            # Parse position from response (format: <...|MPos:x,y,z|...>)
            if 'MPos:' in response:
                mpos_start = response.find('MPos:') + 5
                mpos_end = response.find('|', mpos_start)
                coordinates = list(map(float, response[mpos_start:mpos_end].split(',')))
                return {'X': coordinates[0], 'Y': coordinates[1], 'Z': coordinates[2]}
            return None

    def wait_for_movement_completion(self, ser, cleaned_line):
        Event().wait(1)
        if cleaned_line != '$X' or '$$':
            idle_counter = 0
            while True:
                ser.reset_input_buffer()
                command = str.encode('?' + '\n')
                ser.write(command)
                grbl_out = ser.readline()
                grbl_response = grbl_out.strip().decode('utf-8')
                if grbl_response != 'ok':
                    if 'Idle' in grbl_response:
                        idle_counter += 1
                if idle_counter > 0:
                    break
        return

    def move_down(self):
        self.gcode += "G0 Z-33.5\n"

    def move_up(self):
        self.gcode += "G0 Z0\n"

    def move_to_height(self, z):
        self.gcode += f"G0 Z{z}"

    def move_to_point(self, x, y):
        if self.coordinates_within_bounds(x, y):
            self.gcode += f"G0 X{x + self.X_OFFSET} Y{y + self.Y_OFFSET}\n"
        else:
            print(f"Cannot move to {x}, {y}, coordinates not within bounds")

    def coordinates_within_bounds(self, x, y):
        return (
            self.X_LOW_BOUND <= x <= self.X_HIGH_BOUND and
            self.Y_LOW_BOUND <= y <= self.Y_HIGH_BOUND
        )

    def wake_up(self, ser):
        ser.write(str.encode("\r\n\r\n"))
        time.sleep(1)
        ser.flushInput()
        print("CNC machine is active")

    def render_drawing(self, buffer=20):
        with serial.Serial(self.SERIAL_PORT_PATH, self.BAUD_RATE) as ser:
            self.wake_up(ser)
            out_strings = []
            commands = self.gcode.split('\n')
            for i in range(math.ceil(len(commands) / buffer)):
                buffered_commands = commands[i*buffer:(i+1)*buffer]
                buffered_gcode = "\n".join(buffered_commands) + "\n"
                ser.write(str.encode(buffered_gcode))
                self.wait_for_movement_completion(ser, buffered_gcode)
                grbl_out = ser.readline()
                out_strings.append(grbl_out.strip().decode('utf-8'))
            return out_strings


if __name__ == "__main__":
    """
    Example usage of the liquid_cnc module.
    """
    config = load_config("cnc_settings.yaml", 'Genmitsu 3018-PROVer V2')

    # Example instantiating the simulator and controller
    simulator = CNC_Simulator(config)
    controller = CNC_Controller(find_port(), config)

    # Use the simulator and controller as needed
    simulator.move_to_point(50, 50)
    # simulator.render_drawing()

    try:
        # Home the xyz axis
        # controller.home_xyz()
        # print("CNC is homed.")

        loading_position = (-140.0, 120.0, -38.0)

        # Moving tool to a point on xy
        xy = (loading_position[0], loading_position[1])
        controller.move_to_point(loading_position[0], loading_position[1])
        controller.render_drawing()
        print(f"Moved (X,Y) to {xy}")

        # Moving tool to a point on z
        controller.move_to_height(loading_position[2])
        controller.render_drawing()
        print(f"Moved Z to {loading_position[2]}")

        # Read machine internal coordinates
        coord = controller.read_coordinates()
        print(f"Internal location is: {coord}")
    finally:
        exit()



