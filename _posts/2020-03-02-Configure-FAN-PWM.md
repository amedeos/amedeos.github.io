---
layout: post
title:  "Configure FAN PWM"
date:   2020-03-02 10:00:00 +0100
categories: [hardware,performance]
tags: [hardware,performance]
---
## Introduction
In February, I decided to learn a new, but old, programming language, and my choice falls to C++ and QT Framework, for this I started a little program [ControlFANs](https://github.com/amedeos/ControlFANs) in order to easily configure PWM of my FANs, using the kernel [hwmon](https://www.kernel.org/doc/html/latest/hwmon/index.html) and its superb auto point checkpoint.
## Build
To build ControlFANs you should have ___qmake___ and ___QT framework___ installed, but after that it's very easy:
```bash
$ git clone https://github.com/amedeos/ControlFANs
$ cd ControlFANs
$ qmake
$ make
```
## Usage
Once built it's very easy to use it, you could start it as normal user only to see your hwmon configurations, instead if you want to change your configurations you could start it with sudo:
```bash
$ sudo ./ControlFANs
```

select the desired hwmon:
![hwmon selection](/images/ControlFANs-howto-01.png)

once you select the hwmon device, ControlFANs will list, and enable all detected FANs, select one of them:
![fan selection](/images/ControlFANs-howto-02.png)

now you can see all FAN data like current RPM (Input) and most important the auto point configurations, if you click the ___Edit___ button you could edit the PWM auto point:
![fan data](/images/ControlFANs-howto-03.png)

remember that the PWM value could be in the range from 0 (fan off) to 255 (fan at the highest RPM), and the temperature could be in millidegree, after filling your desired values you could click the ___Save___ button in order to write your configurations to hwmon special files:
![save data](/images/ControlFANs-howto-04.png)
![successfully saved](/images/ControlFANs-howto-05.png)

if you want to make your configuration persistent across reboot, you could click the ___Create systemD___ button which creates a new systemd stanza with the name ___controlfan-hwmonX-fanY.service___ under the directory ___/etc/systemd/system___
![create systemD](/images/ControlFANs-howto-06.png)
![confirm systemD](/images/ControlFANs-howto-07.png)

after the creation you should simply enable the systemd stanza by running:
```bash
$ sudo systemctl enable controlfan-hwmon0-fan2.service
```
if you'll look inside the file /etc/systemd/system/controlfan-hwmon0-fan2.service it's very simple:
```bash
$ cat /etc/systemd/system/controlfan-hwmon0-fan2.service
[Unit]
Description=controlfan hwmon0 fan2
DefaultDependencies=no
After=sysinit.target local-fs.target suspend.target hibernate.target
Before=basic.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo 104 > /sys/class/hwmon/hwmon0/pwm2'
ExecStart=/bin/sh -c 'echo 51 > /sys/class/hwmon/hwmon0/pwm2_auto_point1_pwm'
ExecStart=/bin/sh -c 'echo 20000 > /sys/class/hwmon/hwmon0/pwm2_auto_point1_temp'
ExecStart=/bin/sh -c 'echo 80 > /sys/class/hwmon/hwmon0/pwm2_auto_point2_pwm'
ExecStart=/bin/sh -c 'echo 30000 > /sys/class/hwmon/hwmon0/pwm2_auto_point2_temp'
ExecStart=/bin/sh -c 'echo 140 > /sys/class/hwmon/hwmon0/pwm2_auto_point3_pwm'
ExecStart=/bin/sh -c 'echo 40000 > /sys/class/hwmon/hwmon0/pwm2_auto_point3_temp'
ExecStart=/bin/sh -c 'echo 200 > /sys/class/hwmon/hwmon0/pwm2_auto_point4_pwm'
ExecStart=/bin/sh -c 'echo 50000 > /sys/class/hwmon/hwmon0/pwm2_auto_point4_temp'
ExecStart=/bin/sh -c 'echo 255 > /sys/class/hwmon/hwmon0/pwm2_auto_point5_pwm'
ExecStart=/bin/sh -c 'echo 65000 > /sys/class/hwmon/hwmon0/pwm2_auto_point5_temp'

[Install]
WantedBy=basic.target suspend.target hibernate.target
```

Finally, if you want to delete the systemd stanza you could press the ___Delete systemD___ button:
![delete systemd](/images/ControlFANs-howto-08.png)

confirm the deletion:
![confirm delete](/images/ControlFANs-howto-09.png)
![Picture](/images/ControlFANs-howto-10.png)

