"""Carry out one PIC16F1 instruction on a halted target, by memory access.

A software breakpoint replaces an instruction in flash.  When the target
stops there, the instruction has not run and cannot be run from flash, so
the debugger does its work instead: execute() reads and writes the user's
registers and memory through the machine it is given and returns the
address of the next instruction.  The caller then makes the target
continue there.

The machine supplies

    read_data(addr)         the user's data memory: a register file address
    write_data(addr, v)     0x000-0xFFF with the core registers translated,
                            or an address as an FSR sees it (0x2000 linear,
                            0x8000 program memory)
    push(pc), pop()         the hardware return stack

Three instructions have effects that memory access cannot give (RESET,
SLEEP, CLRWDT); can_emulate() is false for them.
"""

PCL, STATUS, FSR0L, BSR, WREG, PCLATH, INTCON = 2, 3, 4, 8, 9, 10, 11
OPTION_REG, TRISA = 0x095, 0x08C
SHADOWS = ((0xFE4, STATUS), (0xFE5, WREG), (0xFE6, BSR), (0xFE7, PCLATH),
           (0xFE8, 4), (0xFE9, 5), (0xFEA, 6), (0xFEB, 7))
OP_RESET, OP_SLEEP, OP_CLRWDT = 0x0001, 0x0063, 0x0064


class Unsupported(Exception):
    pass


def can_emulate(word):
    return word not in (OP_RESET, OP_SLEEP, OP_CLRWDT)


