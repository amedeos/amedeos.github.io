---
layout: post
title:  "Integrate your Linux Access Point hostapd with the power of Pi-hole"
date:   2020-05-21 10:10:00 +0100
toc: true
categories: [hostapd]
tags: [gentoo,hostapd,pihole]
---
## Introduction
I'll assume that you just have installed and configured [hostapd](http://w1.fi), if not, have a look at my previous post [Configure Linux as an access point with hostapd, and tunnel traffic to (NordVPN) OpenVPN server](https://amedeos.github.io/hostapd/2020/05/10/gentoo-as-wifi-access-point.html).
Now I'll only show you how to add the power of [Pi-hole](https://pi-hole.net/) to protect your devices from unwanted content, without installing any client-side software.

## Install Docker
To run Pi-hole we need a Docker service to be up and running, if you're a [Gentoo](https://gentoo.org/) user like me, you can follow the official wiki for [Docker](https://wiki.gentoo.org/wiki/Docker), otherwise you can find tons of documentation to install and configure Docker for your favorite distro.

## Enable Docker service at boot
We'll start the docker service just some seconds after the hostapd and dnsmasq services:

```bash
# cd /etc/systemd/system
# mkdir docker.service.d
# touch docker.service.d/00hostapd.conf
```
put this content in /etc/systemd/system/docker.service.d/00hostapd.conf file:

```bash
# cat /etc/systemd/system/docker.service.d/00hostapd.conf 
[Unit]
After=network-online.target docker.socket firewalld.service dnsmasq-wifi.service dnsmasq-wifiguests.service
```

