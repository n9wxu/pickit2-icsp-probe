#!/usr/bin/env python3
"""Generate src/target/pic16f1_exec.h for OpenOCD from host/icd16f1.py.

The debug executive is machine code produced by build_executive() in
host/icd16f1.py (assembled with host/asm14.py).  This script only turns that
dictionary {word address: 14 bit word} into a C table, so the OpenOCD tree
never has to contain an assembler.

Usage:
    python3 openocd/gen_pic16f1_exec.py > openocd/openocd-src/src/target/pic16f1_exec.h
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'host'))

try:
    from icd16f1 import (build_executive, DEBUG_VECTOR, EXEC_START, EXEC_END,
                         SAVE_W, SAVE_STATUS, SAVE_FSR0L, SAVE_FSR1H)
except ImportError as e:      # pyusb missing is the usual reason (pk2probe imports usb)
    sys.exit('cannot import host/icd16f1.py: %s' % e)


def main():
    words = build_executive()
    out = []
    w = out.append
    w('/* SPDX-License-Identifier: GPL-2.0-or-later */')
    w('')
    w('/*')
    w(' * Debug executive for PIC16(L)F193x on-chip debugging.')
    w(' *')
    w(' * GENERATED FILE, do not edit.  It is the output of build_executive() in')
    w(' * host/icd16f1.py (assembler: host/asm14.py) of the PICkit 2 probe project.')
    w(' * Regenerate with:')
    w(' *     python3 openocd/gen_pic16f1_exec.py > src/target/pic16f1_exec.h')
    w(' * (run from the project root; the interpreter needs pyusb because')
    w(' * host/icd16f1.py imports host/pk2probe.py).')
    w(' *')
    w(' * %d words, addresses are in the 0x8000 debug/configuration space.' % len(words))
    w(' */')
    w('')
    w('#ifndef OPENOCD_TARGET_PIC16F1_EXEC_H')
    w('#define OPENOCD_TARGET_PIC16F1_EXEC_H')
    w('')
    w('#include <stdint.h>')
    w('')
    w('#define PIC16F1_DEBUG_VECTOR   0x%04X' % DEBUG_VECTOR)
    w('#define PIC16F1_EXEC_START     0x%04X' % EXEC_START)
    w('#define PIC16F1_EXEC_END       0x%04X  /* first address past the writable area */' % EXEC_END)
    w('#define PIC16F1_SAVE_W         0x%03X' % SAVE_W)
    w('#define PIC16F1_SAVE_STATUS    0x%03X  /* STATUS, nibbles swapped */' % SAVE_STATUS)
    w('#define PIC16F1_SAVE_FSR0L     0x%03X  /* FSR0L, FSR0H, FSR1L, FSR1H follow */' % SAVE_FSR0L)
    w('')
    w('struct pic16f1_exec_word {')
    w('\tuint16_t addr;')
    w('\tuint16_t word;')
    w('};')
    w('')
    w('static const struct pic16f1_exec_word pic16f1_exec[%d] = {' % len(words))
    items = sorted(words.items())
    for i in range(0, len(items), 4):
        w('\t' + ' '.join('{ 0x%04X, 0x%04X },' % (a, v) for a, v in items[i:i + 4]))
    w('};')
    w('')
    w('#define PIC16F1_EXEC_WORDS %d' % len(words))
    w('')
    w('#endif /* OPENOCD_TARGET_PIC16F1_EXEC_H */')
    sys.stdout.write('\n'.join(out) + '\n')


if __name__ == '__main__':
    main()
