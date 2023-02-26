---
layout: post
title:  "Change OSDs disk flavor (dimension)"
date:   2023-02-26 10:00:00 +0100
toc: true
categories: [OpenShift]
tags: [OpenShift,odf]
---
In this article, I'll show you how to migrate your **OpenShift Data Foundation OSDs** (disks) from one flavor to another; in my case, I'll migrate OSDs and data from 0.5TiB disks to 2TiB disks; this will be a "rolling" migration with no service or data disruption.

**Warning:** If you are a Red Hat customer, open a support case before going forward, otherwise do the following steps at your own risk!

## Requirements
Before starting, you'll need:

- installed and working OpenShift Data Foundation;
- this article is based on ODF configured with the **replica** parameter set to [0], which is usually the default on hyperscalers; otherwise, you'll need to adapt if you want to do this migration, for example, on bare metal (perhaps you're using the LocalStorage operator on bare metal).
- in this guide, I'll move data and disks from three OSD disks to three other OSD disks; if you have more than three OSD, you must redo this procedure from beginning to end or check if the destination three disks can store data from more than three source disks.

[0] In this guide, I'll assume your OpenShift Data Foundation is installed on a hyperscale cloud provider, such as Azure or AWS, with three availability zones, and that you have replica set to three:
```bash
$ oc get storagecluster -n openshift-storage ocs-storagecluster -ojson | jq .spec.storageDeviceSets
[
  {
    "count": 1,
...
    "replica": 3,
...
  }
]
```

## Run must-gather
Before applying any change run an OpenShift must-gather:
```bash
$ oc adm must-gather
```

then, create a specific ODF must-gather, in this example I use ODF in version 4.10:
```bash
$ mkdir ~/odf-must-gather
$ oc adm must-gather --image=registry.redhat.io/odf4/ocs-must-gather-rhel8:v4.10 --dest-dir=~/odf-must-gather
```

## Check cluster health
Check if your cluster is healthy:
```bash
$ NAMESPACE=openshift-storage;ROOK_POD=$(oc -n ${NAMESPACE} get pod -l app=rook-ceph-operator -o jsonpath='{.items[0].metadata.name}');oc exec -it ${ROOK_POD} -n ${NAMESPACE} -- ceph status --cluster=${NAMESPACE} --conf=/var/lib/rook/${NAMESPACE}/${NAMESPACE}.config --keyring=/var/lib/rook/${NAMESPACE}/client.admin.keyring | grep HEALTH
    health: HEALTH_OK
```

**WARNING:** if your cluster is not in **HEALTH_OK**, stop any activities and check first ODF state!

## Add Capacity
Add new capacity to your cluster using new OSD flavor, in my case original storageDeviceSets is using 0.5TiB disks:

```bash
$ oc get storagecluster ocs-storagecluster -n openshift-storage -oyaml
...
  storageDeviceSets:
  - config: {}
    count: 1
    dataPVCTemplate:
      metadata: {}
      spec:
        accessModes:
        - ReadWriteOnce
        resources:
          requests:
            storage: 500Gi
        storageClassName: gp3-csi
        volumeMode: Block
      status: {}
    name: ocs-deviceset
    placement: {}
    preparePlacement: {}
    replica: 3
    resources:
      limits:
        cpu: "2"
        memory: 5Gi
      requests:
        cpu: "2"
        memory: 5Gi
```

switch to openshift-storage and backup storagecluster:

```bash
$ oc project openshift-storage

$ oc get storagecluster ocs-storagecluster -oyaml | tee backup-storagecluster-ocs-storagecluster.yaml
```

