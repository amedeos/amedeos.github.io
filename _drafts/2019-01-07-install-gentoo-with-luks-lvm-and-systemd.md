---
layout: post_toc
title:  "How to install Gentoo with LUKS LVM and systemd"
date:   2019-01-07 20:36:44 +0100
toc: true
categories: [gentoo]
tags: [gentoo,luks,systemd]
---
## Introduction
In this post I'll describe how to install [Gentoo](https://gentoo.org/) with _**systemd**_ stage3 tarball on _**LUKS**_ partition and _**LVM**_ volume group.

This work is based on [Full Disk Encryption From Scratch Simplified](https://wiki.gentoo.org/wiki/Full_Disk_Encryption_From_Scratch_Simplified).

## Disk partitions
I prefer to use MBR partition tables with simple, old style BIOS, and not GPT with UEFI, so if you want this guide with GPT / UEFI and TPM send me a laptop with them! :grinning:
### Partition scheme
This is the oldest, and simple partition scheme used on this guide.

| **Partition** | **Filesystem** | **Size** | **Description** |
| /dev/sda1 | ext4 | 700MiB | Boot partition |
| /dev/sda2 | LUKS | rest of the disk | LUKS partition |

### Creating the Boot partition
Using **fdisk** utility just create a new _primary_ partition. When prompted for the Last sector, type _**+700M**_ to create a partition of 700MiB in size:
```bash
livecd ~# fdisk /dev/sda

Command (m for help): n
Partition type
   p   primary (0 primary, 0 extended, 4 free)
   e   extended (container for logical partitions)
Select (default p): p
Partition number (1-4, default 1): 1
First sector (2048-500118191, default 2048):
Last sector, +/-sectors or +/-size{K,M,G,T,P} (2048-500118191, default 500118191): +700M

Created a new partition 1 of type 'Linux' and of size 700 MiB.
```
### Creating the LUKS partition
Remaining inside the **fdisk** shell, just type _**n**_ to create a new primary partition, and then leave all defaults typing _enter_ for Partition number, First sector and Last sector:
```bash
Command (m for help): n
Partition type
   p   primary (1 primary, 0 extended, 3 free)
   e   extended (container for logical partitions)
Select (default p): 

Using default response p.
Partition number (2-4, default 2): 
First sector (1435648-500118191, default 1435648): 
Last sector, +/-sectors or +/-size{K,M,G,T,P} (1435648-500118191, default 500118191): 

Created a new partition 2 of type 'Linux' and of size 237.8 GiB.
```
### Change partition type to Linux LVM - Optional
Optionally you can change the second primary partition type from Linux to Linux LVM, by typing **t**, **2** and finally **8e**
```bash
Command (m for help): t
Partition number (1,2, default 2): 2
Hex code (type L to list all codes): 8e

Changed type of partition 'Linux' to 'Linux LVM'.
```
### Write partition layout to disk
To save partition layout and exit **fdisk** type **w**
```bash
Command (m for help): w
The partition table has been altered.
Calling ioctl() to re-read partition table.
Syncing disks.

livecd ~# fdisk -l /dev/sda

Device     Boot   Start       End   Sectors   Size Id Type
/dev/sda1          2048   1435647   1433600   700M 83 Linux
/dev/sda2       1435648 500118191 498682544 237.8G 8e Linux LVM
livecd ~# 

```
## Create boot filesystem
Create ext4 filesystem on first partition with only 1% of reserved space for super user.
```bash
livecd ~# mkfs.ext4 -m1 /dev/sda1
```
## Encrypt partition with LUKS
Now we can crypt the second partition /dev/sda2 with LUKS
```bash
livecd ~# cryptsetup luksFormat -c aes-xts-plain64 -s 512 /dev/sda2

WARNING!
========
This will overwrite data on /dev/sda2 irrevocably.

Are you sure? (Type uppercase yes): YES
Enter passphrase: 
Verify passphrase: 
livecd ~#
```
Open the LUKS device
```bash
livecd ~# cryptsetup luksOpen /dev/sda2 lvm
Enter passphrase for /dev/sda2:
livecd ~#
```
## Create LVM inside LUKS device
Create the physical volume
```bash
livecd ~# pvcreate /dev/mapper/lvm
```
Create the volume group
```bash
livecd ~# vgcreate -s 16M amedeos-g-nexi /dev/mapper/lvm 
```
Create logical volumes
```bash
livecd ~# lvcreate -L 4G -n swap amedeos-g-nexi
livecd ~# lvcreate -L 150G -n root amedeos-g-nexi
```
## Create root filesystem
Format root filesystem as ext4 with only 1% of reserved space for super user and mount it.
```bash
livecd ~# mkfs.ext4 -m1 /dev/amedeos-g-nexi/root
livecd ~# mount /dev/amedeos-g-nexi/root /mnt/gentoo
```

## Create swap area
Format swap logical volume as swap area and activate it.
```bash
livecd ~# mkswap /dev/amedeos-g-nexi/swap 
livecd ~# swapon /dev/amedeos-g-nexi/swap 
```

## Gentoo installation
Now it's time to get your hands dirty.
### Install systemd stage3
Download the systemd stage3 tarball from [Gentoo](https://gentoo.org/downloads/)
```bash
livecd ~# cd /mnt/gentoo/
livecd /mnt/gentoo # wget http://distfiles.gentoo.org/releases/amd64/autobuilds/20181228/systemd/stage3-amd64-systemd-20181228.tar.bz2
```
Unarchive the tarball
```bash
livecd /mnt/gentoo # tar xpvf stage3-*.tar.bz2 --xattrs-include='*.*' --numeric-owner
```
### Configuring compile options
Open /mnt/gentoo/etc/portage/make.conf file and configure the system with your preferred optimization variables. Have a look at [Gentoo Handbook](https://wiki.gentoo.org/wiki/Handbook:AMD64/Full/Installation#Configuring_compile_options)
```bash
livecd /mnt/gentoo # vi /mnt/gentoo/etc/portage/make.conf
```
For example below you can find my make.conf optimization variables
```ini
COMMON_FLAGS="-march=native -O2 -pipe"
CFLAGS="${COMMON_FLAGS}"
CXXFLAGS="${COMMON_FLAGS}"
FCFLAGS="${COMMON_FLAGS}"
FFLAGS="${COMMON_FLAGS}"
MAKEOPTS="-j5"
GRUB_PLATFORMS="pc"
CPU_FLAGS_X86="aes avx avx2 f16c fma3 mmx mmxext pclmul popcnt sse sse2 sse3 sse4_1 sse4_2 ssse3"
USE="-gtk -gnome systemd networkmanager pulseaudio spice usbredir udisks offensive cryptsetup ocr bluetooth bash-completion"
POLICY_TYPES="targeted"
ACCEPT_KEYWORDS="~amd64"
INPUT_DEVICES="libinput"
```
### Chrooting
Copy DNS configurations
```bash
livecd /mnt/gentoo # cp --dereference /etc/resolv.conf /mnt/gentoo/etc/
```
Mount proc, dev and shm filesystems
```bash
livecd /mnt/gentoo # mount -t proc /proc /mnt/gentoo/proc
livecd /mnt/gentoo # mount --rbind /sys /mnt/gentoo/sys
livecd /mnt/gentoo # mount --make-rslave /mnt/gentoo/sys
livecd /mnt/gentoo # mount --rbind /dev /mnt/gentoo/dev
livecd /mnt/gentoo # mount --make-rslave /mnt/gentoo/dev
livecd /mnt/gentoo # test -L /dev/shm && rm /dev/shm && mkdir /dev/shm
livecd /mnt/gentoo # mount -t tmpfs -o nosuid,nodev,noexec shm /dev/shm
livecd /mnt/gentoo # chmod 1777 /dev/shm
```
chroot to /mnt/gentoo
```bash
livecd /mnt/gentoo # chroot /mnt/gentoo /bin/bash 
livecd / # source /etc/profile
livecd / # export PS1="(chroot) $PS1"
(chroot) livecd / #
```
mounting the boot partition
```bash
(chroot) livecd / # mount /dev/sda1 /boot
```
### Updating the Gentoo ebuild repository
Update the Gentoo ebuild repository to the latest version.
```bash
(chroot) livecd ~# emerge --sync
```
#### Update portage
If at the end of emerge sync you see a message like this:
```console
 * An update to portage is available. It is _highly_ recommended
 * that you update portage now, before any other packages are updated.

 * To update portage, run 'emerge --oneshot portage' now.
```
on this case run
```bash
(chroot) livecd ~# emerge --oneshot portage
```
### Choosing the right profile (with systemd)
Choose one of the systemd available, for example for my system I have selected desktop/plasma/systemd
```bash
(chroot) livecd ~# eselect profile list
...
(chroot) livecd ~# eselect profile set 20
(chroot) livecd ~# eselect profile list
Available profile symlink targets:
...
[20]  default/linux/amd64/17.0/desktop/plasma/systemd (stable) *
...
```
### Timezone
Update the timezone, for example Europe/Rome
```bash
(chroot) livecd ~# echo Europe/Rome > /etc/timezone
(chroot) livecd ~# emerge --config sys-libs/timezone-data
```
### Configure locales
If you want only few locales on your system, for example C, en_us and it_IT
```bash
(chroot) livecd /etc # cat locale.gen 
...
en_US ISO-8859-1
en_US.UTF-8 UTF-8
it_IT ISO-8859-1
it_IT.UTF-8 UTF-8

(chroot) livecd /etc # locale-gen
```
now you can choose your preferred locale with
```bash
(chroot) livecd /etc # eselect locale list
(chroot) livecd /etc # eselect locale set 1
```
reload the environment
```bash
(chroot) livecd /etc # env-update && source /etc/profile && export PS1="(chroot) $PS1"
```
### Updating the world
If you change your profile, or if you change your USE flags run the update
```bash
(chroot) livecd ~# emerge --ask --verbose --update --deep --newuse @world
```
now you can take a coffee :coffee::coffee::coffee:
### Optional - GCC Upgrade
If you are in amd64 testing, most probably, updating the world, you have installed a new version of GCC, so from now we can use it
```bash
(chroot) livecd ~# gcc-config --list-profiles
 [1] x86_64-pc-linux-gnu-7.3.0 *
 [2] x86_64-pc-linux-gnu-8.2.0
```
set the default profile to 2, corresponding on the above example to the GCC 8.2
```bash
(chroot) livecd ~# gcc-config 2
 * Switching native-compiler to x86_64-pc-linux-gnu-8.2.0 ...
>>> Regenerating /etc/ld.so.cache...                                                                                                                                                                                                                                     [ ok ]

 * If you intend to use the gcc from the new profile in an already
 * running shell, please remember to do:

 *   . /etc/profile

(chroot) livecd ~# source /etc/profile
livecd ~# export PS1="(chroot) $PS1"
```
after that re-emerge the libtool
```bash
(chroot) livecd ~# emerge --ask --oneshot --usepkg=n sys-devel/libtool
```
### Optional - Install vim
If you hate nano editor like me, now you can install vim
```bash
(chroot) livecd ~# emerge --ask app-editors/vim
```
## Configure fstab
This file contains the mount points of partitions to be mounted.
Run blkid to see the UUIDs
```bash
(chroot) livecd ~# blkid 
/dev/loop0: TYPE="squashfs"
/dev/sda1: UUID="4040cacf-092e-4221-b815-7ca15b4fb7e1" TYPE="ext4" PARTUUID="fdddc7c0-01"
/dev/sda2: UUID="3cb431e7-a6ff-458d-9f1f-f86dac11545b" TYPE="crypto_LUKS" PARTUUID="fdddc7c0-02"
/dev/sdb1: UUID="2019-01-04-02-22-54-77" LABEL="Gentoo amd64 20190103T214502Z" TYPE="iso9660" PTUUID="26a11c8f" PTTYPE="dos" PARTUUID="26a11c8f-01"
/dev/sdb2: SEC_TYPE="msdos" LABEL_FATBOOT="GENTOOLIVE" LABEL="GENTOOLIVE" UUID="37E9-562E" TYPE="vfat" PARTUUID="26a11c8f-02"
/dev/mapper/lvm: UUID="p8UcJf-k9vk-esRW-JTIY-63Rz-4tSc-YjXyb4" TYPE="LVM2_member"
/dev/mapper/amedeos--g--nexi-swap: UUID="e61a7777-d005-470f-9ab2-27c75b911a18" TYPE="swap"
/dev/mapper/amedeos--g--nexi-root: UUID="a2fc60ea-1f7d-4abf-a991-21f7f0832098" TYPE="ext4"
```
copy the UUID for root filesystem -> upon LVM -> upon LUKS, (on the above example is a2fc60ea-1f7d-4abf-a991-21f7f0832098), and for the boot filesystem which resides on /dev/sda1 partition (on the above example is 4040cacf-092e-4221-b815-7ca15b4fb7e1).

This is my fstab
```bash
(chroot) livecd ~ # cat /etc/fstab 
# /etc/fstab: static file system information.

UUID=4040cacf-092e-4221-b815-7ca15b4fb7e1       /boot   ext4    defaults        1 2
UUID=a2fc60ea-1f7d-4abf-a991-21f7f0832098       /       ext4    defaults        1 1
/dev/amedeos-g-nexi/swap   none            swap            sw              0 0
# tmps
tmpfs                                           /tmp            tmpfs           defaults,size=4G        0 0
tmpfs                                           /run            tmpfs           size=100M       0 0
# shm
shm                                             /dev/shm        tmpfs           nodev,nosuid,noexec 0 0
```
## Installing the sources
Install the kernel, genkernel-next and cryptsetup
```bash
(chroot) livecd ~# emerge --ask sys-kernel/gentoo-sources
(chroot) livecd ~# emerge --ask sys-kernel/genkernel-next
(chroot) livecd ~# emerge --ask sys-fs/cryptsetup
```
### Optional - Installing firmware
Some drivers require additional firmware, if you use some of those you need to install the firmware packages
```bash
(chroot) livecd ~# emerge --ask sys-kernel/firmware
```
### Optional - Installing intel microcode
If you have an intel cpu and you want to upgrade the microcode you could install the intel-microcode package.
```bash
(chroot) livecd ~# mkdir -p /etc/portage/package.use
(chroot) livecd ~# echo "sys-firmware/intel-microcode initramfs" > /etc/portage/package.use/intel-microcode
(chroot) livecd ~# emerge --ask sys-firmware/intel-microcode
```
### Configure genkernel.conf
Configure genkernel for systemd, LUKS and LVM
```bash
(chroot) livecd ~# cd /etc/
(chroot) livecd /etc # cp -p genkernel.conf genkernel.conf.ORIG
```
```bash
(chroot) livecd /etc # vim genkernel.conf
...
MAKEOPTS="$(portageq envvar MAKEOPTS)"
...
LVM="yes"
...
LUKS="yes"
...
UDEV="yes"
...
```
### Run genkernel
Configure your kernel with the preferred options and then
```bash
(chroot) livecd ~# time genkernel --luks --lvm  all
```
## Install and configure grub
### Install grub
Configure grub to use device-mapper and standard "pc" platform
```bash
(chroot) livecd ~# mkdir -p /etc/portage/package.use
(chroot) livecd ~# echo "sys-boot/grub device-mapper" > /etc/portage/package.use/grub
(chroot) livecd ~# echo 'GRUB_PLATFORMS="pc"' >> /etc/portage/make.conf
```
emerge grub
```bash
(chroot) livecd ~# emerge --ask sys-boot/grub
```
### Install grub on MBR
just run grub-install
```bash
(chroot) livecd ~# grub-install --target=i386-pc /dev/sda
```
### Configure grub
if you run grub-mkconfig, it hangs because it doesn't has /run filesystem and os-probe will loop indefinitely; so we can exit from chroot env and mount /run filesystem
```bash
(chroot) livecd ~# exit
livecd ~# mount --rbind /run /mnt/gentoo/run 
livecd ~# mount --make-rslave /mnt/gentoo/run 
livecd ~ # cd /mnt/gentoo/
livecd /mnt/gentoo # chroot /mnt/gentoo /bin/bash 
livecd / # source /etc/profile
livecd / # export PS1="(chroot) $PS1"
(chroot) livecd / # 
```
edit /etc/default/grub
```bash
(chroot) livecd /# cd /etc/default/
(chroot) livecd /etc/default # cp grub grub.ORIG
(chroot) livecd /etc/default # vim grub
```
and most important configure GRUB_CMDLINE_LINUX with 
```bash
GRUB_CMDLINE_LINUX="init=/usr/lib/systemd/systemd dolvm crypt_root=UUID=3cb431e7-a6ff-458d-9f1f-f86dac11545b root=/dev/mapper/amedeos--g--nexi-root"
```
where

| **parameter** | **description** |
| init | set init to systemd -> /usr/lib/systemd/systemd |
| dolvm | tell init to use lvm |
| crypt_root | put here the UUID (from blkid) of the second partition /dev/sda2 |
| root | put the logical volume which contains root filesystem |

finally we can run grub-mkconfig
```bash
(chroot) livecd /etc/default # cd
(chroot) livecd ~# grub-mkconfig -o /boot/grub/grub.cfg
```
## Set the root password
Remember to set the root password
```bash
(chroot) livecd ~# passwd
```
## Rebooting the system
Exit the chrooted environment and reboot
```bash
(chroot) livecd ~ # exit
livecd /mnt/gentoo # shutdown -r now
```
