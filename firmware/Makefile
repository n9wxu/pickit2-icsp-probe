# PICkit 2 ICSP probe firmware.
#
# Needs MPLAB XC8 and the PIC18Fxxxx device family pack.  Override the two
# paths below if yours are elsewhere.

XC8_HOME ?= /Applications/microchip/xc8/v4.00
XC8_DFP  ?= $(HOME)/tools/microchip-packs/PIC18Fxxxx_DFP/1.8.178

CC      = $(XC8_HOME)/bin/xc8-cc
BUILD   = build
SRCS    = main.c usb.c power.c icsp.c
HDRS    = hw.h usb.h icsp.h proto.h

# The bootloader owns 0x0000-0x1FFF.  The last 64 byte block holds the
# "application valid" key, written by the loader and erased to get back to
# the bootloader, so no code may be placed there.  0x400-0x5FF is USB RAM.
CFLAGS  = -mcpu=18F2550 -mdfp=$(XC8_DFP)/xc8 -std=c99 -O2 \
          -mcodeoffset=0x2000 -mrom=default,-7FC0-7FFF -mram=default,-400-5FF \
          -Wall $(DEFS)

all: $(BUILD)/pk2probe.hex

$(BUILD)/pk2probe.hex: $(SRCS) $(HDRS) Makefile
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -Wl,-Map=$(BUILD)/pk2probe.map -o $@ $(SRCS)
	@rm -f *.p1 *.d

clean:
	rm -rf $(BUILD) *.p1 *.d

.PHONY: all clean
