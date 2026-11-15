#!/usr/bin/env python3
"""bluetoothctl de mentira para os testes. O estado fica no arquivo JSON indicado
pela variavel de ambiente FAKE_BT_STATE."""
import json
import os
import sys

STATE = os.environ["FAKE_BT_STATE"]


def load():
    with open(STATE) as f:
        return json.load(f)


def save(state):
    with open(STATE, "w") as f:
        json.dump(state, f)


def yn(value):
    return "yes" if value else "no"


def command(args):
    state = load()
    if not state.get("adapter", True):
        print("No default controller available")
        return 1
    cmd = args[0] if args else ""
    devs = state["devices"]
    if cmd == "show":
        print("Controller AA:AA:AA:AA:AA:AA (public)")
        print("\tName: LibreELEC")
        print("\tAlias: CarPC")
        print("\tPowered: " + yn(state["powered"]))
        print("\tDiscoverable: " + yn(state["discoverable"]))
        print("\tPairable: yes")
        print("\tUUID: A/V Remote Control        (0000110e-0000-1000-8000-00805f9b34fb)")
        print("\tDiscovering: no")
    elif cmd == "power":
        state["powered"] = args[1] == "on"
        print("\x1b[0;92mChanging power %s succeeded\x1b[0m" % args[1])
    elif cmd == "discoverable":
        state["discoverable"] = args[1] == "on"
    elif cmd == "pairable":
        pass
    elif cmd == "devices":
        for mac, dev in devs.items():
            print("Device %s %s" % (mac, dev["name"]))
    elif cmd == "info":
        dev = devs.get(args[1])
        if not dev:
            print("Device %s not available" % args[1])
            return 1
        print("Device %s (public)" % args[1])
        print("\tName: " + dev["name"])
        print("\tAlias: " + dev["name"])
        print("\tIcon: phone")
        print("\tPaired: " + yn(dev["paired"]))
        print("\tTrusted: " + yn(dev["trusted"]))
        print("\tConnected: " + yn(dev["connected"]))
    elif cmd == "connect":
        dev = devs.get(args[1])
        if not dev or dev.get("refuse"):
            print("Failed to connect: org.bluez.Error.Failed")
            return 1
        dev["connected"] = True
        print("Connection successful")
    elif cmd == "disconnect":
        devs[args[1]]["connected"] = False
        print("Successful disconnected")
    elif cmd == "trust":
        devs[args[1]]["trusted"] = True
    elif cmd == "remove":
        devs.pop(args[1], None)
        print("Device has been removed")
    elif cmd == "scan":
        devs.setdefault("11:22:33:44:55:66", {"name": "Celular Novo", "paired": False,
                                              "trusted": False, "connected": False})
    elif cmd == "pair":
        dev = devs.get(args[1])
        if dev and not dev.get("refuse_pair"):
            dev["paired"] = True
    save(state)
    return 0


def main():
    args = sys.argv[1:]
    if args and args[0] == "--timeout":
        args = args[2:]
    if not args or args[0].startswith("--agent"):
        state = load()
        state["agent"] = args[0] if args else ""
        save(state)
        for line in sys.stdin:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "quit":
                break
            command(parts)
        return 0
    return command(args)


if __name__ == "__main__":
    sys.exit(main())
