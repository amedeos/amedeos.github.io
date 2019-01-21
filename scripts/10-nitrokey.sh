#!/usr/bin/env bash
#
source /etc/genkernel.conf
rm -rf ${INITRAMFS_OVERLAY}
mkdir -p ${INITRAMFS_OVERLAY}/{usr/lib64,usr/bin,lib64,bin,etc/initrd.d}
NITROLUKS="https://github.com/artosan/nitroluks"
CRYPT_PATCH="https://raw.githubusercontent.com/amedeos/amedeos.github.io/master/scripts/00-crypt.sh.patch"
GENKERNEL_DIR="/usr/share/genkernel/defaults/initrd.d"
CRYPT_FILE="00-crypt.sh"
GIT_BIN=`which git`
GPLUS_BIN=`which g++`
CURL_BIN=`which curl`
#TODO: insert return codes and check them after every commands

# copy libnitrokey
cp /usr/lib64/libnitrokey.so* ${INITRAMFS_OVERLAY}/usr/lib64/
# copy libhidapi-libusb and libusb
cp /usr/lib64/libhidapi-libusb.so.0* ${INITRAMFS_OVERLAY}/usr/lib64/
cp /lib64/libusb-1.0.so.0* ${INITRAMFS_OVERLAY}/lib64/

NITROBUILD=$(mktemp -t -d nitrobuild.XXXXX)
${GIT_BIN} clone ${NITROLUKS} ${NITROBUILD}
mkdir -p ${NITROBUILD}/build
${GPLUS_BIN} ${NITROBUILD}/src/nitro_luks.c -o ${NITROBUILD}/build/nitro_luks -L${NITROBUILD}/build/ -l:libnitrokey.so.3 -Wall
cp ${NITROBUILD}/build/nitro_luks ${INITRAMFS_OVERLAY}/bin/
${CURL_BIN} --output ${NITROBUILD}/00-crypt.sh.patch ${CRYPT_PATCH}
cp ${GENKERNEL_DIR}/${CRYPT_FILE} ${NITROBUILD}/${CRYPT_FILE}
patch ${NITROBUILD}/${CRYPT_FILE} ${NITROBUILD}/00-crypt.sh.patch
cp ${NITROBUILD}/${CRYPT_FILE} ${INITRAMFS_OVERLAY}/etc/initrd.d/${CRYPT_FILE}
rm -rf ${NITROBUILD}
# we need to raise this file in the future, otherwise genkernel will overwrite it in initramfs
TZ=ZZZ0 touch -t "$(TZ=ZZZ-1:30 date +%Y%m%d%H%M.%S)" ${INITRAMFS_OVERLAY}/etc/initrd.d/${CRYPT_FILE}
