#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT

import argparse
import os
import sys
import asyncio
import json
import logging
from rich.logging import RichHandler
import dataclasses
from dataclasses import dataclass, field

from typing import BinaryIO
from dbus_fast.aio import MessageBus
from dbus_fast.proxy_object import BaseProxyObject, BaseProxyInterface
from dbus_fast import BusType, Variant, MessageType, Message

BUSNAME = "org.freedesktop.login1"


logging.basicConfig(
    level="NOTSET", format="%(message)s", datefmt="[%X]", handlers=[RichHandler()]
)
logger = logging.getLogger("poker")


@dataclass
class Device:
    major: int
    minor: int
    fd: int = -1

    def open(self, fd):
        # purposely not closing until we re-open so we can test
        # that we're not getting events on the fd while being pause. And this
        # way we get differently numbered fds too.
        if self.fd != -1:
            self.close()
        logger.debug(f"Opening {self} with fd {fd}")
        self.fd = fd
        loop = asyncio.get_running_loop()
        loop.add_reader(fd, self.on_device_data)

    def close(self):
        loop = asyncio.get_running_loop()
        loop.remove_reader(self.fd)
        os.close(self.fd)
        self.fd = -1

    def on_device_data(self):
        try:
            data = os.read(self.fd, 1024)
            logger.debug(f"{self.fd}: {data}")
        except OSError as e:
            logger.error(f"fd {self.fd}: {e}")
            self.close()


@dataclass
class AvailableSession:
    id: str  # yes, really a string
    uid: int
    user: str
    seat_id: str
    objpath: str


@dataclass
class Session:
    id: str  # yes, really a str
    user: tuple[int, str]
    name: str
    # Timestamp = 1389370644734067;
    # TimestampMonotonic = 72063381;
    # VTNr = 0;
    # Seat = ('', '/');
    tty: str
    # Display = '';
    # Remote = true;
    # RemoteHost = '129.174.150.217';
    # RemoteUser = '';
    # Service = 'sshd';
    # Desktop = '';
    # Scope = 'session-3.scope';
    # Leader = int
    # Audit = 3;
    # Type = 'tty';
    # Class = 'user';
    # Leader = 1854;
    active: bool
    state: str
    # IdleHint = false;
    # IdleSinceHint = 0;
    # IdleSinceHintMonotonic = 0;

    # Extra properties not filled in from DBus properties
    _obj: BaseProxyObject = field(repr=False)
    _intf: BaseProxyInterface = field(repr=False)
    _devices: list[Device] = field(repr=False, default_factory=list)

    async def on_properties_changed(
        self, interface_name, changed_properties, invalidated_properties
    ):
        for changed, variant in changed_properties.items():
            logger.debug(f"property changed: {changed} - {variant.value}")

    async def on_pause_device(self, major, minor, tipo):
        logger.debug(f"signal paused device: {major}.{minor} ({tipo})")
        await self._intf.call_pause_device_complete(major, minor)
        # intentionally *not* closing the fd here

    async def on_resume_device(self, major, minor, fd):
        logger.debug(f"signal resumed device: {major}.{minor} fd: {fd}")
        for device in self._devices:
            if device.major == major and device.minor == minor:
                device.open(fd)

    @property
    def intf(self) -> BaseProxyInterface:
        return self._intf

    @property
    def devices(self) -> list[Device]:
        return self._devices

    def connect(self):
        properties = self._obj.get_interface("org.freedesktop.DBus.Properties")
        properties.on_properties_changed(self.on_properties_changed)
        self._intf.on_pause_device(self.on_pause_device)
        self._intf.on_resume_device(self.on_resume_device)


async def open_session(bus: MessageBus, session: AvailableSession):
    introspection = await bus.introspect(BUSNAME, session.objpath)
    obj = bus.get_proxy_object(BUSNAME, session.objpath, introspection)
    interface = obj.get_interface("org.freedesktop.login1.Session")

    props = {"_obj": obj, "_intf": interface}
    for field in dataclasses.fields(Session):
        name = field.name
        if not name.startswith("_"):
            func = getattr(interface, f"get_{name}")
            value = await func()
            props[name] = value

    return Session(**props)


async def main(sid: str, device_list: list[str]):
    bus = await MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True).connect()

    logger.debug("Listing current sessions:")
    reply = await bus.call(
        Message(
            destination=BUSNAME,
            path="/org/freedesktop/login1",
            interface="org.freedesktop.login1.Manager",
            member="ListSessions",
        )
    )

    if reply.message_type == MessageType.ERROR:
        raise Exception(reply.body[0])

    available_sessions = list(map(lambda s: AvailableSession(*s), reply.body[0]))
    logger.debug(available_sessions)
    sessions = [await open_session(bus, s) for s in available_sessions]
    if sid.startswith("tty"):
        session = next(filter(lambda s: s.tty == sid, sessions))
    else:
        session = next(filter(lambda s: s.id == sid, sessions))
    session.connect()
    logger.debug(session)

    logger.debug("Taking control of the session now")
    res = await session.intf.call_take_control(False)
    if res:
        logger.error(res)

    loop = asyncio.get_running_loop()

    for device in device_list:
        logger.debug(f"Taking device {device}")
        rdev = os.stat(device).st_rdev
        major = os.major(rdev)
        minor = os.minor(rdev)

        res = await session.intf.call_take_device(major, minor)
        if res:
            fd, inactive = res
            is_active = not inactive
            device = Device(major, minor)
            session.devices.append(device)
            logger.debug(f"Device is fd {fd} active: {is_active}")

            if is_active:
                device.open(fd)

    logger.debug("All done, looping forever now")
    await bus.wait_for_disconnect()


parser = argparse.ArgumentParser()
parser.add_argument(
    "session", type=str, help="The session ID (use 'tty3' for the session on tty3)"
)
parser.add_argument("--device", action="append", type=str, help="The device(s) to take")

args = parser.parse_args()
logger.debug(args)

asyncio.run(main(args.session, args.device))