add new OSDs, with desired flavor, in my case I'm adding a new storageDeviceSets with 2TiB disks:
```bash
$ oc edit storagecluster ocs-storagecluster
...
  storageDeviceSets:
  - config: {}
    count: 1
    dataPVCTemplate:
      metadata: {}
      spec:
        accessModes:
        - ReadWriteOnce
        resources:
          requests:
            storage: 500Gi
        storageClassName: gp3-csi
        volumeMode: Block
      status: {}
    name: ocs-deviceset
    placement: {}
    preparePlacement: {}
    replica: 3
    resources:
      limits:
        cpu: "2"
        memory: 5Gi
      requests:
        cpu: "2"
        memory: 5Gi
  - config: {}
    count: 1
    dataPVCTemplate:
      metadata: {}
      spec:
        accessModes:
        - ReadWriteOnce
        resources:
          requests:
            storage: 2000Gi
        storageClassName: gp3-csi
        volumeMode: Block
      status: {}
    name: ocs-deviceset-2t
    placement: {}
    preparePlacement: {}
    replica: 3
    resources:
      limits:
        cpu: "2"
        memory: 5Gi
      requests:
        cpu: "2"
        memory: 5Gi
  version: 4.10.0
```

wait until ODF will rebalance all data, which means cluster will be in **HEALTH_OK** status and all placement groups (**pgs**) must be in **active+clean** state, to monitor rebalance you can use a while true infinite loop:

```bash
$ while true; do NAMESPACE=openshift-storage;ROOK_POD=$(oc -n ${NAMESPACE} get pod -l app=rook-ceph-operator -o jsonpath='{.items[0].metadata.name}');oc exec -it ${ROOK_POD} -n ${NAMESPACE} -- ceph status --cluster=${NAMESPACE} --conf=/var/lib/rook/${NAMESPACE}/${NAMESPACE}.config --keyring=/var/lib/rook/${NAMESPACE}/client.admin.keyring | egrep 'HEALTH_OK|HEALTH_WARN|[0-9]+\s+remapped|[0-9]+\/[0-9]+[ a-z]+misplaced[ ().%a-z0-9]+|' ; sleep 10 ; done
  cluster:                  
    id:     .....
    health: HEALTH_OK                                              
                                                  
  services:                                         
    mon: 3 daemons, quorum a,b,c (age 2h)     
    mgr: a(active, since 2w) 
    mds: 1/1 daemons up, 1 hot standby
    osd: 6 osds: 6 up (since 34s), 6 in (since 51s); 54 remapped pgs
                                                    
  data:                                                        
    volumes: 1/1 healthy            
    pools:   4 pools, 97 pgs                
    objects: 17.77k objects, 54 GiB
    usage:   157 GiB used, 7.2 TiB / 7.3 TiB avail
    pgs:     45509/53298 objects misplaced (85.386%)        
             54 active+remapped+backfill_wait
             37 active+clean
             5  active+remapped
             1  active+remapped+backfilling

  io:
    client:   1023 B/s rd, 217 KiB/s wr, 1 op/s rd, 6 op/s wr
    recovery: 86 MiB/s, 1 keys/s, 30 objects/s
```

in the above example, you can see that ceph is rebalancing / remapping PGs, wait until all PGs are in **active+clean** state:

```bash
$ NAMESPACE=openshift-storage;ROOK_POD=$(oc -n ${NAMESPACE} get pod -l app=rook-ceph-operator -o jsonpath='{.items[0].metadata.name}');oc exec -it ${ROOK_POD} -n ${NAMESPACE} -- ceph status --cluster=${NAMESPACE} --conf=/var/lib/rook/${NAMESPACE}/${NAMESPACE}.config --keyring=/var/lib/rook/${NAMESPACE}/client.admin.keyring
  cluster:
    id:     .....
    health: HEALTH_OK
 
  services:
    mon: 3 daemons, quorum a,b,c (age 2h)
    mgr: a(active, since 2w)
    mds: 1/1 daemons up, 1 hot standby
    osd: 6 osds: 6 up (since 17m), 6 in (since 18m)
 
  data:
    volumes: 1/1 healthy
    pools:   4 pools, 193 pgs
    objects: 17.02k objects, 51 GiB
    usage:   146 GiB used, 7.2 TiB / 7.3 TiB avail
    pgs:     193 active+clean
 
  io:
    client:   853 B/s rd, 76 KiB/s wr, 1 op/s rd, 7 op/s wr
```

