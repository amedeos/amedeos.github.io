---
layout: post
title:  "Configure Gentoo with Signed Kernel module"
date:   2019-01-17 21:15:00 +0100
categories: [gentoo]
tags: [gentoo]
---
## Introduction
This work is wased on [Gentoo wiki](https://wiki.gentoo.org/wiki/Signed_kernel_module_support), but for better security I prefer at the end of Kernel installation to delete the auto generated key.
## Configuring module signature verification
Enable Module signature verification, Require modules to be validly signed and Automatically sign all modules; and last make sure to disable Compress modules on installation (otherwise initramfs can't load compressed modules)
```kernel
--- Enable loadable module support
[*]   Module signature verification
[*]     Require modules to be validly signed
[*]     Automatically sign all modules
      Which hash algorithm should modules be signed with? (Sign modules with SHA-512)  --->
[ ]   Compress modules on installation
```
## Configure genkernel to delete the key
Create the postgen.d directory
```bash
# mkdir -p /etc/kernels/postgen.d
```
then, inside the postgen.d directory create the file 10-remove-certs.sh
```bash
# cd /etc/kernels/postgen.d/
# touch 10-remove-certs.sh
# chmod 0754 10-remove-certs.sh
```
now open the file 10-remove-certs.sh with your preferred editor and put this content
```sh
#!/usr/bin/env bash
#
KERNEL_SOURCE="/usr/src/linux"
CERT_DIR="certs"
FILES="signing_key.pem signing_key.x509 x509.genkey"
SHRED=`which shred`

for f in $FILES
do
    if [ -f ${KERNEL_SOURCE}/${CERT_DIR}/${f} ]; then
            echo "Remove ${KERNEL_SOURCE}/${CERT_DIR}/${f}"
            $SHRED -f -u ${KERNEL_SOURCE}/${CERT_DIR}/${f}
    fi
done
```
## Building the kernel
Now we can run genkernel to build the new kernel
```bash
# genkernel --luks --lvm all
```
## Configure grub and reboot
Finally, we can configure grub to use the new installed kernel and then reboot
```bash
# grub-mkconfig -o /boot/grub/grub.cfg
# shutdown -r now
```
