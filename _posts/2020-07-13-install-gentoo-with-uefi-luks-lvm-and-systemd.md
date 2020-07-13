---
layout: post
title:  "How to install Gentoo with UEFI LUKS LVM and systemd"
date:   2020-07-13 09:00:00 +0200
toc: true
categories: [gentoo]
tags: [gentoo,luks,systemd]
---
## Introduction
In this post I'll describe how to install [Gentoo](https://gentoo.org/) with **systemd** stage3 tarball on **UEFI**  **LUKS** partition and **LVM** volume group.

I've just written a similar [guide](https://amedeos.github.io/gentoo/2019/01/14/install-gentoo-with-luks-lvm-and-systemd.html) to install Gentoo on LUKS and LVM, but is based on old style BIOS, and not on UEFI, if you prefer BIOS have a look at that guide.

## Disk partitions
I'm used to create gpt partitions, with a small [BIOS boot partition](https://en.wikipedia.org/wiki/BIOS_boot_partition) (2 MiB) to be used by grub for second stages of itself.
### Partition scheme
This is the quite simple partition scheme used in this guide.
In this guide I'm using an **NVME** disk _/dev/nvme0n1_, but if you have a scsi disk like _/dev/sda_, its simple as run _sed 's/nvme0n1/sda/g'_

| **Partition** | **Filesystem** | **Size** | **Description** |
| /dev/nvme0n1p1 | fat | 2MiB | bios boot |
| /dev/nvme0n1p2 | fat32 | 800MiB | Boot partition |
| /dev/nvme0n1p3 | LUKS | rest of the disk | LUKS partition |

### Creating the partitions
Using **parted** utility now we can create all required partitions

```bash
livecd ~# parted /dev/nvme0n1 
GNU Parted 3.2
Using /dev/nvme0n1
Welcome to GNU Parted! Type 'help' to view a list of commands.
(parted) print                                                            
Error: /dev/nvme0n1: unrecognised disk label
Model: Unknown (unknown)                                                  
Disk /dev/nvme0n1: 256GB
Sector size (logical/physical): 512B/512B
Partition Table: unknown
Disk Flags:

(parted) mklabel gpt

(parted) mkpart primary fat32 1MiB 3MiB

(parted) mkpart primary fat32 3MiB 803MiB

(parted) mkpart primary 803MiB -1

(parted) name 1 grub                                                      
(parted) name 2 boot                                                      
(parted) name 3 luks

(parted) set 1 bios_grub on                                               
(parted) set 2 boot on                                                    

(parted) print                                                            
Model: Unknown (unknown)
Disk /dev/nvme0n1: 256GB
Sector size (logical/physical): 512B/512B
Partition Table: gpt
Disk Flags: 

Number  Start   End     Size    File system  Name  Flags
 1      1049kB  3146kB  2097kB  fat32        grub  bios_grub
 2      3146kB  842MB   839MB   fat32        boot  boot, esp
 3      842MB   256GB   255GB                luks
 
(parted) quit
```
## Create fat filesystems
For both bios boot we'll create a fat filesystem, instead, for boot partition we'll create a fat32 filesystem:
```bash
livecd ~# mkfs.vfat /dev/nvme0n1p1 
mkfs.fat 4.1 (2017-01-24)
livecd ~# mkfs.vfat -F32 /dev/nvme0n1p2
mkfs.fat 4.1 (2017-01-24)
```
## Encrypt partition with LUKS
Now we can crypt the third partition /dev/nvme0n1p3 with LUKS
```bash
livecd ~# cryptsetup luksFormat -c aes-xts-plain64 -s 512 /dev/nvme0n1p3 

WARNING!
========
This will overwrite data on /dev/nvme0n1p3 irrevocably.

Are you sure? (Type 'yes' in capital letters): YES
Enter passphrase for /dev/nvme0n1p3: 
Verify passphrase: 
livecd ~#
```
Open the LUKS device
```bash
livecd ~# cryptsetup luksOpen /dev/nvme0n1p3 lvm
Enter passphrase for /dev/nvme0n1p3:
livecd ~#
```
## Create LVM inside LUKS device
Create the physical volume
```bash
livecd ~# pvcreate /dev/mapper/lvm 
  WARNING: Failed to connect to lvmetad. Falling back to device scanning.
  Physical volume "/dev/mapper/lvm" successfully created.
livecd ~#
```
Create the volume group
```bash
livecd ~# vgcreate -s 16M amedeos-vg /dev/mapper/lvm
  WARNING: Failed to connect to lvmetad. Falling back to device scanning.
  Volume group "amedeos-vg" successfully created
livecd ~#
```
Create logical volumes
```bash
livecd ~# lvcreate -L 8G -n swap amedeos-vg
  WARNING: Failed to connect to lvmetad. Falling back to device scanning.
  Logical volume "swap" created.
livecd ~# lvcreate -L 100G -n root amedeos-vg
  WARNING: Failed to connect to lvmetad. Falling back to device scanning.
  Logical volume "root" created.
livecd ~#
```
## Create root filesystem
Format root filesystem as ext4 with only 1% of reserved space for super user and mount it.
```bash
livecd ~# mkfs.ext4 -m1 /dev/amedeos-vg/root
livecd ~# mount /dev/amedeos-vg/root /mnt/gentoo
```

