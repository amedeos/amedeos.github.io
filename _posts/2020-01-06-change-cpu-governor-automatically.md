---
layout: post
title:  "Change CPU governor automatically"
date:   2020-01-06 18:00:00 +0100
categories: [cpu,governor]
tags: [cpu,governor]
---
## Introduction
I started this new project [changegovernor](https://github.com/amedeos/changegovernor/) to auto-magically change the CPU governor, from powersave to performance and the other way around, based on the presence of "know" ___process name___, ___cpu threshold___ and hardware ___temperatures___ taken from libsensors.

I wrote it in python3 (mostly in python 3.7) and I kept it simple and stupid, like it's programming flow, who is looking for:
* reaching critical system hardware ___temperatures___;
* presence of user defined ___processes___;
* looking for ___cpu threshold___ in percentages.

If you're interested on more detailed programming flow, have a look at this [flow chart](https://github.com/amedeos/changegovernor/blob/master/changegovernor-operatingflow.png)
## Configure kernel (optional)
For those people, who like builds own kernel's, I whould suggest you to configure cpu frequency scaling as below:
```kernel
Power management and ACPI options --->
    CPU Frequency scaling --->
        -*- CPU Frequency scaling
        [*]   CPU frequency transition statistics
              Default CPUFreq governor (powersave)  --->
        <*>   'performance' governor
        -*-   'powersave' governor
        <*>   'userspace' governor for userspace frequency scaling
        <*>   'ondemand' cpufreq policy governor
        <*>   'conservative' cpufreq governor
        [*]   'schedutil' cpufreq policy governor
```
## Install
Simply clone the project [changegovernor](https://github.com/amedeos/changegovernor/) and move ___changegovernor.py___ and ___changegovernor.json___ to system directories:
```bash
$ git clone https://github.com/amedeos/changegovernor
$ cd changegovernor
$ sudo cp changegovernor.py /usr/sbin/
$ sudo cp changegovernor.json /etc/
```
## Configure
### Process configurations
If you want to switch your linux box to ___performance___ governor for a specific process name, simply edit the ___/etc/changegovernor.json___ json file with your desired process, for example:
```json
    "processes": [
        {
            "name": "vlc",
            "state": "present",
            "extra_commands": [],
            "governor": "performance"
        },
```
in the above example, the programm will search for a process name ___vlc___, and if in case it will find it, ___changegovernor.py___ will change the cpu governor to performance.
### Hardware Temperature configurations
Before configuring changegovernor for looking on critical hardware temperatures inside the system, you have to configure ___libsensors___ to read from the kernel those data / temperatures; on most linux distrubutions this is just done, but if you can't get any data from ___sensors___ command, let's try to execute ___sensors-detect___ command and follow it's suggestions.

Once you have a working libsensors configuration, and suppose you have an AMD cpu (like me) the sensors output will like this:
```bash
$ sensors
...
k10temp-pci-00c3
Adapter: PCI adapter
Tdie:         +30.5°C  (high = +70.0°C)
Tctl:         +30.5°C
```
from the above output we can see that our sensor name is ___k10temp___ and it's principal label is ___Tdie___ (have a look at the high / critical value of 70°C); if you want to force powersave cpu governornor if you reach the 95% (in this example 66.5°C) of the critical temperatures (70.0°C) let's edit the ___/etc/changegovernor.json___ with this values:
```json
    "sensors": [
        {
            "name": "k10temp",
            "state": "present",
            "label": "Tdie",
            "percent_from_critical": "5.0",
            "extra_commands": [],
            "governor": "powersave"
        },
```
### Cpu threshold configurations
Finally, if you want to raise the cpu governor to ___performance___ if your system load reach for example a value upper than 70%, simply edit ___/etc/changegovernor.json___ with:
```json
    "percentages": [
        {
            "name": "highload",
            "min": "70.0",
            "max": "100.0",
            "state": "present",
            "extra_commands": [],
            "governor": "performance"
        },
```
## systemd unit file (optional)
If you want to automatic start ___changegovernor.py___ at boot, and you are using systemd simply copy the unit file and enable it:
```bash
$ sudo cp changegovernor.service /etc/systemd/system/
$ sudo systemctl daemon-reload
$ sudo systemctl enable changegovernor.service
```
## Gentoo installation
If you're running gentoo you could add my [amedeos-overlay](https://github.com/amedeos/amedeos-overlay/) and then install with emerge the sys-power/changegovernor ebuild:
```bash
$ sudo -i
# EPYTHON=python3.6 layman -o https://raw.githubusercontent.com/amedeos/amedeos-overlay/master/overlay.xml -f -a amedeos
# emerge sys-power/changegovernor
# systemctl enable changegovernor.service --now
```
