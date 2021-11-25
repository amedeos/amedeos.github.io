---
layout: post
title:  "Configure Gentoo to use Nitrokey Pro to unlock LUKS root partition, using genkernel"
date:   2020-07-26 16:00:00 +0200
categories: [gentoo,nitrokey]
tags: [gentoo,luks,nitrokey]
---
## Introduction
In this guide I'll show you how to unlock in initramfs, build with new **genkernel**, your LUKS partition (with root partition / file system) using the [Nitrokey Pro 2](https://www.nitrokey.com/) Password Safe.

I've just written an [older guide](https://amedeos.github.io/gentoo/nitrokey/2019/01/21/gentoo-nitrokey-luks.html) about this, but that guide was based on the **genkernel-next**, which is recently masked in the portage, so this one will be based on **~amd64 genkernel**.
## Warning
This guide is only tested on my Gentoo box, __SO BE CAREFUL, YOU CAN MAKE YOUR GENTOO UNBOOTABLE.__



__Update 25/11/2021:__ The latest version of sys-kernel/genkernel (into ~amd64 => sys-kernel/genkernel-4.2.6-r1)removed the shared libraries, if you update the genkernel update also the script __20-nitrokey.sh__ (below you can find the updated version)
## Install nitrokey application
First install nitrokey-app
```bash
# emerge --ask app-crypt/nitrokey-app
```
now, configure the Nitrokey Pro 2 following the [official documentation](https://www.nitrokey.com/start), changing the pin and the admin pin, and creating, under the Password Safe tab a new entry with __LUKS__ Slot name
![Nitrokey app](/images/nitrokeyapp-luks-slot.png)
Copy the password, because we need to add it to LUKS
## Add new passphrase to LUKS
Just add the new passphrase to LUKS (copied from Nitrokey App), for me the LUKS partition is /dev/sda2, but verify on your system
```bash
# cryptsetup luksAddKey /dev/sdaX
Enter any existing passphrase:     <-- insert the current passphrase
Enter new passphrase for key slot: <-- insert the new generated passphrase
Verify passphrase:                 <-- insert the new generated passphrase
```
now you can see two key slot for your device
```bash
# cryptsetup luksDump /dev/sda2 
LUKS header information for /dev/sda2

Version:        1
Cipher name:    aes
Cipher mode:    xts-plain64:sha512
Hash spec:      sha256
Payload offset: 4096
MK bits:        512
MK digest:      5a 08 78 7b 00 fb 82 0a e1 4e 73 e8 fc 12 6e ed d5 a3 82 ab 
MK salt:        21 8b 08 02 8f 8a 17 42 7a 85 bc 6c af cd 6c fb 
                82 27 0e 1e 24 27 1c 5f 7f 47 33 d7 03 e9 c3 a8 
MK iterations:  164000
UUID:           85558b31-7351-4c5f-b283-2a58d4cd7b71

Key Slot 0: ENABLED
        Iterations:             1311138
        Salt:                   fa 5d 2b f5 1b 46 34 d0 61 dd 18 35 c3 00 5f fa 
                                1c 23 5b 41 d1 6a 6e df e1 43 b4 8f e6 e2 a7 ad 
        Key material offset:    8
        AF stripes:             4000
Key Slot 1: ENABLED
        Iterations:             1344328
        Salt:                   10 cb 0a 59 60 15 85 cf 3c 00 d5 92 41 75 36 ba 
                                62 aa b0 0f a3 00 d2 a1 7b aa 98 91 d5 73 57 ca 
        Key material offset:    512
        AF stripes:             4000
Key Slot 2: DISABLED
Key Slot 3: DISABLED
Key Slot 4: DISABLED
Key Slot 5: DISABLED
Key Slot 6: DISABLED
Key Slot 7: DISABLED
```
## Install genkernel
If you haven't installed genkernel yet, this is the time (remember that I'm using genkernel in the ~amd64 flavor)