**WARNING:** wait until your cluster returns all PGs in **active+clean** state!

check also CephFS status:

```bash
$ NAMESPACE=openshift-storage;ROOK_POD=$(oc -n ${NAMESPACE} get pod -l app=rook-ceph-operator -o jsonpath='{.items[0].metadata.name}');oc exec -it ${ROOK_POD} -n ${NAMESPACE} -- ceph fs status --cluster=${NAMESPACE} --conf=/var/lib/rook/${NAMESPACE}/${NAMESPACE}.config --keyring=/var/lib/rook/${NAMESPACE}/client.admin.keyring
ocs-storagecluster-cephfilesystem - 12 clients
=================================
RANK      STATE                       MDS                     ACTIVITY     DNS    INOS   DIRS   CAPS  
 0        active      ocs-storagecluster-cephfilesystem-b  Reqs:   37 /s  34.8k  27.2k  8369   27.1k  
0-s   standby-replay  ocs-storagecluster-cephfilesystem-a  Evts:   47 /s  82.3k  26.8k  8298      0   
```

**WARNING**: one of the two MDS must be in active state!

## Identify old OSDs / disks to remove
Take a note of your 3 OSD id to remove, they are based on your old flavor (weight 0.48830), to see ODF OSD topology run:

```bash
$ NAMESPACE=openshift-storage;ROOK_POD=$(oc -n ${NAMESPACE} get pod -l app=rook-ceph-operator -o jsonpath='{.items[0].metadata.name}');oc exec -it ${ROOK_POD} -n ${NAMESPACE} -- ceph osd tree --cluster=${NA
MESPACE} --conf=/var/lib/rook/${NAMESPACE}/${NAMESPACE}.config --keyring=/var/lib/rook/${NAMESPACE}/client.admin.keyring
ID   CLASS  WEIGHT   TYPE NAME                                       STATUS  REWEIGHT  PRI-AFF
 -1         7.32417  root default
 -5         7.32417      region eu-central-1
-14         2.44139          zone eu-central-1a
-13         2.44139              host ip-XX-XX-XX-4-rete
  2    ssd  0.48830                  osd.2                               up   1.00000  1.00000
  5    ssd  1.95309                  osd.5                               up   1.00000  1.00000
-10         2.44139          zone eu-central-1b
 -9         2.44139              host ip-XX-XX-XX-46-rete
  1    ssd  0.48830                  osd.1                               up   1.00000  1.00000
  4    ssd  1.95309                  osd.4                               up   1.00000  1.00000
 -4         2.44139          zone eu-central-1c
 -3         2.44139              host ip-XX-XX-XX-80-rete
  0    ssd  0.48830                  osd.0                               up   1.00000  1.00000
  3    ssd  1.95309                  osd.3                               up   1.00000  1.00000
```

In my case the old OSD are osd.0, osd.1 and osd.2, those OSDs needs to be removed / deleted one by one, waiting for **HEALTH_OK** after every removing / deleting.

## Remove OSD in old Storage flavor
### Switch to openshift-storage project
First switch to openshift-storage project:

```bash
$ oc project openshift-storage
```

### Copy Ceph config and keyring files
Copy your Ceph config file and keyring file from rook container pod to your Linux box, then those files will be transferred to one mon container in order to run ceph commands after scaling down rook operator.

Copy files from rook container to your Linux box:
```bash
$ ROOK=$(oc get pod | grep rook-ceph-operator | awk '{print $1}')
$ echo ${ROOK}
rook-ceph-operator-5767bbc7b9-w8swd

$ oc rsync ${ROOK}:/var/lib/rook/openshift-storage/openshift-storage.config .
WARNING: cannot use rsync: rsync not available in container
openshift-storage.config
$ oc rsync ${ROOK}:/var/lib/rook/openshift-storage/client.admin.keyring .
WARNING: cannot use rsync: rsync not available in container
client.admin.keyring
```