def _signed(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def execute(m, word, addr):
    """Do the work of instruction `word`, located at `addr`.  Returns the
    address of the instruction that follows it in execution."""
    rd, wr = m.read_data, m.write_data
    state = {'next': (addr + 1) & 0x7FFF}

    def jump(v):
        state['next'] = v & 0x7FFF

    def flags(**kw):
        st = rd(STATUS)
        for name, bit in (('c', 0), ('dc', 1), ('z', 2)):
            if name in kw:
                st = st | (1 << bit) if kw[name] else st & ~(1 << bit)
        wr(STATUS, st)

    def carry():
        return rd(STATUS) & 1

    def pclath():
        return rd(PCLATH) & 0x7F

    def fsr(n):
        return rd(FSR0L + 2 * n) | rd(FSR0L + 2 * n + 1) << 8

    def set_fsr(n, v):
        wr(FSR0L + 2 * n, v & 0xFF)
        wr(FSR0L + 2 * n + 1, (v >> 8) & 0xFF)

    def get(a):
        """Read a data address (register file, or what an FSR holds)."""
        a &= 0xFFFF
        if a < 0x1000:
            core = a & 0x7F
            if core < 2:
                return 0                    # INDF read through INDF
            if core == PCL:
                return (addr + 1) & 0xFF
        return rd(a)

    def put(a, v):
        a &= 0xFFFF
        v &= 0xFF
        if a >= 0x8000:
            return                          # program memory is not written this way
        if a < 0x1000:
            core = a & 0x7F
            if core < 2:
                return
            if core == PCL:
                jump(pclath() << 8 | v)
                return
            if core == STATUS:
                v = (v & 0x07) | (rd(STATUS) & 0x18)    # TO and PD cannot be written
        wr(a, v)

    def ea(f):
        """Data address of a 7 bit file operand."""
        if f < 2:
            return fsr(f)
        if f < 0x0C:
            return f
        return (rd(BSR) & 0x1F) << 7 | f

    hi = word >> 8
    f = word & 0x7F
    to_f = bool(word & 0x80)
    k = word & 0xFF

    def is_status(a):
        return a < 0x1000 and a & 0x7F == STATUS

    def result(a, r, sets_flags):
        """Store a result.  When an instruction that sets a flag has STATUS
        as its destination, the part does not write C, DC and Z from the
        result; only the instruction's own flags change (D16)."""
        if not to_f:
            wr(WREG, r & 0xFF)
        elif not (sets_flags and is_status(a)):
            put(a, r)

    if word < 0x80:
        if word == 0x08:                                    # RETURN
            jump(m.pop())
        elif word == 0x09:                                  # RETFIE
            for shadow, reg in SHADOWS:
                put(reg, rd(shadow))
            jump(m.pop())
            wr(INTCON, rd(INTCON) | 0x80)
        elif word == 0x0A:                                  # CALLW
            m.push(state['next'])
            jump(pclath() << 8 | rd(WREG))
        elif word == 0x0B:                                  # BRW
            jump(state['next'] + rd(WREG))
        elif 0x10 <= word <= 0x1F:                          # MOVIW / MOVWI with ++ --
            n, mode = (word >> 2) & 1, word & 3
            a = fsr(n)
            if mode == 0:
                a = (a + 1) & 0xFFFF
            elif mode == 1:
                a = (a - 1) & 0xFFFF
            if word & 8:
                put(a, rd(WREG))
            else:
                v = get(a)
                wr(WREG, v)
                flags(z=v == 0)
            if mode == 2:
                a += 1
            elif mode == 3:
                a -= 1
            set_fsr(n, a & 0xFFFF)
        elif 0x20 <= word <= 0x3F:                          # MOVLB
            wr(BSR, word & 0x1F)
        elif word == 0x62:                                  # OPTION
            wr(OPTION_REG, rd(WREG))
        elif 0x65 <= word <= 0x67:                          # TRIS
            wr(TRISA + word - 0x65, rd(WREG))
        elif word in (OP_RESET, OP_SLEEP, OP_CLRWDT):
            raise Unsupported('instruction %04X cannot be carried out by the debugger' % word)
        # everything else here is a NOP
    elif hi == 0x00:                                        # MOVWF
        put(ea(f), rd(WREG))
    elif hi == 0x01:                                        # CLRF / CLRW
        result(ea(f) if to_f else None, 0, True)
        flags(z=True)
    elif hi <= 0x0F or hi in (0x35, 0x36, 0x37, 0x3B, 0x3D):
        a = ea(f)
        v = get(a)
        fl = {}
        skip = False
        if hi in (0x02, 0x3B):                              # SUBWF, SUBWFB
            w = ~rd(WREG) & 0xFF
            cin = 1 if hi == 0x02 else carry()
            r = v + w + cin
            fl = dict(c=r > 0xFF, dc=(v & 15) + (w & 15) + cin > 15, z=r & 0xFF == 0)
        elif hi in (0x07, 0x3D):                            # ADDWF, ADDWFC
            w = rd(WREG)
            cin = 0 if hi == 0x07 else carry()
            r = v + w + cin
            fl = dict(c=r > 0xFF, dc=(v & 15) + (w & 15) + cin > 15, z=r & 0xFF == 0)
        elif hi in (0x03, 0x0A):                            # DECF, INCF
            r = v + (1 if hi == 0x0A else -1)
            fl = dict(z=r & 0xFF == 0)
        elif hi in (0x04, 0x05, 0x06):                      # IORWF, ANDWF, XORWF
            w = rd(WREG)
            r = v | w if hi == 0x04 else v & w if hi == 0x05 else v ^ w
            fl = dict(z=r == 0)
        elif hi == 0x08:                                    # MOVF
            r = v
            fl = dict(z=r == 0)
        elif hi == 0x09:                                    # COMF
            r = ~v & 0xFF
            fl = dict(z=r == 0)
        elif hi in (0x0B, 0x0F):                            # DECFSZ, INCFSZ
            r = v + (1 if hi == 0x0F else -1)
            skip = r & 0xFF == 0
        elif hi == 0x0C:                                    # RRF
            r = v >> 1 | carry() << 7
            fl = dict(c=v & 1)
        elif hi == 0x0D:                                    # RLF
            r = v << 1 | carry()
            fl = dict(c=v & 0x80)
        elif hi == 0x0E:                                    # SWAPF
            r = v << 4 | v >> 4
        elif hi == 0x35:                                    # LSLF
            r = v << 1
            fl = dict(c=v & 0x80, z=r & 0xFF == 0)
        elif hi == 0x36:                                    # LSRF
            r = v >> 1
            fl = dict(c=v & 1, z=r == 0)
        else:                                               # ASRF
            r = v >> 1 | v & 0x80
            fl = dict(c=v & 1, z=r == 0)
        result(a, r, bool(fl))
        if fl:
            flags(**fl)
        if skip:
            jump(addr + 2)
    elif hi < 0x20:                                         # bit operations
        a = ea(f)
        bit = 1 << ((word >> 7) & 7)
        v = get(a)
        kind = hi >> 2
        if kind == 4:                                       # BCF
            put(a, v & ~bit)
        elif kind == 5:                                     # BSF
            put(a, v | bit)
        elif bool(v & bit) == (kind == 7):                  # BTFSC, BTFSS
            jump(addr + 2)
    elif hi < 0x28:                                         # CALL
        m.push(state['next'])
        jump((pclath() & 0x78) << 8 | (word & 0x7FF))
    elif hi < 0x30:                                         # GOTO
        jump((pclath() & 0x78) << 8 | (word & 0x7FF))
    elif hi == 0x30:                                        # MOVLW
        wr(WREG, k)
    elif hi == 0x31:
        if to_f:                                            # MOVLP
            wr(PCLATH, word & 0x7F)
        else:                                               # ADDFSR
            n = (word >> 6) & 1
            set_fsr(n, (fsr(n) + _signed(word & 0x3F, 6)) & 0xFFFF)
    elif hi in (0x32, 0x33):                                # BRA
        jump(state['next'] + _signed(word & 0x1FF, 9))
    elif hi == 0x34:                                        # RETLW
        wr(WREG, k)
        jump(m.pop())
    elif hi in (0x38, 0x39, 0x3A):                          # IORLW, ANDLW, XORLW
        w = rd(WREG)
        r = w | k if hi == 0x38 else w & k if hi == 0x39 else w ^ k
        wr(WREG, r)
        flags(z=r == 0)
    elif hi in (0x3C, 0x3E):                                # SUBLW, ADDLW
        w = rd(WREG)
        if hi == 0x3C:
            w = ~w & 0xFF
        cin = 1 if hi == 0x3C else 0
        r = k + w + cin
        wr(WREG, r & 0xFF)
        flags(c=r > 0xFF, dc=(k & 15) + (w & 15) + cin > 15, z=r & 0xFF == 0)
    else:                                                   # 0x3F: MOVIW / MOVWI k[FSRn]
        n = (word >> 6) & 1
        a = (fsr(n) + _signed(word & 0x3F, 6)) & 0xFFFF
        if to_f:
            put(a, rd(WREG))
        else:
            v = get(a)
            wr(WREG, v)
            flags(z=v == 0)
    return state['next']
