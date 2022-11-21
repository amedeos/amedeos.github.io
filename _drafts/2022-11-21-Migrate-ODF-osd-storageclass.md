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
- configured new / destination Storage Class => in this article I'll use **managed-csi**
