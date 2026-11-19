#!/usr/bin/env python3
"""Load firmware into a PICkit 2 through its factory USB bootloader.

The bootloader (0x0000-0x1FFF, write protected) is never modified.  It runs
the application at 0x2000 when the byte at 0x7FFE is 0x55 and the button is
not held while the PICkit 2 is plugged in.

    pk2boot.py info                 what is connected, and in which mode
    pk2boot.py backup DIR           save flash, EEPROM and configuration
    pk2boot.py flash FILE.hex       load an application and start it
    pk2boot.py enter                switch a running application to the bootloader
    pk2boot.py run                  leave the bootloader (needs a valid application)

Needs the Python packages hidapi and pyusb.
"""
import argparse
import os
import sys
import time

import hid

VID, PID = 0x04D8, 0x0033
APP_START, APP_END = 0x2000, 0x8000
KEY_BLOCK = 0x7FC0
KEY_ADDR = 0x7FFE

BL_READ_VERSION = 0x76
BL_READ_FLASH = 0x01
BL_WRITE_FLASH = 0x02
BL_ERASE_FLASH = 0x03
BL_READ_EEDATA = 0x04
BL_READ_CONFIG = 0x06
BL_RESET = 0xFF

STOCK_GET_VERSION = 0x76
STOCK_ENTER_BOOT = 0x42
STOCK_END = 0xAD

PROBE_REQ_BOOTLOADER = 0xB0
PROBE_REQ_INFO = 0xB1
PROBE_BOOT_MAGIC = 0x4C42


class Error(Exception):
    pass


# ---- Intel HEX -----------------------------------------------------------

def read_hex(path):
    """Return {address: byte} for an Intel HEX file."""
    mem = {}
    base = 0
    with open(path) as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            if line[0] != ':':
                raise Error(f'{path}:{n}: not an Intel HEX record')
            raw = bytes.fromhex(line[1:])
            if sum(raw) & 0xFF:
                raise Error(f'{path}:{n}: bad checksum')
            count, addr, kind = raw[0], (raw[1] << 8) | raw[2], raw[3]
            data = raw[4:4 + count]
            if kind == 0:
                for i, b in enumerate(data):
                    mem[base + addr + i] = b
            elif kind == 1:
                break
            elif kind == 4:
                base = ((data[0] << 8) | data[1]) << 16
            elif kind == 2:
                base = ((data[0] << 8) | data[1]) << 4
    return mem


def write_hex(path, mem):
    """Write {address: byte} as an Intel HEX file."""
    def rec(count_addr_kind_data):
        s = sum(count_addr_kind_data) & 0xFF
        return ':' + (bytes(count_addr_kind_data) + bytes([(-s) & 0xFF])).hex().upper()

    lines = []
    upper = None
    addrs = sorted(mem)
    i = 0
    while i < len(addrs):
        a = addrs[i]
        chunk = [mem[a]]
        while (i + 1 < len(addrs) and addrs[i + 1] == addrs[i] + 1
               and len(chunk) < 16 and (addrs[i + 1] & 0xFFFF) != 0):
            i += 1
            chunk.append(mem[addrs[i]])
        i += 1
        if (a >> 16) != upper:
            upper = a >> 16
            lines.append(rec([2, 0, 0, 4, upper >> 8, upper & 0xFF]))
        lines.append(rec([len(chunk), (a >> 8) & 0xFF, a & 0xFF, 0] + chunk))
    lines.append(':00000001FF')
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


# ---- Device access -------------------------------------------------------

class Hid:
    """A PICkit 2 in bootloader mode or running the stock firmware (both HID)."""

    def __init__(self):
        self.dev = hid.device()
        self.dev.open(VID, PID)

    def close(self):
        self.dev.close()

    def write(self, data, fill=0x00):
        buf = bytes(data) + bytes([fill]) * (64 - len(data))
        self.dev.write(b'\x00' + buf)

    def read(self, timeout_ms=1000):
        r = bytes(self.dev.read(64, timeout_ms))
        if len(r) != 64:
            raise Error('no reply from the PICkit 2')
        return r

    def mode(self):
        """Return ('bootloader', (major, minor)) or ('stock', (major, minor, dot))."""
        self.write([BL_READ_VERSION], fill=STOCK_END)
        r = self.read()
        if r[0] == BL_READ_VERSION and r[5] == ord('B'):
            return 'bootloader', (r[6], r[7])
        return 'stock', (r[0], r[1], r[2])

    # Bootloader commands
    def bl_read(self, cmd, addr, length):
        out = bytearray()
        while length:
            n = min(length, 59)
            self.write([cmd, n, addr & 0xFF, (addr >> 8) & 0xFF, (addr >> 16) & 0xFF])
            r = self.read()
            if r[0] != cmd or r[1] != n:
                raise Error(f'unexpected bootloader reply at {addr:#x}')
            out += r[5:5 + n]
            addr += n
            length -= n
        return bytes(out)

    def bl_erase(self, addr, blocks):
        while blocks:
            n = min(blocks, 16)
            self.write([BL_ERASE_FLASH, n, addr & 0xFF, (addr >> 8) & 0xFF, 0])
            time.sleep(0.01 + 0.005 * n)
            addr += 64 * n
            blocks -= n

    def bl_write32(self, addr, data):
        assert len(data) == 32 and addr % 32 == 0
        self.write([BL_WRITE_FLASH, 32, addr & 0xFF, (addr >> 8) & 0xFF, 0] + list(data))

    def bl_reset(self):
        self.write([BL_RESET])


