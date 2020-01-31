---
layout: post
title:  "Reset ssd disks for performance reason"
date:   2020-01-31 18:00:00 +0100
categories: [ssd,performance]
tags: [ssd,performance]
---
## Introduction
Recently I observed a degraded performance on my desktop workstation, and this was caused by an old ssd disk bought five or six years before. To restore the initial state of the disk and, I hope, the initial state of the IO performance I followed the base instructions kept on [memory cell clearing](https://wiki.archlinux.org/index.php/Solid_state_drive/Memory_cell_clearing), but as my disks are in mirror raid I never loose data.
## Check raid data
Before break any raid mirror force mdadm to check the mirror raid
```bash
$ cat /proc/mdstat 
Personalities : [linear] [raid0] [raid1] [raid10] [raid6] [raid5] [raid4] 
md125 : active raid10 sdf1[3] sde1[2] sdc1[0] sdd1[1]
      1953258496 blocks super 1.2 512K chunks 2 near-copies [4/4] [UUUU]
      bitmap: 0/15 pages [0KB], 65536KB chunk

md126 : active raid1 sda1[0] sdb1[1]
      818176 blocks super 1.2 [2/2] [UU]
      
md127 : active raid1 sda2[0] sdb2[1]
      233478720 blocks super 1.2 [2/2] [UU]
      bitmap: 2/2 pages [8KB], 65536KB chunk

unused devices: <none>
```
My degraded disk is ___/dev/sda___, and upon it there are two MD raid devices ___md126___, which is ___/boot___ partition, and ___md127___, which is a ___LUKS___ device, and everything seems to be fine because for those MD devices are present the double ___UU___, but I prefer for force RAID check:
```bash
$ sudo echo check > /sys/block/md126/md/sync_action
$ cat /proc/mdstat
Personalities : [linear] [raid0] [raid1] [raid10] [raid6] [raid5] [raid4]
md125 : active raid10 sdf1[3] sde1[2] sdc1[0] sdd1[1]
      1953258496 blocks super 1.2 512K chunks 2 near-copies [4/4] [UUUU]
      bitmap: 0/15 pages [0KB], 65536KB chunk

md126 : active raid1 sda1[0] sdb1[1]
      818176 blocks super 1.2 [2/2] [UU]
      [===========>.........]  check = 57.1% (468416/818176) finish=0.0min speed=156138K/sec

md127 : active raid1 sda2[0] sdb2[1]
      233478720 blocks super 1.2 [2/2] [UU]
      bitmap: 2/2 pages [8KB], 65536KB chunk

unused devices: <none>
$ cat /proc/mdstat
Personalities : [linear] [raid0] [raid1] [raid10] [raid6] [raid5] [raid4]
md125 : active raid10 sdf1[3] sde1[2] sdc1[0] sdd1[1]
      1953258496 blocks super 1.2 512K chunks 2 near-copies [4/4] [UUUU]
      bitmap: 0/15 pages [0KB], 65536KB chunk

md126 : active raid1 sda1[0] sdb1[1]
      818176 blocks super 1.2 [2/2] [UU]

md127 : active raid1 sda2[0] sdb2[1]
      233478720 blocks super 1.2 [2/2] [UU]
      bitmap: 2/2 pages [8KB], 65536KB chunk

unused devices: <none>
```
wait until it ends, and then force RAID check to the bigger md127:
```bash
$ sudo echo check > /sys/block/md127/md/sync_action
$ cat /proc/mdstat
Personalities : [linear] [raid0] [raid1] [raid10] [raid6] [raid5] [raid4]
md125 : active raid10 sdf1[3] sde1[2] sdc1[0] sdd1[1]
      1953258496 blocks super 1.2 512K chunks 2 near-copies [4/4] [UUUU]
      bitmap: 0/15 pages [0KB], 65536KB chunk

md126 : active raid1 sda1[0] sdb1[1]
      818176 blocks super 1.2 [2/2] [UU]

md127 : active raid1 sda2[0] sdb2[1]
      233478720 blocks super 1.2 [2/2] [UU]
      [>....................]  check =  0.0% (84352/233478720) finish=230.5min speed=16870K/sec
      bitmap: 2/2 pages [8KB], 65536KB chunk

unused devices: <none>
```
and finally, check if there are some data mismatch between the two disks --> you should get ___0___ in mismatch_cnt special file
```bash
$ cat /sys/block/md127/md/mismatch_cnt
0
$ cat /sys/block/md126/md/mismatch_cnt
0
```
## Break the mirror(s)
Set sda1 and sda2 partitions as fault mirror devices
```bash
$ sudo mdadm --manage /dev/md127 --fail /dev/sda2
mdadm: set /dev/sda2 faulty in /dev/md127
$ sudo mdadm --manage /dev/md126 --fail /dev/sda1
mdadm: set /dev/sda1 faulty in /dev/md126
```
Remove the sda1 and sda2 device from the two mirrors
```bash
$ sudo mdadm --manage /dev/md127 --remove /dev/sda2
mdadm: hot removed /dev/sda2 from /dev/md127
$ sudo mdadm --manage /dev/md126 --remove /dev/sda1
mdadm: hot removed /dev/sda1 from /dev/md126
```
now, you can see "_U" state for the md126 and md127 devices
```bash
$ cat /proc/mdstat 
Personalities : [linear] [raid0] [raid1] [raid10] [raid6] [raid5] [raid4] 
md125 : active raid10 sdf1[3] sde1[2] sdc1[0] sdd1[1]
      1953258496 blocks super 1.2 512K chunks 2 near-copies [4/4] [UUUU]
      bitmap: 0/15 pages [0KB], 65536KB chunk

md126 : active raid1 sdb1[1]
      818176 blocks super 1.2 [2/1] [_U]
      
md127 : active raid1 sdb2[1]
      233478720 blocks super 1.2 [2/1] [_U]
      bitmap: 2/2 pages [8KB], 65536KB chunk
```
## Cell clearing
I tried to unplug and plug the sata disk but on my host the device remains in ___frozen___ state, so I was unable to reset the disk; to overcome this situation I unplugged the disk and put it into an USB case, and then:
```bash
$ sudo hdparm -I /dev/sda | grep frozen
        not     frozen
```
enable security setting user password
```bash
$ sudo hdparm --user-master u --security-set-pass PasSWorD /dev/sda
security_password: "PasSWorD"

/dev/sda:
 Issuing SECURITY_SET_PASS command, password="PasSWorD", user=user, mode=high
```
check if ___security___ is ___enabled___
```bash
$ sudo hdparm -I /dev/sda
...
Security:
        Master password revision code = 65534
                supported
                enabled
        not     locked
        not     frozen
        not     expired: security count
                supported: enhanced erase
        Security level high
        4min for SECURITY ERASE UNIT. 2min for ENHANCED SECURITY ERASE UNIT.
```
and then issue the security erase:
```bash
$ sudo hdparm --user-master u --security-erase PasSWorD /dev/sda
security_password: "PasSWorD"

/dev/sda:
 Issuing SECURITY_ERASE command, password="PasSWorD", user=user
```
now plug in your disk in original sata cable and re-mirror data.
## Create partition(s)
Create all needed partitions, on my case two, one for /boot and one for LUKS
```bash
$ sudo fdisk /dev/sda

Welcome to fdisk (util-linux 2.34).
Changes will remain in memory only, until you decide to write them.
Be careful before using the write command.

Device does not contain a recognized partition table.
Created a new DOS disklabel with disk identifier 0x581a1eef.

Command (m for help): n
Partition type
   p   primary (0 primary, 0 extended, 4 free)
   e   extended (container for logical partitions)
Select (default p): p
Partition number (1-4, default 1): 1
First sector (2048-468862127, default 2048):
Last sector, +/-sectors or +/-size{K,M,G,T,P} (2048-468862127, default 468862127): 1640447

Created a new partition 1 of type 'Linux' and of size 800 MiB.

Command (m for help): t
Selected partition 1
Hex code (type L to list all codes): fd
Changed type of partition 'Linux' to 'Linux raid autodetect'.

Command (m for help): n
Partition type
   p   primary (1 primary, 0 extended, 3 free)
   e   extended (container for logical partitions)
Select (default p): p
Partition number (2-4, default 2):
First sector (1640448-468862127, default 1640448):
Last sector, +/-sectors or +/-size{K,M,G,T,P} (1640448-468862127, default 468862127):

Created a new partition 2 of type 'Linux' and of size 222.8 GiB.

Command (m for help): t
Partition number (1,2, default 2): 2
Hex code (type L to list all codes): fd

Changed type of partition 'Linux' to 'Linux raid autodetect'.

Command (m for help): p
Disk /dev/sda: 223.58 GiB, 240057409536 bytes, 468862128 sectors
Disk model: KINGSTON SV300S3
Units: sectors of 1 * 512 = 512 bytes
Sector size (logical/physical): 512 bytes / 512 bytes
I/O size (minimum/optimal): 512 bytes / 512 bytes
Disklabel type: dos
Disk identifier: 0x581a1eef

Device     Boot   Start       End   Sectors   Size Id Type
/dev/sda1          2048   1640447   1638400   800M fd Linux raid autodetect
/dev/sda2       1640448 468862127 467221680 222.8G fd Linux raid autodetect

Command (m for help): w
The partition table has been altered.
Calling ioctl() to re-read partition table.
Syncing disks.
```
## Re-mirror data
Finally, we can re-add partitions to mirror devices
```bash
$ sudo mdadm --manage /dev/md126 --add /dev/sda1
mdadm: added /dev/sda1
$ sudo mdadm --manage /dev/md127 --add /dev/sda2
mdadm: added /dev/sda2
$ cat /proc/mdstat
Personalities : [linear] [raid0] [raid1] [raid10] [raid6] [raid5] [raid4]
md125 : active raid10 sdf1[3] sde1[2] sdc1[0] sdd1[1]
      1953258496 blocks super 1.2 512K chunks 2 near-copies [4/4] [UUUU]
      bitmap: 0/15 pages [0KB], 65536KB chunk

md126 : active raid1 sda1[2] sdb1[1]
      818176 blocks super 1.2 [2/2] [UU]

md127 : active raid1 sda2[2] sdb2[1]
      233478720 blocks super 1.2 [2/1] [_U]
      [>....................]  recovery =  0.1% (369408/233478720) finish=21.0min speed=184704K/sec
      bitmap: 2/2 pages [8KB], 65536KB chunk

unused devices: <none>
```
and wait until all mirrors were synced.
```bash
$ cat /proc/mdstat 
Personalities : [linear] [raid0] [raid1] [raid10] [raid6] [raid5] [raid4] 
md125 : active raid10 sdf1[3] sde1[2] sdc1[0] sdd1[1]
      1953258496 blocks super 1.2 512K chunks 2 near-copies [4/4] [UUUU]
      bitmap: 0/15 pages [0KB], 65536KB chunk

md126 : active raid1 sda1[2] sdb1[1]
      818176 blocks super 1.2 [2/2] [UU]
      
md127 : active raid1 sda2[2] sdb2[1]
      233478720 blocks super 1.2 [2/2] [UU]
      bitmap: 1/2 pages [4KB], 65536KB chunk

unused devices: <none>
```
