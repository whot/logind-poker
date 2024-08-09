# logind-poker

`logind-poker` is a tool to test systemd-logind's `TakeDevice` implementation.
This tool tries to become a systemd-logind session owner and then calls 
`TakeDevice` on all devices provided on the CLI.

Typically you run this in a tty (since any compositor will be the session
controller already), i.e. switch to a tty first
```
$ chvt 3
```
Now log in on tty3 and figure out your session id
```
$ loginctl 
SESSION  UID USER SEAT  LEADER CLASS   TTY   IDLE SINCE
     10 1000 whot seat0 7585   user    tty3  yes  36min ago
      2 1000 whot seat0 1938   user    tty2  no   -
      3 1000 whot -     1951   manager -     no   -
...
```
and use the numeric session ID (here `10`) for `logind-poker`:
```
$ logind-poker --device=/dev/input/event0 --device=/dev/hidraw0 10
```
or, as a shortcut that should work most of the time use `tty3` as session ID:
```
$ logind-poker --device=/dev/input/event0 --device=/dev/hidraw0 tty3
```
The latter will simply use the first session on `tty3` as returned by logind.


## Testing

Use [hid-replay](https://github.com/hidutils/hid-replay) to create a uhid device
and replay some events from a previously [recorded hid device](https://github.com/hidutils/hid-recorder).

Use `chvt 2` and `chvt 3` to VT-switch and trigger the revoke calls on the devices.
