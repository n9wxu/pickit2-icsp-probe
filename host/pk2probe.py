#!/usr/bin/env python3
"""Host library and command line tool for the PICkit 2 ICSP probe firmware.

    pk2probe.py info                       firmware version, voltages, status
    pk2probe.py detect [--hvp]             identify the target
    pk2probe.py read OUT.hex               read the whole device
    pk2probe.py program FILE.hex           erase, program and verify
    pk2probe.py verify FILE.hex
    pk2probe.py erase
    pk2probe.py power on|off [--vdd MV]    switch target power
    pk2probe.py calibrate show|run|clear   voltage calibration, stored in the probe
    pk2probe.py scope vdd|vpp|mclr|clock   repeat a waveform for an oscilloscope

Common options: --vdd MV (default 3000), --hvp (enter with VPP on MCLR
instead of the low-voltage key sequence), --no-power (target has its own
supply), --device NAME (skip auto-detection).

Needs the Python package pyusb (and libusb).
"""
import argparse
import struct
import sys
import time

import usb.core
import usb.util

VID, PID = 0x04D8, 0x0033
EP_OUT, EP_IN = 0x01, 0x81
PKT = 64

# Operations (firmware/proto.h)
OP_END, OP_INFO, OP_STATUS, OP_READ_VOLT = 0x00, 0x01, 0x02, 0x03
OP_SET_VDD, OP_VDD_MODE, OP_SET_VPP, OP_MCLR = 0x04, 0x05, 0x06, 0x07
OP_PINS, OP_DELAY_US, OP_DELAY_MS, OP_SPEED = 0x08, 0x09, 0x0A, 0x0B
OP_LED, OP_CLEAR_FAULTS, OP_BOOTLOADER, OP_RESET = 0x0C, 0x0D, 0x0E, 0x0F
OP_WRITE_BITS, OP_READ_BITS, OP_KEY = 0x10, 0x11, 0x12
OP_EE_READ, OP_EE_WRITE = 0x14, 0x15
OP_G6_CMD, OP_G6_LOAD, OP_G6_READ, OP_G6_READN, OP_G6_LOADN = 0x20, 0x21, 0x22, 0x23, 0x24
OP_G8_CMD, OP_G8_WRITE, OP_G8_READ, OP_G8_READN, OP_G8_LOADN = 0x30, 0x31, 0x32, 0x33, 0x34
OP_ICD_READY, OP_ICD_TX, OP_ICD_RX = 0x40, 0x41, 0x42

MSB_FIRST = 0x01
PIN_DAT, PIN_DAT_IN, PIN_CLK, PIN_CLK_IN = 0x01, 0x02, 0x04, 0x08
PINS_IDLE = PIN_DAT_IN | PIN_CLK_IN       # both released
PINS_LOW = 0x00                            # both driven low

MCLR_RELEASE, MCLR_GROUND, MCLR_VPP = 0, 1, 2
VDD_OFF, VDD_ON, VDD_DISCHARGE = 0, 1, 2

ST_VDD_ON, ST_VDD_GND, ST_VPP_PUMP, ST_VPP_SWITCH = 0x01, 0x02, 0x04, 0x08
ST_MCLR_GND, ST_VDD_FAULT, ST_VPP_FAULT, ST_BUTTON = 0x10, 0x20, 0x40, 0x80

ERRORS = {
    1: 'unknown operation',
    2: 'truncated operation',
    3: 'reply too long',
    4: 'argument out of range',
    5: 'debug executive did not respond',
    6: 'VDD or VPP short circuit; target power was switched off',
}


class ProbeError(Exception):
    pass


