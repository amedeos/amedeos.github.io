---
layout: post
title:  "How to install Gentoo with UEFI LUKS Btrfs and systemd"
date:   2020-12-26 09:00:00 +0100
toc: true
categories: [gentoo]
tags: [gentoo,luks,systemd]
---
## Introduction
In this post I'll describe how to install [Gentoo](https://gentoo.org/) with **systemd** stage3 tarball on **UEFI**  **LUKS** partition and **Btrfs** filesystem, using the standard de facto **@ subvolume** as root file system.

I've also written two different guides to install Gentoo on LUKS, but using LVM Volume group, and ext4 filesystem, if you're interested in those you can find [here](https://amedeos.github.io/gentoo/2019/01/14/install-gentoo-with-luks-lvm-and-systemd.html) a guide to install on BIOS partition, and [here](https://amedeos.github.io/gentoo/2019/01/14/install-gentoo-with-luks-lvm-and-systemd.html) a guide to install on UEFI partition.

**UPDATE 23/08/2023**: Correct typo on GRUB_PLATFORMS

## Disk partitions
I'm using to create gpt partitions, with a small [BIOS boot partition](https://en.wikipedia.org/wiki/BIOS_boot_partition) (2 MiB) to be used by grub for second stages of itself.
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
GNU Parted 3.3
Using /dev/nvme0n1
Welcome to GNU Parted! Type 'help' to view a list of commands.
(parted) print 
Error: /dev/nvme0n1: unrecognised disk label
Model: WDC PC SN730 SDBQNTY-256G-1001 (nvme)                              
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
Model: WDC PC SN730 SDBQNTY-256G-1001 (nvme)
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
livecd ~# cryptsetup luksOpen /dev/nvme0n1p3 luksdev
Enter passphrase for /dev/nvme0n1p3: 
livecd ~#
```
## Create Btrfs filesystem and subvolume
I'll create this Btrfs volume/filesytem and subvolumes

| **Volume** | **Subvolume name** | **Parent Volume** | **Mount point** | **Description** |
| /dev/nvme0n1p3 | - | - | - | Btrfs primary volume / device |
| - | @ | /dev/nvme0n1p3 | / | Root filesystem |
| - | @home | /dev/nvme0n1p3 | /home | home filesystem |
| - | @snapshots | /dev/nvme0n1p3 | /.snapshots | snapshots filesystem |

Create the Btrfs filesystem with **Gentoo label** and mount under **/mnt/gentoo**
```bash
livecd ~# mkfs.btrfs -L Gentoo /dev/mapper/luksdev 
btrfs-progs v5.4.1 
See http://btrfs.wiki.kernel.org for more information.

Detected a SSD, turning off metadata duplication.  Mkfs with -m dup if you want to force metadata duplication.
Label:              Gentoo
UUID:               a000eea9-d97c-4107-ae39-602049a6acaa
Node size:          16384
Sector size:        4096
Filesystem size:    237.67GiB
Block group profiles:
  Data:             single            8.00MiB
  Metadata:         single            8.00MiB
  System:           single            4.00MiB
SSD detected:       yes
Incompat features:  extref, skinny-metadata
Checksum:           crc32c
Number of devices:  1
Devices:
   ID        SIZE  PATH
    1   237.67GiB  /dev/mapper/luksdev

livecd ~# mount /dev/mapper/luksdev /mnt/gentoo
```
Create all subvolumes:
```bash
livecd ~# btrfs subvolume create /mnt/gentoo/@
Create subvolume '/mnt/gentoo/@'

livecd ~# btrfs subvolume create /mnt/gentoo/@home
Create subvolume '/mnt/gentoo/@home'

livecd ~# btrfs subvolume create /mnt/gentoo/@snapshots
Create subvolume '/mnt/gentoo/@snapshots'

livecd ~# btrfs subvolume list /mnt/gentoo
ID 256 gen 7 top level 5 path @
ID 257 gen 8 top level 5 path @home
ID 258 gen 9 top level 5 path @snapshots
livecd ~#
```
**umount** /mnt/gentoo, because for root filesystem we'll use the **@** subvolume:
```bash
livecd ~# umount /mnt/gentoo
```
and finally we can mount our root filesystem based on @ subvolume:
```bash
livecd ~#  mount -t btrfs -o noatime,relatime,compress=lzo,ssd,space_cache,subvol=@ /dev/mapper/luksdev /mnt/gentoo
```

**WARNING**: if you have a recent kernel, for example 5.19 space_cache option must be **space_cache=v2**:
```bash
livecd ~#  mount -t btrfs -o noatime,relatime,compress=lzo,ssd,space_cache=v2,subvol=@ /dev/mapper/luksdev /mnt/gentoo
```

## Gentoo installation
Now it's time to get your hands dirty.
### Install systemd stage3
Download the systemd stage3 tarball from [Gentoo](https://gentoo.org/downloads/)
```bash
livecd ~# cd /mnt/gentoo/
livecd /mnt/gentoo # wget https://bouncer.gentoo.org/fetch/root/all/releases/amd64/autobuilds/20201222T005811Z/stage3-amd64-systemd-20201222T005811Z.tar.xz
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
# These settings were set by the catalyst build script that automatically
# built this stage.
# Please consult /usr/share/portage/config/make.conf.example for a more
# detailed example.
COMMON_FLAGS="-march=skylake -O2 -pipe"
CFLAGS="${COMMON_FLAGS}"
CXXFLAGS="${COMMON_FLAGS}"
FCFLAGS="${COMMON_FLAGS}"
FFLAGS="${COMMON_FLAGS}"

CPU_FLAGS_X86="aes avx avx2 f16c fma3 mmx mmxext pclmul popcnt sse sse2 sse3 sse4_1 sse4_2 ssse3"

MAKEOPTS="-j8"

GRUB_PLATFORMS="efi-64"

L10N="en it"

USE="-gtk -gnome systemd networkmanager pulseaudio spice usbredir udisks offensive cryptsetup ocr bluetooth bash-completion opengl opencl vulkan v4l x265 theora policykit vaapi vdpau lto cec cameras_ptp2 wayland"

POLICY_TYPES="targeted"
INPUT_DEVICES="libinput"

ACCEPT_KEYWORDS="~amd64"
ACCEPT_LICENSE="* -@EULA"

VIDEO_CARDS="intel i965 iris"

LLVM_TARGETS="BPF WebAssembly"

PYTHON_TARGETS="python2_7 python3_7 python3_8 python3_9"

# NOTE: This stage was built with the bindist Use flag enabled
PORTDIR="/var/db/repos/gentoo"
DISTDIR="/var/cache/distfiles"
PKGDIR="/var/cache/binpkgs"

# This sets the language of build output to English.
# Please keep this setting intact when reporting bugs.
LC_MESSAGES=C
```
### Chrooting
Copy DNS configurations:
```bash
livecd /mnt/gentoo # cp --dereference /etc/resolv.conf /mnt/gentoo/etc/
```
Mount proc, dev and shm filesystems:
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
chroot to /mnt/gentoo:
```bash
livecd /mnt/gentoo # chroot /mnt/gentoo /bin/bash 
livecd / # source /etc/profile
livecd / # export PS1="(chroot) $PS1"
(chroot) livecd / #
```
mounting the boot partition:
```bash
(chroot) livecd / # mount /dev/nvme0n1p2 /boot
```
and then mount **/home** and **/.snapshots** subvolumes:

```bash
(chroot) livecd / # mkdir /.snapshots

(chroot) livecd / # mount -t btrfs -o noatime,relatime,compress=lzo,ssd,subvol=@snapshots /dev/mapper/luksdev /.snapshots

(chroot) livecd / # mount -t btrfs -o noatime,relatime,compress=lzo,ssd,subvol=@home /dev/mapper/luksdev /home
```

### Updating the Gentoo ebuild repository
Update the Gentoo ebuild repository to the latest version:
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
if you are on this case emerge the portage:
```bash
(chroot) livecd ~# emerge --oneshot sys-apps/portage
```
### Choosing the right profile (with systemd)
Choose one of the systemd profile available, for example for my system I have selected desktop/plasma/systemd
```bash
(chroot) livecd ~ # eselect profile list
...
(chroot) livecd ~ # eselect profile set 9
(chroot) livecd ~ # eselect profile list
Available profile symlink targets:
...
  [9]   default/linux/amd64/17.1/desktop/plasma/systemd (stable) *
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
 [2] x86_64-pc-linux-gnu-10.2.0
```
set the default profile to 2, corresponding to the above example to the GCC 10.2
```bash
(chroot) livecd ~# gcc-config 2
 * Switching native-compiler to x86_64-pc-linux-gnu-10.2.0 ...
>>> Regenerating /etc/ld.so.cache...                                                                                                                                                                                                                                    [ ok ]

 * If you intend to use the gcc from the new profile in an already
 * running shell, please remember to do:

 *   . /etc/profile

(chroot) livecd ~# source /etc/profile
livecd ~# export PS1="(chroot) $PS1"
```
after that re-emerge the libtool:
```bash
(chroot) livecd ~# emerge --ask --oneshot --usepkg=n sys-devel/libtool
```
### Optional - Install vim
If you hate nano editor like me, now you can install vim:
```bash
(chroot) livecd ~# emerge --ask app-editors/vim
```
## Configure fstab
This file contains the mount points of partitions to be mounted.
Run blkid to see the UUIDs:
```bash
(chroot) livecd ~# blkid 
/dev/loop0: TYPE="squashfs"
/dev/nvme0n1p1: SEC_TYPE="msdos" UUID="1C3B-C680" BLOCK_SIZE="512" TYPE="vfat" PARTLABEL="grub" PARTUUID="39bd8ab8-3708-4ecf-b4e3-f5714a6e4ea1"
/dev/nvme0n1p2: UUID="1D97-3854" BLOCK_SIZE="512" TYPE="vfat" PARTLABEL="boot" PARTUUID="b44718e2-d7fe-4eba-a6c7-1d1beee11806"
/dev/nvme0n1p3: UUID="1ce717f4-5a82-49e7-ae1c-9a92e4c20251" TYPE="crypto_LUKS" PARTLABEL="luks" PARTUUID="c271c93e-6f59-446f-9139-a0b98afab820"
/dev/sda1: BLOCK_SIZE="2048" UUID="2020-12-22-12-44-06-70" LABEL="Gentoo amd64 20201222T005811Z" TYPE="iso9660" PTUUID="7437c9e0" PTTYPE="dos" PARTUUID="7437c9e0-01"
/dev/sda2: SEC_TYPE="msdos" LABEL_FATBOOT="GENTOOLIVE" LABEL="GENTOOLIVE" UUID="A168-D76E" BLOCK_SIZE="512" TYPE="vfat" PARTUUID="7437c9e0-02"
/dev/mapper/luksdev: LABEL="Gentoo" UUID="a000eea9-d97c-4107-ae39-602049a6acaa" UUID_SUB="d45b2afd-7250-4ba1-a896-b0e81a20fa4b" BLOCK_SIZE="4096" TYPE="btrfs"
```
copy the UUID for the root filesystem upon **luksdev** device, (in the above example is a000eea9-d97c-4107-ae39-602049a6acaa), also copy the UUID for the boot filesystem which resides on /dev/nvme0n1p2 partition (on the above example is 1D97-3854).

This is my fstab
```bash
(chroot) livecd /etc # cat fstab
# /etc/fstab: static file system information.
UUID=1D97-3854                                  /boot                           vfat            noatime                                                                         0 1
UUID=a000eea9-d97c-4107-ae39-602049a6acaa       /                               btrfs           noatime,relatime,compress=lzo,ssd,discard=async,subvol=@            0 0
UUID=a000eea9-d97c-4107-ae39-602049a6acaa       /home                           btrfs           noatime,relatime,compress=lzo,ssd,discard=async,subvol=@home        0 0
UUID=a000eea9-d97c-4107-ae39-602049a6acaa       /.snapshots                     btrfs           noatime,relatime,compress=lzo,ssd,discard=async,subvol=@snapshots   0 0
# tmps
tmpfs                                           /tmp                            tmpfs           defaults,size=4G                                                                0 0
tmpfs                                           /run                            tmpfs           size=100M                                                                       0 0
# shm
shm                                             /dev/shm                        tmpfs           nodev,nosuid,noexec                                                             0 0
```
**WARNING** I've been using the option **discard=async** since I'm using kernel greater then 5.6, if you're using kernel 5.4.x (or older) don't use the discard=async option!!!


## Installing the sources
Install the kernel, genkernel and cryptsetup:
```bash
(chroot) livecd ~# emerge --ask sys-kernel/gentoo-sources
(chroot) livecd ~# emerge --ask sys-kernel/genkernel
(chroot) livecd ~# emerge --ask sys-fs/cryptsetup
```
### Optional - Installing firmware
Some drivers require additional firmware, if you use some of those you need to install the firmware packages:
```bash
(chroot) livecd ~# emerge --ask sys-kernel/linux-firmware
```
### Optional - Installing intel microcode
If you have an Intel cpu and you want to upgrade the microcode you could install the intel-microcode package:
```bash
(chroot) livecd ~# mkdir -p /etc/portage/package.use
(chroot) livecd ~# echo "sys-firmware/intel-microcode initramfs" > /etc/portage/package.use/intel-microcode
(chroot) livecd ~# emerge --ask sys-firmware/intel-microcode
```
### Configure genkernel.conf
Configure genkernel for systemd, LUKS and Btrfs:
```bash
(chroot) livecd ~# cd /etc/
(chroot) livecd /etc # cp -p genkernel.conf genkernel.conf.ORIG
```
```bash
(chroot) livecd /etc # vim genkernel.conf
...
MAKEOPTS="$(portageq envvar MAKEOPTS)"
...
LUKS="yes"
...
BTRFS="yes"
...
```
### Run genkernel
Configure your kernel with the preferred options, and then
```bash
(chroot) livecd ~# time genkernel all
```
## Install and configure grub
### Install grub
Configure grub to use efi-64 platform:
```bash
(chroot) livecd ~# echo 'GRUB_PLATFORMS="efi-64"' >> /etc/portage/make.conf
```
emerge grub:
```bash
(chroot) livecd ~# emerge --ask sys-boot/grub
```
### Install grub
just run grub-install:
```bash
(chroot) livecd ~# grub-install --target=x86_64-efi --efi-directory=/boot
```
### Configure grub
First find the LUKS UUID and the root filesystem UUID:
```bash
(chroot) livecd ~# blkid  | egrep '(crypto_LUKS|luksdev)'
/dev/nvme0n1p3: UUID="1ce717f4-5a82-49e7-ae1c-9a92e4c20251" TYPE="crypto_LUKS" PARTLABEL="luks" PARTUUID="c271c93e-6f59-446f-9139-a0b98afab820"
/dev/mapper/luksdev: LABEL="Gentoo" UUID="a000eea9-d97c-4107-ae39-602049a6acaa" UUID_SUB="d45b2afd-7250-4ba1-a896-b0e81a20fa4b" BLOCK_SIZE="4096" TYPE="btrfs"
```
In my case the LUKS UUID is 1ce717f4-5a82-49e7-ae1c-9a92e4c20251 and the root UUID is a000eea9-d97c-4107-ae39-602049a6acaa

Edit /etc/default/grub
```bash
(chroot) livecd ~# cd /etc/default/
(chroot) livecd /etc/default # cp -p grub grub.ORIG
(chroot) livecd /etc/default # vim grub
```
and most important configure GRUB_CMDLINE_LINUX with 
```bash
GRUB_CMDLINE_LINUX="init=/usr/lib/systemd/systemd crypt_root=UUID=1ce717f4-5a82-49e7-ae1c-9a92e4c20251 root=UUID=a000eea9-d97c-4107-ae39-602049a6acaa rootflags=subvol=@"
```
where

| **parameter** | **description** |
| init | set init to systemd -> /usr/lib/systemd/systemd |
| crypt_root | put here the LUKS UUID (from blkid) of the third partition /dev/nvme0n1p3 |
| root | put here the Btrfs UUID (kept from luksdev device on blkid) |
| rootflags | tell the kernel what Btrfs' subvolume contains root filesystem (@) |

finally we can run grub-mkconfig:
```bash
(chroot) livecd /etc/default # cd
(chroot) livecd ~# grub-mkconfig -o /boot/grub/grub.cfg
```
## Set the root password
Remember to set the root password:
```bash
(chroot) livecd ~# passwd
```
## Rebooting the system
Exit the chrooted environment and reboot:
```bash
(chroot) livecd ~# exit
livecd /mnt/gentoo # shutdown -r now
```

## Optional: Add swap subvolume and swapfile
If you want to add a swapfile, inside your Btrfs filesystem, after the first reboot, check at first, the LUKS device mapper created by your initramfs, if you're using genkernel this device mapper is called **root**:

```bash
~# blkid | grep Gentoo
/dev/mapper/root: LABEL="Gentoo" UUID="a000eea9-d97c-4107-ae39-602049a6acaa" UUID_SUB="d45b2afd-7250-4ba1-a896-b0e81a20fa4b" BLOCK_SIZE="4096" TYPE="btrfs"
```
now mount it under /mnt/gentoo directory:
```bash
~# mkdir -p /mnt/gentoo
~# mount /dev/mapper/root /mnt/gentoo
```
create the **@swap** subvolume:
```bash
~# btrfs subvolume create /mnt/gentoo/@swap
Create subvolume '/mnt/gentoo/@swap'
```
create the swapfile, in my case 4G of swapfile, but you can adapt it as your needs:
```bash
~# truncate -s 0 /mnt/gentoo/@swap/swapfile
```
disable the copy on write and Btrfs compression:
```bash
~# chattr +C /mnt/gentoo/@swap/swapfile

~# btrfs property set /mnt/gentoo/@swap/swapfile compression none
```
and create the 4G swapfile:
```bash
~# fallocate -l 4G /mnt/gentoo/@swap/swapfile

~# chmod 0600 /mnt/gentoo/@swap/swapfile

~# mkswap /mnt/gentoo/@swap/swapfile
Setting up swapspace version 1, size = 4 GiB (4294963200 bytes)
```
create the mountpoint **/.swap**:
```bash
~# mkdir /.swap
```
and add two rows in the fstab, one for the **@swap** subvolume, and the second one for the swapfile **/.swap/swapfile**
```bash
~# cd /etc

/etc# cat fstab
# /etc/fstab: static file system information.
UUID=1D97-3854                                  /boot                           vfat            noatime                                                                         0 1
UUID=a000eea9-d97c-4107-ae39-602049a6acaa       /                               btrfs           noatime,relatime,compress=lzo,ssd,discard=async,subvol=@            0 0
UUID=a000eea9-d97c-4107-ae39-602049a6acaa       /home                           btrfs           noatime,relatime,compress=lzo,ssd,discard=async,subvol=@home        0 0
UUID=a000eea9-d97c-4107-ae39-602049a6acaa       /.snapshots                     btrfs           noatime,relatime,compress=lzo,ssd,discard=async,subvol=@snapshots   0 0
UUID=a000eea9-d97c-4107-ae39-602049a6acaa       /.swap                          btrfs           noatime,relatime,compress=no,ssd,discard=async,subvol=@swap         0 0
/.swap/swapfile                                 none                            swap            sw                                                                              0 0
# tmps
tmpfs                                           /tmp                            tmpfs           defaults,size=4G                                                                0 0
tmpfs                                           /run                            tmpfs           size=100M                                                                       0 0
# shm
shm                                             /dev/shm                        tmpfs           nodev,nosuid,noexec                                                             0 0
```
remember to set **compress=no** to speeding up the swapfile and set **discard=async** only if have a kernel > 5.6.

Final umount /mnt/gentoo and reboot:

```bash
~# umount /mnt/gentoo
~# reboot
```
