---
layout: post
title:  "Migrate Elasticsearch shards to a new StorageClass"
date:   2023-01-08 10:00:00 +0100
toc: true
categories: [OpenShift]
tags: [OpenShift,elasticsearch,elk]
---
In this **OpenShift** / **Kubernetes** article, I'll explain how to migrate your **Elasticsearch** data (shards), residing on one cloud storage class, for example Azure managed-premium, to another storage class, for example Azure **managed-csi**, this will be a "rolling" migration, with no service and data interruption.

**Warning:** If you are a Red Hat customer, open a support case before going forward, otherwise doing the following steps at your own risk!

## Requirements
Before starting you'll need:

- installed and working Elasticsearch[0];
- configured new / destination Storage Class => in this article I'll use **managed-csi**;
- Elasticsearch working on 3 different worker nodes (usually belonging to 3 Availability Zones);
- Elasticsearch working on 3 different CDM, where each of them has its own PVC on __old__ StorageClass (in my case Azure managed-premium)[1];
- Elasticsearch configured with minimum_master_nodes set to 2;
- in this guide I'll move data / disks, only from 3 OSD disks to other 3 OSD disks, in different storage classes, if you have more than 3 OSD you have to redo this procedure from start to finish.

[0] In this guide I'll assume your Elasticsearch is installed on the hyperscaler cloud provider, for example Azure or AWS, with 3 availability zones

[1] Example of 3 elasticsearch CDM running on OpenShift:
```bash
$ oc get pods -l component=elasticsearch -o wide -n openshift-logging
NAME                                            READY   STATUS    RESTARTS   AGE   IP            NODE                                          NOMINATED NODE   READINESS GATES
elasticsearch-cdm-19ibb0br-1-f58b8f764-6dnvg    2/2     Running   0          42d   100.65.8.8    nodename-xxxx-elastic-northeurope3-vk7cf   <none>           <none>
elasticsearch-cdm-19ibb0br-2-787fd9c4c5-r88lc   2/2     Running   0          41d   100.65.6.8    nodename-xxxx-elastic-northeurope1-rd545   <none>           <none>
elasticsearch-cdm-19ibb0br-3-6bc8c8f98-w6jh9    2/2     Running   0          42d   100.65.10.8   nodename-xxxx-elastic-northeurope2-mbtc9   <none>           <none>
```

## Run must-gather
Before applying any change run an OpenShift must-gather:
```bash
$ oc adm must-gather
```

then, create a specific cluster-logging must-gather:
```bash
$ oc adm must-gather --image=$(oc -n openshift-logging get deployment.apps/cluster-logging-operator -o jsonpath='{.spec.template.spec.containers[?(@.name == "cluster-logging-operator")].image}')
```

## Check cluster health / green state
Check if your cluster is in green state:
```bash
$ oc project openshift-logging
$ export ELKCDM=$(oc get pods -l component=elasticsearch -o wide | egrep '2\/2\s+Running' | head -n1 | awk '{print $1}')

$ oc exec ${ELKCDM} -c elasticsearch -- health | egrep 'green|'
epoch      timestamp cluster       status node.total node.data shards pri relo init unassign pending_tasks max_task_wait_time active_shards_percent
1661176875 14:01:15  elasticsearch green           3         3    428 214    0    0        0             0                  -                100.0%
```

**WARNING:** if your cluster is not in **green**, and **active_shards_percent** is not equal to 100%, stop any activities and check first elasticsearch state!

## Check cluster routing allocation parameter
The cluster.routing.allocation.enable parameter must to be "all", for example, if you have "primaries", you need to change it to "all" and wait for shards creation / relocation.

This is the correct value:
```bash
$ oc exec ${ELKCDM} -c elasticsearch -- es_util --query=_cluster/settings?pretty
{
  "persistent" : {
    "cluster" : {
      "routing" : {
        "allocation" : {
          "enable" : "all"
        }
      }
    },
    "discovery" : {
      "zen" : {
        "minimum_master_nodes" : "2"
      }
    }
  },
  "transient" : { }
}
```

instead, if you have primaries:
```bash
$ oc exec ${ELKCDM} -c elasticsearch -- es_util --query=_cluster/settings?pretty
{
  "persistent" : {
    "cluster" : {
      "routing" : {
        "allocation" : {
          "enable" : "primaries"
        }
      }
    },
    "discovery" : {
      "zen" : {
        "minimum_master_nodes" : "2"
      }
    }
  },
  "transient" : { }
}
```

