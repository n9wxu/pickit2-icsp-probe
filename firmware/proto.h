/*
 * Probe command protocol.
 *
 * The host writes one packet of up to 64 bytes to the bulk OUT endpoint.  The
 * packet holds a sequence of operations, executed in order.  The probe
 * answers every packet with exactly one packet on the bulk IN endpoint:
 *
 *   byte 0   status: 0 = all operations ran, otherwise an ERR_ code
 *   byte 1   offset in the request of the operation that failed (0 if none)
 *   byte 2.. data returned by the operations, in order
 *
 * Operations whose results would not fit in the reply fail with
 * ERR_OVERFLOW.  Multi-byte values are little endian.
 *
 * docs/protocol.md describes every operation.
 */
#ifndef PROTO_H
#define PROTO_H

#define PROTO_VERSION     1
#define FW_VERSION_MAJOR  0
#define FW_VERSION_MINOR  1

/* General */
#define OP_END            0x00   /* stop processing this packet */
#define OP_INFO           0x01   /* -> 8 bytes, see app_info() */
#define OP_STATUS         0x02   /* -> flags, pin state */
#define OP_READ_VOLT      0x03   /* -> vdd mV u16, vpp mV u16, raw vdd u16, raw vpp u16 */
#define OP_SET_VDD        0x04   /* mV u16 */
#define OP_VDD_MODE       0x05   /* 0 off, 1 on, 2 off and discharge */
#define OP_SET_VPP        0x06   /* mV u16; 0 stops the boost converter */
#define OP_MCLR           0x07   /* 0 release, 1 ground, 2 VPP */
#define OP_PINS           0x08   /* pin byte -> pin state */
#define OP_DELAY_US       0x09   /* u16 */
#define OP_DELAY_MS       0x0A   /* u8 */
#define OP_SPEED          0x0B   /* extra half-period delay, about 0.75 us per count */
#define OP_LED            0x0C   /* 0 off, 1 on */
#define OP_CLEAR_FAULTS   0x0D
#define OP_BOOTLOADER     0x0E   /* 'B' 'L' : erase the application key and reset */
#define OP_RESET          0x0F   /* 'R' 'S' : reset the probe */

/* Raw bit transfers */
#define OP_WRITE_BITS     0x10   /* nbits (1..32), flags, ceil(nbits/8) bytes */
#define OP_READ_BITS      0x11   /* nbits (1..32), flags -> ceil(nbits/8) bytes */
#define OP_KEY            0x12   /* flags, 4 key bytes (first on the wire first), extra clocks */
#define BITS_MSB_FIRST    0x01

/* 6 bit command generation */
#define OP_G6_CMD         0x20   /* cmd */
#define OP_G6_LOAD        0x21   /* cmd, word u16 */
#define OP_G6_READ        0x22   /* cmd -> word u16 */
#define OP_G6_READN       0x23   /* read cmd, increment cmd, n -> n words */
#define OP_G6_LOADN       0x24   /* load cmd, increment cmd, n, n words; no increment after the last */

/* 8 bit command generation */
#define OP_G8_CMD         0x30   /* cmd */
#define OP_G8_WRITE       0x31   /* cmd, 3 payload bytes, first on the wire first */
#define OP_G8_READ        0x32   /* cmd -> 3 payload bytes */
#define OP_G8_READN       0x33   /* cmd, n -> n words u16: (payload >> 1) & 0xFFFF */
#define OP_G8_LOADN       0x34   /* cmd, last cmd, n, n words u16: payload = word << 1 */

/* Debug-executive link */
#define OP_ICD_READY      0x40   /* -> 1 if the executive is waiting for a byte */
#define OP_ICD_TX         0x41   /* timeout (10 ms units), n, n bytes */
#define OP_ICD_RX         0x42   /* timeout (10 ms units), n -> n bytes */

/* Status codes */
#define ERR_OK            0x00
#define ERR_UNKNOWN_OP    0x01
#define ERR_TRUNCATED     0x02   /* operation runs past the end of the packet */
#define ERR_OVERFLOW      0x03   /* reply does not fit in one packet */
#define ERR_RANGE         0x04   /* argument outside the allowed range */
#define ERR_TIMEOUT       0x05   /* debug executive did not respond */
#define ERR_POWER_FAULT   0x06   /* VDD or VPP short circuit detected */

/* Capability bits in the INFO block */
#define CAP_HVP           0x01
#define CAP_VDD_SOURCE    0x02
#define CAP_GEN6          0x04
#define CAP_GEN8          0x08
#define CAP_ICD           0x10

#endif
