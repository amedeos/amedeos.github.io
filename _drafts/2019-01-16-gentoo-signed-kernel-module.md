---
layout: post
title:  "Configure Gentoo with Signed Kernel module"
date:   2019-01-16 21:15:00 +0100
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
## Build 
```sh
#!/usr/bin/env bash
#
KERNEL_SOURCE="/usr/src/linux"
CERT_DIR="certs"
FILES="signing_key.pem signing_key.x509 x509.genkey"
SHRED=`which shred`

for f in $FILES
do
        echo "Remove ${KERNEL_SOURCE}/${CERT_DIR}/${f}"
        $SHRED -f -u ${KERNEL_SOURCE}/${CERT_DIR}/${f}
done
```