in this case you have to overwrite to all:
```bash
$ oc exec -c elasticsearch ${ELKCDM} -- curl -s --key /etc/elasticsearch/secret/admin-key --cert /etc/elasticsearch/secret/admin-cert --cacert /etc/elasticsearch/secret/admin-ca -H "Content-Type: application/json" -XPUT "https://localhost:9200/_cluster/settings" -d '{ "persistent":{ "cluster.routing.allocation.enable" : "all" }}'
{"acknowledged":true,"persistent":{"cluster":{"routing":{"allocation":{"enable":"all"}}}},"transient":{}}

$ oc exec ${ELKCDM} -c elasticsearch -- es_util --query=_cluster/settings?pretty
{
  "persistent" : {
    "cluster" : {
      "routing" : {
        "allocation" : {
          "enable" : "all"
        }
      }
    },
    "discovery" : {
      "zen" : {
        "minimum_master_nodes" : "2"
      }
    }
  },
  "transient" : { }
}
```
then wait until relocation (relo column) falls to zero (0)
```bash
$ while true ; do oc exec ${ELKCDM} -c elasticsearch -- health | egrep 'green\s+3\s+3|' ; sleep 10 ; done
epoch      timestamp cluster       status node.total node.data shards pri relo init unassign pending_tasks max_task_wait_time active_shards_percent
1661259701 13:01:41  elasticsearch green           3         3    428 214    2    0        0             0                  -                100.0%
...........
```

## Check for shards not started
Check that all your shards are in STARTED state:
```bash
$  oc exec ${ELKCDM} -c elasticsearch -- es_util --query=_cat/shards?v | grep -v STARTED
index                          shard prirep state      docs   store ip          node
```

**Warning:** the above command must return only one line which is the column header; if you have some shards that is NOT in STARTED state, stop any activities and check first elasticsearch state!

## Modify clusterlogging instance with new StorageClass
Edit you clusterlogging instance with your new StorageClass name (in my case managed-csi).

Backup it before editing:
```bash
$ oc get clusterlogging instance -oyaml | tee -a clusterlogging-instance-before-storageclass-change.yaml
```

then edit it changing only the storageClassName parameter:
#TODO: put a snippet
```bash
$ oc edit clusterlogging instance
clusterlogging.logging.openshift.io/instance edited
```

verify the correct storageClassName value:
```bash
$ oc get clusterlogging instance -ojson | jq -r '.spec.logStore.elasticsearch.storage.storageClassName'
managed-csi
```

## Remove shards from one elastic CDM pod
Now, you can identify one elastic CDM and its overlay IP, in order to relocate all shards from it:
```bash
$  oc exec ${ELKCDM} -c elasticsearch -- es_util --query=_cat/nodes?v
ip          heap.percent ram.percent cpu load_1m load_5m load_15m node.role master name
100.65.8.8            48          99  15    2.36    2.21     2.40 mdi       -      elasticsearch-cdm-19ibb0br-1
100.65.6.8            26          99  10    0.90    1.32     1.72 mdi       *      elasticsearch-cdm-19ibb0br-2
100.65.10.8           24          99  18    2.21    2.63     3.30 mdi       -      elasticsearch-cdm-19ibb0br-3
```

In this example I'll relocate shards from CDM-1 **elasticsearch-cdm-19ibb0br-1**, which has **100.65.8.8** IP

### Exclude CDM IP
In order to move shards from idenfied elasticsearch cdm, you have to eclude its IP, in my case 100.65.8.8, but you need to change with your CDM' IP:
```bash
$  oc exec ${ELKCDM} -c elasticsearch -- es_util --query=_cluster/settings?pretty -X PUT -d '{"transient":{"cluster.routing.allocation.exclude._ip": "100.65.8.8"}}'
{
  "acknowledged" : true,
  "persistent" : { },
  "transient" : {
    "cluster" : {
      "routing" : {
        "allocation" : {
          "exclude" : {
            "_ip" : "100.65.8.8"
          }
        }
      }
    }
  }
}
```

wait until all shards are relocated to other two elasticsearch nodes:
```bash
$ oc rsh ${ELKCDM} 
Defaulted container "elasticsearch" out of: elasticsearch, proxy
sh-4.4$ while true ; do es_util --query=_cat/shards?v | grep 100.65.8.8 | wc -l ; sleep 10 ; done
142
140
... (cut)
0
(Ctrl-c)
sh-4.4$ exit
```
### Scale elasticsearch CDM deploy to zero
Scale to zero (0) elasticsearch CDM deploy, in my case elasticsearch-cdm-19ibb0br-1
```bash
$ oc get deploy
NAME                           READY   UP-TO-DATE   AVAILABLE   AGE
cluster-logging-operator       1/1     1            1           137d
elasticsearch-cdm-19ibb0br-1   1/1     1            1           137d
elasticsearch-cdm-19ibb0br-2   1/1     1            1           137d
elasticsearch-cdm-19ibb0br-3   1/1     1            1           137d
kibana                         1/1     1            1           89d

$ oc scale deploy elasticsearch-cdm-19ibb0br-1 --replicas=0
deployment.apps/elasticsearch-cdm-19ibb0br-1 scaled
```

