---
layout: post_toc
title:  "How to install Gentoo with LUKS and systemd"
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
Format root filesystem as ext4 with only 1% of reserved space for super user.
```bash
livecd ~# mkfs.ext4 -m1 /dev/amedeos-g-nexi/root
```
