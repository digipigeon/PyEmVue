import pyemvue
import json
import getpass
import os

# Create PyEmVue object
vue = pyemvue.PyEmVue()

# Check if keys.json exists
if not os.path.exists('keys.json'):
    # Get email and password
    email = input("Enter your email: ")
    password = getpass.getpass("Enter your password: ")

    # Log in to PyEmVue
    logged_in = vue.login(username=email, password=password, token_storage_file='keys.json')
else:
    # If keys.json exists, log in using the keys in the file
    logged_in = vue.login(token_storage_file='keys.json')

print("Logged in?", logged_in)
if not logged_in:
    raise Exception("Login failed")

# Call the status API
outlets, evse_statuses = vue.get_devices_status()

evse_data = vue.get_evses([evse.device_id for evse in evse_statuses])

# Print EVSE data to the screen
print("EVSE status info:")
print(json.dumps([evse.__dict__ for evse in evse_statuses], indent=4))

print("EVSE data:")
for evse in evse_data:
    print(json.dumps(evse.as_dictionary(), indent=4))

# print outlet data to the screen
print("Outlet data:")
print(json.dumps([outlet.__dict__ for outlet in outlets], indent=4))

# turn off first EVSE if available
if evse_statuses:
    evse_to_control = evse_statuses[0]
    evse_full = next((evse for evse in evse_data if evse.device_id == evse_to_control.device_id), None)
    if not evse_full:
        raise Exception("Could not find full EVSE data for the selected EVSE")
    input(f"Press Enter to toggle EVSE {evse_to_control.device_id} off...")

    current_charge_rate = evse_full.charging_rate
    print(f"Toggling EVSE {evse_to_control.device_id} state...")
    success = vue.set_evse_state(evse_to_control.device_id, enabled = False)
    print("Disabled?", success)

    # wait for input before turning it back on
    input(f"Press Enter to re-enable the EVSE and set charge rate to {current_charge_rate // 2} amps...")

    # turn it back on and reduce the charge rate to 12 amps
    print(f"Setting EVSE {evse_to_control.device_id} to {current_charge_rate // 2} amps...")
    success = vue.set_evse_state(evse_to_control.device_id, enabled = True)
    print("Enabled?", success)
    success = vue.set_evse_settings(evse_to_control.device_id, charge_rate_amps = current_charge_rate // 2)
    print("Updated?", success)

    # set back to normal after another input
    input(f"Press Enter to set the EVSE charge rate back to {current_charge_rate} amps...")
    print(f"Setting EVSE {evse_to_control.device_id} to {current_charge_rate} amps...")
    success = vue.set_evse_settings(evse_to_control.device_id, charge_rate_amps = current_charge_rate)
    print("Updated?", success)