"""In-circuit debugging of PIC16(L)F193x devices through the PICkit 2 probe.

This is an independent implementation.  It uses a debug executive written
for this project (below, assembled by asm14.py), not Microchip's, and the
behaviour of the on-chip debug logic was established by experiment on a
PIC16LF1937; docs/icd.md records what was found and how.

How on-chip debug works on these parts
--------------------------------------
With the DEBUG configuration bit programmed (0), the core has a second,
512-word program space at 0x8000-0x81FF (mirrored through 0x8000-0xFFFF)
that holds the configuration words and, from 0x8010 to 0x80FF, room for a
debug executive.  The core enters that space at the debug vector, 0x8004:

  * after executing the instruction at the hardware breakpoint address,
    when the breakpoint is enabled.  Power-on reset enables it at address
    0, so a fresh target stops with PC = 1;
  * after executing opcode 0x0002, a software breakpoint;
  * when ICSPCLK is driven high while user code runs (external halt).

In debug mode these registers in bank 31 matter:

  0xF8C  debug pins: bit 7 ICSPDAT, bit 6 ICSPCLK (write: output level,
         read: pin), bit 3 ICSPDAT direction, bit 2 ICSPCLK direction (1 = input)
  0xF8E  bit 7 reads 1 in debug mode
  0xF90  read: PC at the halt.  Write: hardware breakpoint address.
  0xF91  (high 7 bits); bit 7 enables the breakpoint.  After a halt the pair
         holds the current PC, so resuming with the enable bit still set
         executes exactly one instruction: that is the single step.
  0xFE3  the user's BSR, saved on entry and restored on return

Opcode 0x0004 returns to user code where it stopped; no way of changing
that address has been found.  W, STATUS, the FSRs and PCLATH are not
saved by the hardware.

The executive
-------------
It saves the registers it uses in the 16 bytes of RAM that the toolchain
reserves for a debugger (0x320-0x32F), then serves three commands over the
debug link (firmware/icsp.c describes the link):

  0x01 addr_lo addr_hi          -> one byte read through FSR0
  0x02 addr_lo addr_hi value       write one byte through FSR0
  0x03                             restore the registers and resume

Everything else (registers, PC, stepping, breakpoints) is done by the host
with those three commands.

Breakpoints stop after the instruction, not before it ("skid" of one).
"""
import time

from asm14 import Asm, W, F, STATUS, FSR0L, FSR0H, FSR1L, FSR1H, INDF0, INDF1, Z
from pk2probe import (ProbeError, Gen6, identify, split_image, verify, BLANK,
                      OP_G6_CMD, OP_ICD_TX, OP_ICD_RX, OP_ICD_READY,
                      PINS_IDLE, PIN_CLK, PIN_DAT_IN, MCLR_GROUND, MCLR_RELEASE,
                      VDD_OFF, VDD_ON, VDD_DISCHARGE)

# ---- Device facts (PIC16(L)F193x) ---------------------------------------

DEBUG_VECTOR = 0x8004
EXEC_START = 0x8010
EXEC_END = 0x8100                   # first address past the writable area
EXEC_ROWS = range(0x8020, 0x8100, 0x20)   # rows that need a row erase
CONFIG2_ADDR = 0x8008
CONFIG2_DEBUG = 0x1000              # 0 = debugger enabled

REG_PINS = 0xF8C
REG_CTRL = 0xF8E
REG_PCL = 0xF90
REG_PCH = 0xF91
REG_BSR = 0xFE3
BREAK_ENABLE = 0x80

OP_DEBUG_RETURN = 0x0004

# Executive save area, in the RAM reserved for a debugger (0x320-0x32F)
SAVE_W, SAVE_STATUS = 0x320, 0x321          # STATUS is stored with its nibbles swapped
SAVE_FSR0L, SAVE_FSR0H, SAVE_FSR1L, SAVE_FSR1H = 0x322, 0x323, 0x324, 0x325
EXEC_RAM = range(0x320, 0x330)