Copy openshift-storage.config and openshift-storage.config files from your Linux box to one mon container:

```bash
$ MONA=$(oc get pod | grep rook-ceph-mon | egrep '2\/2\s+Running' | head -n1 | awk '{print $1}')
$ echo ${MONA}
rook-ceph-mon-a-769fc864f-btmmr

$ oc cp openshift-storage.config ${MONA}:/tmp/openshift-storage.config
Defaulted container "mon" out of: mon, log-collector, chown-container-data-dir (init), init-mon-fs (init)
$ oc cp client.admin.keyring ${MONA}:/tmp/client.admin.keyring
Defaulted container "mon" out of: mon, log-collector, chown-container-data-dir (init), init-mon-fs (init)
```

**NOTE**: MONA, in one of Italian regional language means stupid people :smile:

Check ceph command on MONA container:

```bash
$ oc rsh ${MONA}
Defaulted container "mon" out of: mon, log-collector, chown-container-data-dir (init), init-mon-fs (init)
sh-4.4# ceph health --cluster=openshift-storage --conf=/tmp/openshift-storage.config --keyring=/tmp/client.admin.keyring
2023-XX -1 auth: unable to find a keyring on /var/lib/rook/openshift-storage/client.admin.keyring: (2) No such file or directory
2023-XX -1 AuthRegistry(0x7fbbb805bb68) no keyring found at /var/lib/rook/openshift-storage/client.admin.keyring, disabling cephx
HEALTH_OK
sh-4.4# exit
```

### Scale down OpenShift Data Foundation operators
Now we can scale to zero rook and ocs operators:

```bash
$ oc scale deploy ocs-operator --replicas=0
deployment.apps/ocs-operator scaled
$ oc scale deploy rook-ceph-operator --replicas=0
deployment.apps/rook-ceph-operator scaled
```

### Remove one OSD
Now you can remove one OSD, in my case I'll remove osd.0 (zero), but in your case could be a different ID.

```bash
$ failed_osd_id=0
$ export PS1="[\u@\h \W]\ OSD=$failed_osd_id $ "

$ oc scale deploy rook-ceph-osd-${failed_osd_id} --replicas=0
deployment.apps/rook-ceph-osd-0 scaled


$ oc process -n openshift-storage ocs-osd-removal -p FAILED_OSD_IDS=${failed_osd_id} FORCE_OSD_REMOVAL=true |oc create -n openshift-storage -f -
job.batch/ocs-osd-removal-job created

$ JOBREMOVAL=$(oc get pod | grep ocs-osd-removal-job- | awk '{print $1}')

$ oc logs ${JOBREMOVAL} | egrep "cephosd: completed removal of OSD ${failed_osd_id}"
2023-XX I | cephosd: completed removal of OSD 0
```

**NOTE**: on the last command you must see **cephosd: completed removal of OSD X**, where X is your osd id (in my case zero).

check ceph health status, where you can see a degraded state due to one osd removal:

```bash
$ oc rsh ${MONA}
Defaulted container "mon" out of: mon, log-collector, chown-container-data-dir (init), init-mon-fs (init)
sh-4.4# 
sh-4.4# ceph status --cluster=openshift-storage --conf=/tmp/openshift-storage.config --keyring=/tmp/client.admin.keyring
2023-XX -1 auth: unable to find a keyring on /var/lib/rook/openshift-storage/client.admin.keyring: (2) No such file or directory
2023-XX -1 AuthRegistry(0x7f207005bb68) no keyring found at /var/lib/rook/openshift-storage/client.admin.keyring, disabling cephx
  cluster:
    id:     .....
    health: HEALTH_OK
 
  services:
    mon: 3 daemons, quorum a,b,c (age 2h)
    mgr: a(active, since 2w)
    mds: 1/1 daemons up, 1 hot standby
    osd: 5 osds: 5 up (since 19m), 5 in (since 9m)
 
  data:
    volumes: 1/1 healthy
    pools:   4 pools, 193 pgs
    objects: 17.10k objects, 52 GiB
    usage:   146 GiB used, 6.7 TiB / 6.8 TiB avail
    pgs:     193 active+clean
 
  io:
    client:   1.2 KiB/s rd, 460 KiB/s wr, 2 op/s rd, 7 op/s wr
 
sh-4.4#
```

