---
layout: post
title:  "Configure CPU FAN on ASRock DeskMini A300"
date:   2020-02-03 17:00:00 +0100
categories: [hardware,performance]
tags: [hardware,performance]
---
## Introduction
I finally decided to have a home server, where to put backups, virtual machines, and, as I'm a [Gentoo](https://gentoo.org/) user, build packages for my other hosts. My hardware decision for this, falls to [ASRock DeskMini A300](https://www.asrock.com/nettop/AMD/DeskMini%20A300%20Series/index.asp), but, as I decided to put this host in the middle of the living room, it must be quiet on idle use, and for this I bought also a FAN from noctua [NH-L9a-AM4](https://noctua.at/en/nh-l9a-am4) to have a low noise and low profile fan inside my A300.
## Using motherboard configurations
When I finished my build, I started Gentoo installation, but I soon noticed, that the firmware of the ASRock motherboard doesn't fit my needs for CPU FAN profile, because I tried ___Standard___ profile, and this was fine for cooling, but not when the host was idle, because on that situation the CPU temperature goes under 30 degree, but the FAN's RPM still goes at ~1400, witch is loudly in the silent living room; this is the configuration passed by the mobo firmware to Linux kernel hwmon module NCT6775 (I'll describe later any details, don't worry):

| Auto Point | PWM | Temp (millidegree) |
| :--------- | :---: | ----: |
| auto_point1 | 140 | 50000 |
| auto_point2 | 165 | 60000 |
| auto_point3 | 191 | 65000 |
| auto_point4 | 216 | 70000 |
| auto_point5 | 255 | 75000 |

you could see those values under the sysfs special files:
```
/sys/devices/platform/nct6775.656/hwmon/hwmon0/pwm2_auto_point1_pwm
/sys/devices/platform/nct6775.656/hwmon/hwmon0/pwm2_auto_point1_temp
/sys/devices/platform/nct6775.656/hwmon/hwmon0/pwm2_auto_point2_pwm
/sys/devices/platform/nct6775.656/hwmon/hwmon0/pwm2_auto_point2_temp
/sys/devices/platform/nct6775.656/hwmon/hwmon0/pwm2_auto_point3_pwm
/sys/devices/platform/nct6775.656/hwmon/hwmon0/pwm2_auto_point3_temp
/sys/devices/platform/nct6775.656/hwmon/hwmon0/pwm2_auto_point4_pwm
/sys/devices/platform/nct6775.656/hwmon/hwmon0/pwm2_auto_point4_temp
/sys/devices/platform/nct6775.656/hwmon/hwmon0/pwm2_auto_point5_pwm
/sys/devices/platform/nct6775.656/hwmon/hwmon0/pwm2_auto_point5_temp
```
instead, when I tried to use the motherboard ___Silent___ profile, I noticed that this was fine when the host is idle, but, for example when I started to compile some packages, the CPU raises warning temperatures close to 70 degrees, but the CPU FAN was still at ~1600-1800 RPM, because the firmware passed these values to NCT6775 hwmon module:

| Auto Point | PWM | Temp (millidegree) |
| :--------- | :---: | ----: |
| auto_point1 | 102 | 50000 |
| auto_point2 | 114 | 60000 |
| auto_point3 | 127 | 65000 |
| auto_point4 | 153 | 75000 |
| auto_point5 | 255 | 85000 |

### Small explanation of HWMON data
Fortunately, A300's mobo give me the opportunity to use the Smart Fan mode, using five slopes to control / calculate (in chip) the DC/PWM output for the CPU FAN, by simply write the desired PWM, from 0 (lowest speed) to 255 (full speed) to the corresponding slope millidegree, for example if you write 65 PWM in pwm2_auto_point1_pwm and 30000 millidegrees in pwm2_auto_point1_temp, then the module will set the pwm to 65 when the chip take the temperatures near to 30 degrees.

If you want additional information about hwmon and NCT6775 you can read:

[Linux Hardware Monitoring](https://www.kernel.org/doc/html/latest/hwmon/index.html)

[Kernel driver NCT6775](https://www.kernel.org/doc/html/latest/hwmon/nct6775.html)

## Setting custom values for CPU FAN
To resolve this problem, and meet all my requirements, the solution was very simple, I just write inside those sysfs special files these values:

| Auto Point | PWM | Temp (millidegree) |
| :--------- | :---: | ----: |
| auto_point1 | 65 | 30000 |
| auto_point2 | 110 | 40000 |
| auto_point3 | 150 | 50000 |
| auto_point4 | 210 | 60000 |
| auto_point5 | 255 | 64000 |

shifting down the ___auto___ temperatures, because lisensors tell me that CPU critical temperature is 70 degrees and I saw the CPU under pressure raises 65-70 degrees really fast.

But setting those values needs some configurations
### Optional - Build kernel with NCT6775 module
If you're building your custom kernel like me, you'll need to include the NCT6775 module

```kernel
Device Drivers --->
    {*} Hardware Monitoring support  --->
        <M>   Nuvoton NCT6775F and compatibles
```
then rebuild your kernel and reboot with it.
### Automatically load nct6775 module
Make sure to load nct6775 module at boot and for this you could simply create a file under systemd /etc/modules-load.d directory:
```bash
echo nct6775 >> /etc/modules-load.d/lm_sensors.conf
systemctl restart systemd-modules-load.service
```
### Check hwmon data
Make sure your hwmon nct6775 module create the special files, in my case this is hwmon0 device and the CPU fan is detected as FAN2 with [PWM2](https://en.wikipedia.org/wiki/Pulse-width_modulation)
```bash
cat /sys/class/hwmon/hwmon0/fan2_input
1421
ls /sys/class/hwmon/hwmon0/fan2*
/sys/class/hwmon/hwmon0/fan2_alarm  /sys/class/hwmon/hwmon0/fan2_min     /sys/class/hwmon/hwmon0/fan2_tolerance
/sys/class/hwmon/hwmon0/fan2_beep   /sys/class/hwmon/hwmon0/fan2_pulses
/sys/class/hwmon/hwmon0/fan2_input  /sys/class/hwmon/hwmon0/fan2_target

ls /sys/class/hwmon/hwmon0/pwm2*
/sys/class/hwmon/hwmon0/pwm2                      /sys/class/hwmon/hwmon0/pwm2_mode
/sys/class/hwmon/hwmon0/pwm2_auto_point1_pwm      /sys/class/hwmon/hwmon0/pwm2_start
/sys/class/hwmon/hwmon0/pwm2_auto_point1_temp     /sys/class/hwmon/hwmon0/pwm2_step_down_time
/sys/class/hwmon/hwmon0/pwm2_auto_point2_pwm      /sys/class/hwmon/hwmon0/pwm2_step_up_time
/sys/class/hwmon/hwmon0/pwm2_auto_point2_temp     /sys/class/hwmon/hwmon0/pwm2_stop_time
/sys/class/hwmon/hwmon0/pwm2_auto_point3_pwm      /sys/class/hwmon/hwmon0/pwm2_target_temp
/sys/class/hwmon/hwmon0/pwm2_auto_point3_temp     /sys/class/hwmon/hwmon0/pwm2_temp_sel
/sys/class/hwmon/hwmon0/pwm2_auto_point4_pwm      /sys/class/hwmon/hwmon0/pwm2_temp_tolerance
/sys/class/hwmon/hwmon0/pwm2_auto_point4_temp     /sys/class/hwmon/hwmon0/pwm2_weight_duty_base
/sys/class/hwmon/hwmon0/pwm2_auto_point5_pwm      /sys/class/hwmon/hwmon0/pwm2_weight_duty_step
/sys/class/hwmon/hwmon0/pwm2_auto_point5_temp     /sys/class/hwmon/hwmon0/pwm2_weight_temp_sel
/sys/class/hwmon/hwmon0/pwm2_crit_temp_tolerance  /sys/class/hwmon/hwmon0/pwm2_weight_temp_step
/sys/class/hwmon/hwmon0/pwm2_enable               /sys/class/hwmon/hwmon0/pwm2_weight_temp_step_base
/sys/class/hwmon/hwmon0/pwm2_floor                /sys/class/hwmon/hwmon0/pwm2_weight_temp_step_tol
```
## Write PWM special files at boot
To write the PWM auto point special files I use my python [changegovernor](https://github.com/amedeos/changegovernor/) program, who I use also to [automatically change CPU governor from powersave to performance](https://amedeos.github.io/cpu/governor/2020/01/06/change-cpu-governor-automatically.html), by simply adding those configurations in DEFAULTS stanza inside the changegovernor.json
```json
        {
            "name": "DEFAULTS",
            "state": "present",
            "extra_commands": [
                "echo 30000 > /sys/class/hwmon/hwmon0/pwm2_auto_point1_temp",
                "echo 65 > /sys/class/hwmon/hwmon0/pwm2_auto_point1_pwm",
                "echo 40000 > /sys/class/hwmon/hwmon0/pwm2_auto_point2_temp",
                "echo 110 > /sys/class/hwmon/hwmon0/pwm2_auto_point2_pwm",
                "echo 50000 > /sys/class/hwmon/hwmon0/pwm2_auto_point3_temp",
                "echo 150 > /sys/class/hwmon/hwmon0/pwm2_auto_point3_pwm",
                "echo 60000 > /sys/class/hwmon/hwmon0/pwm2_auto_point4_temp",
                "echo 210 > /sys/class/hwmon/hwmon0/pwm2_auto_point4_pwm",
                "echo 64000 > /sys/class/hwmon/hwmon0/pwm2_auto_point5_temp",
                "echo 255 > /sys/class/hwmon/hwmon0/pwm2_auto_point5_pwm"
            ]
        }
```
and here you can find the [changegovernor.json](https://raw.githubusercontent.com/amedeos/amedeos.github.io/master/files/a300/changegovernor.json) file for my DeskMini A300, but you could also simply write a bash script to write your values inside sysfs special files.