CMD_READ, CMD_WRITE, CMD_GO = 0x01, 0x02, 0x03

# Pin register values
P_IDLE = 0x0C        # both pins inputs
P_READY = 0x48       # clock high, data input
P_LISTEN = 0x08      # clock low, data input


def build_executive():
    """Assemble the debug executive.  Returns {address: word}, including the
    debug vector."""
    a = Asm()
    # Bank 6 offsets
    s_w, s_status, s_f0l, s_f0h, s_f1l, s_f1h = 0x20, 0x21, 0x22, 0x23, 0x24, 0x25
    txb, rxb, cnt = 0x26, 0x27, 0x28

    def pause(cycles):
        """Burn instruction cycles so the probe can follow at any target clock."""
        for _ in range(cycles // 2):
            a.bra(a.pc + 1)         # branch to the next instruction: 2 cycles, 1 word

    def handshake():
        """Raise the clock, wait for the probe to pulse data low, drop the clock."""
        a.movlw(P_READY)
        a.movwf(INDF1)
        here = a.pc
        a.btfsc(INDF1, 7)
        a.goto(here)
        here = a.pc
        a.btfss(INDF1, 7)
        a.goto(here)
        a.movlw(P_LISTEN)
        a.movwf(INDF1)

    a.org(DEBUG_VECTOR)
    a.goto(EXEC_START)

    a.org(EXEC_START)
    # The hardware has saved BSR, so the bank can be changed straight away.
    # SWAPF reads STATUS without changing it.
    a.movlb(6)
    a.movwf(s_w)
    a.swapf(STATUS, W)
    a.movwf(s_status)
    for reg, save in ((FSR0L, s_f0l), (FSR0H, s_f0h), (FSR1L, s_f1l), (FSR1H, s_f1h)):
        a.movf(reg, W)
        a.movwf(save)
    a.movlw(REG_PINS & 0xFF)            # FSR1 addresses the pin register throughout
    a.movwf(FSR1L)
    a.movlw(REG_PINS >> 8)
    a.movwf(FSR1H)

    a.label('main')
    a.call('rx')
    a.xorlw(CMD_READ)
    a.btfsc(STATUS, Z)
    a.goto('read')
    a.xorlw(CMD_READ ^ CMD_WRITE)
    a.btfsc(STATUS, Z)
    a.goto('write')
    a.xorlw(CMD_WRITE ^ CMD_GO)
    a.btfss(STATUS, Z)
    a.goto('main')

    # go: put everything back and return to user code
    a.movlw(P_IDLE)
    a.movwf(INDF1)
    for reg, save in ((FSR1L, s_f1l), (FSR1H, s_f1h), (FSR0L, s_f0l), (FSR0H, s_f0h)):
        a.movf(save, W)
        a.movwf(reg)
    a.swapf(s_status, W)
    a.movwf(STATUS)
    a.swapf(s_w, F)                     # two swaps restore W without touching STATUS
    a.swapf(s_w, W)
    a.word(OP_DEBUG_RETURN)

    a.label('read')
    a.call('rx')
    a.movwf(FSR0L)
    a.call('rx')
    a.movwf(FSR0H)
    a.movf(INDF0, W)
    a.call('tx')
    a.goto('main')

    a.label('write')
    a.call('rx')
    a.movwf(FSR0L)
    a.call('rx')
    a.movwf(FSR0H)
    a.call('rx')
    a.movwf(INDF0)
    a.nop()                             # skipped by the core if the write
    a.nop()                             # started a program memory read
    a.goto('main')

    # tx: send W, MSB first.  Data changes while the clock is low; the probe
    # samples after the falling edge.
    a.label('tx')
    a.movwf(txb)
    handshake()
    a.movlw(8)
    a.movwf(cnt)
    a.label('txbit')
    a.movlw(0x00)
    a.btfsc(txb, 7)
    a.movlw(0x80)
    a.movwf(INDF1)                      # data out, clock low
    a.iorlw(0x40)
    a.movwf(INDF1)                      # clock high
    a.rlf(txb, F)
    pause(8)
    a.andlw(0xBF)
    a.movwf(INDF1)                      # clock low, data held
    pause(6)
    a.decfsz(cnt, F)
    a.goto('txbit')
    a.movlw(P_LISTEN)
    a.movwf(INDF1)
    a.ret()

    # rx: receive a byte into W, MSB first.  The probe sets data when it sees
    # the clock rise.
    a.label('rx')
    handshake()
    a.movlw(8)
    a.movwf(cnt)
    a.label('rxbit')
    a.movlw(P_READY)
    a.movwf(INDF1)                      # clock high
    pause(12)
    a.rlf(rxb, F)
    a.bcf(rxb, 0)
    a.btfsc(INDF1, 7)
    a.bsf(rxb, 0)
    a.movlw(P_LISTEN)
    a.movwf(INDF1)                      # clock low
    pause(6)
    a.decfsz(cnt, F)
    a.goto('rxbit')
    a.movf(rxb, W)
    a.ret()

    words = a.image()
    if max(words) >= EXEC_END:
        raise AssertionError('executive does not fit: ends at %#x' % max(words))
    return words


class DebugError(Exception):
    pass


class Debugger:
    """A debug session with a PIC16(L)F193x target."""

    def __init__(self, probe, vdd_mv=3000, power=True):
        self.p = probe
        self.vdd_mv = vdd_mv
        self.power = power
        self.device = None
        self.image = {}                 # user program, for reading program memory

    # -- loading -----------------------------------------------------------

    def load(self, words, hvp=True):
        """Program a user image ({word address: word}) for debugging: the
        image, the executive, and the configuration with DEBUG enabled."""
        p = self.p
        t = Gen6(p, vdd_mv=self.vdd_mv, hvp=hvp, power=self.power)
        t.enter()
        rev, dev = t.read_ids()
        t.device = identify(dev)
        if t.device is None or t.device.gen != 6 or not t.device.name.startswith(('PIC16F193', 'PIC16LF193')):
            t.exit()
            raise DebugError('debugging supports the PIC16(L)F193x; device ID %04X' % dev)
        self.device = t.device

        t.bulk_erase()
        for row in EXEC_ROWS:
            t._seek(row)
            p.queue([OP_G6_CMD, Gen6.ERASE_ROW])
            p.delay_ms(6)
        p.flush()

        flash, cfg, ee = split_image(t.device, words)
        if CONFIG2_ADDR not in cfg:
            t.exit()
            raise DebugError('the image has no configuration words')
        cfg[CONFIG2_ADDR] &= ~CONFIG2_DEBUG
        top = max((a for a, w in enumerate(flash) if w != BLANK), default=-1) + 1
        top = (top + t.device.latches - 1) // t.device.latches * t.device.latches
        t.write_flash(flash[:top])
        if ee is not None:
            t.write_eeprom(ee)
        ids = {a: w for a, w in cfg.items() if a < DEBUG_VECTOR}
        if ids:
            t.write_config_space(ids)
        errors = verify(t, flash, ids, ee)

        ex = build_executive()
        t.write_config_space(ex)
        lo, hi = min(ex), max(ex)
        back = t.read_words(lo, hi - lo + 1)
        errors += ['executive %04X' % a for a in ex if back[a - lo] != ex[a]]

        conf = {a: w for a, w in cfg.items() if a > DEBUG_VECTOR}
        t.write_config_space(conf)
        lo = min(conf)
        back = t.read_words(lo, max(conf) - lo + 1)
        errors += ['config %04X' % a for a, w in conf.items() if back[a - lo] != w]
        if errors:
            t.exit()
            raise DebugError('programming failed: ' + ', '.join(errors[:5]))

        self.image = {a: w for a, w in enumerate(flash) if w != BLANK}
        t.exit(keep_power=True)         # target leaves reset
        self._after_reset()

    def attach(self, image=None):
        """Attach to a target that is already programmed for debugging and powered."""
        if image:
            self.image = dict(image)
        self.halt()

    def unload(self):
        """Erase the executive and the device, leaving it blank."""
        t = Gen6(self.p, vdd_mv=self.vdd_mv, hvp=True, power=self.power)
        t.enter()
        t.bulk_erase()
        for row in EXEC_ROWS:
            t._seek(row)
            self.p.queue([OP_G6_CMD, Gen6.ERASE_ROW])
            self.p.delay_ms(6)
        self.p.flush()
        t.exit()

    # -- link --------------------------------------------------------------

    def halted(self):
        """True when the executive is waiting for a command."""
        return bool(self.p.run([OP_ICD_READY], 1)[0])

    def _wait_halted(self, timeout):
        end = time.time() + timeout
        while True:
            if self.halted():
                return True
            if time.time() > end:
                return False
            time.sleep(0.002)

    def _xfer(self, tx, rx=0):
        p = self.p
        p.flush()
        p.queue([OP_ICD_TX, 50, len(tx)] + list(tx))
        if rx:
            p.queue([OP_ICD_RX, 50, rx], rx)
        try:
            return p.flush()
        except ProbeError as e:
            p._queue = []
            raise DebugError('lost contact with the debug executive (%s)' % e)

    def read8(self, addr):
        return self._xfer([CMD_READ, addr & 0xFF, addr >> 8], 1)[0]

    def write8(self, addr, value):
        self._xfer([CMD_WRITE, addr & 0xFF, addr >> 8, value & 0xFF])

    def read_block(self, addr, n):
        p = self.p
        p.flush()
        for i in range(n):
            a = addr + i
            p.queue([OP_ICD_TX, 50, 3, CMD_READ, a & 0xFF, a >> 8])
            p.queue([OP_ICD_RX, 50, 1], 1)
        try:
            return p.flush()
        except ProbeError as e:
            p._queue = []
            raise DebugError('lost contact with the debug executive (%s)' % e)

    # -- run control -------------------------------------------------------

    def _after_reset(self):
        if not self._wait_halted(0.5):
            self.halt()

    def halt(self):
        """Stop a running target."""
        if self.halted():
            return
        p = self.p
        p.pins(PIN_CLK | PIN_DAT_IN)        # clock driven high
        p.delay_us(200)
        p.pins(PINS_IDLE)
        p.flush()
        if not self._wait_halted(0.5):
            raise DebugError('the target did not halt; is it programmed for debugging and powered?')

    def set_breakpoint(self, addr):
        """Arm the hardware breakpoint.  The target halts after it has
        executed the instruction at addr (there is one breakpoint)."""
        self.write8(REG_PCL, addr & 0xFF)
        self.write8(REG_PCH, ((addr >> 8) & 0x7F) | BREAK_ENABLE)

    def clear_breakpoint(self):
        self.write8(REG_PCH, self.read8(REG_PCH) & ~BREAK_ENABLE & 0xFF)

    def step(self):
        """Execute one instruction: a breakpoint on the current instruction."""
        self.set_breakpoint(self.pc)
        self._xfer([CMD_GO])
        if not self._wait_halted(1.0):
            raise DebugError('the target did not come back from a single step')

    def resume(self, breakpoint=None):
        """Run until halt() or, if given, until the instruction at
        breakpoint has executed."""
        if breakpoint is None:
            self.clear_breakpoint()
        else:
            self.set_breakpoint(breakpoint)
        self._xfer([CMD_GO])

    def wait(self, timeout):
        """Wait for a running target to stop at a breakpoint or trap."""
        return self._wait_halted(timeout)

    def reset(self):
        """Reset the target and stop it after the instruction at the reset
        vector (PC = 1, or the target of a GOTO placed there).

        MCLR has no effect while the executive is running, so the target is
        resumed with the breakpoint on address 0 and then reset; the
        breakpoint register survives the reset.  User code runs for a moment
        in between.  If MCLR is not a reset input, the probe power-cycles
        the target instead, which arms the same breakpoint."""
        p = self.p
        if not self.halted():
            self.halt()
        self.resume(breakpoint=0)
        p.mclr(MCLR_GROUND)
        p.delay_ms(2)
        p.pins(PINS_IDLE)
        p.mclr(MCLR_RELEASE)
        p.flush()
        if self._wait_halted(0.5) and self.pc <= 1:
            self.write8(REG_BSR, 0)     # the saved copy is not cleared by the reset
            return
        if not self.power:
            raise DebugError('the target did not stop after an MCLR reset')
        p.pins(PINS_IDLE)
        p.vdd_mode(VDD_DISCHARGE)
        p.delay_ms(100)
        p.vdd_mode(VDD_OFF)
        p.vdd_mode(VDD_ON)
        p.flush()
        if not self._wait_halted(1.0):
            raise DebugError('the target did not stop after a power cycle')

    # -- registers ---------------------------------------------------------

    @property
    def pc(self):
        return self.read8(REG_PCL) | ((self.read8(REG_PCH) & 0x7F) << 8)

    # Where the user's value of a core register lives while halted
    _HOME = {0x004: SAVE_FSR0L, 0x005: SAVE_FSR0H, 0x006: SAVE_FSR1L, 0x007: SAVE_FSR1H,
             0x008: REG_BSR, 0x009: SAVE_W}

    def _map(self, addr):
        """Translate a data address to where the user's value is held."""
        if addr < 0x1000:
            core = addr & 0x7F
            if core in self._HOME:
                return self._HOME[core]
            if core < 0x0C:
                return core             # other core registers: any bank will do
        return addr

    def read_data(self, addr):
        """Read user data memory (traditional or 0x2000+ linear address)."""
        if addr < 0x1000 and (addr & 0x7F) == 0x03:
            v = self.read8(SAVE_STATUS)
            return ((v << 4) | (v >> 4)) & 0xFF
        if addr < 0x1000 and (addr & 0x7F) == 0x02:
            return self.pc & 0xFF
        return self.read8(self._map(addr))

    def write_data(self, addr, value):
        if addr < 0x1000 and (addr & 0x7F) == 0x03:
            self.write8(SAVE_STATUS, ((value << 4) | (value >> 4)) & 0xFF)
        elif addr < 0x1000 and (addr & 0x7F) == 0x02:
            raise DebugError('the program counter of a halted target cannot be changed')
        else:
            self.write8(self._map(addr), value)

    def registers(self):
        """The core registers of the halted target."""
        p = self.p
        addrs = [REG_PCL, REG_PCH, SAVE_W, SAVE_STATUS, REG_BSR, 0x00A,
                 SAVE_FSR0L, SAVE_FSR0H, SAVE_FSR1L, SAVE_FSR1H, 0xFED, 0x00B]
        p.flush()
        for a in addrs:
            p.queue([OP_ICD_TX, 50, 3, CMD_READ, a & 0xFF, a >> 8])
            p.queue([OP_ICD_RX, 50, 1], 1)
        try:
            v = p.flush()
        except ProbeError as e:
            p._queue = []
            raise DebugError('lost contact with the debug executive (%s)' % e)
        return {
            'PC': v[0] | ((v[1] & 0x7F) << 8),
            'W': v[2],
            'STATUS': ((v[3] << 4) | (v[3] >> 4)) & 0xFF,
            'BSR': v[4] & 0x1F,
            'PCLATH': v[5] & 0x7F,
            'FSR0': v[6] | (v[7] << 8),
            'FSR1': v[8] | (v[9] << 8),
            'STKPTR': v[10] & 0x1F,
            'INTCON': v[11],
        }

    def read_program(self, addr):
        """Program memory comes from the image that was loaded."""
        return self.image.get(addr, BLANK)