```bash
# emerge --ask sys-kernel/genkernel
```
## Configure initramfs to use nitroluks
We'll use the C++ source code kept from [Nitroluks](https://github.com/artosan/nitroluks), who is a simple iterator from Nitrokey Pro 2 Password Safe slots, simple but very useful.
### Configure genkernel to inject an overlay
Edit /etc/genkernel.conf with the following parameter
```ini
INITRAMFS_OVERLAY="/etc/kernels/nitro"
```
### Create the initramfs overlay
Create the postbuild.d directory
```bash
# mkdir -p /etc/kernels/postbuild.d
```
Create a new script __20-nitrokey.sh__ inside the postbuild.d directory
```bash
# touch /etc/kernels/postbuild.d/20-nitrokey.sh
# chmod 0754 /etc/kernels/postbuild.d/20-nitrokey.sh
```
Put this content inside the 20-nitrokey.sh script file or [download from here](https://raw.githubusercontent.com/amedeos/amedeos.github.io/master/scripts/genkernel/20-nitrokey.sh)
```bash
#!/usr/bin/env bash
#
source /etc/genkernel.conf
rm -rf ${INITRAMFS_OVERLAY}
mkdir -p ${INITRAMFS_OVERLAY}/{usr/lib64,usr/bin,lib64,bin,etc}
NITROLUKS="https://github.com/artosan/nitroluks"
INITRD_PATCH="https://raw.githubusercontent.com/amedeos/amedeos.github.io/master/scripts/genkernel/initrd.scripts.patch"
GENKERNEL_DIR="/usr/share/genkernel/defaults"
CRYPT_FILE="initrd.scripts"
GIT_BIN=$(which git)
GPLUS_BIN=$(which g++)
CURL_BIN=$(which curl)
LDD_BIN=$(which ldd)
LD_LINUX=$(whereis ld-linux-x86-64.so.2 | awk '{print $2}')
#TODO: insert return codes and check them after every commands

NITROBUILD=$(mktemp -t -d nitrobuild.XXXXX)
${GIT_BIN} clone ${NITROLUKS} ${NITROBUILD}
mkdir -p ${NITROBUILD}/build
${GPLUS_BIN} ${NITROBUILD}/src/nitro_luks.c -o ${NITROBUILD}/build/nitro_luks -L${NITROBUILD}/build/ -l:libnitrokey.so.3 -Wall
cp ${NITROBUILD}/build/nitro_luks ${INITRAMFS_OVERLAY}/bin/

for f in $(ldd ${NITROBUILD}/build/nitro_luks | egrep "=>" |awk '{print $3}'); do
        echo "Copy shared libraries $f"
        mkdir -p "${INITRAMFS_OVERLAY}/$(dirname $f)"
        cp --dereference ${f}* ${INITRAMFS_OVERLAY}/$(dirname $f)/
done

cp --dereference ${LD_LINUX} ${INITRAMFS_OVERLAY}/lib/
cp --dereference -a /etc/ld.so.conf.d ${INITRAMFS_OVERLAY}/etc/

${CURL_BIN} --output ${NITROBUILD}/initrd.scripts.patch ${INITRD_PATCH}
cp ${GENKERNEL_DIR}/${CRYPT_FILE} ${NITROBUILD}/${CRYPT_FILE}
patch ${NITROBUILD}/${CRYPT_FILE} ${NITROBUILD}/initrd.scripts.patch
cp ${NITROBUILD}/${CRYPT_FILE} ${INITRAMFS_OVERLAY}/etc/${CRYPT_FILE}
rm -rf ${NITROBUILD}
# we need to raise this file in the future, otherwise genkernel will overwrite it in initramfs
TZ=ZZZ0 touch -t "$(TZ=ZZZ-12:00 date +%Y%m%d%H%M.%S)" ${INITRAMFS_OVERLAY}/etc/${CRYPT_FILE}
```
### Create a new alias for genkernel
The drawback of genkernel is that don't use postbuild.d directory facilities like genkernel-next, so for this I created a **nitrogenkernel** alias.

Create a new file **/etc/bash/bashrc.d/nitrogenkernel.sh** and put inside it the new alias:

```bash
# touch /etc/bash/bashrc.d/nitrogenkernel.sh
# cat /etc/bash/bashrc.d/nitrogenkernel.sh
alias nitrogenkernel='/etc/kernels/postbuild.d/20-nitrokey.sh && genkernel --luks --lvm --mdadm all'
```
## Build a new kernel and a new initramfs
Let's create a new kernel and a new initramfs with your genkernel alias nitrogenkernel
```bash
# source /etc/profile
# time nitrogenkernel
```
## Configure grub
It's time to configure grub
```bash
# grub-mkconfig -o /boot/grub/grub.cfg
```
## Reboot
Now, you can reboot your box and unlock LUKS with your Nitrokey.