## Create swap area
Format swap logical volume as swap area and activate it.
```bash
livecd ~# mkswap /dev/amedeos-vg/swap
livecd ~# swapon /dev/amedeos-vg/swap
```

## Gentoo installation
Now it's time to get your hands dirty.
### Install systemd stage3
Download the systemd stage3 tarball from [Gentoo](https://gentoo.org/downloads/)
```bash
livecd ~# cd /mnt/gentoo/
livecd /mnt/gentoo # wget https://bouncer.gentoo.org/fetch/root/all/releases/amd64/autobuilds/20200708T103427Z/stage3-amd64-systemd-20200708T103427Z.tar.xz
```
Unarchive the tarball
```bash
livecd /mnt/gentoo # tar xpvf stage3-*.tar.xz --xattrs-include='*.*' --numeric-owner
```
### Configuring compile options
Open /mnt/gentoo/etc/portage/make.conf file and configure the system with your preferred optimization variables. Have a look at [Gentoo Handbook](https://wiki.gentoo.org/wiki/Handbook:AMD64/Full/Installation#Configuring_compile_options)
```bash
livecd /mnt/gentoo # vi /mnt/gentoo/etc/portage/make.conf
```
For example, below you can find my make.conf optimization variables
```ini
COMMON_FLAGS="-march=skylake -O2 -pipe"
CFLAGS="${COMMON_FLAGS}"
CXXFLAGS="${COMMON_FLAGS}"
FCFLAGS="${COMMON_FLAGS}"
FFLAGS="${COMMON_FLAGS}"
CPU_FLAGS_X86="aes avx avx2 f16c fma3 mmx mmxext pclmul popcnt sse sse2 sse3 sse4_1 sse4_2 ssse3"
MAKEOPTS="-j8"
GRUB_PLATFORM="efi-64"
L10N="en it"
USE="-gtk -gnome systemd networkmanager pulseaudio spice usbredir udisks offensive cryptsetup ocr bluetooth bash-completion opengl opencl vulkan v4l x265 theora policykit vaapi vdpau lto cec cameras_ptp2 wayland"
POLICY_TYPES="targeted"
INPUT_DEVICES="libinput"
ACCEPT_KEYWORDS="~amd64"
ACCEPT_LICENSE="* -@EULA"
VIDEO_CARDS="intel i965 iris"
LLVM_TARGETS="BPF WebAssembly"
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
(chroot) livecd / # mount /dev/nvme0n1p2 /boot
```
### Updating the Gentoo ebuild repository
Update the Gentoo ebuild repository to the latest version.
```bash
(chroot) livecd ~# emerge --sync
```
#### Update portage
If at the end of emerge sync you see a message like this:
```console
Action: sync for repo: gentoo, returned code = 0

 * An update to portage is available. It is _highly_ recommended
 * that you update portage now, before any other packages are updated.

 * To update portage, run 'emerge --oneshot sys-apps/portage' now.
```
if you are on this case run
```bash
(chroot) livecd ~# emerge --oneshot sys-apps/portage
```
### Choosing the right profile (with systemd)
Choose one of the systemd available, for example for my system I have selected desktop/plasma/systemd
```bash
(chroot) livecd ~# eselect profile list
...
(chroot) livecd ~# eselect profile set 24
(chroot) livecd ~# eselect profile list
Available profile symlink targets:
...
[24]  default/linux/amd64/17.1/desktop/plasma/systemd (stable) *
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
C.UTF8 UTF-8
en_US ISO-8859-1
en_US.UTF-8 UTF-8
it_IT ISO-8859-1
it_IT.UTF-8 UTF-8

(chroot) livecd /etc # locale-gen
```
now you can choose your preferred locale with
```bash
(chroot) livecd /etc # eselect locale list
(chroot) livecd /etc # eselect locale set 10
(chroot) livecd /etc # eselect locale list
...
[10]  C.UTF8 *
```
reload the environment
```bash
(chroot) livecd /etc # env-update && source /etc/profile && export PS1="(chroot) $PS1"
```
### Updating the world
If you change your profile, or if you change your USE flags run the update
```bash
(chroot) livecd ~# mkdir -p /etc/portage/package.{accept_keywords,license,mask,unmask,use}
(chroot) livecd ~# time emerge --ask --verbose --update --deep --with-bdeps=y --newuse  --keep-going --backtrack=30 @world
```
now you can take a coffee :coffee::coffee::coffee:
### Optional - GCC Upgrade
If you are in amd64 testing, most probably, updating the world, you have installed a new version of GCC, so from now we can use it
```bash
(chroot) livecd ~# gcc-config --list-profiles
 [1] x86_64-pc-linux-gnu-9.3.0 *
 [2] x86_64-pc-linux-gnu-10.1.0
```
set the default profile to 2, corresponding on the above example to the GCC 10.1
```bash
(chroot) livecd ~# gcc-config 2
 * Switching native-compiler to x86_64-pc-linux-gnu-10.1.0 ...
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
/dev/nvme0n1p1: SEC_TYPE="msdos" UUID="B504-5AA5" BLOCK_SIZE="512" TYPE="vfat" PARTLABEL="grub" PARTUUID="6a184475-901b-4db6-908a-92d71417c8a6"
/dev/nvme0n1p2: UUID="B584-288C" BLOCK_SIZE="512" TYPE="vfat" PARTLABEL="boot" PARTUUID="2b2858be-b3eb-43da-ac62-0c207ce66c00"
/dev/nvme0n1p3: UUID="a3638986-f4dc-4c20-96a3-137654261c30" TYPE="crypto_LUKS" PARTLABEL="luks" PARTUUID="23a5f82d-9b59-4478-a5bf-5e048afdb1b9"
/dev/sda1: BLOCK_SIZE="2048" UUID="2020-06-10-23-34-05-36" LABEL="Gentoo amd64 20200610T214505Z" TYPE="iso9660" PTUUID="3d15dee3" PTTYPE="dos" PARTUUID="3d15dee3-01"
/dev/sda2: SEC_TYPE="msdos" LABEL_FATBOOT="GENTOOLIVE" LABEL="GENTOOLIVE" UUID="DED2-B1A8" BLOCK_SIZE="512" TYPE="vfat" PARTUUID="3d15dee3-02"
/dev/mapper/lvm: UUID="TmhEHU-5jOv-8hWV-qtyr-p7jQ-KQkD-WrjlQ7" TYPE="LVM2_member"
/dev/mapper/amedeos--vg-swap: UUID="65e7d17d-5120-44ca-8399-bd8af5417e5c" TYPE="swap"
/dev/mapper/amedeos--vg-root: UUID="1100db5c-4ee8-4093-bdfc-c234e0183293" BLOCK_SIZE="4096" TYPE="ext4"
```
copy the UUID for root filesystem -> upon LVM -> upon LUKS, (in the above example is 1100db5c-4ee8-4093-bdfc-c234e0183293), and for the boot filesystem which resides on /dev/nvme0n1p3 partition (on the above example is B584-288C).

This is my fstab
```bash
(chroot) livecd ~ # cat /etc/fstab 
# /etc/fstab: static file system information.
UUID=B584-288C                                  /boot           vfat            noatime 0 1
UUID=1100db5c-4ee8-4093-bdfc-c234e0183293       /               ext4            defaults,acl                0 1
# tmps
tmpfs                                           /tmp            tmpfs           defaults,size=4G        0 0
tmpfs                                           /run            tmpfs           size=100M       0 0
# shm
shm                                             /dev/shm        tmpfs           nodev,nosuid,noexec 0 0
```
## Installing the sources
Install the kernel, genkernel and cryptsetup
```bash
(chroot) livecd ~# emerge --ask sys-kernel/gentoo-sources
(chroot) livecd ~# emerge --ask sys-kernel/genkernel
(chroot) livecd ~# emerge --ask sys-fs/cryptsetup
```
### Optional - Installing firmware
Some drivers require additional firmware, if you use some of those you need to install the firmware packages
```bash
(chroot) livecd ~# emerge --ask sys-kernel/linux-firmware
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
```
### Run genkernel
Configure your kernel with the preferred options and then
```bash
(chroot) livecd ~# time genkernel --luks --lvm  all
```
## Install and configure grub
### Install grub
Configure grub to use device-mapper and efi-64 platform
```bash
(chroot) livecd ~# mkdir -p /etc/portage/package.use
(chroot) livecd ~# echo "sys-boot/grub device-mapper" > /etc/portage/package.use/grub
(chroot) livecd ~# echo 'GRUB_PLATFORM="efi-64"' >> /etc/portage/make.conf
```
emerge grub
```bash
(chroot) livecd ~# emerge --ask sys-boot/grub
```
### Install grub
just run grub-install
```bash
(chroot) livecd ~# grub-install --target=x86_64-efi --efi-directory=/boot
```
### Configure grub
First find the LUKS UUID
```bash
(chroot) livecd ~# blkid  | grep crypto_LUKS
/dev/nvme0n1p3: UUID="a3638986-f4dc-4c20-96a3-137654261c30" TYPE="crypto_LUKS" PARTLABEL="luks" PARTUUID="23a5f82d-9b59-4478-a5bf-5e048afdb1b9"
```
In my case the LUKS UUID is a3638986-f4dc-4c20-96a3-137654261c30

Edit /etc/default/grub
```bash
(chroot) livecd /# cd /etc/default/
(chroot) livecd /etc/default # cp grub grub.ORIG
(chroot) livecd /etc/default # vim grub
```
and most important configure GRUB_CMDLINE_LINUX with 
```bash
GRUB_CMDLINE_LINUX="init=/usr/lib/systemd/systemd dolvm crypt_root=UUID=a3638986-f4dc-4c20-96a3-137654261c30 root=/dev/mapper/amedeos--vg-root scsi_mod.use_blk_mq=1"
```
where

| **parameter** | **description** |
| init | set init to systemd -> /usr/lib/systemd/systemd |
| dolvm | tell init to use lvm |
| crypt_root | put here the LUKS UUID (from blkid) of the third partition /dev/nvme0n1p3 |
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
