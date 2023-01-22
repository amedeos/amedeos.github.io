---
layout: post
title:  "Using eBPF on OpenShift nodes (the quick and dirty way)"
date:   2023-01-23 16:00:00 +0100
toc: true
categories: [OpenShift]
tags: [OpenShift,ebpf]
---
In this **OpenShift** article, I'll show you how to run [bcc](https://iovisor.github.io/bcc/) tools, [bpftrace](https://github.com/iovisor/bpftrace), and the kernel tool [bpftool](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/tools/bpf/bpftool).

**Warning:** If you are a Red Hat customer and you are in trouble, open a support case before going forward; otherwise, do the following steps at your own risk!

## Requirements
Before starting, you'll need:

- Working OpenShift 4.10+ cluster, I've only tested this procedure on 4.10, 4.11, and 4.12 OpenShift clusters, but it may work on all supported 4.x versions (please let me know);
- cluster-admin grant on the OpenShift cluster;
- one subscribed RHEL host with **podman** and **buildah** installed or installable; You could use a non-subscribed host, but to use baseos and appstream eus repositories, you'd need to temporarily subscribe to the ubi8 container.
- SSH enabled on your OpenShift node(s).

## Run must-gather
Before applying any change run an OpenShift must-gather:
```bash
$ oc adm must-gather
```

## A Special mention to OpenShift 4.12+
Starting with OpenShift 4.12, the bpftool is included package in a toolbox and can be used without following this procedure:
```bash
$ ssh core@worker
[core@worker-0 ~]$ sudo -i

[root@worker-0 ~]# toolbox 
Trying to pull registry.redhat.io/rhel8/support-tools:latest...
...
toolbox-root
Container started successfully. To exit, type 'exit'.
[root@worker-0 /]#

[root@worker-0 /]# bpftool -h
Usage: bpftool [OPTIONS] OBJECT { COMMAND | help }
       bpftool batch file FILE
       bpftool version

       OBJECT := { prog | map | link | cgroup | perf | net | feature | btf | gen | struct_ops | iter }
       OPTIONS := { {-j|--json} [{-p|--pretty}] | {-d|--debug} |
                    {-V|--version} }
[root@worker-0 /]#
```

but, if you want to run the bcc and bpftrace tools, you can continue to follow this guide.

## Build a bpf-ocp image for your OpenShift cluster
Before running eBPF on your OpenShift nodes, you need to build a tailored image for your cluster.

This image will include:

- kernel-core and kernel-headers for your OpenShift kernel version nodes;
- bpftrace, bcc, and bpftool packages;
- some other performance troubleshooting packages.

### Install tools on RHEL
You need one host, usually a RHEL host, where you can build your new image with eBPF tools installed, in this example, I'll show you how to install those tools on RHEL host.

Install buildah and podman:
```bash
$ sudo dnf install buildah podman -y
```

### Retrieve OpenShift node information / version
Remember to log in to your cluster and then choose a name for one of your ready nodes:
```bash
$ OCPNODE=$(oc get node | egrep '\s+Ready\s+' | head -n1 | awk '{print $1}')
$ echo ${OCPNODE}
master-0
```

obtain the node kernel version:
```bash
$ KERNELVERSION=$(oc debug node/${OCPNODE} -- chroot /host uname -r 2> /dev/null )
$ echo ${KERNELVERSION} 
4.18.0-372.26.1.el8_6.x86_64
```

obtain the node RHEL minor version:
```bash
$ RHEL8MINOR=$(oc debug node/${OCPNODE} -- chroot /host sh -c "uname -r | sed -E 's/.+\.el8_([0-9])\..*/\1/g'" 2> /dev/null )
$ echo ${RHEL8MINOR} 
6
```