create the systemd timer [/etc/systemd/system/docker.timer](https://github.com/amedeos/amedeos.github.io/blob/master/files/hostapd/docker.timer) with the following content:

```bash
# cat /etc/systemd/system/docker.timer 
[Unit]
Description=Run docker 3.5 minutes after the boot

[Timer]
OnBootSec=210seconds

[Install]
WantedBy=timers.target
```

enable the timer and start the service:

```bash
# systemctl enable docker.timer
# systemctl start docker.service
```

## Pull Pi-hole docker image
This guide is based on the latest, at the time of this writing, Pi-hole docker image, which is v5.0, but if you want to use another docker image simply check availability by curl:

```bash
curl -s https://registry.hub.docker.com/v1/repositories/pihole/pihole/tags | python -m json.tool | egrep '\"name\": \"v[0-9]'
        "name": "v4.0_aarch64"
        "name": "v4.0_amd64"
        "name": "v4.0_armhf"
        "name": "v4.2_rc1"
        "name": "v4.2_rc1_aarch64"
        "name": "v4.2_rc1_amd64"
        "name": "v4.2_rc1_armhf"
        "name": "v4.2_rc2"
        "name": "v4.2_rc2_aarch64"
        "name": "v4.2_rc2_amd64"
        "name": "v4.2_rc2_armhf"
        "name": "v4.4"
        "name": "v4.4-amd64"
        "name": "v4.4-arm64"
        "name": "v4.4-armel"
        "name": "v4.4-armhf"
        "name": "v5.0"
        "name": "v5.0-amd64"
        "name": "v5.0-arm64"
        "name": "v5.0-armhf"
```

pull your desired version or the latest:

```bash
$ docker pull pihole/pihole:v5.0
$ docker pull pihole/pihole:latest
```

## Create a user docker bridge network
In order to start the container with a pre-defined IP and network, you'll have to create a new docker network:

```bash
$ docker network create --subnet 172.20.0.0/16 piholenet
```

docker may have created a new bridge network with the given subnet 172.20.0.0/16, check if is present and note it's bridge name which will be used later on:

```bash
$ ip a
...
6: br-d14f54fa58e0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default
    link/ether 02:42:61:43:0d:e1 brd ff:ff:ff:ff:ff:ff
    inet 172.20.0.1/16 brd 172.20.255.255 scope global br-d14f54fa58e0
       valid_lft forever preferred_lft forever
    inet6 fe80::42:61ff:fe43:de1/64 scope link
       valid_lft forever preferred_lft forever
...
```

in my case the bridge interface name is **br-d14f54fa58e0**

### Optional - Integrate your wifiguests routing table with Docker network
For whom of you as followed my previous post configurations for hostapd [Configure Linux as an access point with hostapd, and tunnel traffic to (NordVPN) OpenVPN server](https://amedeos.github.io/hostapd/2020/05/10/gentoo-as-wifi-access-point.html) you'll need to add this new bridge interface to your **wifiguests** routing table:

```bash
# ip route add 172.20.0.0/16 dev br-d14f54fa58e0 table wifiguests
```

replace **br-d14f54fa58e0** with your bridge interface name.

## Create Docker container
Now we can create a new Pi-hole container **pihole-v5.0** with a fixed IP **172.20.0.10** which will be used in dnsmasq dhcp option, and in iptables filter

```bash
$ docker run -d --name pihole-v5.0 --network piholenet --ip 172.20.0.10 -p 172.20.0.1:53:53/tcp -p 172.20.0.1:53:53/udp -p 172.20.0.1:80:80 -p 172.20.0.1:443:443 -e TZ="Europe/Rome" -v "${HOME}/pihole/etc-pihole/:/etc/pihole/" -v "${HOME}/pihole/etc-dnsmasq.d/:/etc/dnsmasq.d/" --dns=127.0.0.1 --dns=1.1.1.1 --restart=unless-stopped --hostname pi.hole -e VIRTUAL_HOST="pi.hole" -e PROXY_LOCATION="pi.hole" -e ServerIP="127.0.0.1" pihole/pihole:v5.0
```

or in a multiline command:

```bash
$ docker run -d --name pihole-v5.0 \
    --network piholenet --ip 172.20.0.10 \
    -p 172.20.0.1:53:53/tcp -p 172.20.0.1:53:53/udp \
    -p 172.20.0.1:80:80 -p 172.20.0.1:443:443 \
    -e TZ="Europe/Rome" \
    -v "${HOME}/pihole/etc-pihole/:/etc/pihole/" \
    -v "${HOME}/pihole/etc-dnsmasq.d/:/etc/dnsmasq.d/" \
    --dns=127.0.0.1 --dns=1.1.1.1 --restart=unless-stopped \
    --hostname pi.hole -e VIRTUAL_HOST="pi.hole" \
    -e PROXY_LOCATION="pi.hole" -e ServerIP="127.0.0.1" pihole/pihole:v5.0
```

after the first docker run keep note of the admin Pi-hole **password**:

```bash
$ docker logs pihole-v5.0 | grep password
+ pihole -a -p sM2a39K8 sM2a39K8
Assigning random password: sM2a39K8
Setting password: sM2a39K8
  [✓] New password set
```

in the above example the login password is **sM2a39K8**

## Configure dnsmasq dhcp server
With Pi-hole running, and routing table able to reach it from wifiguests, you should pass, via **dhcp option 6**, a new DNS server 172.20.0.10 (Pi-hole container):

```bash
# cat /etc/dnsmasq-wifi.conf 
strict-order
interface=wlp4s0f3u2
except-interface=lo
listen-address=192.168.79.1
bind-dynamic
dhcp-range=192.168.79.50,192.168.79.150,255.255.255.0,12h
dhcp-leasefile=/var/lib/misc/dnsmasq-wlp4s0f3u2.leases
dhcp-option=6,172.20.0.10
log-dhcp
#
# systemctl restart dnsmasq-wifi.service
```

also for guests:

```bash
# cat /etc/dnsmasq-wifiguests.conf 
strict-order
interface=wlp2s0
except-interface=lo
listen-address=192.168.69.1
bind-dynamic
dhcp-range=192.168.69.50,192.168.69.150,255.255.255.0,12h
dhcp-leasefile=/var/lib/misc/dnsmasq-wlp2s0.leases
dhcp-option=6,172.20.0.10
log-dhcp
#
# systemctl restart dnsmasq-wifiguests.service
```

## Filter all external DNS servers
If your client can reach your Pi-hole container at 172.168.20.10, you can disable all connections to other DNS servers using previously created **iptables chain wifi-filter-clients**:

```bash
# iptables -A wifi-filter-clients ! -d 172.20.0.10/32 -p tcp -m multiport --dports 53 -j REJECT
# iptables -A wifi-filter-clients ! -d 172.20.0.10/32 -p udp -m multiport --dports 53 -j REJECT
# iptables-save > /var/lib/iptables/rules-save
```

and also for your guests with the **iptables chain wifi-filter-guests**:

```bash
# iptables -A wifi-filter-guests ! -d 172.20.0.10/32 -p tcp -m multiport --dports 53 -j REJECT
# iptables -A wifi-filter-guests ! -d 172.20.0.10/32 -p udp -m multiport --dports 53 -j REJECT
#
# iptables -A wifi-filter-guests -d 172.20.0.10/32 -p tcp -m multiport --dports 80,443 -j REJECT
# iptables-save > /var/lib/iptables/rules-save
```

## Modify systemd update-nordvpn.service service
You should add your new bridge interface into the update-nordvpn.service, in order to route traffic from guests to the docker container, simply add a new **"ExecStart=-/bin/ip route add 172.20.0.0/16 dev br-d14f54fa58e0 table wifiguests"**:

```bash
# cat update-nordvpn.service 
[Unit]
Description=Update nordvpn DB and configure with the desired country

[Service]
Type=oneshot
#ExecStart=/usr/sbin/update-nordvpn.sh "United States"
ExecStart=-/bin/ip route add 192.168.79.0/24 dev wlp4s0f3u2 table wifiguests
ExecStart=-/bin/ip route add 192.168.69.0/24 dev wlp2s0 table wifiguests
ExecStart=-/bin/ip route add 172.20.0.0/16 dev br-d14f54fa58e0 table wifiguests
ExecStart=/usr/sbin/update-nordvpn.sh Italy
#
# systemctl daemon-reload
```

## Conclusion
Now you can configure your Pi-hole blackhole for your entire network, with ensuring your clients to use it. Remember to disable Firefox DNS Over Https (DOH) if you want to filter ads on it.