### Delete elasticsearch CDM PVC
Delete the PVC corresponding to your elasticsearch CDM, in my case **elasticsearch-elasticsearch-cdm-19ibb0br-1** but you need to change with your pvc:
```bash
$ oc get pvc
NAME                                         STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS       AGE
elasticsearch-elasticsearch-cdm-19ibb0br-1   Bound    pvc-3d378adc-901a-4198-9ff0-f720d32eaa4d   500Gi      RWO            managed-premium    137d
elasticsearch-elasticsearch-cdm-19ibb0br-2   Bound    pvc-318f2d40-2580-486d-a6ac-cb1822427fd3   500Gi      RWO            managed-premium    137d
elasticsearch-elasticsearch-cdm-19ibb0br-3   Bound    pvc-7052bed6-09aa-4789-b86e-9d68616b6401   500Gi      RWO            managed-premium    137d

$ oc delete pvc elasticsearch-elasticsearch-cdm-19ibb0br-1
persistentvolumeclaim "elasticsearch-elasticsearch-cdm-19ibb0br-1" deleted

$ oc get pvc
NAME                                         STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS       AGE
elasticsearch-elasticsearch-cdm-19ibb0br-2   Bound    pvc-318f2d40-2580-486d-a6ac-cb1822427fd3   500Gi      RWO            managed-premium    137d
elasticsearch-elasticsearch-cdm-19ibb0br-3   Bound    pvc-7052bed6-09aa-4789-b86e-9d68616b6401   500Gi      RWO            managed-premium    137d
```

### Check cluster health / green state
Check if your cluster is still in green state:
```bash
$ export ELKCDM=$(oc get pods -l component=elasticsearch -o wide | egrep '2\/2\s+Running' | head -n1 | awk '{print $1}')
$ oc exec ${ELKCDM} -c elasticsearch -- health | egrep 'green|'
epoch      timestamp cluster       status node.total node.data shards pri relo init unassign pending_tasks max_task_wait_time active_shards_percent
1661258957 12:49:17  elasticsearch green           2         2    416 208    0    0        0             0                  -                100.0%
```

**WARNING:** if your cluster is not in **green**, and **active_shards_percent** is not equal to 100%, stop any activities and check first elasticsearch state!

### Remove exclude IP
Remove your previously exclude ip parameter:
```bash
$ oc exec ${ELKCDM} -c elasticsearch -- es_util --query=_cluster/settings?pretty -X PUT -d '{"transient":{"cluster.routing.allocation.exclude._ip" : null}}'
{
  "acknowledged" : true,
  "persistent" : { },
  "transient" : { }
}
```

### Scale elasticsearch CDM deploy to one
Scale back to one (1) elasticsearch CDM deploy, in my case elasticsearch-cdm-19ibb0br-1
```bash
$ oc get deploy
NAME                           READY   UP-TO-DATE   AVAILABLE   AGE
cluster-logging-operator       1/1     1            1           137d
elasticsearch-cdm-19ibb0br-1   0/0     0            0           137d
elasticsearch-cdm-19ibb0br-2   1/1     1            1           137d
elasticsearch-cdm-19ibb0br-3   1/1     1            1           137d
kibana                         1/1     1            1           89d

$ oc scale deploy elasticsearch-cdm-19ibb0br-1 --replicas=1
deployment.apps/elasticsearch-cdm-19ibb0br-1 scaled
```
check if there are 3 nodes:
```bash
$ oc exec ${ELKCDM} -c elasticsearch -- health | egrep 'green\s+3\s+3|'
Tue Aug 23 12:58:52 UTC 2022
epoch      timestamp cluster       status node.total node.data shards pri relo init unassign pending_tasks max_task_wait_time active_shards_percent
1661259532 12:58:52  elasticsearch green           3         3    416 208    2    0        0             0                  -                100.0%
```

### Re-set cluster routing to all
Re-set cluster.routing.allocation.enable parameter to all:
```bash
$ oc exec -c elasticsearch ${ELKCDM} -- curl -s --key /etc/elasticsearch/secret/admin-key --cert /etc/elasticsearch/secret/admin-cert --cacert /etc/elasticsearch/secret/admin-ca -H "Content-Type: application/json" -XPUT "https://localhost:9200/_cluster/settings" -d '{ "persistent":{ "cluster.routing.allocation.enable" : "all" }}'
{"acknowledged":true,"persistent":{"cluster":{"routing":{"allocation":{"enable":"all"}}}},"transient":{}}

$ oc exec ${ELKCDM} -c elasticsearch -- es_util --query=_cluster/settings?pretty
{
  "persistent" : {
    "cluster" : {
      "routing" : {
        "allocation" : {
          "enable" : "all"
        }
      }
    },
    "discovery" : {
      "zen" : {
        "minimum_master_nodes" : "2"
      }
    }
  },
  "transient" : { }
}
```

and then wait for relocation:
```bash
$ while true ; do oc exec ${ELKCDM} -c elasticsearch -- health | egrep 'green\s+3\s+3|' ; sleep 10 ; done
epoch      timestamp cluster       status node.total node.data shards pri relo init unassign pending_tasks max_task_wait_time active_shards_percent
1661259701 13:01:41  elasticsearch green           3         3    428 214    2    0        0             0                  -                100.0%
```
