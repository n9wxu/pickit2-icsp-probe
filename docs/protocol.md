# Probe USB protocol

The probe is a full-speed USB device, 04D8:0033, with one vendor-specific
interface (class 0xFF) and two bulk endpoints of 64 bytes: 0x01 OUT and
0x81 IN. The stock PICkit 2 firmware and its bootloader use the same
VID:PID but are HID devices, so the interface class tells them apart.

## Transfers

The host writes one packet of up to 64 bytes to the OUT endpoint. It holds
operations, executed in order. The probe answers each packet with exactly
one packet on the IN endpoint.

| Reply byte | Content |
|---|---|
| 0 | Status: 0 if every operation ran, otherwise an error code |
| 1 | Offset in the request of the operation that failed, otherwise 0 |
| 2… | Data returned by the operations, in order |

Operations after a failed one are not executed. Multi-byte values are little
endian. A reply holds at most 62 data bytes.

| Error | Meaning |
|---|---|
| 1 | Unknown operation |
| 2 | Operation runs past the end of the packet |
| 3 | Reply does not fit in one packet |
| 4 | Argument out of range |
| 5 | Debug executive did not respond in time |
| 6 | VDD or VPP fault. Target power has been switched off |

## Operations

`firmware/proto.h` is the authoritative list.

### General

| Code | Name | Arguments | Reply |
|---|---|---|---|
| 0x00 | END | None | None. Stops processing the packet |
| 0x01 | INFO | None | `'PK2P'`, version major, minor, protocol version, capabilities |
| 0x02 | STATUS | None | Power flags, pin state |
| 0x03 | READ_VOLT | None | VDD mV, VPP mV, raw VDD, raw VPP (four u16) |
| 0x04 | SET_VDD | mV (u16), 1800–5000 | None |
| 0x05 | VDD_MODE | 0 off, 1 on, 2 off and discharge | None |
| 0x06 | SET_VPP | mV (u16), 5000–13000, or 0 to stop the boost converter | None |
| 0x07 | MCLR | 0 release, 1 ground, 2 VPP | None |
| 0x08 | PINS | Pin byte | Pin state |
| 0x09 | DELAY_US | u16 | None |
| 0x0A | DELAY_MS | u8 | None |
| 0x0B | SPEED | Extra clock half-period, about 0.75 µs per count | None |
| 0x0C | LED | 0 or 1 | None |
| 0x0D | CLEAR_FAULTS | None | None |
| 0x0E | BOOTLOADER | `'B'`, `'L'` | None. The probe then returns to its bootloader |
| 0x0F | RESET | `'R'`, `'S'` | None. The probe then resets |
| 0x14 | EE_READ | Address, count | Bytes of the probe's EEPROM |
| 0x15 | EE_WRITE | Address, count, bytes | None. Reloads the calibration |

Power flags: bit 0 VDD on, 1 VDD grounded, 2 boost converter on, 3 VPP on
MCLR, 4 MCLR grounded, 5 VDD fault, 6 VPP fault, 7 button pressed.

Pin byte: bit 0 ICSPDAT level, 1 ICSPDAT is an input, 2 ICSPCLK level,
3 ICSPCLK is an input. In a reply the level bits are the pins as read.

The boost converter is fed from the VDD regulator, so with it stopped the
"VPP" level on MCLR is the VDD setpoint.

### Bit transfers

The probe drives the clock. Data changes on the rising edge and is latched on
the falling edge. The clock is high for 1.0 µs with a period of 2.75 µs.

| Code | Name | Arguments | Reply |
|---|---|---|---|
| 0x10 | WRITE_BITS | Bit count 1–32, flags, data bytes | None |
| 0x11 | READ_BITS | Bit count 1–32, flags | Data bytes |
| 0x12 | KEY | Flags, four bytes, extra clocks 0–8 | None |

Flag bit 0 selects MSB first; the default is LSB first. Bytes go out in the
order given.

### 6-bit commands (PIC16F1xxx)

A command is 6 bits, LSB first. A data frame is 16 clocks: start bit, 14
data bits LSB first, stop bit.

| Code | Name | Arguments | Reply |
|---|---|---|---|
| 0x20 | G6_CMD | Command | None |
| 0x21 | G6_LOAD | Command, word (u16) | None |
| 0x22 | G6_READ | Command | Word (u16) |
| 0x23 | G6_READN | Read command, increment command, count ≤ 31 | Words |
| 0x24 | G6_LOADN | Load command, increment command, count ≤ 29, words | None. No increment after the last word |

### 8-bit commands (PIC16F1xxxx)

A command is 8 bits and a payload 24 bits, both MSB first. A data word
occupies payload bits 16–1.

| Code | Name | Arguments | Reply |
|---|---|---|---|
| 0x30 | G8_CMD | Command | None |
| 0x31 | G8_WRITE | Command, three payload bytes | None |
| 0x32 | G8_READ | Command | Three payload bytes |
| 0x33 | G8_READN | Command, count ≤ 31 | Words (u16) |
| 0x34 | G8_LOADN | Command, command for the last word, count ≤ 29, words | None |

### Debug link

Here the target's debug executive drives the clock and the probe follows.
For each byte the target raises ICSPCLK, the probe answers by pulling ICSPDAT
low for 800 µs and then high, the target lowers ICSPCLK, and eight clock
pulses follow, MSB first. The receiver samples after the falling edge.
Interrupts are masked in the probe during a byte, and the boost converter is
held off.

| Code | Name | Arguments | Reply |
|---|---|---|---|
| 0x40 | ICD_READY | None | 1 if ICSPCLK is an input and high: the executive is waiting |
| 0x41 | ICD_TX | Timeout in 10 ms units, count, bytes | None |
| 0x42 | ICD_RX | Timeout in 10 ms units, count | Bytes |

## Control requests

These work even if the bulk path does not.

| bmRequestType | bRequest | wValue | Effect |
|---|---|---|---|
| 0x40 | 0xB0 | 0x4C42 | Return to the bootloader |
| 0xC0 | 0xB1 | 0 | Returns the INFO block |

## Entering programming mode

The host builds entry sequences from the operations above;
`host/pk2probe.py` has the reference versions.

| Method | Sequence |
|---|---|
| Low voltage | VDD on, MCLR released then grounded, KEY, 2 ms |
| High voltage, probe powers the target | Boost converter up, VDD off and discharged, MCLR to VPP, 200 µs, VDD on, 10 ms |
| High voltage, target self-powered | Boost converter up, MCLR grounded, MCLR to VPP, 5 ms |

The key is `'MCHP'`. For 6-bit devices it is sent LSB first starting with
`'P'`, followed by one extra clock. For 8-bit devices it is sent MSB first
starting with `'M'`.