def find_probe():
    """Return a pyusb device running the probe firmware, or None."""
    try:
        import usb.core
    except ImportError:
        return None
    for dev in usb.core.find(find_all=True, idVendor=VID, idProduct=PID):
        try:
            if dev[0][(0, 0)].bInterfaceClass == 0xFF:
                return dev
        except Exception:
            pass
    return None


def hid_present():
    return bool(hid.enumerate(VID, PID))


def wait_for(predicate, seconds, what):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return
        time.sleep(0.1)
    raise Error(f'timed out waiting for {what}')


def open_bootloader(verbose=True):
    """Get the PICkit 2 into bootloader mode, whatever it is running."""
    probe = find_probe()
    if probe is not None:
        if verbose:
            print('probe firmware running; asking it to enter the bootloader')
        try:
            probe.ctrl_transfer(0x40, PROBE_REQ_BOOTLOADER, PROBE_BOOT_MAGIC, 0, None, 1000)
        except Exception:
            pass                # the device may drop off the bus before the status stage
        import usb.util
        usb.util.dispose_resources(probe)
        time.sleep(1.0)
        wait_for(hid_present, 10, 'the bootloader to enumerate')
        time.sleep(0.3)

    if not hid_present():
        raise Error('no PICkit 2 found (04D8:0033)')

    h = Hid()
    mode, ver = h.mode()
    if mode == 'stock':
        if verbose:
            print('stock firmware %d.%02d.%02d running; asking it to enter the bootloader' % ver)
        h.write([STOCK_ENTER_BOOT], fill=STOCK_END)
        h.close()
        time.sleep(1.5)
        wait_for(hid_present, 10, 'the bootloader to enumerate')
        time.sleep(0.5)
        h = Hid()
        mode, ver = h.mode()
    if mode != 'bootloader':
        raise Error('the PICkit 2 did not enter its bootloader')
    if verbose:
        print('bootloader %d.%d' % ver)
    return h


# ---- Commands ------------------------------------------------------------

def cmd_info(args):
    probe = find_probe()
    if probe is not None:
        info = bytes(probe.ctrl_transfer(0xC0, PROBE_REQ_INFO, 0, 0, 8, 1000))
        print('probe firmware %d.%d, protocol %d, capabilities %#04x'
              % (info[4], info[5], info[6], info[7]))
        return
    if not hid_present():
        raise Error('no PICkit 2 found (04D8:0033)')
    h = Hid()
    mode, ver = h.mode()
    if mode == 'bootloader':
        key = h.bl_read(BL_READ_FLASH, KEY_ADDR, 2)
        print('bootloader %d.%d; application key %s'
              % (ver[0], ver[1], 'present' if key[0] == 0x55 else 'absent'))
    else:
        print('stock PICkit 2 firmware %d.%02d.%02d' % ver)
    h.close()