class Probe:
    """USB connection to the probe, with operation batching.

    Operations are queued with the op_* methods and sent with flush(), which
    returns the concatenated reply data.  A batch is split into packets so
    that neither a packet nor its reply exceeds 64 bytes.
    """

    def __init__(self):
        self.dev = None
        for dev in usb.core.find(find_all=True, idVendor=VID, idProduct=PID):
            try:
                if dev[0][(0, 0)].bInterfaceClass == 0xFF:
                    self.dev = dev
                    break
            except Exception:
                pass
        if self.dev is None:
            raise ProbeError('no probe found; is the probe firmware loaded? (pk2boot.py info)')
        self.dev.set_configuration()
        usb.util.claim_interface(self.dev, 0)
        self._queue = []            # list of (request bytes, reply length)

    def close(self):
        usb.util.dispose_resources(self.dev)

    # -- transport ---------------------------------------------------------

    def _transact(self, request):
        self.dev.write(EP_OUT, request, 2000)
        r = bytes(self.dev.read(EP_IN, PKT, 5000))
        if len(r) < 2:
            raise ProbeError('short reply from the probe')
        if r[0]:
            raise ProbeError('%s (operation at offset %d)' % (ERRORS.get(r[0], f'error {r[0]}'), r[1]))
        return r[2:]

    def queue(self, request, reply_len=0):
        self._queue.append((bytes(request), reply_len))

    def flush(self):
        out = bytearray()
        req = bytearray()
        rlen = 0
        for r, n in self._queue:
            if len(req) + len(r) > PKT or rlen + n > PKT - 2:
                out += self._transact(req)
                req = bytearray()
                rlen = 0
            req += r
            rlen += n
        self._queue = []
        if req:
            out += self._transact(req)
        return bytes(out)

    def run(self, request, reply_len=0):
        """Send one operation now and return its reply data."""
        self.flush()
        self.queue(request, reply_len)
        return self.flush()

    # -- general operations ------------------------------------------------

    def info(self):
        r = self.run([OP_INFO], 8)
        if r[:4] != b'PK2P':
            raise ProbeError('unexpected INFO reply')
        return {'version': (r[4], r[5]), 'protocol': r[6], 'caps': r[7]}

    def status(self):
        r = self.run([OP_STATUS], 2)
        return r[0], r[1]

    def voltages(self):
        """Return (target VDD, VPP rail) in volts."""
        vdd, vpp, _, _ = struct.unpack('<4H', self.run([OP_READ_VOLT], 8))
        return vdd / 1000.0, vpp / 1000.0

    def set_vdd(self, mv):       self.queue([OP_SET_VDD, mv & 0xFF, mv >> 8])
    def vdd_mode(self, mode):    self.queue([OP_VDD_MODE, mode])
    def set_vpp(self, mv):       self.queue([OP_SET_VPP, mv & 0xFF, mv >> 8])
    def mclr(self, mode):        self.queue([OP_MCLR, mode])
    def pins(self, v):           self.queue([OP_PINS, v], 1)
    def delay_us(self, us):      self.queue([OP_DELAY_US, us & 0xFF, us >> 8])
    def speed(self, n):          self.queue([OP_SPEED, n])
    def led(self, on):           self.queue([OP_LED, 1 if on else 0])
    def clear_faults(self):      self.queue([OP_CLEAR_FAULTS])

    def delay_ms(self, ms):
        while ms > 0:
            n = min(ms, 100)
            self.queue([OP_DELAY_MS, n])
            ms -= n

    def write_bits(self, value, nbits, msb_first=False):
        nbytes = (nbits + 7) // 8
        if msb_first:
            data = (value << (8 * nbytes - nbits)).to_bytes(nbytes, 'big')
        else:
            data = value.to_bytes(nbytes, 'little')
        self.queue([OP_WRITE_BITS, nbits, MSB_FIRST if msb_first else 0] + list(data))

    def key(self, key_bytes, msb_first, extra_clocks):
        self.queue([OP_KEY, MSB_FIRST if msb_first else 0] + list(key_bytes) + [extra_clocks])

    # -- power helpers -----------------------------------------------------

    def target_off(self):
        self.pins(PINS_IDLE)
        self.mclr(MCLR_RELEASE)
        self.set_vpp(0)
        self.vdd_mode(VDD_OFF)
        self.led(False)
        self.flush()

    def wait_vpp(self, mv, timeout=1.0):
        end = time.time() + timeout
        while True:
            _, vpp = self.voltages()
            if vpp * 1000 >= mv - 400:
                return vpp
            if time.time() > end:
                raise ProbeError(f'VPP only reached {vpp:.2f} V, wanted {mv / 1000:.2f} V')
            time.sleep(0.01)

    # -- debug link --------------------------------------------------------

    def icd_ready(self):
        return bool(self.run([OP_ICD_READY], 1)[0])

    def icd_tx(self, data, timeout_ms=500):
        self.run([OP_ICD_TX, max(1, timeout_ms // 10), len(data)] + list(data))

    def icd_rx(self, n, timeout_ms=500):
        return self.run([OP_ICD_RX, max(1, timeout_ms // 10), n], n)


# ---- Devices -------------------------------------------------------------

class Device:
    def __init__(self, name, gen, dev_id, id_mask, flash_words, latches, eeprom,
                 config_words, vpp_mv=8500, vdd_max_mv=5500):
        self.name = name
        self.gen = gen                      # 6 or 8: bits in an ICSP command
        self.dev_id = dev_id
        self.id_mask = id_mask
        self.flash_words = flash_words
        self.latches = latches              # words per program memory write
        self.eeprom = eeprom                # bytes of data EEPROM
        self.config_words = config_words    # number of words from 0x8007
        self.vpp_mv = vpp_mv
        self.vdd_max_mv = vdd_max_mv


# Device IDs and memory sizes are from the Microchip device family packs;
# write latch counts are from the programming specifications.
def _pic16f193x():
    """PIC16(L)F193x: device ID in bits 13:5 of 0x8006, revision in bits 4:0."""
    out = []
    for name, f_id, lf_id, words in [('1933', 0x2300, 0x2400, 4096), ('1934', 0x2340, 0x2440, 4096),
                                     ('1936', 0x2360, 0x2460, 8192), ('1937', 0x2380, 0x2480, 8192),
                                     ('1938', 0x23A0, 0x24A0, 16384), ('1939', 0x23C0, 0x24C0, 16384)]:
        out.append(Device('PIC16F' + name, 6, f_id, 0x3FE0, words, 8, 256, 2))
        out.append(Device('PIC16LF' + name, 6, lf_id, 0x3FE0, words, 8, 256, 2, vdd_max_mv=3600))
    return out


DEVICES = _pic16f193x() + [
    Device('PIC16F1829',  6, 0x27E0, 0x3FE0, 8192, 32, 256, 2),
    Device('PIC16F1619',  6, 0x307D, 0x3FFF, 8192, 32, 0, 3),
    Device('PIC16F18877', 8, 0x3075, 0x3FFF, 32768, 32, 256, 5),
    Device('PIC16F15276', 8, 0x30E4, 0x3FFF, 16384, 32, 0, 5),
]

USERID_ADDR = 0x8000
REVID_ADDR = 0x8005
DEVID_ADDR = 0x8006
CONFIG_ADDR = 0x8007
EEPROM_HEX_ADDR = 0xF000

BLANK = 0x3FFF


class Target:
    """ICSP session with a PIC16F1 device.  Subclasses implement one command
    generation each."""

    gen = None

    def __init__(self, probe, vdd_mv=3300, hvp=False, power=True, vpp_mv=8500):
        self.p = probe
        self.vdd_mv = vdd_mv
        self.hvp = hvp
        self.power = power
        self.vpp_mv = vpp_mv
        self.device = None
        self.active = False

    # -- entry and exit ----------------------------------------------------

    def _key(self):
        raise NotImplementedError

    def enter(self):
        p = self.p
        p.clear_faults()
        p.led(True)
        p.pins(PINS_LOW)
        p.mclr(MCLR_GROUND)
        if self.power:
            p.set_vdd(self.vdd_mv)
        p.flush()

        if self.hvp:
            # The boost converter is fed from the VDD regulator, so it can be
            # brought up before the target is powered.
            p.set_vpp(self.vpp_mv)
            p.flush()
            p.wait_vpp(self.vpp_mv)
            if self.power:
                # VPP first: works whatever the configuration words say about
                # the MCLR pin and the oscillator.
                p.vdd_mode(VDD_DISCHARGE)
                p.delay_ms(50)
                p.vdd_mode(VDD_OFF)
                p.mclr(MCLR_VPP)
                p.delay_us(200)
                p.vdd_mode(VDD_ON)
                p.delay_ms(10)
            else:
                p.delay_ms(5)
                p.mclr(MCLR_VPP)
                p.delay_ms(5)
        else:
            if self.power:
                p.vdd_mode(VDD_ON)
                p.delay_ms(20)
            p.mclr(MCLR_RELEASE)        # a rising edge, then hold MCLR low
            p.delay_ms(2)
            p.mclr(MCLR_GROUND)
            p.delay_ms(2)
            self._key()
            p.delay_ms(2)
        p.flush()
        self.active = True

    def exit(self, keep_power=False):
        p = self.p
        p.mclr(MCLR_GROUND)
        p.delay_ms(2)
        p.set_vpp(0)
        p.pins(PINS_IDLE)
        if self.power and not keep_power:
            p.vdd_mode(VDD_DISCHARGE)
            p.delay_ms(50)
            p.vdd_mode(VDD_OFF)
        p.mclr(MCLR_RELEASE)
        p.led(False)
        p.flush()
        self.active = False

    # -- memory access, implemented per generation ------------------------

    def read_words(self, addr, count):
        raise NotImplementedError

    def read_ids(self):
        """Return (revision word, device id word)."""
        w = self.read_words(REVID_ADDR, 2)
        return w[0], w[1]


class Gen6(Target):
    """PIC16F1xxx: 6 bit commands, LSB first, 16 bit data frames."""

    gen = 6
    LOAD_CONFIG, LOAD_PROG, LOAD_DATA = 0x00, 0x02, 0x03
    READ_PROG, READ_DATA, INCREMENT, RESET_ADDR = 0x04, 0x05, 0x06, 0x16
    BEGIN_INT, BEGIN_EXT, END_EXT = 0x08, 0x18, 0x0A
    ERASE_PROG, ERASE_DATA, ERASE_ROW = 0x09, 0x0B, 0x11

    T_PROG_MS, T_CONFIG_MS, T_ERASE_MS = 3, 6, 6

    def _key(self):
        self.p.key(b'PHCM', msb_first=False, extra_clocks=1)

    def _seek(self, addr):
        """Leave the address counter at addr.  It can only be reset to 0,
        loaded with 0x8000, or incremented."""
        p = self.p
        if addr >= 0x8000:
            p.queue([OP_G6_LOAD, self.LOAD_CONFIG, 0xFF, 0x3F])
            n = addr - 0x8000
        else:
            p.queue([OP_G6_CMD, self.RESET_ADDR])
            n = addr
        for _ in range(n):
            p.queue([OP_G6_CMD, self.INCREMENT])

    def read_words(self, addr, count):
        p = self.p
        self._seek(addr)
        left = count
        while left:
            n = min(left, 31)
            p.queue([OP_G6_READN, self.READ_PROG, self.INCREMENT, n], 2 * n)
            left -= n
        data = p.flush()
        return list(struct.unpack(f'<{count}H', data))

    def read_eeprom(self, count):
        p = self.p
        p.queue([OP_G6_CMD, self.RESET_ADDR])
        left = count
        while left:
            n = min(left, 31)
            p.queue([OP_G6_READN, self.READ_DATA, self.INCREMENT, n], 2 * n)
            left -= n
        return [w & 0xFF for w in struct.unpack(f'<{count}H', p.flush())]

    def bulk_erase(self):
        p = self.p
        # With the address in configuration space the user IDs go too.
        p.queue([OP_G6_LOAD, self.LOAD_CONFIG, 0xFF, 0x3F])
        p.queue([OP_G6_CMD, self.ERASE_PROG])
        p.delay_ms(self.T_ERASE_MS)
        if self.device and self.device.eeprom:
            p.queue([OP_G6_CMD, self.ERASE_DATA])
            p.delay_ms(self.T_ERASE_MS)
        p.queue([OP_G6_CMD, self.RESET_ADDR])
        p.flush()

    def write_flash(self, words, progress=None):
        """Program memory from address 0.  words is a list padded to a whole
        number of write latches."""
        p = self.p
        row = self.device.latches
        p.queue([OP_G6_CMD, self.RESET_ADDR])
        for base in range(0, len(words), row):
            chunk = words[base:base + row]
            if all(w == BLANK for w in chunk):
                for _ in range(row):
                    p.queue([OP_G6_CMD, self.INCREMENT])
            else:
                for i in range(0, row, 29):
                    part = chunk[i:i + 29]
                    req = [OP_G6_LOADN, self.LOAD_PROG, self.INCREMENT, len(part)]
                    for w in part:
                        req += [w & 0xFF, w >> 8]
                    p.queue(req)
                    if i + 29 < row:
                        p.queue([OP_G6_CMD, self.INCREMENT])
                p.queue([OP_G6_CMD, self.BEGIN_INT])
                p.delay_ms(self.T_PROG_MS)
                p.queue([OP_G6_CMD, self.INCREMENT])
            if progress and base % (row * 16) == 0:
                p.flush()
                progress(base, len(words))
        p.flush()

    def write_config_space(self, values):
        """values: {address: word} for 0x8000-0x800F.  One word per write."""
        p = self.p
        p.queue([OP_G6_LOAD, self.LOAD_CONFIG, 0xFF, 0x3F])
        addr = 0x8000
        for a in sorted(values):
            while addr < a:
                p.queue([OP_G6_CMD, self.INCREMENT])
                addr += 1
            p.queue([OP_G6_LOAD, self.LOAD_PROG, values[a] & 0xFF, values[a] >> 8])
            p.queue([OP_G6_CMD, self.BEGIN_INT])
            p.delay_ms(self.T_CONFIG_MS)
        p.flush()

    def write_eeprom(self, data):
        p = self.p
        p.queue([OP_G6_CMD, self.RESET_ADDR])
        for b in data:
            if b != 0xFF:
                p.queue([OP_G6_LOAD, self.LOAD_DATA, b, 0])
                p.queue([OP_G6_CMD, self.BEGIN_INT])
                p.delay_ms(self.T_CONFIG_MS)
            p.queue([OP_G6_CMD, self.INCREMENT])
        p.flush()


class Gen8(Target):
    """PIC16F1xxxx: 8 bit commands, MSB first, 24 bit data frames."""

    gen = 8
    LOAD_PC, LOAD, LOAD_INC = 0x80, 0x00, 0x02
    READ, READ_INC, INCREMENT = 0xFC, 0xFE, 0xF8
    BEGIN_INT, BEGIN_EXT, END_EXT = 0xE0, 0xC0, 0x82
    BULK_ERASE, ROW_ERASE = 0x18, 0xF0

    T_PROG_MS, T_CONFIG_MS, T_ERASE_MS = 3, 6, 9

    def _key(self):
        self.p.key(b'MCHP', msb_first=True, extra_clocks=0)

    def _seek(self, addr):
        v = addr << 1
        self.p.queue([OP_G8_WRITE, self.LOAD_PC, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])

    def read_words(self, addr, count):
        p = self.p
        self._seek(addr)
        left = count
        while left:
            n = min(left, 31)
            p.queue([OP_G8_READN, self.READ_INC, n], 2 * n)
            left -= n
        return [w & 0x3FFF for w in struct.unpack(f'<{count}H', p.flush())]

    def read_eeprom(self, count):
        return [w & 0xFF for w in self.read_words(EEPROM_HEX_ADDR, count)]

    def bulk_erase(self):
        p = self.p
        # Address in configuration space: flash, EEPROM, user IDs and
        # configuration words are all erased.
        self._seek(0x8000)
        p.queue([OP_G8_CMD, self.BULK_ERASE])
        p.delay_ms(self.T_ERASE_MS)
        p.flush()

    def write_flash(self, words, progress=None):
        p = self.p
        row = self.device.latches
        for base in range(0, len(words), row):
            chunk = words[base:base + row]
            if all(w == BLANK for w in chunk):
                continue
            self._seek(base)
            for i in range(0, row, 29):
                part = chunk[i:i + 29]
                last = self.LOAD if i + 29 >= row else self.LOAD_INC
                req = [OP_G8_LOADN, self.LOAD_INC, last, len(part)]
                for w in part:
                    req += [w & 0xFF, w >> 8]
                p.queue(req)
            p.queue([OP_G8_CMD, self.BEGIN_INT])
            p.delay_ms(self.T_PROG_MS)
            if progress and base % (row * 16) == 0:
                p.flush()
                progress(base, len(words))
        p.flush()

    def _write_single(self, values, t_ms):
        p = self.p
        for a in sorted(values):
            self._seek(a)
            v = values[a] << 1
            p.queue([OP_G8_WRITE, self.LOAD, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF])
            p.queue([OP_G8_CMD, self.BEGIN_INT])
            p.delay_ms(t_ms)
        p.flush()

    def write_config_space(self, values):
        self._write_single(values, self.T_CONFIG_MS)

    def write_eeprom(self, data):
        self._write_single({EEPROM_HEX_ADDR + i: b for i, b in enumerate(data) if b != 0xFF},
                           self.T_CONFIG_MS)


def identify(dev_word):
    for d in DEVICES:
        if (dev_word & d.id_mask) == d.dev_id:
            return d
    return None


def plausible_id(w):
    return w not in (0x0000, 0x3FFF) and (w & 0x3000) in (0x2000, 0x3000)


def connect(probe, args):
    """Enter programming mode and identify the target.  Tries both command
    generations unless --device names one."""
    kw = dict(vdd_mv=args.vdd, hvp=args.hvp, power=not args.no_power, vpp_mv=args.vpp)
    wanted = None
    if args.device:
        wanted = next((d for d in DEVICES if d.name.lower() == args.device.lower()), None)
        if wanted is None:
            raise ProbeError('unknown device %s; known: %s'
                             % (args.device, ', '.join(d.name for d in DEVICES)))
    seen = []
    for cls in (Gen8, Gen6):
        if wanted and wanted.gen != cls.gen:
            continue
        t = cls(probe, **kw)
        t.enter()
        rev, dev = t.read_ids()
        seen.append((cls.gen, rev, dev))
        d = identify(dev)
        if d is not None and d.gen == cls.gen and (wanted is None or d is wanted):
            if kw['power'] and kw['vdd_mv'] > d.vdd_max_mv:
                t.exit()
                raise ProbeError('%s allows at most %.1f V; --vdd is %.1f V'
                                 % (d.name, d.vdd_max_mv / 1000, kw['vdd_mv'] / 1000))
            t.device = d
            t.rev = rev
            t.dev_word = dev
            return t
        if wanted is None and plausible_id(dev) and d is None:
            t.exit()
            raise ProbeError('unsupported device: ID word %04X read with %d bit commands'
                             % (dev, cls.gen))
        t.exit()
        time.sleep(0.1)
    detail = ', '.join('%d bit: %04X' % (g, d) for g, _, d in seen)
    raise ProbeError(f'no supported target answered (device ID read as {detail})')


# ---- HEX files -----------------------------------------------------------

def load_hex(path):
    """Return {word address: 14 bit word} from an Intel HEX file."""
    from pk2boot import read_hex
    mem = read_hex(path)
    words = {}
    for a in sorted(mem):
        if a & 1:
            continue
        words[a >> 1] = (mem[a] | (mem.get(a + 1, 0x3F) << 8)) & 0x3FFF
    return words


def save_hex(path, words):
    from pk2boot import write_hex
    mem = {}
    for a, w in words.items():
        mem[2 * a] = w & 0xFF
        mem[2 * a + 1] = w >> 8
    write_hex(path, mem)


def split_image(device, words):
    """Split a HEX image into (flash list, config-space dict, eeprom bytes or None)."""
    flash = [BLANK] * device.flash_words
    cfg = {}
    ee = None
    for a, w in words.items():
        if a < device.flash_words:
            flash[a] = w
        elif USERID_ADDR <= a < USERID_ADDR + 4 or CONFIG_ADDR <= a < CONFIG_ADDR + device.config_words:
            cfg[a] = w
        elif EEPROM_HEX_ADDR <= a < EEPROM_HEX_ADDR + device.eeprom:
            if ee is None:
                ee = [0xFF] * device.eeprom
            ee[a - EEPROM_HEX_ADDR] = w & 0xFF
        elif a < 0x8000:
            raise ProbeError(f'HEX file has data at {a:#06x}, beyond the {device.flash_words} word flash')
    return flash, cfg, ee


# ---- Commands ------------------------------------------------------------

def describe(t):
    d = t.device
    if d.id_mask == 0x3FFF:
        rev = 'revision %04X' % t.rev
    else:
        rev = 'revision %d' % (t.dev_word & ~d.id_mask & 0x3FFF)
    return '%s, %s (%d bit ICSP commands, %s entry)' % (
        d.name, rev, d.gen, 'high voltage' if t.hvp else 'low voltage')


def cmd_info(p, args):
    i = p.info()
    st, pins = p.status()
    vdd, vpp = p.voltages()
    print('probe firmware %d.%d, protocol %d' % (i['version'] + (i['protocol'],)))
    print(f'target VDD {vdd:.2f} V, VPP rail {vpp:.2f} V')
    flags = [name for bit, name in [
        (ST_VDD_ON, 'VDD on'), (ST_VDD_GND, 'VDD grounded'), (ST_VPP_PUMP, 'VPP pump on'),
        (ST_VPP_SWITCH, 'VPP on MCLR'), (ST_MCLR_GND, 'MCLR grounded'),
        (ST_VDD_FAULT, 'VDD FAULT'), (ST_VPP_FAULT, 'VPP FAULT'), (ST_BUTTON, 'button pressed')]
        if st & bit]
    print('status: ' + (', '.join(flags) or 'idle'))
    print('pins: DAT=%d%s CLK=%d%s' % (pins & 1, ' (input)' if pins & 2 else '',
                                      (pins >> 2) & 1, ' (input)' if pins & 8 else ''))


def cmd_detect(p, args):
    t = connect(p, args)
    try:
        print(describe(t))
        cfg = t.read_words(CONFIG_ADDR, t.device.config_words)
        print('configuration words: ' + ' '.join('%04X' % w for w in cfg))
        print('user IDs: ' + ' '.join('%04X' % w for w in t.read_words(USERID_ADDR, 4)))
    finally:
        t.exit()


def cmd_read(p, args):
    t = connect(p, args)
    try:
        d = t.device
        print(describe(t))
        words = {}
        t0 = time.time()
        for a, w in enumerate(t.read_words(0, d.flash_words)):
            if w != BLANK:
                words[a] = w
        for a, w in zip(range(USERID_ADDR, USERID_ADDR + 4), t.read_words(USERID_ADDR, 4)):
            words[a] = w
        for a, w in enumerate(t.read_words(CONFIG_ADDR, d.config_words), CONFIG_ADDR):
            words[a] = w
        if d.eeprom:
            for a, b in enumerate(t.read_eeprom(d.eeprom), EEPROM_HEX_ADDR):
                words[a] = b
        save_hex(args.file, words)
        used = sum(1 for a in words if a < d.flash_words)
        print(f'read {d.flash_words} words in {time.time() - t0:.1f} s ({used} not blank) -> {args.file}')
    finally:
        t.exit()


def verify(t, flash, cfg, ee):
    d = t.device
    top = max((a for a, w in enumerate(flash) if w != BLANK), default=-1) + 1
    top = (top + d.latches - 1) // d.latches * d.latches
    back = t.read_words(0, top) if top else []
    errors = []
    for a in range(top):
        if back[a] != flash[a]:
            errors.append('flash %04X: wrote %04X, read %04X' % (a, flash[a], back[a]))
    if cfg:
        lo, hi = min(cfg), max(cfg)
        back = t.read_words(lo, hi - lo + 1)
        for a, w in sorted(cfg.items()):
            if back[a - lo] != w:
                errors.append('config %04X: wrote %04X, read %04X' % (a, w, back[a - lo]))
    if ee is not None:
        back = t.read_eeprom(d.eeprom)
        for a in range(d.eeprom):
            if back[a] != ee[a]:
                errors.append('eeprom %02X: wrote %02X, read %02X' % (a, ee[a], back[a]))
    return errors


def report(errors):
    if errors:
        for e in errors[:10]:
            print('  ' + e)
        if len(errors) > 10:
            print(f'  ... and {len(errors) - 10} more')
        raise ProbeError(f'verify failed: {len(errors)} differences')
    print('verified')


def cmd_program(p, args):
    words = load_hex(args.file)
    t = connect(p, args)
    try:
        d = t.device
        print(describe(t))
        flash, cfg, ee = split_image(d, words)
        t0 = time.time()
        t.bulk_erase()
        top = max((a for a, w in enumerate(flash) if w != BLANK), default=-1) + 1
        top = (top + d.latches - 1) // d.latches * d.latches
        t.write_flash(flash[:top])
        if ee is not None:
            t.write_eeprom(ee)
        ids = {a: w for a, w in cfg.items() if a < CONFIG_ADDR}
        conf = {a: w for a, w in cfg.items() if a >= CONFIG_ADDR}
        if ids:
            t.write_config_space(ids)
        errors = verify(t, flash, ids, ee)
        # Configuration words last: they may enable code protection.
        if conf and not errors:
            t.write_config_space(conf)
            lo = min(conf)
            back = t.read_words(lo, max(conf) - lo + 1)
            for a, w in sorted(conf.items()):
                if back[a - lo] != w:
                    errors.append('config %04X: wrote %04X, read %04X' % (a, w, back[a - lo]))
        print(f'programmed {top} words in {time.time() - t0:.1f} s')
        report(errors)
    finally:
        t.exit(keep_power=args.run)
    if args.run:
        print('target left running')


def cmd_verify(p, args):
    words = load_hex(args.file)
    t = connect(p, args)
    try:
        print(describe(t))
        flash, cfg, ee = split_image(t.device, words)
        report(verify(t, flash, cfg, ee))
    finally:
        t.exit()


def cmd_erase(p, args):
    t = connect(p, args)
    try:
        print(describe(t))
        t.bulk_erase()
        print('erased')
    finally:
        t.exit()


def cmd_power(p, args):
    if args.state == 'on':
        p.clear_faults()
        p.set_vdd(args.vdd)
        p.pins(PINS_IDLE)
        p.mclr(MCLR_RELEASE)
        p.vdd_mode(VDD_ON)
        p.flush()
        time.sleep(0.1)
    else:
        p.target_off()
        p.vdd_mode(VDD_DISCHARGE)
        p.delay_ms(50)
        p.vdd_mode(VDD_OFF)
        p.flush()
    vdd, vpp = p.voltages()
    print(f'target VDD {vdd:.2f} V')


def cal_from_points(points):
    """points: list of (setpoint mV, measured V, probe ADC reading V), taken
    with the calibration at unity.  Returns (adc_cal, vdd_offset, vdd_cal) as
    stored in the probe EEPROM (the stock PICkit 2 format)."""
    adc_cal = round(256 * sum(m / a for _, m, a in points) / len(points))
    # Measured VDD against the nominal duty count d = 32 V + 10.5 is a line.
    xs = [int((mv * 32 + 10500) / 1000) for mv, _, _ in points]
    ys = [m for _, m, _ in points]
    n = len(points)
    mx, my = sum(xs) / n, sum(ys) / n
    a = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    b = my - a * mx
    vdd_cal = round(4 / a)
    vdd_offset = round(-32 * b - 10.5)
    if not (0xC0 <= adc_cal <= 0x140 and 0x50 <= vdd_cal <= 0xAF and -128 <= vdd_offset <= 127):
        raise ProbeError('calibration out of range: ADC %#x, VDD offset %d, VDD factor %#x'
                         % (adc_cal, vdd_offset, vdd_cal))
    return adc_cal, vdd_offset, vdd_cal


def cmd_calibrate(p, args):
    """Voltage calibration.  The PICkit 2 measures and generates voltages
    relative to its USB supply, so the factors belong to a unit and port."""
    if args.action == 'show':
        b = p.run([OP_EE_READ, 0, 4], 4)
        adc = b[0] | (b[1] << 8)
        off = b[2] - 256 if b[2] > 127 else b[2]
        valid = 0xC0 <= adc <= 0x140 and 0x50 <= b[3] <= 0xAF
        if valid:
            print('ADC factor %.4f, VDD offset %d counts, VDD factor %.4f' % (adc / 256, off, b[3] / 128))
        else:
            print('not calibrated (EEPROM %s); unity factors in use' % b.hex(' '))
        return
    if args.action == 'clear':
        p.run([OP_EE_WRITE, 0, 4, 0xFF, 0xFF, 0xFF, 0xFF])
        print('calibration cleared')
        return

    points = []
    if args.data:
        for item in args.data.split(','):
            mv, measured, adc = item.split(':')
            points.append((int(mv), float(measured), float(adc)))
    else:
        print('Connect a voltmeter to VDD (pin 2) and ground (pin 3) of the PICkit 2.')
        print('Setpoints: %s mV.  Remove any target that cannot take the highest one.'
              % ', '.join(str(v) for v in args.setpoints))
        p.run([OP_EE_WRITE, 0, 4, 0xFF, 0xFF, 0xFF, 0xFF])      # unity while measuring
        p.clear_faults()
        p.pins(PINS_IDLE)
        p.mclr(MCLR_RELEASE)
        try:
            for mv in args.setpoints:
                p.set_vdd(mv)
                p.vdd_mode(VDD_ON)
                p.flush()
                time.sleep(0.5)
                adc = sum(p.voltages()[0] for _ in range(16)) / 16
                measured = float(input(f'  setpoint {mv / 1000:.2f} V, voltmeter reads (V): '))
                points.append((mv, measured, adc))
        finally:
            p.target_off()
    if len(points) < 2:
        raise ProbeError('calibration needs at least two points')
    adc_cal, off, cal = cal_from_points(points)
    p.run([OP_EE_WRITE, 0, 4, adc_cal & 0xFF, adc_cal >> 8, off & 0xFF, cal])
    print('stored: ADC factor %.4f, VDD offset %d counts, VDD factor %.4f' % (adc_cal / 256, off, cal / 128))


def cmd_scope(p, args):
    """Repeat a waveform so the rails and pins can be checked on a scope."""
    what = args.what
    print(f'{what} test running; Ctrl-C stops it')
    p.clear_faults()
    try:
        if what == 'vdd':
            # VDD steps through its range with the target switch on.
            p.vdd_mode(VDD_ON)
            while True:
                for mv in (2500, 3300, 5000):
                    p.set_vdd(mv)
                    p.flush()
                    time.sleep(0.5)
                    vdd, vpp = p.voltages()
                    print(f'  set {mv / 1000:.2f} V: measured {vdd:.2f} V')
        elif what == 'vpp':
            # The rail is always regulated; MCLR alternates ground / VPP.
            p.set_vdd(args.vdd)
            p.set_vpp(args.vpp)
            p.mclr(MCLR_GROUND)
            p.flush()
            vpp = p.wait_vpp(args.vpp)
            print(f'  VPP rail {vpp:.2f} V')
            while True:
                p.mclr(MCLR_VPP)
                p.delay_ms(5)
                p.mclr(MCLR_GROUND)
                p.delay_ms(5)
                p.flush()
        elif what == 'mclr':
            # Release, ground, VPP level without the pump (= VDD setpoint).
            p.set_vdd(args.vdd)
            while True:
                for m in (MCLR_GROUND, MCLR_VPP, MCLR_RELEASE):
                    p.mclr(m)
                    p.delay_ms(5)
                p.flush()
        else:
            # 0xA5 LSB first then 0xA5 MSB first, 1 ms apart, needs target VDD
            # for the output drivers.
            p.set_vdd(args.vdd)
            p.vdd_mode(VDD_ON)
            p.pins(PINS_LOW)
            p.flush()
            while True:
                p.write_bits(0xA5, 8)
                p.delay_us(100)
                p.write_bits(0xA5, 8, msb_first=True)
                p.delay_ms(1)
                p.flush()
    except KeyboardInterrupt:
        pass
    finally:
        p.target_off()
        print('outputs off')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--vdd', type=int, default=3000, metavar='MV', help='target VDD in mV (default 3000)')
    ap.add_argument('--vpp', type=int, default=8500, metavar='MV', help='VPP in mV for --hvp (default 8500)')
    ap.add_argument('--hvp', action='store_true', help='high-voltage entry instead of the LVP key')
    ap.add_argument('--no-power', action='store_true', help='target has its own supply')
    ap.add_argument('--device', help='device name; default is to detect it')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('info').set_defaults(fn=cmd_info)
    sub.add_parser('detect').set_defaults(fn=cmd_detect)
    s = sub.add_parser('read'); s.add_argument('file'); s.set_defaults(fn=cmd_read)
    s = sub.add_parser('program'); s.add_argument('file')
    s.add_argument('--run', action='store_true', help='leave the target powered and running')
    s.set_defaults(fn=cmd_program)
    s = sub.add_parser('verify'); s.add_argument('file'); s.set_defaults(fn=cmd_verify)
    sub.add_parser('erase').set_defaults(fn=cmd_erase)
    s = sub.add_parser('power'); s.add_argument('state', choices=['on', 'off']); s.set_defaults(fn=cmd_power)
    s = sub.add_parser('calibrate'); s.add_argument('action', choices=['show', 'run', 'clear'])
    s.add_argument('--setpoints', type=lambda v: [int(x) for x in v.split(',')], default=[2500, 3300, 4500],
                   metavar='MV,MV', help='VDD setpoints to measure (default 2500,3300,4500)')
    s.add_argument('--data', metavar='MV:MEASURED:ADC,...',
                   help='use measurements taken earlier at unity calibration instead of prompting')
    s.set_defaults(fn=cmd_calibrate)
    s = sub.add_parser('scope'); s.add_argument('what', choices=['vdd', 'vpp', 'mclr', 'clock'])
    s.set_defaults(fn=cmd_scope)
    args = ap.parse_args()

    try:
        p = Probe()
    except ProbeError as e:
        sys.exit(f'error: {e}')
    try:
        args.fn(p, args)
    except ProbeError as e:
        try:
            p._queue = []
            p.target_off()
        except Exception:
            pass
        sys.exit(f'error: {e}')
    finally:
        p.close()


if __name__ == '__main__':
    main()
