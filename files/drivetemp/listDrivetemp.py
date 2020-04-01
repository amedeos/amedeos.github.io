#!/usr/bin/env python
#
import psutil

SDRIVE = 'drivetemp'

stemps = psutil.sensors_temperatures()

sdrives = stemps.get(SDRIVE)

for s in sdrives:
    tcurrent = s.current
    thigh = s.high
    tcritical = s.critical

    sMessage = "Current: " + str(tcurrent)
    if thigh:
        sMessage += ", High: " + str(thigh)
    if tcritical:
        sMessage += ", Critical: " + str(tcritical)

    print(sMessage)
