---
layout: post
title:  "Inspecting OpenShift container images for cgroups v2 compatibility"
date:   2026-03-09 08:00:00 +0100
toc: true
categories: [OpenShift]
tags: [OpenShift,cgroupsv2,java,nodejs,dotnet]
---
In my daily work I regularly help customers plan their OpenShift upgrades, and one of the most common concerns when moving to cgroups v2 is understanding which workloads are affected. I needed a quick and reliable way to scan an entire cluster and identify incompatible Java, Node.js, and .NET runtimes, so I built **image-cgroupsv2-inspector** and released it as open source, so that anyone can use it, modify it, and contribute to it.

In this article, I'll walk you through the tool: what it does, how it works, and how you can use it on your own clusters. If you're planning to upgrade your OpenShift cluster to a version that uses cgroups v2 by default (OpenShift 4.14+), or if you're migrating from cgroups v1, this tool helps you identify which workloads might break after the transition. Starting from **OpenShift 4.19+**, the migration to cgroups v2 will be **mandatory** if not already performed, so it is important to assess your workloads sooner rather than later.

For a deep dive into how cgroups v2 impacts these runtimes, I recommend reading the Red Hat Developers article: [How does cgroups v2 impact Java, .NET, and Node.js on OpenShift 4?](https://developers.redhat.com/articles/2025/11/27/how-does-cgroups-v2-impact-java-net-and-nodejs-openshift-4).

## Why cgroups v2 compatibility matters

Linux cgroups (control groups) are used by container runtimes to enforce resource limits (CPU, memory, etc.). Cgroups v2 is the successor to cgroups v1 and brings a unified hierarchy, improved resource management, and better support for rootless containers.

However, older versions of popular runtimes (Java, Node.js, .NET) read cgroup information from the filesystem to determine available resources. When a cluster switches from cgroups v1 to v2, the filesystem layout changes, and older runtimes may fail to detect resource limits correctly, leading to:

- **Java**: The JVM may see the host's total memory instead of the container's memory limit, potentially causing OOM kills
- **Node.js**: Incorrect memory and CPU detection, leading to performance issues
- **.NET**: Similar resource detection failures

The minimum runtime versions that properly support cgroups v2 are:

| Runtime | Minimum cgroups v2 compatible version |
|---------|---------------------------------------|
| OpenJDK / HotSpot | 8u372, 11.0.16, 15+ |
| IBM Semeru | 8u345-b01, 11.0.16.0, 17.0.4.0, 18.0.2.0+ |
| IBM Java | 8.0.7.15+ |
| Node.js | 20.3.0+ |
| .NET | 5.0+ |

For more details on the compatibility matrix, refer to the [Red Hat Developers article](https://developers.redhat.com/articles/2025/11/27/how-does-cgroups-v2-impact-java-net-and-nodejs-openshift-4).

## What does image-cgroupsv2-inspector do?

The tool connects to your OpenShift cluster, collects all container images from running workloads, and then optionally analyzes each image by:

1. **Collecting images**: Scans Deployments, DeploymentConfigs, StatefulSets, DaemonSets, CronJobs, ReplicaSets, Jobs, and standalone Pods to find all container images in use
2. **Smart deduplication**: Only reports top-level controllers (e.g., a Deployment but not its child ReplicaSets or Pods), avoiding duplicate entries
3. **Image analysis**: For each unique image, pulls it locally, extracts the filesystem, and searches for Java, Node.js, and .NET binaries
4. **Version detection**: Executes each binary to determine its exact version
5. **Compatibility check**: Compares detected versions against the known cgroups v2 minimum compatibility versions
6. **CSV report**: Generates a detailed CSV report with all findings

## Requirements

Before starting, you'll need:

- Access to an **OpenShift 4.x** cluster with a valid token
- **podman** installed on the machine where you run the tool
- **Python 3.12+**
- At least **20GB of free disk space** for image extraction
- The **acl** package installed (for extended ACL support on the rootfs directory)
- Network access to all container registries used by your cluster

## Installation

Clone the repository and set up a Python virtual environment:

```bash
$ git clone https://github.com/amedeos/image-cgroupsv2-inspector.git
$ cd image-cgroupsv2-inspector
$ python3 -m venv venv
$ source venv/bin/activate
$ pip install -r requirements.txt
```

## Usage

### Connecting to the cluster

The first step is to connect to your OpenShift cluster. You can provide the API URL and token directly:

```bash
$ ./image-cgroupsv2-inspector --api-url https://api.mycluster.example.com:6443 --token sha256~xxxxx
```

After the first successful connection, credentials are saved to an `.env` file so you don't need to provide them again.

### Collecting images (without analysis)

To simply list all container images in your cluster without analyzing them:

```bash
$ ./image-cgroupsv2-inspector --rootfs-path /tmp/images
```

This produces output like:

```
╔══════════════════════════════════════════════════════════════╗
║           image-cgroupsv2-inspector v1.0.0                   ║
║     OpenShift Container Image Inspector for cgroups v2       ║
╚══════════════════════════════════════════════════════════════╝

🔍 Running system checks...
✓ podman is installed: podman version 5.7.1
✓ podman is functional (OS: linux)

🔧 Setting up rootfs directory at: /tmp/images
✓ Write permission verified on /tmp/images
✓ Sufficient disk space: 32.0GB free (required: 20GB, total: 32.0GB)
✓ Filesystem supports extended ACLs
✓ Created directory: /tmp/images/rootfs
...

🔌 Connecting to OpenShift cluster...
✓ Connected to OpenShift cluster
  Kubernetes version: v1.30.14
  Cluster name: mycluster.example.com
✓ Credentials saved to .env
✓ Pull secret already exists at .pull-secret, skipping download

📋 Namespace exclusion patterns: openshift-*, kube-*

📦 Collecting container images from cluster...
  (Only top-level controllers are reported, child objects are skipped)
  (Excluding namespaces matching: openshift-*, kube-*)
  Collecting images from Deployments...
    Found 10 containers in Deployments
  Collecting images from DeploymentConfigs...
    Found 2 containers in DeploymentConfigs
  Collecting images from StatefulSets...
    Found 0 containers in StatefulSets
  Collecting images from DaemonSets...
    Found 0 containers in DaemonSets
  Collecting images from CronJobs...
    Found 0 containers in CronJobs
  Collecting images from standalone ReplicaSets...
    Found 0 containers in standalone ReplicaSets (skipped 10 managed/empty)
  Collecting images from standalone Jobs...
    Found 0 containers in standalone Jobs (skipped 0 CronJob-managed)
  Collecting images from standalone Pods...
    Found 0 containers in standalone Pods (skipped 307 managed/static pods)

✓ Total containers found: 12
  (Excluded 51 namespaces: openshift-apiserver, openshift-apiserver-operator, ...)

📊 Summary:
   Total containers: 12
   Unique images: 10
   Namespaces: 6
   Object types: {'Deployment': 10, 'DeploymentConfig': 2}

   Output file: output/mycluster.example.com-20260309-085433.csv

📋 Top 10 most used images:
      2 × registry.access.redhat.com/ubi8/openjdk-17:latest
      2 × registry.access.redhat.com/ubi8/openjdk-8:1.14
      1 × registry.redhat.io/ubi8/dotnet-30:latest
      1 × registry.redhat.io/dotnet/sdk:8.0.122
      1 × image-registry.openshift-image-registry.svc:5000/test-java-internalreg/openjdk-17:latest
      1 × image-registry.openshift-image-registry.svc:5000/test-java-internalreg/openjdk-8:1.14
      1 × docker.io/library/eclipse-temurin:8u302-b08-jdk-centos7
      1 × docker.io/library/eclipse-temurin:17
      1 × registry.access.redhat.com/ubi8/nodejs-20:latest
      1 × registry.access.redhat.com/ubi8/nodejs-18:latest
✓ Disconnected from OpenShift cluster

✓ Done!
```

By default, the tool excludes OpenShift internal namespaces (`openshift-*`, `kube-*`) since those are managed by the platform itself.

### Full analysis with cgroups v2 compatibility check

To analyze all images and determine cgroups v2 compatibility, add the `--analyze` flag:

```bash
$ ./image-cgroupsv2-inspector --rootfs-path /tmp/images --analyze
```

The tool will pull each unique image, extract its filesystem, search for Java/Node.js/.NET binaries, run version checks, and report compatibility:

```
🔬 Analyzing images for Java, NodeJS, and .NET binaries...
  (Each image will be pulled, analyzed, and cleaned up)
  (CSV will be saved after each image for resumability)
  Found 10 unique images to analyze

  [1/10] Analyzing: image-registry.openshift-image-registry.svc:5000/test-java-internalreg...
    Pulling image: image-registry.openshift-image-registry.svc:5000/test-java-internalreg/openjdk-17:latest...
    Exporting container filesystem...
    Extracting filesystem...
    Searching for Java binaries...
    Searching for Node.js binaries...
    Searching for .NET binaries...
      ✓ Java (OpenJDK): 17.0.18 at /usr/lib/jvm/jre-17-openjdk-17.0.18.0.8-1.el8.x86_64/bin/java
    💾 Progress saved: 1 rows (1/10 images)
...
  [5/10] Analyzing: registry.redhat.io/ubi8/dotnet-30:latest...
    Pulling image: registry.redhat.io/ubi8/dotnet-30:latest...
    Exporting container filesystem...
    Extracting filesystem...
    Searching for Java binaries...
    Searching for Node.js binaries...
    Searching for .NET binaries...
      ✗ Node.js: 10.19.0 at /usr/bin/node
      ✗ .NET: 3.0.3 at /usr/lib64/dotnet/dotnet
    💾 Progress saved: 6 rows (5/10 images)
...
```

Notice the symbols: **checkmark** means the runtime is compatible with cgroups v2, while **cross** means it is **not** compatible and needs to be upgraded.

At the end of the analysis, a summary is printed:

```
📊 Summary:
   Total containers: 12
   Unique images: 10
   Namespaces: 6
   Object types: {'Deployment': 10, 'DeploymentConfig': 2}

   🔬 Analysis Results:
      Java found in: 8 containers
        ✓ cgroup v2 compatible: 4
        ✗ cgroup v2 incompatible: 4
      Node.js found in: 3 containers
        ✓ cgroup v2 compatible: 1
        ✗ cgroup v2 incompatible: 2
      .NET found in: 2 containers
        ✓ cgroup v2 compatible: 1
        ✗ cgroup v2 incompatible: 1

   Output file: output/mycluster.example.com-20260309-085455.csv
```

### Analyzing a single namespace

If you want to focus on a specific namespace, use the `-n` flag:

```bash
$ ./image-cgroupsv2-inspector --rootfs-path /tmp/images --analyze -n test-java
```

```
📋 Inspecting single namespace: test-java

📦 Collecting container images from namespace: test-java
  (Only top-level controllers are reported, child objects are skipped)
  Collecting images from Deployments...
    Found 2 containers in Deployments
...

🔬 Analyzing images for Java, NodeJS, and .NET binaries...
  Found 2 unique images to analyze

  [1/2] Analyzing: registry.access.redhat.com/ubi8/openjdk-8:1.14...
    Pulling image: registry.access.redhat.com/ubi8/openjdk-8:1.14...
    Exporting container filesystem...
    Extracting filesystem...
    Searching for Java binaries...
    Searching for Node.js binaries...
    Searching for .NET binaries...
      ✗ Java (OpenJDK): 1.8.0_362 at /usr/lib/jvm/jre-1.8.0-openjdk-1.8.0.362.b09-2.el8_7.x86_64/bin/java
      ✗ Java (OpenJDK): 1.8.0_362 at /usr/lib/jvm/java-1.8.0-openjdk-1.8.0.362.b09-2.el8_7.x86_64/bin/java
    💾 Progress saved: 1 rows (1/2 images)

  [2/2] Analyzing: registry.access.redhat.com/ubi8/openjdk-17:latest...
    Pulling image: registry.access.redhat.com/ubi8/openjdk-17:latest...
    Exporting container filesystem...
    Extracting filesystem...
    Searching for Java binaries...
    Searching for Node.js binaries...
    Searching for .NET binaries...
      ✓ Java (OpenJDK): 17.0.18 at /usr/lib/jvm/jre-17-openjdk-17.0.18.0.8-1.el8.x86_64/bin/java
    💾 Progress saved: 2 rows (2/2 images)

✓ Analyzed 2 unique images

📊 Summary:
   Total containers: 2
   Unique images: 2
   Namespaces: 1
   Object types: {'Deployment': 2}

   🔬 Analysis Results:
      Java found in: 2 containers
        ✓ cgroup v2 compatible: 1
        ✗ cgroup v2 incompatible: 1
      Node.js found in: 0 containers
      .NET found in: 0 containers
```

In this example, one container uses **OpenJDK 17.0.18** (compatible) while the other uses **OpenJDK 1.8.0_362** (incompatible, since the minimum required for Java 8 is **8u372**).

## Understanding the CSV output

The tool generates a CSV file in the `output/` directory, named after the cluster and timestamp. Here's what the columns mean:

| Column | Description |
|--------|-------------|
| `container_name` | Name of the container |
| `namespace` | Kubernetes namespace |
| `object_type` | Resource type (Deployment, StatefulSet, etc.) |
| `object_name` | Name of the parent resource |
| `image_name` | Full image name with tag |
| `java_binary` | Path to Java binary found ("None" if not found) |
| `java_version` | Detected Java version |
| `java_cgroup_v2_compatible` | "Yes", "No", or "N/A" |
| `node_binary` | Path to Node.js binary found |
| `node_version` | Detected Node.js version |
| `node_cgroup_v2_compatible` | "Yes", "No", or "N/A" |
| `dotnet_binary` | Path to .NET binary found |
| `dotnet_version` | Detected .NET version |
| `dotnet_cgroup_v2_compatible` | "Yes", "No", or "N/A" |
| `analysis_error` | Error message if analysis failed |

The CSV can be easily imported into a spreadsheet or processed with standard tools to generate reports for your team.

## How the analysis works under the hood

For each unique container image, the tool performs the following steps:

1. **Pull the image** using `podman pull` with the cluster's pull-secret for authentication
2. **Create a temporary container** and export its filesystem as a tar archive
3. **Extract the tar** to a local rootfs directory
4. **Search for binaries** by walking the extracted filesystem looking for `java`, `node`, and `dotnet` executables (skipping symlinks that point to already-found binaries)
5. **Execute version checks** by running `podman run` with the original image, overriding the entrypoint to call the binary with its version flag (`java -version`, `node --version`, `dotnet --list-runtimes`)
6. **Compare versions** against the known minimum compatible versions
7. **Clean up** by removing the extracted files, tar archive, and the pulled image

The tool handles several edge cases:

- **OpenShift internal registry images**: Automatically detects the internal registry route and rewrites URLs for external access
- **Short-name image resolution**: Resolves short image names (e.g., `eclipse-temurin:17`) to their fully qualified domain name by querying pod status
- **Resumability**: The CSV is saved after each image is analyzed, so if the process is interrupted, already-analyzed images are preserved

## Additional options

### Custom namespace exclusions

By default, `openshift-*` and `kube-*` namespaces are excluded. You can customize this:

```bash
$ ./image-cgroupsv2-inspector --rootfs-path /tmp/images --analyze \
    --exclude-namespaces "openshift-*,kube-*,staging-*"
```

### Verbose mode

For detailed debugging output, add the `-v` flag:

```bash
$ ./image-cgroupsv2-inspector --rootfs-path /tmp/images --analyze -v
```

### Log to file

To save all output to a log file for later review:

```bash
$ ./image-cgroupsv2-inspector --rootfs-path /tmp/images --analyze \
    --log-to-file --log-file my-analysis.log
```

### Skip disk check

If you know your disk has enough space and want to skip the 20GB check:

```bash
$ ./image-cgroupsv2-inspector --rootfs-path /tmp/images --analyze --skip-disk-check
```

### Custom internal registry route

If your OpenShift cluster exposes the internal registry with a custom route:

```bash
$ ./image-cgroupsv2-inspector --rootfs-path /tmp/images --analyze \
    --internal-registry-route my-registry.apps.mycluster.example.com
```

## Conclusion

Before upgrading your OpenShift cluster to a version that defaults to cgroups v2, it is critical to assess your workloads for compatibility. The **image-cgroupsv2-inspector** tool automates this process by scanning all your container images, detecting Java, Node.js, and .NET runtimes, and checking whether they meet the minimum version requirements for cgroups v2 support.

The source code is available on GitHub: [image-cgroupsv2-inspector](https://github.com/amedeos/image-cgroupsv2-inspector).

For a comprehensive explanation of how cgroups v2 impacts these runtimes, check out the Red Hat Developers article: [How does cgroups v2 impact Java, .NET, and Node.js on OpenShift 4?](https://developers.redhat.com/articles/2025/11/27/how-does-cgroups-v2-impact-java-net-and-nodejs-openshift-4).
