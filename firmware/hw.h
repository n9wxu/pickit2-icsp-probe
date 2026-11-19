/*
 * PICkit 2 board definitions (PIC18F2550, 20 MHz crystal, 48 MHz CPU clock).
 *
 * Pin assignments follow the PICkit 2 schematic (DS51553E, appendix B).
 */
#ifndef HW_H
#define HW_H

#include <xc.h>
#include <stdint.h>

#define _XTAL_FREQ 48000000UL

/* ---- Port A: target interface ------------------------------------- */
/* RA0/AN0  VPP feedback   (13.7 V full scale)                          */
/* RA1/AN1  target VDD feedback (5.0 V full scale)                      */
#define ICSPDAT_TRIS   TRISAbits.TRISA2
#define ICSPDAT_IN     PORTAbits.RA2
#define ICSPDAT_OUT    LATAbits.LATA2
#define ICSPCLK_TRIS   TRISAbits.TRISA3
#define ICSPCLK_IN     PORTAbits.RA3
#define ICSPCLK_OUT    LATAbits.LATA3
#define AUX_TRIS       TRISAbits.TRISA4
#define MCLR_GND       LATAbits.LATA5   /* 1 = pull target MCLR to ground */

/* ---- Port B --------------------------------------------------------- */
#define VPP_SWITCH     LATBbits.LATB2   /* 1 = connect VPP rail to MCLR   */
#define VDD_GND        LATBbits.LATB3   /* 1 = pull target VDD to ground  */
#define VDD_OFF_N      LATBbits.LATB4   /* 0 = target VDD switch on       */
#define BUTTON_IN      PORTBbits.RB5    /* 0 = pressed                    */

/* ---- Port C --------------------------------------------------------- */
#define LED            LATCbits.LATC0
/* RC1/CCP2 boost converter switch, RC2/CCP1 VDD reference PWM          */
#define EEPROM_WP      LATCbits.LATC6

/* Voltage limits enforced by the firmware, in millivolts. */
#define VDD_MIN_MV     1800u
#define VDD_MAX_MV     5000u
#define VPP_MIN_MV     5000u     /* below this the boost stage only passes USB 5 V */
#define VPP_MAX_MV     13000u

/* Status flags (power.c) */
#define ST_VDD_ON      0x01
#define ST_VDD_GND     0x02
#define ST_VPP_PUMP    0x04
#define ST_VPP_SWITCH  0x08
#define ST_MCLR_GND    0x10
#define ST_VDD_FAULT   0x20
#define ST_VPP_FAULT   0x40
#define ST_BUTTON      0x80

void    hw_init(void);
void    delay_us(uint16_t us);
void    delay_ms(uint16_t ms);

uint8_t ee_read(uint8_t addr);
void    ee_write(uint8_t addr, uint8_t value);

void    power_init(void);
void    power_load_cal(void);
void    power_isr(void);
uint8_t power_set_vdd(uint16_t mv);       /* 0 = ok */
void    power_vdd_mode(uint8_t mode);     /* 0 off, 1 on, 2 off + discharge */
uint8_t power_set_vpp(uint16_t mv);       /* 0 = pump off */
void    power_mclr(uint8_t mode);         /* 0 release, 1 ground, 2 VPP */
uint8_t power_status(void);
void    power_clear_faults(void);
uint16_t power_read_vdd_mv(void);
uint16_t power_read_vpp_mv(void);
void    power_read_raw(uint16_t *vdd, uint16_t *vpp);
void    power_pump_pause(void);           /* force the pump off, regulator held */
void    power_pump_resume(void);

extern volatile uint16_t uptime_ms;

void    enter_bootloader(void);

#endif
