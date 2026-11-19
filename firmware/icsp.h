#ifndef ICSP_H
#define ICSP_H

#include <stdint.h>

#define ICSP_PIN_DAT     0x01
#define ICSP_PIN_DAT_IN  0x02
#define ICSP_PIN_CLK     0x04
#define ICSP_PIN_CLK_IN  0x08

void    icsp_set_speed(uint8_t n);
void    icsp_pins(uint8_t v);
uint8_t icsp_pin_state(void);

void    icsp_out_lsb(uint8_t v, uint8_t n);
void    icsp_out_msb(uint8_t v, uint8_t n);
uint8_t icsp_in_lsb(uint8_t n);
uint8_t icsp_in_msb(uint8_t n);

void     g6_cmd(uint8_t c);
void     g6_load(uint8_t c, uint16_t w);
uint16_t g6_read(uint8_t c);

void    g8_cmd(uint8_t c);
void    g8_write(uint8_t c, uint8_t b2, uint8_t b1, uint8_t b0);
void    g8_read(uint8_t c, uint8_t *p);

uint8_t icd_ready(void);
uint8_t icd_tx(uint8_t b, uint8_t t10ms);       /* 0 = ok, 1 = timeout */
uint8_t icd_rx(uint8_t *b, uint8_t t10ms);

#endif
