#!/usr/bin/env bash
#
IP=$(which ip)
if [ -x "$(command -v macchanger)" ];then
    MACCHANGER=$(command -v macchanger)
fi
SLEEP=$(which sleep)
S_SLEEP=2
DEVGUESTS=wlp2s0
DEV=wlp4s0f3u2
TABLEGUESTS=wifiguests

# setup $DEVGUESTS
echo Setup device $DEVGUESTS
$IP link set $DEVGUESTS down
$IP addr flush dev $DEVGUESTS
if [ -x "$(command -v macchanger)" ];then
    $MACCHANGER -e $DEVGUESTS
fi
$SLEEP $S_SLEEP
$IP link set $DEVGUESTS up
$SLEEP $S_SLEEP
$IP addr add 192.168.69.1/24 dev $DEVGUESTS

# setup $DEV
echo Setup device $DEV
$IP link set $DEV down
$IP addr flush dev $DEV
if [ -x "$(command -v macchanger)" ];then
    $MACCHANGER -e $DEV
fi
$SLEEP $S_SLEEP
$IP link set $DEV up
$SLEEP $S_SLEEP
$IP addr add 192.168.79.1/24 dev $DEV

# flush table and rule $TABLEGUESTS
echo Flush table and rules in $TABLEGUESTS
$IP route flush table $TABLEGUESTS
$IP rule del from 192.168.79.0/24
$IP rule del from 192.168.69.0/24
$SLEEP $S_SLEEP

echo Setup table and rules $TABLEGUESTS
$IP rule add from 192.168.69.0/24 lookup $TABLEGUESTS
$IP rule add from 192.168.79.0/24 to 192.168.69.0/24 lookup $TABLEGUESTS
$IP route add default via 192.168.1.254 table $TABLEGUESTS
$SLEEP $S_SLEEP
$IP route add 192.168.79.0/24 dev $DEV table $TABLEGUESTS
$SLEEP $S_SLEEP
$IP route add 192.168.69.0/24 dev $DEVGUESTS table $TABLEGUESTS

