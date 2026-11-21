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
  0x04                             run the EECON2 unlock sequence and set WR

Everything else (registers, PC, stepping, breakpoints) is done by the host
with those three commands.

The hardware breakpoint stops after the instruction, not before it ("skid"
of one).

Software breakpoints
--------------------
Any number, and they stop before the instruction.  load() puts a two-word
gadget in user flash, at the same offset of every page:

    G:    0x0002   break
    G+1:  RETURN

A breakpoint replaces its instruction with CALL G; the executive rewrites
the flash row.  The target then stops at G+1 with the breakpoint address
+ 1 on top of the return stack.  To go on, the debugger pops that, does
the work of the replaced instruction itself (emu16f1.py), pushes the
address of the next instruction and resumes: the RETURN goes there.
docs/icd.md, experiments D14 to D16, has the evidence.
"""
import json
import os
import time

import emu16f1

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

CMD_READ, CMD_WRITE, CMD_GO, CMD_UNLOCK = 0x01, 0x02, 0x03, 0x04

# Software breakpoints
OP_BREAK, OP_RETURN, OP_CALL = 0x0002, 0x0008, 0x2000
PAGE = 0x800
FLASH_ROW, FLASH_LATCHES = 32, 8            # words per erase, words per write
STKPTR, TOSL, TOSH = 0xFED, 0xFEE, 0xFEF
EEADRL, EEADRH, EEDATL, EEDATH, EECON1 = 0x191, 0x192, 0x193, 0x194, 0x195
EE_EEPGD, EE_LWLO, EE_FREE, EE_WREN, EE_RD = 0x80, 0x20, 0x10, 0x04, 0x01


def choose_gadget(flash):
    """The highest offset at which two words are blank in every page of the
    image, or None."""
    pages = range(0, len(flash), PAGE)
    for k in range(PAGE - 2, 7, -1):
        if all(flash[p + k] == BLANK and flash[p + k + 1] == BLANK for p in pages):
            return k
    return None

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
    a.btfsc(STATUS, Z)
    a.goto('go')
    a.xorlw(CMD_GO ^ CMD_UNLOCK)
    a.btfss(STATUS, Z)
    a.goto('main')

    # unlock: start the flash or EEPROM operation the host has set up in
    # EEADR, EEDAT and EECON1.  The sequence must be consecutive instructions.
    a.movlb(3)
    a.movlw(0x55)
    a.movwf(0x16)                       # EECON2
    a.movlw(0xAA)
    a.movwf(0x16)
    a.bsf(0x15, 1)                      # EECON1.WR; the core stalls for a flash operation
    a.nop()
    a.nop()
    a.movlb(6)
    a.goto('main')

    # go: put everything back and return to user code
    a.label('go')
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

    def __init__(self, probe, vdd_mv=3000, power=True, state_path=None):
        """state_path names a file that carries the software breakpoints
        from one process to the next (the command line tool is run once
        per command).  Without it they live in this object only."""
        self.p = probe
        self.vdd_mv = vdd_mv
        self.power = power
        self.device = None
        self.image = {}                 # user program, for reading program memory
        self.state_path = state_path
        self.gadget = None              # offset of the break/RETURN pair in each page
        self.flash_words = 0
        self.breaks = {}                # address: the instruction replaced there
        self.ghost = None               # (address, instruction) of a breakpoint removed
                                        # while the target was stopped at it
        self._load_state()

    def _load_state(self):
        if not self.state_path or not os.path.exists(self.state_path):
            return
        with open(self.state_path) as f:
            st = json.load(f)
        self.gadget = st.get('gadget')
        self.flash_words = st.get('flash_words', 0)
        self.breaks = {int(a): w for a, w in st.get('breaks', {}).items()}
        self.ghost = tuple(st['ghost']) if st.get('ghost') else None

    def _save_state(self):
        if not self.state_path:
            return
        os.makedirs(os.path.dirname(self.state_path) or '.', exist_ok=True)
        with open(self.state_path, 'w') as f:
            json.dump({'gadget': self.gadget, 'flash_words': self.flash_words,
                       'breaks': self.breaks, 'ghost': self.ghost}, f)

    def _forget_state(self):
        self.gadget, self.flash_words, self.breaks, self.ghost = None, 0, {}, None
        if self.state_path and os.path.exists(self.state_path):
            os.remove(self.state_path)

    # -- loading -----------------------------------------------------------

    def load(self, words, hvp=True, gadget=True):
        """Program a user image ({word address: word}) for debugging: the
        image, the executive, and the configuration with DEBUG enabled.
        Unless gadget is false, also the software breakpoint gadget, in
        flash that the image leaves blank."""
        p = self.p
        self._forget_state()
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
        k = choose_gadget(flash) if gadget else None
        if k is not None:
            for page in range(0, len(flash), PAGE):
                flash[page + k], flash[page + k + 1] = OP_BREAK, OP_RETURN
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
        self.gadget, self.flash_words = k, len(flash)
        self._save_state()
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
        self._forget_state()

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

    def _raw_step(self):
        """Let the target execute one instruction from flash."""
        self.set_breakpoint(self._real_pc())
        self._xfer([CMD_GO])
        if not self._wait_halted(1.0):
            raise DebugError('the target did not come back from a single step')

    def step(self):
        """Execute one instruction.  At a software breakpoint that is the
        instruction the breakpoint replaced."""
        self._leave_site()
        self._raw_step()

    def resume(self, breakpoint=None):
        """Run until halt(), a software breakpoint or, if given, until the
        instruction at the hardware breakpoint address has executed."""
        self._leave_site()
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
        p.delay_ms(10)                  # let the executive leave debug mode first
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

    # -- software breakpoints ----------------------------------------------

    def _real_pc(self):
        return self.read8(REG_PCL) | ((self.read8(REG_PCH) & 0x7F) << 8)

    def _tos(self):
        return self.read8(TOSL) | self.read8(TOSH) << 8

    def push(self, addr):
        """Push onto the user's return stack."""
        self.write8(STKPTR, (self.read8(STKPTR) + 1) & 0x1F)
        self.write8(TOSL, addr & 0xFF)
        self.write8(TOSH, (addr >> 8) & 0x7F)

    def pop(self):
        sp = self.read8(STKPTR) & 0x1F
        if sp > 15:
            raise DebugError('the return stack is empty')
        addr = self._tos()
        self.write8(STKPTR, (sp - 1) & 0x1F)
        return addr

    def _site(self, pc=None):
        """The address of the software breakpoint the target is stopped at:
        it has executed CALL G and the break, and nothing else.  None when
        it is anywhere else."""
        if self.gadget is None:
            return None
        if pc is None:
            pc = self._real_pc()
        if pc >= self.flash_words or pc % PAGE != self.gadget + 1:
            return None
        return (self._tos() - 1) & 0x7FFF

    def _original(self, site):
        if site in self.breaks:
            return self.breaks[site]
        if self.ghost and self.ghost[0] == site:
            return self.ghost[1]
        raise DebugError('stopped at a software breakpoint at %04X that this session did not set; '
                         'its instruction is not known' % site)

    def _leave_site(self):
        """Bring the target to where its next instruction from flash is the
        right one to execute.  At a software breakpoint: do the work of the
        replaced instruction and leave the next address on the stack for the
        gadget's RETURN.  The target stays halted, at the RETURN."""
        if self.gadget is None:
            return
        pc = self._real_pc()
        if pc in self.breaks:
            self._raw_step()            # the CALL to the gadget
            pc = self._real_pc()
        if pc < self.flash_words and pc % PAGE == self.gadget:
            self._raw_step()            # the break
            pc = self._real_pc()
        site = self._site(pc)
        if site is None:
            return
        word = self._original(site)
        self.pop()
        try:
            nxt = emu16f1.execute(self, word, site)
        except emu16f1.Unsupported as e:
            self.push(site + 1)
            raise DebugError(str(e))
        self.push(nxt)
        if self.ghost:
            self.ghost = None
            self._save_state()

    def _flash_ops(self, ops):
        """Run executive commands in one batch.  ops are ('w', addr, value),
        ('r', addr) and ('u',) for the unlock.  Returns the bytes read."""
        p = self.p
        p.flush()
        for op in ops:
            if op[0] == 'w':
                p.queue([OP_ICD_TX, 50, 4, CMD_WRITE, op[1] & 0xFF, op[1] >> 8, op[2] & 0xFF])
            elif op[0] == 'r':
                p.queue([OP_ICD_TX, 50, 3, CMD_READ, op[1] & 0xFF, op[1] >> 8])
                p.queue([OP_ICD_RX, 50, 1], 1)
            else:
                p.queue([OP_ICD_TX, 50, 1, CMD_UNLOCK])
        try:
            return p.flush()
        except ProbeError as e:
            p._queue = []
            raise DebugError('lost contact with the debug executive (%s)' % e)

    def read_flash(self, addr, n=1):
        """Read n words of program memory from the halted part itself.
        Changes EEADR, EEDAT and EECON1; see _rewrite_row for saving them."""
        ops = []
        for a in range(addr, addr + n):
            ops += [('w', EEADRL, a & 0xFF), ('w', EEADRH, a >> 8), ('w', EECON1, EE_EEPGD | EE_RD),
                    ('r', EEDATL), ('r', EEDATH)]
        v = self._flash_ops(ops)
        return [v[i] | v[i + 1] << 8 for i in range(0, len(v), 2)]

    def _rewrite_row(self, addr, word, check=None):
        """Change one word of program memory: erase its row and write the
        row again.  Returns the word that was there.  check(old word) may
        raise to stop before anything is erased."""
        saved = self._flash_ops([('r', r) for r in (EEADRL, EEADRH, EEDATL, EEDATH, EECON1)])
        try:
            base = addr - addr % FLASH_ROW
            row = self.read_flash(base, FLASH_ROW)
            old = row[addr - base]
            if check:
                check(old)
            row[addr - base] = word
            ops = [('w', EEADRL, base & 0xFF), ('w', EEADRH, base >> 8),
                   ('w', EECON1, EE_EEPGD | EE_FREE | EE_WREN), ('u',)]
            for i in range(0, FLASH_ROW, FLASH_LATCHES):
                group = row[i:i + FLASH_LATCHES]
                if all(w == BLANK for w in group):
                    continue
                for j, w in enumerate(group):
                    last = j == FLASH_LATCHES - 1
                    ops += [('w', EEADRL, (base + i + j) & 0xFF), ('w', EEDATL, w & 0xFF), ('w', EEDATH, w >> 8),
                            ('w', EECON1, EE_EEPGD | EE_WREN | (0 if last else EE_LWLO)), ('u',)]
            ops.append(('w', EECON1, EE_EEPGD))
            self._flash_ops(ops)
            back = self.read_flash(base, FLASH_ROW)
            if back != row:
                bad = [base + i for i in range(FLASH_ROW) if back[i] != row[i]]
                raise DebugError('flash row %04X did not take the write (first at %04X: read %04X, wanted %04X); '
                                 'is the program memory write protected?'
                                 % (base, bad[0], back[bad[0] - base], row[bad[0] - base]))
            return old
        finally:
            self._flash_ops([('w', r, v) for r, v in zip((EEADRL, EEADRH, EEDATL, EEDATH), saved)]
                            + [('w', EECON1, saved[4] & 0xF4)])

    def set_soft_breakpoint(self, addr):
        """Stop before the instruction at addr executes, every time it is
        reached.  Rewrites one row of flash."""
        if self.gadget is None:
            raise DebugError('no software breakpoints: the target was not loaded by this tool, '
                             'or its image left no two words free at one offset of every page')
        if addr in self.breaks:
            return
        if not 0 <= addr < self.flash_words or addr % PAGE in (self.gadget, self.gadget + 1):
            raise DebugError('%04X is not an address a breakpoint can go' % addr)
        def check(word):
            if not emu16f1.can_emulate(word):
                raise DebugError('the instruction at %04X (%04X: RESET, SLEEP or CLRWDT) cannot take a software '
                                 'breakpoint; use the hardware breakpoint' % (addr, word))
        at_site = self._site() == addr      # stopped here by a breakpoint cleared earlier
        old = self._rewrite_row(addr, OP_CALL | self.gadget, check)
        self.breaks[addr] = old
        if at_site:
            self.ghost = None
        self._save_state()

    def clear_soft_breakpoint(self, addr):
        if addr not in self.breaks:
            raise DebugError('no software breakpoint at %04X' % addr)
        if self._site() == addr:
            self.ghost = (addr, self.breaks[addr])      # its instruction is still owed
        self._rewrite_row(addr, self.breaks[addr])
        del self.breaks[addr]
        self._save_state()

    # -- registers ---------------------------------------------------------

    @property
    def pc(self):
        """Address of the next instruction the program will execute.  At a
        software breakpoint that is the breakpoint's address."""
        pc = self._real_pc()
        site = self._site(pc)
        return pc if site is None else site

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
        pc = v[0] | ((v[1] & 0x7F) << 8)
        site = self._site(pc)
        if site is not None:            # hide the gadget: its CALL has not happened yet
            pc = site
            v = v[:10] + bytes([(v[10] - 1) & 0x1F]) + v[11:]
        return {
            'PC': pc,
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
