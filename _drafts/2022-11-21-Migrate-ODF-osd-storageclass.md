---
layout: post
title:  "Migrate OSDs from one storage class to another"
date:   2022-11-21 09:00:00 +0100
toc: true
categories: [OpenShift]
tags: [OpenShift,odf]
---
**Warning:** If you are a Red Hat customer, open a support case before going forward, otherwise doing the following steps at your own risk!

In this article, I'll explain how to migrate your **OpenShift Data Foundation** OSDs (disks), residing on one cloud storage class, for example Azure managed-premium, to another storage class, for example Azure **managed-csi**, this will be a "rolling" migration, with no service and data interruption.

## Requirements
Before starting you'll need:

- installed and working OpenShift Data Foundation;
- configured new / destination Storage Class => in this article I'll use **managed-csi**;
- ODF configured with **replica** parameter set to 3[0];
- in this guide I'll move data / disks, only from 3 OSD disks to other 3 OSD disks, in differrent storage classes, if you have more than 3 OSD you have to redo this procedure from start to end.

[0] In this guide I'll assume your OpenShift Data Foundation is installed on hyperscaler cloud provider, for example Azure or AWS, with 3 availability zones, and with this configuration you should have replica set to 3:
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
Before apply any change run an OpenShift must-gather
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
Add new capacity to your cluster using new StorageClass, in my case managed-csi navigating to:

- select Left menu Operators => Installed Operators => OpenShift Data Foundation (selecting project openshift-storage on left corner);
- select "Storage System" tab;
- click on three dot on the right and then select Add Capacity

![01-add-capacity.png](/images/openshift/odf-move/01-add-capacity.png)

- select your desired storage class and then click Add

![02-add-capacity.png](/images/openshift/odf-move/02-add-capacity.png)

wait until ODF will rebalance all data and cluster returns to **HEALTH_OK**

```bash
$ while true; do NAMESPACE=openshift-storage;ROOK_POD=$(oc -n ${NAMESPACE} get pod -l app=rook-ceph-operator -o jsonpath='{.items[0].metadata.name}');oc exec -it ${ROOK_POD} -n ${NAMESPACE} -- ceph status --cluster=${NAMESPACE} --conf=/var/lib/rook/${NAMESPACE}/${NAMESPACE}.config --keyring=/var/lib/rook/${NAMESPACE}/client.admin.keyring | egrep 'HEALTH_OK|HEALTH_WARN|[0-9]+\s+remapped|[0-9]+\/[0-9]+[ a-z]+misplaced[ ().%a-z0-9]+|' ; sleep 10 ; done
  cluster:
    id:  ....
    health: HEALTH_OK
```

**WARNING:** wait until your cluster returns to **HEALTH_OK**
