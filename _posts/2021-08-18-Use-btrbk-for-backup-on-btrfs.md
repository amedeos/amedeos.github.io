---
layout: post
title:  "Use btrbk for remote backup solution with btrfs"
date:   2021-08-18 09:00:00 +0100
toc: true
categories: [backup]
tags: [backup,btrfs,btrbk]
---
## Introduction
In this "simple" post I'll show you how to configure [btrbk](https://digint.ch/btrbk/) to send to a remote Linux box your subvolume, in order to backup your data, also I'll show you how to limit permissions to btrbk using __sudo__ and __ssh_filter_btrbk.sh__ script file.

btrbk program uses the btrfs send / receive feature, but it simplifies the management of subvolumes and the ability to send from your source box and receive in your target box the subvolumes over ssh.

## Requirements
You will need:

* Your source Linux box must use btrfs subvolume, in this post I'll use the __@home__ subvolume to backup / send to the remote box, but you could adapt to your needs and use another btrfs subvolume
* Your destination Linux box must have one __btrfs device / file system__;
* Ability to __install btrbk__ on your preferred Linux distro, on both source and destination Linux boxes;
* Ability to create a __dedicated user__ for backup, on both source and destination Linux boxes, in this post I'll use __backupuser__;
* Ability to configure __sudo permissions__ on both source and destination Linux boxes.

## Install btrbk
Install btrbk on both source and destination hosts, using the package manager of your preferred distro; regarding the destination host we'll use only the provided script __ssh_filter_btrbk.sh__, for this reason we'll install also on destination host the btrbk program.

On Gentoo:

```bash
# emerge --ask app-backup/btrbk
```

On Fedora:

```bash
# dnf install btrbk
```

After the installation identifies where your distro install the __ssh_filter_btrbk.sh__ script, on Gentoo and Fedora, this script is located on __/usr/share/btrbk/scripts/ssh_filter_btrbk.sh__

## Configure your source box to backup
### Mount btrfs volume
Mount your primary btrfs volume under the directory __/mnt/btrbk_pool__, doing this you'll be able to backup all subvolumes

Create the directory:

```bash
# mkdir -p /mnt/btrbk_pool
```

Identify your btrfs UUID, in my case is a000eea9-d97c-4107-ae39-602049a6acaa:

```bash
# blkid | egrep 'TYPE=\"btrfs\"' | sed -E 's/.+\s+UUID=\"([0-9a-z\-]+)\"\s+.+/\1/g'
a000eea9-d97c-4107-ae39-602049a6acaa
```

Now edit your __/etc/fstab__ in order to mount your btrfs volume under __/mnt/btrbk_pool__:

```bash
# vi /etc/fstab
# grep btrbk_pool /etc/fstab
UUID=a000eea9-d97c-4107-ae39-602049a6acaa       /mnt/btrbk_pool                 btrfs           noatime,relatime,compress=no,ssd,space_cache,discard=async                      0 0
```

__NOTE 1:__ remove __ssd__ option if you're using rotational disks

__NOTE 2:__ remove __discard=async__ if your're using Kernel < 5.6

Mount the volume and check if the subvolume __@home__ is present:

```bash
# mount -a
# btrfs subvolume list /mnt/btrbk_pool | egrep -E '\@home$'
ID 257 gen 84832 top level 5 path @home
```

### Create backupuser
Now you can create on your source box the new user __backupuser__:

```bash
# useradd backupuser
```

Add sudo permission for backupser creating a new file /etc/sudoers.d/backupuser:

```bash
# cat /etc/sudoers.d/backupuser 
%backupuser ALL=(ALL) NOPASSWD: /sbin/btrfs, /bin/readlink, /usr/bin/readlink
```

### Create ssh Key
Create a new ssh key, which will be trusted on the destination box:

```bash
# mkdir /etc/btrbk/ssh
# chown backupuser. /etc/btrbk/ssh/
# chmod 0700 /etc/btrbk/ssh
# su - backupuser
backupuser@sourcebox ~ $ ssh-keygen -t rsa -b 4096 -f /etc/btrbk/ssh/id_rsa -C backuser@$(hostname) -N ""
```

### Configure /etc/btrbk/btrbk.conf
In this example, I'll backup and send to the remote Linux box only the __@home__ subvolume, but you can adapt it based on your needs.

```bash
# cat /etc/btrbk/btrbk.conf
timestamp_format        long
ssh_identity /etc/btrbk/ssh/id_rsa
ssh_user backupuser

backend_remote btrfs-progs-sudo
backend btrfs-progs-sudo

snapshot_preserve_min   2d
snapshot_preserve      14d

target_preserve_min    no
target_preserve        20d 10w *m

volume /mnt/btrbk_pool
  subvolume @home
    target ssh://<FQDN>/ssddata/backup/lapdog
```