### Create Dockerfile
Create a Dockerfile for your image:
```bash
$ mkdir buildbpf
$ cd buildbpf

$ tee "Dockerfile" > /dev/null <<'EOF'
# Start from ubi8 with minor version RHEL8MINOR
FROM registry.access.redhat.com/ubi8:8.RHEL8MINOR
# Install some useful tools
RUN dnf install --disablerepo='*' --enablerepo=rhel-8-for-x86_64-baseos-eus-rpms --enablerepo=rhel-8-for-x86_64-appstream-eus-rpms --releasever=8.RHEL8MINOR \
        redhat-lsb-core curl wget tcpdump vim iproute \
        bind-utils sysstat procps-ng -y
# Install OCP node version of kernel-core and kernel-headers      
RUN dnf install --disablerepo='*' --enablerepo=rhel-8-for-x86_64-baseos-eus-rpms --enablerepo=rhel-8-for-x86_64-appstream-eus-rpms --releasever=8.RHEL8MINOR \
        kernel-core-KERNELVERSION kernel-headers-KERNELVERSION -y
# Install bpftrace and bpftool, and their dependencies (bcc, python-bcc)
RUN dnf install --disablerepo='*' --enablerepo=rhel-8-for-x86_64-baseos-eus-rpms --enablerepo=rhel-8-for-x86_64-appstream-eus-rpms --releasever=8.RHEL8MINOR \
        bpftrace bpftool -y
# Clean dnf cache
RUN dnf clean all
EOF
```

replace the RHEL 8 minor version and kernel version with your cluster versions:
```bash
$ sed -i "s/RHEL8MINOR/${RHEL8MINOR}/g" Dockerfile
$ sed -i "s/KERNELVERSION/${KERNELVERSION}/g" Dockerfile
```

review the content:
```bash
$ cat Dockerfile 
# Start from ubi8 with minor version 6
FROM registry.access.redhat.com/ubi8:8.6
# Install some useful tools
RUN dnf install --disablerepo='*' --enablerepo=rhel-8-for-x86_64-baseos-eus-rpms --enablerepo=rhel-8-for-x86_64-appstream-eus-rpms --releasever=8.6 \
        redhat-lsb-core curl wget tcpdump vim iproute \
        bind-utils sysstat procps-ng -y
# Install OCP node version of kernel-core and kernel-headers      
RUN dnf install --disablerepo='*' --enablerepo=rhel-8-for-x86_64-baseos-eus-rpms --enablerepo=rhel-8-for-x86_64-appstream-eus-rpms --releasever=8.6 \
        kernel-core-4.18.0-372.26.1.el8_6.x86_64 kernel-headers-4.18.0-372.26.1.el8_6.x86_64 -y
# Install bpftrace and bpftool, and their dependencies (bcc, python-bcc)
RUN dnf install --disablerepo='*' --enablerepo=rhel-8-for-x86_64-baseos-eus-rpms --enablerepo=rhel-8-for-x86_64-appstream-eus-rpms --releasever=8.6 \
        bpftrace bpftool -y
# Clean dnf cache
RUN dnf clean all

```

**WARNING**: the above content is an example! Your Dockerfile could have different versions!!!

### Build the bpf-ocp image
Run buildah:
```bash
$ export BUILDAH_FORMAT=docker

$ buildah bud -t bpf-ocp:8.${RHEL8MINOR}-${KERNELVERSION}
...
COMMIT bpf-ocp:8.6-4.18.0-372.26.1.el8_6.x86_64
Getting image source signatures
Copying blob b4e347eee7c8 skipped: already exists  
Copying blob 724516754461 done  
Copying config 594a7e339c done  
Writing manifest to image destination
Storing signatures
--> 594a7e339cb
Successfully tagged localhost/bpf-ocp:8.6-4.18.0-372.26.1.el8_6.x86_64
594a7e339cb7ee321ad126c776012b29f4c5da2c8d302331906260d67e394ea2
$
```

### Special case for NOT RHEL subscribed buildah host
**WARNING:** Run these commands only if buildah bud has failed!!!

if your host is not a subscribed RHEL, you can run the following commands:
```bash
$ rm Dockerfile
$ buildah from registry.access.redhat.com/ubi8:8.${RHEL8MINOR}
ubi8-working-container
```

