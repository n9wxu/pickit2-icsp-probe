"""Minimal SCPI client for a Siglent SDS1000X-E oscilloscope (TCP port 5025)."""
import socket
import time


class Scope:
    def __init__(self, host, port=5025, timeout=3.0):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.s.settimeout(timeout)
        self.cmd('CHDR OFF')            # replies without the command header
        time.sleep(0.3)

    def close(self):
        self.s.close()

    def cmd(self, c):
        self.s.sendall(c.encode() + b'\n')
        time.sleep(0.05)

    def ask(self, c):
        # The scope occasionally drops a query while it is reconfiguring.
        for attempt in range(3):
            self.s.sendall(c.encode() + b'\n')
            buf = b''
            try:
                while not buf.endswith(b'\n'):
                    buf += self.s.recv(4096)
                return buf.decode(errors='replace').strip()
            except socket.timeout:
                if buf or attempt == 2:
                    raise
        return ''

    def num(self, c):
        """Query a value such as '2.00E+00V' and return it as a float."""
        r = self.ask(c)
        r = r.split(',')[-1] if ',' in r else r
        return float(''.join(ch for ch in r if ch in '0123456789.eE+-'))

    def setup_channel(self, ch, vdiv, offset=0.0, on=True):
        self.cmd(f'C{ch}:TRA {"ON" if on else "OFF"}')
        self.cmd(f'C{ch}:VDIV {vdiv}V')
        self.cmd(f'C{ch}:OFST {offset}V')

    def timebase(self, tdiv, delay=0.0):
        self.cmd(f'TDIV {tdiv}S')
        self.cmd(f'TRDL {delay}S')

    def trigger(self, ch, level, slope='POS', mode='SINGLE'):
        self.cmd(f'TRSE EDGE,SR,C{ch},HT,OFF')
        self.cmd(f'C{ch}:TRSL {slope}')
        # TRLV is taken at the scope input: divide by the probe attenuation.
        self.cmd(f'C{ch}:TRLV {level / self.num(f"C{ch}:ATTN?")}V')
        self.cmd(f'TRMD {mode}')

    def state(self):
        return self.ask('SAST?')

    def wait_stop(self, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            if self.state() == 'Stop':
                return True
            time.sleep(0.05)
        return False

    def waveform(self, ch, sparse=1):
        """Return (times, volts) for a channel of the stopped acquisition."""
        vdiv = self.num(f'C{ch}:VDIV?')
        ofst = self.num(f'C{ch}:OFST?')
        tdiv = self.num('TDIV?')
        sara = self.num('SARA?')
        delay = self.num('TRDL?')
        self.cmd(f'WFSU SP,{sparse},NP,0,FP,0')
        self.s.sendall(f'C{ch}:WF? DAT2\n'.encode())
        buf = b''
        while b'#9' not in buf:
            buf += self.s.recv(65536)
        i = buf.index(b'#9')
        n = int(buf[i + 2:i + 11])
        body = buf[i + 11:]
        while len(body) < n + 2:
            body += self.s.recv(1 << 20)
        raw = body[:n]
        volts = [((b - 256 if b > 127 else b) * vdiv / 25.0) - ofst for b in raw]
        dt = sparse / sara
        t0 = -tdiv * 14 / 2 - delay
        times = [t0 + k * dt for k in range(len(volts))]
        return times, volts

    def screenshot(self, path):
        self.s.sendall(b'SCDP\n')
        buf = b''
        self.s.settimeout(3.0)
        try:
            while True:
                d = self.s.recv(1 << 20)
                if not d:
                    break
                buf += d
                if len(buf) >= 54 and len(buf) >= int.from_bytes(buf[2:6], 'little'):
                    break
        except socket.timeout:
            pass
        with open(path, 'wb') as f:
            f.write(buf)
