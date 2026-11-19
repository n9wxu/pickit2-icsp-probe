#!/usr/bin/env python3
"""Debug a PIC16(L)F193x target through the PICkit 2 probe.

    pk2debug.py load FILE.hex        program for debugging; stops at the reset vector
    pk2debug.py regs                 core registers
    pk2debug.py step [N]             execute N instructions (default 1)
    pk2debug.py cont [ADDR]          run; with ADDR, until that instruction has executed
    pk2debug.py halt                 stop a running target
    pk2debug.py reset                reset and stop at the reset vector
    pk2debug.py read ADDR [N]        data memory (register file address, or 0x2000+ linear)
    pk2debug.py write ADDR BYTE...
    pk2debug.py unload               erase the target and the debug executive, power off

The probe keeps the target powered between commands, so each command simply
continues the session.  Addresses and values are hexadecimal.

A breakpoint stops the target after the instruction at ADDR has executed, and
there is one hardware breakpoint.  The program counter cannot be changed.
"""
import argparse
import sys

from pk2probe import Probe, ProbeError, load_hex
from icd16f1 import Debugger, DebugError


def show_regs(d):
    r = d.registers()
    s = r['STATUS']
    flags = ''.join(n if s & (1 << b) else '-' for n, b in (('Z', 2), ('D', 1), ('C', 0)))
    print('PC=%04X  W=%02X  STATUS=%02X [%s]  BSR=%02X  PCLATH=%02X  FSR0=%04X  FSR1=%04X  STKPTR=%02X  INTCON=%02X'
          % (r['PC'], r['W'], s, flags, r['BSR'], r['PCLATH'], r['FSR0'], r['FSR1'], r['STKPTR'], r['INTCON']))


def need_halted(d):
    if not d.halted():
        raise DebugError('the target is running; use "halt" first')


def main():
    hexint = lambda s: int(s, 16)
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--vdd', type=int, default=3000, metavar='MV', help='target VDD in mV (default 3000)')
    ap.add_argument('--no-power', action='store_true', help='target has its own supply')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('load'); s.add_argument('file')
    sub.add_parser('regs')
    s = sub.add_parser('step'); s.add_argument('count', nargs='?', type=int, default=1)
    s = sub.add_parser('cont'); s.add_argument('addr', nargs='?', type=hexint)
    s.add_argument('--wait', type=float, default=0, metavar='S', help='wait up to S seconds for the target to stop')
    sub.add_parser('halt')
    sub.add_parser('reset')
    s = sub.add_parser('read'); s.add_argument('addr', type=hexint); s.add_argument('count', nargs='?', type=int, default=1)
    s = sub.add_parser('write'); s.add_argument('addr', type=hexint); s.add_argument('values', nargs='+', type=hexint)
    sub.add_parser('unload')
    args = ap.parse_args()

    try:
        p = Probe()
    except ProbeError as e:
        sys.exit(f'error: {e}')
    d = Debugger(p, vdd_mv=args.vdd, power=not args.no_power)
    try:
        if args.cmd == 'load':
            d.load(load_hex(args.file))
            print('%s programmed for debugging' % d.device.name)
            show_regs(d)
        elif args.cmd == 'regs':
            need_halted(d)
            show_regs(d)
        elif args.cmd == 'step':
            need_halted(d)
            for _ in range(args.count):
                d.step()
            show_regs(d)
        elif args.cmd == 'cont':
            need_halted(d)
            d.resume(breakpoint=args.addr)
            if args.wait and d.wait(args.wait):
                show_regs(d)
            else:
                print('running')
        elif args.cmd == 'halt':
            d.halt()
            show_regs(d)
        elif args.cmd == 'reset':
            d.reset()
            show_regs(d)
        elif args.cmd == 'read':
            need_halted(d)
            data = [d.read_data(args.addr + i) for i in range(args.count)]
            for i in range(0, len(data), 16):
                print('%04X: %s' % (args.addr + i, ' '.join('%02X' % b for b in data[i:i + 16])))
        elif args.cmd == 'write':
            need_halted(d)
            for i, v in enumerate(args.values):
                d.write_data(args.addr + i, v)
        elif args.cmd == 'unload':
            d.unload()
            print('target erased and powered off')
    except (ProbeError, DebugError) as e:
        sys.exit(f'error: {e}')
    finally:
        p.close()


if __name__ == '__main__':
    main()