subscribe your container:
```bash
$ buildah run ubi8-working-container  subscription-manager register
Registering to: subscription.rhsm.redhat.com:443/subscription
Username: <YOUR RH ACCOUNT>
Password: <YOUR RH PASSWORD>
The system has been registered with ID: 86326611-9b37-4888-b6bb-850007165594
The registered system name is: 84ff9ac8faa2
```

navigate to the [Red Hat Customer Portal](https://access.redhat.com/management/), click on **Systems**, then click on your container hostname (in my case, 84ff9ac8faa2), select **Subscriptions**, click on the **Attach Subscriptions** button, Select the subscription you want in the left check box, then click **Attach Subscriptions**.

go back to the terminal and run:
```bash
$ buildah run ubi8-working-container  subscription-manager repos --list | tee -a /tmp/repos.txt

$ buildah run ubi8-working-container dnf install \
        --disablerepo='*' --enablerepo=rhel-8-for-x86_64-baseos-eus-rpms \
        --enablerepo=rhel-8-for-x86_64-appstream-eus-rpms --releasever=8.${RHEL8MINOR} \
        redhat-lsb-core curl wget tcpdump vim iproute \
        bind-utils sysstat procps-ng -y

$ buildah run ubi8-working-container dnf install --disablerepo='*' \
        --enablerepo=rhel-8-for-x86_64-baseos-eus-rpms \
        --enablerepo=rhel-8-for-x86_64-appstream-eus-rpms --releasever=8.${RHEL8MINOR} \
        kernel-core-${KERNELVERSION} kernel-headers-${KERNELVERSION} -y

$ buildah run ubi8-working-container dnf install --disablerepo='*' \
        --enablerepo=rhel-8-for-x86_64-baseos-eus-rpms \
        --enablerepo=rhel-8-for-x86_64-appstream-eus-rpms --releasever=8.${RHEL8MINOR} \
        bpftrace bpftool -y

$ buildah run ubi8-working-container dnf clean all

$ buildah run ubi8-working-container subscription-manager unregister

$ buildah run ubi8-working-container subscription-manager clean
```

execute buildah commit:
```bash
$ buildah commit ubi8-working-container bpf-ocp:8.${RHEL8MINOR}-${KERNELVERSION}
```

remove the buildah image:
```bash
$ buildah rm ubi8-working-container
```

check image:
```bash
$ podman image ls | egrep '^REPOSI|bpf-ocp'
REPOSITORY                                                               TAG                               IMAGE ID      CREATED             SIZE
localhost/bpf-ocp                                                        8.6-4.18.0-372.26.1.el8_6.x86_64  30712fe599dd  About a minute ago  1.54 GB
```

### Save the image as a tar file
Save the just created bpf-ocp image as a tar file:
```bash
$ podman save --quiet --format docker-archive \
    -o bpf-ocp-8.${RHEL8MINOR}-${KERNELVERSION}.tar \
    localhost/bpf-ocp:8.${RHEL8MINOR}-${KERNELVERSION}
```

### Transfer bpf-ocp image to desired OpenShift node
In this example, I want to run bpf tools on the __worker-1__ node, but change this to your real OpenShift node.

First, obtain the IP address of the node:
```bash
$ IPNODE=$(oc get node -owide | grep worker-1 | awk '{print $6}')
$ echo ${IPNODE} 
192.168.203.57
```

transfer image using scp:
```bash
$ scp bpf-ocp-8.${RHEL8MINOR}-${KERNELVERSION}.tar \
      core@${IPNODE}:/tmp/bpf-ocp-8.${RHEL8MINOR}-${KERNELVERSION}.tar
bpf-ocp-8.6-4.18.0-372.26.1.el8_6.x86_64.tar 100% 1464MB 109.9MB/s   00:13
```

### Load image from tar file
If you're running OpenShift 4.11+, you can simply run:
```bash
$ ssh core@${IPNODE}
[core@worker-1 ~]$ sudo -i
[root@worker-1 ~]# 

[root@worker-1 ~]# podman load --input /tmp/bpf-ocp-8.6-4.18.0-372.26.1.el8_6.x86_64.tar
Getting image source signatures
Copying blob 724516754461 done
Copying blob b4e347eee7c8 done
Copying config 594a7e339c done
Writing manifest to image destination
Storing signatures
Loaded image(s): localhost/bpf-ocp:8.6-4.18.0-372.26.1.el8_6.x86_64
[root@worker-1 ~]#
```

Instead, if you're trying to load image on OpenShift 4.10 with podman 3.x / CoreOS 8.4, you can get this error (loglevel debug):
```bash
[root@worker-1 ~]# podman load --log-level=debug -i /tmp/bpf-ocp-8.4-4.18.0-305.65.1.el8_4.x86_64.tar
...
DEBU[0001] Error loading /tmp/bpf-ocp-8.4-4.18.0-305.65.1.el8_4.x86_64.tar: Source image rejected: Running image docker-archive:/tmp/bpf-ocp-8.4-4.18.0-305.65.1.el8_4.x86_64.tar:localhost/bpf-ocp:8.4-4.18.0-305.65.1.el8_4.x86_64 is rejected by policy.
```

in this case, create a permissive policy file:
```bash
[root@worker-1 ~]# echo '{ "default": [{"type": "insecureAcceptAnything"}]}' > /tmp/policy-permissive.json
```

and use this permissive signature file in order to load the image:
```bash
[root@worker-1 ~]# podman load --signature-policy /tmp/policy-permissive.json -i /tmp/bpf-ocp-8.4-4.18.0-305.65.1.el8_4.x86_64.tar 
Getting image source signatures
Copying blob d46291327397 done  
Copying blob 5bc03dec6239 done  
Copying blob 525ed45dbdb1 done  
Copying config 17ae9469bd done  
Writing manifest to image destination
Storing signatures
Loaded image(s): localhost/bpf-ocp:8.4-4.18.0-305.65.1.el8_4.x86_64
```

### Run the bpf-ocp container
Finally, you can spin up a new bpf-ocp container:
```bash
[root@worker-1 ~]# podman run --privileged --name bpf-ocp \
    --mount type=bind,source=/sys/kernel/debug,target=/sys/kernel/debug \
    -it localhost/bpf-ocp:8.6-4.18.0-372.26.1.el8_6.x86_64 
[root@d18d4f16d28a /]#
```

and test a bcc tool biolatency in order to see if it is working properly (press Ctrl-C to end tracing):
```bash
[root@d18d4f16d28a /]# /usr/share/bcc/tools/biolatency
Tracing block device I/O... Hit Ctrl-C to end.
^C
     usecs               : count     distribution
         0 -> 1          : 0        |                                        |
         2 -> 3          : 0        |                                        |
         4 -> 7          : 0        |                                        |
         8 -> 15         : 0        |                                        |
        16 -> 31         : 7        |                                        |
        32 -> 63         : 386      |**************************              |
        64 -> 127        : 452      |******************************          |
       128 -> 255        : 585      |****************************************|
       256 -> 511        : 501      |**********************************      |
       512 -> 1023       : 161      |***********                             |
      1024 -> 2047       : 18       |*                                       |
      2048 -> 4095       : 58       |***                                     |
      4096 -> 8191       : 56       |***                                     |
      8192 -> 16383      : 55       |***                                     |
     16384 -> 32767      : 14       |                                        |
     32768 -> 65535      : 3        |                                        |
     65536 -> 131071     : 5        |                                        |
[root@d18d4f16d28a /]#
```

### Conclusion
This is a quick and dirty way to run eBPF on your OpenShift cluster, but you can build your bpf-ocp image for your Cluster(s), publish it / them to your registry, and for example, deploy it as DaemonSet on all your cluster nodes.
