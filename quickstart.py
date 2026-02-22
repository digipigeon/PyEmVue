#!/usr/bin/env python3
"""Quick start script to test PyEmVue library."""

import pyemvue
from pyemvue.enums import Scale, Unit


def print_recursive(usage_dict, info, depth=0):
    """Recursively print device usage information."""
    for gid, device in usage_dict.items():
        for channelnum, channel in device.channels.items():
            name = channel.name
            if name == 'Main':
                name = info[gid].device_name
            print('-' * depth, f'{gid} {channelnum} {name} {channel.usage} kWh')
            if channel.nested_devices:
                print_recursive(channel.nested_devices, info, depth + 1)


def main():
    # Create PyEmVue instance
    vue = pyemvue.PyEmVue()

    # Login using keys.json (will use stored tokens if available, otherwise username/password)
    print("Logging in...")
    vue.login(token_storage_file='keys.json')

    # Get customer details
    print("\n--- Customer Details ---")
    customer = vue.get_customer_details()
    print(f"Name: {customer.first_name} {customer.last_name}")
    print(f"Email: {customer.email}")
    print(f"Customer GID: {customer.customer_gid}")

    # Get devices
    print("\n--- Devices ---")
    devices = vue.get_devices()
    device_gids = []
    device_info = {}

    for device in devices:
        if device.device_gid not in device_gids:
            device_gids.append(device.device_gid)
            device_info[device.device_gid] = device
        else:
            device_info[device.device_gid].channels += device.channels

    print(f"Found {len(device_gids)} device(s)")
    for gid in device_gids:
        dev = device_info[gid]
        print(f"  - GID: {gid}, Model: {dev.model}, Channels: {len(dev.channels)}")

    # Get usage for the last minute
    print("\n--- Energy Usage (Last Minute) ---")
    print("device_gid channel_num name usage")
    device_usage_dict = vue.get_device_list_usage(
        deviceGids=device_gids,
        instant=None,
        scale=Scale.MINUTE.value,
        unit=Unit.KWH.value
    )
    print_recursive(device_usage_dict, device_info)

    print("\nDone!")


if __name__ == '__main__':
    main()