wait until ceph returns HEALTH_OK and all PGs are in **active+clean** state:

```bash
sh-4.4# while true; do ceph status --cluster=openshift-storage --conf=/tmp/openshift-storage.config --keyring=/tmp/client.admin.keyring | egrep --color=always '[0-9]+\/[0-9]+.*(degraded|misplaced)|' ; sleep 10 ; done
```

**WARNING**: before going forward you must wait for ceph **HEALTH_OK** and all PGs in **active+clean** state!

Delete removal job:

```bash
$ oc delete job ocs-osd-removal-job
job.batch "ocs-osd-removal-job" deleted
```

Repeat these steps for each OSD you need to remove (in my case for osd.1 and osd.2)

## Remove your old storageDeviceSets pointing to old OSD disks flavor
After removing all OSD that belongs to your old storageDeviceSets (in my case with disks flavor set to 0.5TiB), you can edit your **storagecluster** object to removing it:

Make a backup before editing your storagecluster:

```bash
$ oc get storagecluster ocs-storagecluster -oyaml | tee storagecluster-ocs-storagecluster-before-remove-500g.yaml
```

change / edit your storagecluster storageDeviceSets, leaving only new created storageDeviceSets, in my case with 2TiB disks flavor:

```bash
$ oc edit storagecluster ocs-storagecluster
...
  storageDeviceSets:
  - config: {}
    count: 1
    dataPVCTemplate:
      metadata: {}
      spec:
        accessModes:
        - ReadWriteOnce
        resources:
          requests:
            storage: 2000Gi
        storageClassName: gp3-csi
        volumeMode: Block
      status: {}
    name: ocs-deviceset-2t
    placement: {}
    preparePlacement: {}
    replica: 3
    resources:
      limits:
        cpu: "2"
        memory: 5Gi
      requests:
        cpu: "2"
        memory: 5Gi
  version: 4.10.0
```

## Scale up OpenShift Data Foundation operators
At this point you can scale up ocs-operator:

```bash
$ oc scale deploy ocs-operator --replicas=1
deployment.apps/ocs-operator scaled
```

and then re-check Ceph health status:

```bash
$ NAMESPACE=openshift-storage;ROOK_POD=$(oc -n ${NAMESPACE} get pod -l app=rook-ceph-operator -o jsonpath='{.items[0].metadata.name}');oc exec -it ${ROOK_POD} -n ${NAMESPACE} -- ceph status --cluster=${NAMESPACE} --conf=/var/lib/rook/${NAMESPACE}/${NAMESPACE}.config --keyring=/var/lib/rook/${NAMESPACE}/client.admin.keyring | egrep -i 'remapped|misplaced|active\+clean|HEALTH_OK|'
  cluster:
    id:     .....
    health: HEALTH_OK
 
  services:
    mon: 3 daemons, quorum a,b,c (age 3h)
    mgr: a(active, since 2w)
    mds: 1/1 daemons up, 1 hot standby
    osd: 3 osds: 3 up (since 7m), 3 in (since 6m)
 
  data:
    volumes: 1/1 healthy
    pools:   4 pools, 193 pgs
    objects: 17.15k objects, 52 GiB
    usage:   145 GiB used, 5.7 TiB / 5.9 TiB avail
    pgs:     193 active+clean
 
  io:
    client:   853 B/s rd, 246 KiB/s wr, 1 op/s rd, 4 op/s wr
```