def cmd_backup(args):
    os.makedirs(args.dir, exist_ok=True)
    h = open_bootloader()
    print('reading flash ...')
    flash = h.bl_read(BL_READ_FLASH, 0x0000, 0x8000)
    eeprom = h.bl_read(BL_READ_EEDATA, 0x00, 0x100)
    config = h.bl_read(BL_READ_CONFIG, 0x300000, 14)
    idlocs = h.bl_read(BL_READ_CONFIG, 0x200000, 8)
    devid = h.bl_read(BL_READ_CONFIG, 0x3FFFFE, 2)
    h.close()

    def region(base, data):
        return {base + i: b for i, b in enumerate(data)}

    full = {}
    full.update(region(0, flash))
    full.update(region(0x200000, idlocs))
    full.update(region(0x300000, config))
    full.update(region(0xF00000, eeprom))
    # Entering the bootloader erased the application key; put it back so the
    # image is the one that was running.
    full[KEY_ADDR] = 0x55
    full[KEY_ADDR + 1] = 0x55
    write_hex(os.path.join(args.dir, 'pickit2_full.hex'), full)

    app = {a: b for a, b in full.items() if APP_START <= a < APP_END}
    write_hex(os.path.join(args.dir, 'pickit2_app.hex'), app)
    with open(os.path.join(args.dir, 'eeprom.bin'), 'wb') as f:
        f.write(eeprom)
    with open(os.path.join(args.dir, 'bootloader.bin'), 'wb') as f:
        f.write(flash[:APP_START])

    print('device id %02X%02X' % (devid[1], devid[0]))
    print('config    ' + config.hex(' '))
    print('eeprom    ' + eeprom[:8].hex(' ') + ' ...  (voltage calibration in the first 4 bytes)')
    print(f'saved to {args.dir}/: pickit2_full.hex, pickit2_app.hex, eeprom.bin, bootloader.bin')
    print('the PICkit 2 is still in bootloader mode; "flash" or "run" continues')


def flash_image(h, mem, verbose=True):
    app = {a: b for a, b in mem.items() if APP_START <= a < KEY_BLOCK}
    outside = [a for a in mem if a < APP_START or KEY_BLOCK <= a < APP_END]
    if not app:
        raise Error('the image has nothing in 0x2000-0x7FBF; was it built with -mcodeoffset=0x2000?')
    if any(a < APP_START for a in outside):
        raise Error('the image has data below 0x2000, which belongs to the bootloader')

    image = bytearray([0xFF] * (APP_END - APP_START))
    for a, b in app.items():
        image[a - APP_START] = b
    top = (max(app) + 64) & ~63                     # end of the last block used

    if verbose:
        print(f'erasing 0x{APP_START:04X}-0x7FFF')
    h.bl_erase(APP_START, (APP_END - APP_START) // 64)

    if verbose:
        print(f'writing 0x{APP_START:04X}-0x{top - 1:04X}')
    for addr in range(APP_START, top, 32):
        chunk = image[addr - APP_START:addr - APP_START + 32]
        if any(b != 0xFF for b in chunk):
            h.bl_write32(addr, chunk)
            time.sleep(0.004)

    back = h.bl_read(BL_READ_FLASH, APP_START, KEY_BLOCK - APP_START)
    if back != bytes(image[:KEY_BLOCK - APP_START]):
        bad = next(i for i in range(len(back)) if back[i] != image[i])
        raise Error(f'verify failed at 0x{APP_START + bad:04X}; the PICkit 2 stays in bootloader mode')

    # The key goes in last, so an interrupted load never leaves a bad image marked valid.
    last = bytearray([0xFF] * 32)
    last[30] = 0x55
    last[31] = 0x55
    h.bl_write32(APP_END - 32, last)
    time.sleep(0.01)
    if h.bl_read(BL_READ_FLASH, KEY_ADDR, 2) != b'\x55\x55':
        raise Error('could not write the application key')
    if verbose:
        print('verified')


def cmd_flash(args):
    mem = read_hex(args.hex)
    h = open_bootloader()
    flash_image(h, mem)
    h.bl_reset()
    h.close()
    print('started the application')


def cmd_enter(args):
    open_bootloader().close()


def cmd_run(args):
    h = open_bootloader()
    if h.bl_read(BL_READ_FLASH, KEY_ADDR, 1)[0] != 0x55:
        # The application is intact if only the key block was erased.
        first = h.bl_read(BL_READ_FLASH, APP_START, 4)
        if first == b'\xFF' * 4:
            raise Error('no application is loaded')
        last = bytearray([0xFF] * 32)
        last[30] = 0x55
        last[31] = 0x55
        h.bl_write32(APP_END - 32, last)
        time.sleep(0.01)
    h.bl_reset()
    h.close()
    print('started the application')


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('info').set_defaults(fn=cmd_info)
    s = sub.add_parser('backup')
    s.add_argument('dir')
    s.set_defaults(fn=cmd_backup)
    s = sub.add_parser('flash')
    s.add_argument('hex')
    s.set_defaults(fn=cmd_flash)
    sub.add_parser('enter').set_defaults(fn=cmd_enter)
    sub.add_parser('run').set_defaults(fn=cmd_run)
    args = p.parse_args()
    try:
        args.fn(args)
    except Error as e:
        sys.exit(f'error: {e}')


if __name__ == '__main__':
    main()
