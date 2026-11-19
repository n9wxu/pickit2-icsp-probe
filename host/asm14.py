"""A very small assembler for the PIC16F1 (enhanced mid-range) instruction set.

It exists so that the debug executive, which has to be placed at exact
addresses including the debug vector at 0x8004, can be built without an
external toolchain.  Instructions are methods; labels are strings resolved
when the image is finished.

    a = Asm()
    a.org(0x700)
    a.label('loop')
    a.incf(0x20, F)
    a.bra('loop')
    words = a.image()        # {address: 14 bit word}
"""

W, F = 0, 1

# Core registers, present in every bank
INDF0, INDF1, PCL, STATUS, FSR0L, FSR0H, FSR1L, FSR1H = range(8)
BSR, WREG, PCLATH, INTCON = 8, 9, 10, 11
C, DC, Z = 0, 1, 2


class AsmError(Exception):
    pass


class Asm:
    def __init__(self):
        self.mem = {}
        self.pc = 0
        self.labels = {}
        self.fixups = []            # (address, kind, label)

    # -- layout ------------------------------------------------------------

    def org(self, addr):
        self.pc = addr

    def label(self, name):
        if name in self.labels:
            raise AsmError(f'duplicate label {name}')
        self.labels[name] = self.pc

    def word(self, w):
        if self.pc in self.mem:
            raise AsmError(f'address {self.pc:#06x} assembled twice')
        self.mem[self.pc] = w & 0x3FFF
        self.pc += 1

    def _target(self, kind, base, target):
        if isinstance(target, str):
            self.fixups.append((self.pc, kind, target))
            self.word(base)
        else:
            self.word(base | self._encode(kind, self.pc, target))

    @staticmethod
    def _encode(kind, at, target):
        if kind == 'abs11':
            return target & 0x7FF
        off = target - (at + 1)
        if not -256 <= off <= 255:
            raise AsmError(f'BRA at {at:#06x} cannot reach {target:#06x}')
        return off & 0x1FF

    def image(self):
        for at, kind, name in self.fixups:
            if name not in self.labels:
                raise AsmError(f'undefined label {name}')
            self.mem[at] |= self._encode(kind, at, self.labels[name])
        self.fixups = []
        return dict(self.mem)

    # -- byte-oriented file register operations -----------------------------

    def _fd(self, op, f, d):
        self.word(op | ((d & 1) << 7) | (f & 0x7F))

    def addwf(self, f, d):   self._fd(0x0700, f, d)
    def addwfc(self, f, d):  self._fd(0x3D00, f, d)
    def andwf(self, f, d):   self._fd(0x0500, f, d)
    def comf(self, f, d):    self._fd(0x0900, f, d)
    def decf(self, f, d):    self._fd(0x0300, f, d)
    def decfsz(self, f, d):  self._fd(0x0B00, f, d)
    def incf(self, f, d):    self._fd(0x0A00, f, d)
    def incfsz(self, f, d):  self._fd(0x0F00, f, d)
    def iorwf(self, f, d):   self._fd(0x0400, f, d)
    def movf(self, f, d):    self._fd(0x0800, f, d)
    def rlf(self, f, d):     self._fd(0x0D00, f, d)
    def rrf(self, f, d):     self._fd(0x0C00, f, d)
    def subwf(self, f, d):   self._fd(0x0200, f, d)
    def swapf(self, f, d):   self._fd(0x0E00, f, d)
    def xorwf(self, f, d):   self._fd(0x0600, f, d)
    def clrf(self, f):       self.word(0x0180 | (f & 0x7F))
    def clrw(self):          self.word(0x0100)
    def movwf(self, f):      self.word(0x0080 | (f & 0x7F))

    # -- bit-oriented operations ------------------------------------------

    def _fb(self, op, f, b):
        self.word(op | ((b & 7) << 7) | (f & 0x7F))

    def bcf(self, f, b):     self._fb(0x1000, f, b)
    def bsf(self, f, b):     self._fb(0x1400, f, b)
    def btfsc(self, f, b):   self._fb(0x1800, f, b)
    def btfss(self, f, b):   self._fb(0x1C00, f, b)

    # -- literal operations -----------------------------------------------

    def addlw(self, k):      self.word(0x3E00 | (k & 0xFF))
    def andlw(self, k):      self.word(0x3900 | (k & 0xFF))
    def iorlw(self, k):      self.word(0x3800 | (k & 0xFF))
    def movlw(self, k):      self.word(0x3000 | (k & 0xFF))
    def sublw(self, k):      self.word(0x3C00 | (k & 0xFF))
    def xorlw(self, k):      self.word(0x3A00 | (k & 0xFF))
    def movlb(self, k):      self.word(0x0020 | (k & 0x1F))
    def movlp(self, k):      self.word(0x3180 | (k & 0x7F))
    def retlw(self, k):      self.word(0x3400 | (k & 0xFF))

    # -- control ------------------------------------------------------------

    def goto(self, target):  self._target('abs11', 0x2800, target)
    def call(self, target):  self._target('abs11', 0x2000, target)
    def bra(self, target):   self._target('rel9', 0x3200, target)
    def brw(self):           self.word(0x000B)
    def callw(self):         self.word(0x000A)
    def ret(self):           self.word(0x0008)
    def retfie(self):        self.word(0x0009)
    def nop(self):           self.word(0x0000)
    def clrwdt(self):        self.word(0x0064)
    def sleep(self):         self.word(0x0063)
    def reset(self):         self.word(0x0001)

    # -- indirect -----------------------------------------------------------

    def moviw_postinc(self, n):  self.word(0x0012 | (n << 2))     # MOVIW FSRn++
    def movwi_postinc(self, n):  self.word(0x001A | (n << 2))     # MOVWI FSRn++