Change the FQDN with your target box IP or FQDN

## Configure your target box to receive backup
Now we can configure the target box in order to receive the btrfs subvolume coming from our source box.
### Create a new @backup subvolume
Identify your btrfs volume and create a new __@backup__ subvolume, personally I've been using a luks device named __"ssddata"__, but you could use for example an hdd disk(s) /dev/sdX1.

Create a new subvolume:

```bash
# mount /dev/mapper/ssddata /mnt/ssddata
# cd /mnt/ssddata
# btrfs subvolume create @backup
```

update your __/etc/fstab__ with the entry for subvolume __@backup__ mounting it under __/ssddata/backup__

```bash
# mkdir -p /ssddata/backup
# vi /etc/fstab
# grep backup /etc/fstab
UUID=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee       /ssddata/backup         btrfs   noatime,relatime,compress=lzo,ssd,space_cache,discard=async,subvol=@backup      0 0
```

mount the subvolume:

```bash
# mount -a
```

and create the __lapdog__ directory (if you want to change the name, remember to change it also on btrbk.conf on source box):

```bash
# mkdir -p /ssddata/backup/lapdog
```

### Create backupuser
Now you can create on your target box the new user __backupuser__ (same as we have done on source box :smile: ):

```bash
# useradd backupuser
```

Add sudo permission for backupser creating a new file /etc/sudoers.d/backupuser:

```bash
# cat /etc/sudoers.d/backupuser 
%backupuser ALL=(ALL) NOPASSWD: /sbin/btrfs, /bin/readlink, /usr/bin/readlink
```

### Trust ssh key
Copy the content of the ssh pub file from your source box:

```bash
# cat /etc/btrbk/ssh/id_rsa.pub
```

Put the content of the file __/etc/btrbk/ssh/id_rsa.pub__ in your clipboard and then go to your target box and run:

```bash
# su - backupuser
$ mkdir -p ~/.ssh
$ chmod 0700 ~/.ssh
```

and the edit the file __vim ~/.ssh/authorized_keys__ of the backupuser adding first the _command="/usr/share/btrbk/scripts/ssh_filter_btrbk.sh -l --sudo --target --delete --info"_ and then, on the same line with only a space dividing them, the content of id_rsa.pub coming from your source box; 

below an example of the ~/.ssh/authorized_keys file:

```bash
$ cat /home/backupuser/.ssh/authorized_keys
command="/usr/share/btrbk/scripts/ssh_filter_btrbk.sh -l --sudo --target --delete --info" ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQDwRPIBZMgomFVfXOyOwYm+CuSdWfWR7tMIh+aJgWGv1pK8zuTiZtoaCSnobrRVJNkWWNIeL672o9zgn8y5N2nb64pWxDCcJWFKHuxCZk3ZN1i70JPTZ25sUZ0YUQ8YCd4YtLIujPdIdCMNTESrB0QYe0CCyD6HnX2DRR36G3EVRbNmBpzeLLthIoZLzRpGXFeHMLIz3W9v5VrIwDYZGWdUptyqbh9YQd7x9+lqmaCSlAzRttMVk6HiH8hUuJLgseNtvamqqsEQcZGk3j4v3EbYR+oCQqb4njcxQ3YbPuKtc88PREIezNt/rcoo4m720nXOeKZCad5Ob0/gd9CnBPY3xo8Po1UZdOSrvUxr46moAhMMBVy8c9LO32AlJ7oKjgt2UFelOdWlx69vCZ7TezYRCSj5DS2ZtlYe4KN1pRfLwe1h+h/tt4QVMmKpbl771VKaTzb1xM3TwR8SSXRqct/NeXGWNm7CPrsPx1qK6NFsqx0KH/Wc93uIqbucC5fUhd7rc5yYX43yO3vDon+Omlc9OIAmfxtssTK8/XU7C9fQDMACgwcFxh7JixdPzqlVvJxNiJiSjpWSkixXubBRwgWlTf/L7hZppFcnS0j+ZtgsTiBofm5QiMHskQIUoZ0WmdyuzwJQVQMBV58rZdB7goxvLaW63SM/b6FVk5c0m9dV4w== backuser@lapdog
```

## Run your first backup and send it via ssh to target box
Now you can run the first backup using btrbk and it will automagically send the btrfs subvolumes through ssh to the target box:

From your source box switch to backupuser and run it:

```bash
# su - backupuser
$ btrbk -c /etc/btrbk/btrbk.conf -v run
```

after it ends, you can run the __list all__ command in order to see all backups:

```bash
# su - backupuser
$ btrbk -c /etc/btrbk/btrbk.conf -n list all
```

