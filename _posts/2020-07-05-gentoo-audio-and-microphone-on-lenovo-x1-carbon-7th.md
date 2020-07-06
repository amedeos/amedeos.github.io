---
layout: post
title:  "Configure Gentoo audio and microphone on Lenovo X1 Carbon gen 7"
date:   2020-07-05 10:10:00 +0100
toc: true
categories: [hardware]
tags: [gentoo,hardware,lenovo]
---
## Introduction
Recently, my company gives me a new laptop, which is a [Lenovo Thinkpad X1 Carbon Gen 7](https://www.lenovo.com/us/en/laptops/thinkpad/thinkpad-x1/X1-Carbon-Gen-7/p/22TP2TXX17G), it went to me with an enterprise Linux distribution where seems that everything was working fine, but I instantly formatted the disk to install Gentoo, and after a couple of hours I was able to login to this new box where I installed the KDE plasma desktop environment.

All was in good shape and pace, but when I tried the audio and the microphone, the Linux audio fears of the nineties came back to me, I checked **alsa** in kernel config, pulseaudio in the userspace, but never changed; at one point I was able to have audio with the standard **snd-hda-intel**, and starting ducking on the web I found on the [Arch wiki](https://wiki.archlinux.org/index.php/Lenovo_ThinkPad_X1_Carbon_(Gen_7)) some useful information about the audio and the microphone, but there are a little differences in Gentoo.

## Configure alsa module
Configure your **snd** kernel module with the option **options snd slots=snd_soc_skl_hda_dsp** and blacklist the kernel modules **snd_hda_intel** and **snd_soc_skl**.

put those configuration in a new file **/etc/modprobe.d/alsa.conf** with the following content:

```conf
# Alsa kernel modules' configuration file.

# ALSA portion
alias char-major-116 snd
# OSS/Free portion
alias char-major-14 soundcore

##
## IMPORTANT:
## You need to customise this section for your specific sound card(s)
## and then run `update-modules' command.
## Read alsa-driver's INSTALL file in /usr/share/doc for more info.
##
##  ALSA portion
## alias snd-card-0 snd-interwave
## alias snd-card-1 snd-ens1371
##  OSS/Free portion
## alias sound-slot-0 snd-card-0
## alias sound-slot-1 snd-card-1
##

# OSS/Free portion - card #1
alias sound-service-0-0 snd-mixer-oss
alias sound-service-0-1 snd-seq-oss
alias sound-service-0-3 snd-pcm-oss
alias sound-service-0-8 snd-seq-oss
alias sound-service-0-12 snd-pcm-oss
##  OSS/Free portion - card #2
## alias sound-service-1-0 snd-mixer-oss
## alias sound-service-1-3 snd-pcm-oss
## alias sound-service-1-12 snd-pcm-oss

alias /dev/mixer snd-mixer-oss
alias /dev/dsp snd-pcm-oss
alias /dev/midi snd-seq-oss

# Set this to the correct number of cards.
options snd slots=snd_soc_skl_hda_dsp
blacklist snd_hda_intel
blacklist snd_soc_skl
```

## Update pulseaudio to a newer version
Unfortunately the default pulseaudio 13.0 doesn't work with this laptop, so I saw that on pg_**overlay** overlay there are an updatad 13.99.1 ebuild for pulseaudio, lets install that:

```bash
$ sudo layman -a pg_overlay
```

I usually mask all ebuilds from an overlay and unmask the packages who I'm looking for.

Mask all:

```bash
$ cat /etc/portage/package.mask/pg_overlay 
*/*::pg_overlay
```

Unmask pulseaudio:

```bash
$ cat /etc/portage/package.unmask/pulseaudio 
media-sound/pulseaudio::pg_overlay
```

and finally update pulseaudio:

```bash
$ sudo emerge --ask --verbose --update --deep --with-bdeps=y --newuse  @world
```

## Configure SOF firmware
After some debug I found that the package **sys-firmware/sof-firmware** has only the sof-icl-v1.4.2.ri but not (yet) the firmware **sof-hda-generic.tplg**, have a look at [https://bbs.archlinux.org/viewtopic.php?id=249900](https://bbs.archlinux.org/viewtopic.php?id=249900).

To resolve this I created a simple script to download the two firmware and put them in the correct path, create a file **run-sof.sh** with the following content:

```script
rm -rf /lib/firmware/intel/sof /lib/firmware/intel/sof-tplg sof-cnl-signed-intel.ri hda-topology.tar.gz
wget https://github.com/thesofproject/sof/releases/download/v1.3/sof-cnl-signed-intel.ri
mkdir /lib/firmware/intel/sof
cp sof-cnl-signed-intel.ri /lib/firmware/intel/sof/sof-cnl.ri

mkdir /lib/firmware/intel/sof-tplg

wget https://bugzilla.kernel.org/attachment.cgi?id=284395 -O hda-topology.tar.gz

tar xf hda-topology.tar.gz -C /lib/firmware/intel/sof-tplg

mv /lib/firmware/intel/sof-tplg/sof-hda-generic.tplg /lib/firmware/intel/sof-tplg/sof-hda-generic.tplg.original

ln -s /lib/firmware/intel/sof-tplg/sof-hda-generic-4ch.tplg /lib/firmware/intel/sof-tplg/sof-hda-generic.tpl
```

run with sudo permission:

```bash
$ sudo bash run-sof.sh
```

## Configure pulseaudio for Lenovo X1 Carbon Gen 7
Last, but not least, you'll need to configure pulseaudio with two additional configuration lines:

```conf
load-module module-alsa-sink device=hw:0,0 channels=4
load-module module-alsa-source device=hw:0,6 channels=4
```

put them at the end of the file **/etc/pulse/default.pa**.

## Reboot
Reboot your system and your audio and microphone now should work.
