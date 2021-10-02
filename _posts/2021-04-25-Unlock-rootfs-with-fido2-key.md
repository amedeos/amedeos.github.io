---
layout: post
title:  "Configure Gentoo to unlock LUKS root file system with FIDO2 key"
date:   2021-04-25 09:00:00 +0100
toc: true
categories: [gentoo]
tags: [gentoo,luks,systemd]
---
## Introduction
In this post I'll describe how to unlock your **LUKS** device, which contains the root file system, using a **FIDO2** hardware key.

## Requirements
In order to unlock your LUKS device at boot using your FIDO2 hardware key your Gentoo box need to meet these conditions:

+ only **LUKS2** device is supported, if your device is LUKS1 you can't unlock it with FIDO2 key; to check if your device is LUKS2 you can simply run a cryptsetup status command:
```bash
# cryptsetup status <YOUR LUKS DEVICE> | grep type
  type: LUKS2
```
+ systemd version **248** or higher;
```bash
# qlist -Idv | grep sys-apps/systemd
sys-apps/systemd-248
```
+ FIDO2 hardware key; for this I bought the [Solokeys Solo USB-A](https://solokeys.com/collections/all/products/solo-usb-a) but I hope you can use any FIDO2 available in the market;
+ **sys-kernel/dracut** will be used for building the initial ram file system.

## Software installation
### sys-apps/systemd
Recently, Gentoo systemd mantainer has added fido2 support, just add fido2 USE flag:

```bash
# mkdir -p /etc/portage/package.use
# echo "sys-apps/systemd fido2" >> /etc/portage/package.use/systemd
```

after enabling fido2 USE flag re-emerge systemd:

```bash
# time emerge --ask --verbose --update --deep --with-bdeps=y --newuse  --keep-going --autounmask-write=y --backtrack=30  @world
```

check if your systemd has FIDO2 capability:
```bash
# systemctl --version | grep FIDO | sed -E 's/.+([+-]FIDO2).+/\1/'
+FIDO2
```
reboot the system in order to use your new systemd:
```bash
# reboot
```
### sys-kernel/dracut
Install dracut if you haven't done before:
```bash
# emerge --ask sys-kernel/dracut
```
## Enroll your FIDO2 key in your LUKS device
Now you can plug your FIDO2 hardware token and enroll a FIDO2 key on your LUKS device, in my case the device is /dev/nvme0n1p3, but change accordingly to your environment (for example /dev/sda3):
```bash
# systemd-cryptenroll --fido2-device=auto /dev/nvme0n1p3 
🔐 Please enter current passphrase for disk /dev/nvme0n1p3: (no echo)               
Initializing FIDO2 credential on security token.
👆 (Hint: This might require verification of user presence on security token.)
Generating secret key on FIDO2 security token.
New FIDO2 token enrolled as key slot 1.
```
when requested type your current passphrase for your LUKS device, and then, in case you're using Solokeys, press the button on the token when the led becomes red

If you want to check if your LUKS device now has the FIDO2 key you can run:
```bash
# cryptsetup luksDump /dev/nvme0n1p3
...
Tokens:
  0: systemd-fido2
        Keyslot:  1
...
```
## Configure /etc/crypttab
Configure your **/etc/crypttab** to point to your LUKS device, but giving a __human__ name like **rootvolume**, instead of classical UUID:
```bash
# cat /etc/crypttab 
rootvolume /dev/nvme0n1p3 - fido2-device=auto
```
## Configure dracut
Dracut, by default doesn't install libfido2 and crypttab file, for this you can create a new file **/etc/dracut.conf.d/fido2.conf** with the following contents:
```bash
# cat /etc/dracut.conf.d/fido2.conf 
install_items+=" /etc/crypttab /usr/bin/fido2-token "
```

now you can rebuild your initial ram file system for your current kernel:
```bash
# dracut --force --kver $(uname -r)
```
instead, if you want to rebuild it for a specific kernel, for example **5.11.16-gentoo-amedeo05**, run this command:

```bash
# dracut --force --kver 5.11.16-gentoo-amedeo05
```
## Configure grub
Edit your grub **GRUB_CMDLINE_LINUX** parameter removing all luks options which refer to your LUKS UUID, you should do this in order to make easier the boot procedure without the FIDO2 key; your GRUB_CMDLINE_LINUX should be something like this:

```ini
GRUB_CMDLINE_LINUX="init=/usr/lib/systemd/systemd rd.luks.allow-discards root=UUID=a000eea9-d97c-4107-ae39-602049a6acaa rootflags=subvol=@"
```

**Note:** the above root=UUID refers to my btrfs UUID and not to the LUKS UUID

now you can run the **grub-mkconfig**:
```bash
# grub-mkconfig -o /boot/grub/grub.cfg
```
## Reboot
Plug your FIDO2 key and reboot, and check if your newly initial ram file system can unlock your root file system:
```bash
# reboot
```
## (Bonus) Unlock your root file system using the passphrase
If you lose, or forget your FIDO2 key you can boot your system using a LiveCD, or using the following trick.

When grub starts, press ___e___ to edit the boot parameter, then go to the **linux** entry and after all your boot parameters (in my case init=/usr/lib/systemd/systemd rd.luks.allow-discards root=UUID=a000eea9-d97c-4107-ae39-602049a6acaa rootflags=subvol=@) add the following:
```bash
rd.break=initqueue
```
Press **Ctrl+x** or **F10** and wait for the following messages:
```bash
Press Enter for maintenance
(or press Control-D to continue):
```
now press **Enter** and at prompt first mask your systemd service systemd-cryptsetup@rootvolume.service:
```bash
# systemctl mask systemd-cryptsetup@rootvolume.service
```
mount your rootvolume by typing your passphrase:
```bash
# /lib/systemd/systemd-cryptsetup attach rootvolume /dev/nvme0n1p3
```
now you can press **Control-D** to tell systemd to continue the boot process.
