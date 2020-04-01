---
layout: post
title:  "Configure kernel 5.6+ SATA drive temperature for HWMON"
date:   2020-04-01 10:00:00 +0200
categories: [hardware,performance]
tags: [hardware,performance]
---
## Introduction
With the release of the latest stable kernel 5.6, finally, was merged the module [drivetemp](https://www.kernel.org/doc/html/latest/hwmon/drivetemp.html) who is able to monitor the HDD SATA temperatures using [hwmon](https://www.kernel.org/doc/html/latest/hwmon/index.html) and [libsensors](https://github.com/lm-sensors/lm-sensors), with the advantage to use them in user space without the need to use super user privilege like the command [hddtemp](https://savannah.nongnu.org/projects/hddtemp/).
## Compile as module
Before using the module drivetemp, we need to compile it as a module, for this you should set the kernel configuration parameter ___CONFIG_SENSORS_DRIVETEMP___ to "m":
```kernel
Device Drivers --->
    {*} Hardware Monitoring support  --->
        <M>   Hard disk drives with temperature sensors
```
curious note, if you're looking the help of that module will be called ___satatemp___, but this is wrong, because it will be called instead ___drivetemp___
```kernel
config SENSORS_DRIVETEMP
	tristate "Hard disk drives with temperature sensors"
	depends on SCSI && ATA
	help
	  If you say yes you get support for the temperature sensor on
	  hard disk drives.

	  This driver can also be built as a module. If so, the module
	  will be called satatemp.
```
then you can build and install your new 5.6 kernel.
## Automatically load kernel module drivetemp at boot
To automatically load the ___drivetemp___ module at boot, simply create a new file ___drivetemp.conf___ under the directory ___/etc/modules-load.d___ and write in it drivetemp:
```bash
$ cat /etc/modules-load.d/drivetemp.conf 
# add drivetemp module
drivetemp
```
## Reboot
Reboot your host with your new kernel 5.6
```bash
$ sudo reboot
```
## Verify HDD temperatures
Now, you could be able to verify your HDD temperatures reading them from ___sysfs___ file system or using ___libsensors___ and ___sensors___ command tool:
```bash
$ sensors
...
drivetemp-scsi-5-0
Adapter: SCSI adapter
temp1:        +31.0°C  (lowest = +31.0°C, highest = +31.0°C)

drivetemp-scsi-3-0
Adapter: SCSI adapter
temp1:        +30.0°C  (lowest = +31.0°C, highest = +30.0°C)

drivetemp-scsi-1-0
Adapter: SCSI adapter
temp1:        +29.0°C  (low  =  -5.0°C, high = +80.0°C)
                       (crit low = -10.0°C, crit = +85.0°C)
                       (lowest = +19.0°C, highest = +29.0°C)
...
```
## Simple python to read HDD temperatures
Below you can find an example using ___drivetemp___ data:
```python
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
```
and finally, if you execute it ([listDrivetemp.py](https://raw.githubusercontent.com/amedeos/amedeos.github.io/master/files/drivetemp/listDrivetemp.py))
```bash
$ python3 listDrivetemp.py
Current: 29.0, High: 80.0, Critical: 85.0
Current: 36.0
Current: 31.0
Current: 30.0
Current: 31.0
Current: 31.0, High: 55.0, Critical: 60.0
```
