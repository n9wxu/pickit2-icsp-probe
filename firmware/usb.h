/*
 * Minimal polled USB device stack for the PIC18F2550.
 * One vendor-specific interface with a bulk OUT and a bulk IN endpoint.
 */
#ifndef USB_H
#define USB_H

#include <stdint.h>

#define USB_VID          0x04D8
#define USB_PID          0x0033      /* same as the PICkit 2 bootloader */
#define USB_BCD_DEVICE   0x0300      /* stock firmware reports 0x0002 */

#define USB_PKT_SIZE     64

/* Vendor requests on the control endpoint.  They work even if the bulk
 * command path is broken, which keeps the bootloader reachable. */
#define USB_REQ_BOOTLOADER   0xB0    /* OUT, wValue = 0x4C42 */
#define USB_REQ_INFO         0xB1    /* IN, returns the INFO block */
#define USB_BOOT_MAGIC       0x4C42

void    usb_init(void);
void    usb_poll(void);
uint8_t usb_configured(void);

/* Bulk OUT: a received packet stays in usb_rx_buf until released. */
extern volatile uint8_t usb_rx_buf[USB_PKT_SIZE];
uint8_t usb_rx_len(void);            /* 0xFF = nothing waiting */
void    usb_rx_release(void);

/* Bulk IN: blocks until the previous packet has been collected. */
void    usb_tx(const uint8_t *data, uint8_t len);

extern volatile uint8_t usb_boot_request;

/* Provided by the application: fills buf with the INFO block, returns its length. */
uint8_t app_info(uint8_t *buf);

#endif
