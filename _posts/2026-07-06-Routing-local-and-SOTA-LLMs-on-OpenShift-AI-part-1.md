---
layout: post
title:  "Routing between local and SOTA LLMs on OpenShift AI — Part 1: the routing engine"
date:   2026-07-06 06:00:00 +0200
toc: true
categories: [OpenShift]
tags: [openshift, openshift-ai, rhoai, kserve, vllm, litellm, llm-routing, ai]
---
**Warning:** This document / project is a **lab exploration** meant **only for testing** and learning. It runs local inference on CPU and uses tiny models, so it is **not** representative of a production setup -- do **not** use it as-is for production workloads.

Lately I've been playing with a simple idea. If you run AI applications, you usually end up with two very different kinds of model in your life:

- a **local** model, self-hosted, small, cheap to run, and -- crucially -- one where the data never leaves your own infrastructure;
- a **SOTA** (state-of-the-art) model from an external frontier provider, much stronger, but one you pay per token and that sees whatever you send it.

Most of the time you don't want to pick one *forever*. You want to send each request to the *right* backend, and you want that decision to be made **for you**, server-side, without changing the client. A short "translate this" can happily go to the small local model; a "analyze these trade-offs step by step" is worth the SOTA call; and anything containing personal data should probably **never** leave the cluster at all.

That "send it to the right place" logic is the interesting part, and it's what this two-part series is about. I built a small lab on **Red Hat OpenShift AI (RHOAI)** that puts a **single OpenAI-compatible endpoint** in front of both tiers and applies an **interchangeable routing policy** -- privacy, cost, or complexity -- to decide LOCAL vs SOTA on every request. The application just calls one URL with the logical model name `auto` and gets back an answer; it has no idea (and doesn't need to know) which backend actually served it.

- **Part 1 (this post)** builds the whole thing up to a working router: the RHOAI base with a local vLLM model, and the LiteLLM policy engine that makes the routing decision.
- **Part 2** puts a **governed front-door** in front of it with [Red Hat Connectivity Link](https://amedeos.github.io/openshift/2026/07/06/Routing-local-and-SOTA-LLMs-on-OpenShift-AI-part-2.html) (Kuadrant): API-key authentication and per-team token rate limiting, all as GA components.

### Why route at all?

Three motivations show up again and again, and they map neatly onto three policies I'll implement later:

- **Cost** -- self-hosted inference is (roughly) free once the hardware is there; frontier APIs are billed per token. Sending the easy 80% of traffic to the local model and only escalating the hard 20% to SOTA can cut the bill dramatically.
- **Data sovereignty / privacy** -- some payloads simply must not be sent to a third party (PII, regulated data, secrets). A policy can detect that and **force** the request to stay in-cluster.
- **Complexity / quality tiering** -- match the request to the model that's actually good enough for it. A cheap heuristic (or a small classifier) assigns a tier, and the tier decides the backend.

### Two honest caveats about this lab

Two things are deliberately simplified, and I want to be upfront about them because they change how you'd read the results:

1. **Local inference runs on CPU**, purely for lab simplicity -- I don't have spare GPUs for this. The local model is a tiny `Qwen2.5-0.5B`, which is fine to *demonstrate routing* but is slow and not very smart. In any real deployment the local tier should be a proper model on **GPU** nodes; nothing about the routing architecture changes when you do that.
2. **The SOTA tier is just "some OpenAI-compatible endpoint".** In my lab it happens to point at an internal model I have access to, but that's irrelevant: it's one entry in a config file. Swap in your provider of choice (any OpenAI-compatible API) by changing a single `api_base` / `model` / key, and everything else stays the same. Throughout this post I'll write it as a generic `https://your-sota-provider.example.com/v1` with model `your-sota-model`.

With that out of the way, let's build it.

## The architecture

The design is three layers. The client only ever talks to Layer 1; the routing brain is Layer 2; the actual models are Layer 3.

```
  app ──►  Layer 1: single OpenAI-compatible endpoint
                      │
           Layer 2: policy engine  (LiteLLM)
                      │   privacy / cost / complexity  =  which backend?
           ┌──────────┴───────────┐
   LOCAL vLLM (CPU)          SOTA provider (external, OpenAI-compatible)
   in-cluster, KServe        key in a Secret, billed per token
```

A couple of design notes worth stating early:

- The policy is **not** three separate products, it's **one pipeline with an interchangeable rule**. You flip an environment variable (`ACTIVE_POLICY=privacy|cost|complexity`) and the same router behaves differently. That is what makes it reusable.
- Cross-provider routing **cannot** be "KV-cache aware". Clever routing that inspects a vLLM engine's KV-cache to place a request only works when you own both sides. An external SOTA provider is a black box, so the LOCAL↔SOTA decision is made on the *request* (its content, length, PII, the caller's team), never on backend internals.

Everything in Part 1 lives in two logical phases:

- **Phase 1** -- the RHOAI base: operators, a `DataScienceCluster`, a Gateway, and the local vLLM model. All of this is GA and Red Hat-supported.
- **Phase 2a** -- the routing engine: a [LiteLLM](https://github.com/BerriAI/litellm) proxy that applies the policy. LiteLLM is a **community / self-operated** component rather than a Red Hat product, so on OpenShift you own its operations and support. That said, it's a mature, widely adopted open-source project -- and its routing, fallback and budgeting features are a perfectly reasonable choice in production, not just in a lab.

## Prerequisites

My lab cluster is a **3-node compact OpenShift 4.22** cluster (the control-plane nodes are also workers), installed the same way I described in [a previous post](https://amedeos.github.io/openshift/2026/06/29/Install-OpenShift-Assisted-Installer-lab-on-Hetzner.html). What you need:

- OpenShift **4.20+** (I'm on 4.22), with `cluster-admin` and an identity provider configured (log in as a real admin user, not `kubeadmin`).
- **RHOAI 3.4.2 or later** -- the manifests target RHOAI 3.x, and 3.4.2 is the version I ran here. Earlier 3.4.x builds need an extra dashboard workaround that 3.4.2 ships out of the box, so pin to 3.4.2+ to keep the walkthrough clean.
- A default **StorageClass** (`oc get storageclass`) and a couple of workers with some headroom (≥ 8 CPU / 32 GiB is comfortable).
- The `redhat-operators` catalog present (it ships RHOAI, cert-manager, and later the Connectivity Link operator).
- An **apps wildcard domain** -- the manifests below use `apps.example.com` as a placeholder; replace it with your own `*.apps.<cluster-domain>`.

Log in:

```bash
oc login --token=<your-token> --server=https://api.example.com:6443
oc whoami    # expect your admin user
```

> **Everything you need is inline in these two posts** -- there's no repo to clone. The `manifests/…/*.yaml`, `litellm/…` and `policy/…` paths are just how I keep things organized in my lab; the numeric prefixes only set the apply order. Copy each block into a file of that name and `oc apply -f` it (or, for the `litellm/` and `policy/` directories, drop the files in place before building the ConfigMap in Phase 2a).

## Phase 1 -- the RHOAI base

### Step 1 & 2: the operators

Two operators are needed. The **RHOAI** operator is the platform itself. The **cert-manager** operator is a new prerequisite for KServe in RHOAI 3.x (it wasn't required in the 2.x era) -- without it the `kserve` component never becomes Ready.

`manifests/00-operators/10-rhoai-operator.yaml` -- pinned to the `stable-3.4` channel so the lab doesn't auto-jump to a newer minor:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: redhat-ods-operator
---
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: rhods-operator
  namespace: redhat-ods-operator
# Empty spec => cluster-wide (AllNamespaces) install mode, as required by RHOAI.
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: rhods-operator
  namespace: redhat-ods-operator
spec:
  name: rhods-operator
  channel: stable-3.4
  source: redhat-operators
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
```

`manifests/00-operators/20-cert-manager-operator.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: cert-manager-operator
---
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: openshift-cert-manager-operator
  namespace: cert-manager-operator
spec:
  targetNamespaces:
    - cert-manager-operator
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: openshift-cert-manager-operator
  namespace: cert-manager-operator
spec:
  name: openshift-cert-manager-operator
  channel: stable-v1
  source: redhat-operators
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
```

Apply both and wait for the CSVs to reach `Succeeded`:

```bash
oc apply -f manifests/00-operators/10-rhoai-operator.yaml
oc apply -f manifests/00-operators/20-cert-manager-operator.yaml

oc get csv -n redhat-ods-operator -w        # wait: Succeeded  (Ctrl-C)
oc get csv -n cert-manager-operator -w       # wait: Succeeded
```

On my cluster this landed **RHOAI 3.4.2** and **cert-manager 1.20.0**:

```
NAME                   DISPLAY                VERSION   PHASE
rhods-operator.3.4.2   Red Hat OpenShift AI   3.4.2     Succeeded
```

### Step 3: the DataScienceCluster

The operator auto-creates a `DSCInitialization`; you just declare a `DataScienceCluster` that enables the components you want. The key choices here are **`kserve` in `RawDeployment` mode** with the Knative serving stack **removed**. That's what keeps this lab free of Service Mesh and Serverless -- RawDeployment serves models as plain Kubernetes Deployments, which is all we need (and it means **no GPUs are assumed**).

`manifests/10-dsci-dsc/10-datasciencecluster.yaml` (trimmed to the essentials):

```yaml
apiVersion: datasciencecluster.opendatahub.io/v2
kind: DataScienceCluster
metadata:
  name: default-dsc
spec:
  components:
    dashboard:
      managementState: Managed
    kserve:
      managementState: Managed
      defaultDeploymentMode: RawDeployment
      rawDeploymentServiceConfig: Headed
      serving:
        managementState: Removed        # no Knative / Service Mesh serving
    workbenches:
      managementState: Managed
      workbenchNamespace: rhods-notebooks
    # everything else Removed to keep the lab lean:
    aipipelines:       { managementState: Removed }
    kueue:             { managementState: Removed }
    llamastackoperator:{ managementState: Removed }
    modelregistry:     { managementState: Removed }
    ray:               { managementState: Removed }
    trainingoperator:  { managementState: Removed }
    trustyai:          { managementState: Removed }
```

```bash
oc apply -f manifests/10-dsci-dsc/10-datasciencecluster.yaml
oc get datasciencecluster default-dsc -o jsonpath='{.status.phase}{"\n"}'   # wait: Ready
```

It took about two and a half minutes to go `Ready` here, with the components I care about reporting healthy:

```
Ready=True KserveReady=True DashboardReady=True WorkbenchesReady=True ...
```

### Step 4: the Gateway

RawDeployment routing uses the **Gateway API** (GA in OpenShift 4.20). KServe wants a `GatewayClass` and a `Gateway` named **exactly** `openshift-ai-inference` in the `openshift-ingress` namespace -- the name is a contract, don't rename it. KServe then generates one `HTTPRoute` per model and attaches it to this Gateway.

`manifests/20-gateway/00-gatewayclass.yaml`:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: openshift-default
spec:
  controllerName: openshift.io/gateway-controller/v1   # OCP 4.20+
```

The Gateway itself has two lab-specific fixes baked in, both because my cluster is **BareMetal with no LoadBalancer provider**:

1. Force the generated Service to **ClusterIP** (via an infrastructure ConfigMap), otherwise it waits forever for a LoadBalancer IP and never becomes `Programmed`. External reach is added later with a plain Route.
2. Point the TLS listener at whatever the cluster's **default ingress wildcard cert** Secret is called. On my cluster that's `apps-certs`; check yours with:

```bash
oc get ingresscontroller default -n openshift-ingress-operator \
  -o jsonpath='{.spec.defaultCertificate.name}{"\n"}'
```

`manifests/20-gateway/10-gateway-openshift-ai-inference.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: openshift-ai-inference-config
  namespace: openshift-ingress
data:
  service: |
    spec:
      type: ClusterIP
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: openshift-ai-inference
  namespace: openshift-ingress
spec:
  gatewayClassName: openshift-default
  infrastructure:
    parametersRef:
      group: ""
      kind: ConfigMap
      name: openshift-ai-inference-config
  listeners:
    - name: https
      protocol: HTTPS
      port: 443
      hostname: "*.apps.example.com"
      tls:
        mode: Terminate
        certificateRefs:
          - kind: Secret
            group: ""
            name: apps-certs
      allowedRoutes:
        namespaces:
          from: All
```

```bash
oc apply -f manifests/20-gateway/00-gatewayclass.yaml
oc get gatewayclass openshift-default -w    # wait: ACCEPTED=True

oc apply -f manifests/20-gateway/10-gateway-openshift-ai-inference.yaml
oc get gateway openshift-ai-inference -n openshift-ingress \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status} {end}{"\n"}'
```

Expected -- `Programmed=True`, and a `LoadBalancerReady=False` that is **expected and harmless** on BareMetal:

```
Accepted=True Programmed=True LoadBalancerReady=False DNSReady=False
```

### Step 5: the local model (vLLM on CPU)

Now the actual LOCAL backend. It lives in its own namespace and needs two objects: a **ServingRuntime** (the vLLM CPU engine) and an **InferenceService** (the model). The runtime launches `vllm.entrypoints.openai.api_server`, so the model is served with an **OpenAI-compatible API** on port 8080 -- no separate mock needed, it *is* our local OpenAI endpoint.

`manifests/30-serving/00-namespace.yaml` -- the `opendatahub.io/dashboard` label makes the model visible in the RHOAI dashboard:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: local-models
  labels:
    opendatahub.io/dashboard: "true"
    modelmesh-enabled: "false"
```

`manifests/30-serving/10-servingruntime-vllm-cpu.yaml` (the important bits -- it's a copy of the cluster's `vllm-cpu-x86-runtime-template` with a KV-cache size and a bigger `/dev/shm`):

```yaml
apiVersion: serving.kserve.io/v1alpha1
kind: ServingRuntime
metadata:
  name: vllm-cpu-x86-runtime
  namespace: local-models
spec:
  supportedModelFormats:
    - name: vLLM
      autoSelect: true
  containers:
    - name: kserve-container
      image: registry.redhat.io/rhaii/vllm-cpu-rhel9@sha256:dd104214095322ca92fb71149ae2bea8cfff54d6d261079740f673a840ed0795
      command: [python, -m, vllm.entrypoints.openai.api_server]
      args:
        - --port=8080
        - --model=/mnt/models
        - --served-model-name={{.Name}}
      env:
        - name: VLLM_CPU_KVCACHE_SPACE
          value: "4"          # GiB of RAM for the KV cache (must fit the memory limit)
      ports:
        - containerPort: 8080
      volumeMounts:
        - { name: shm, mountPath: /dev/shm }
  volumes:
    - name: shm
      emptyDir: { medium: Memory, sizeLimit: 2Gi }
```

`manifests/30-serving/20-inferenceservice-qwen-local.yaml` -- the model is pulled as a **public OCI "modelcar" image**, `Qwen2.5-0.5B-Instruct`, tiny enough to run on CPU. The served model name equals the object name, `qwen25-05b-local`:

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: qwen25-05b-local
  namespace: local-models
  annotations:
    serving.kserve.io/deploymentMode: RawDeployment
spec:
  predictor:
    minReplicas: 1
    maxReplicas: 1
    model:
      runtime: vllm-cpu-x86-runtime
      modelFormat: { name: vLLM }
      storageUri: oci://quay.io/redhat-ai-services/modelcar-catalog:qwen2.5-0.5b-instruct
      resources:
        requests: { cpu: "1", memory: 2Gi }
        limits:   { cpu: "4", memory: 8Gi }
```

There's one more object: a `NetworkPolicy` (`manifests/30-serving/25-networkpolicy-allow-ingress.yaml`). On RHOAI 3.4 / OCP 4.22 there's a known issue ([RHOAIENG-70137](https://issues.redhat.com/browse/RHOAIENG-70137)) where KServe doesn't create the ingress NetworkPolicy the predictor pods need, so cross-namespace and router traffic gets a 503. The policy allows ingress to `component: predictor` pods on port 8080 from the host-network (on BareMetal the OCP router runs there), `openshift-ingress` (the gateway pods), monitoring, and same-namespace callers. It's a temporary workaround; expect it to disappear in a later RHOAI.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-ingress-to-predictors
  namespace: local-models
spec:
  podSelector:
    matchLabels:
      component: predictor
  policyTypes:
    - Ingress
  ingress:
    - from:
        # OCP router runs on HostNetwork (BareMetal) -> host-network policy group
        - namespaceSelector:
            matchLabels:
              policy-group.network.openshift.io/host-network: ""
        # openshift-ai-inference gateway pods live in openshift-ingress
        - namespaceSelector:
            matchLabels:
              policy-group.network.openshift.io/ingress: ""
        # Prometheus metrics scraping
        - namespaceSelector:
            matchLabels:
              network.openshift.io/policy-group: monitoring
        # same-namespace callers
        - podSelector: {}
      ports:
        - protocol: TCP
          port: 8080
```

Apply everything and wait for the model to come up (it has to pull the image and start vLLM, ~5 minutes on CPU):

```bash
oc apply -f manifests/30-serving/00-namespace.yaml
oc apply -f manifests/30-serving/10-servingruntime-vllm-cpu.yaml
oc apply -f manifests/30-serving/20-inferenceservice-qwen-local.yaml
oc apply -f manifests/30-serving/25-networkpolicy-allow-ingress.yaml

oc get inferenceservice qwen25-05b-local -n local-models -w     # wait: READY=True
```

```
NAME               URL                                                                READY
qwen25-05b-local   http://qwen25-05b-local-predictor.local-models.svc.cluster.local   True
```

### Phase 1 smoke test

Before wiring up any routing, prove the local model answers -- in isolation, nothing exposed externally, just a port-forward:

```bash
oc port-forward -n local-models svc/qwen25-05b-local-predictor 8080:80 &
curl -s http://localhost:8080/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"qwen25-05b-local","messages":[{"role":"user","content":"Say hi in 5 words."}]}' | jq .
kill %1
```

```json
{
  "model": "qwen25-05b-local",
  "choices": [{ "message": { "content": "Hello! How can I help you today?" } }],
  "usage": { "prompt_tokens": 36, "completion_tokens": 10, "total_tokens": 46 }
}
```

That's the whole GA backbone: a self-hosted, OpenAI-compatible model on CPU. Now the fun part.

## Phase 2a -- the routing engine (LiteLLM)

The router is a [LiteLLM](https://github.com/BerriAI/litellm) proxy. It gives us the single OpenAI-compatible endpoint, a `model_list` mixing the local and SOTA backends, and -- via a small custom hook -- the actual routing decision. One thing to keep in mind: LiteLLM is **community / self-operated**, not a Red Hat product, so you own its operations and support. It's a solid, widely used open-source project, though -- if its capabilities fit your needs, it's a legitimate choice well beyond a lab.

### The three policies, one pipeline

The decision lives in a single Python hook, `policy_hook.py`, that LiteLLM calls before every request (`async_pre_call_hook`). It reads one env var, `ACTIVE_POLICY`, and applies one of three policies. This is the whole point: **switching policy is a config change, not a redeploy of a different product.**

```python
# policy_hook.py -- the decision, condensed
def _decide_privacy(self, text, _team):
    for name, rx in self._pii:                 # regexes from policy/privacy.yaml
        if rx.search(text):
            return self.local_model, f"privacy: matched PII '{name}' -> LOCAL"
    return self.sota_model, "privacy: no PII detected -> SOTA"

def _decide_cost(self, text, _team):
    if self._sota_tokens_used >= self.budget:  # in-memory SOTA token budget
        return self.local_model, "cost: SOTA budget exhausted -> LOCAL"
    if len(text) <= self.max_chars and not self._is_complex(text):
        return self.local_model, f"cost: short/simple -> LOCAL"
    return self.sota_model, "cost: long/complex -> SOTA"

def _decide_complexity(self, text, _team):
    words = len(text.split())
    if words <= self.simple_max_words:
        return self.local_model, f"complexity: simple ({words} words) -> LOCAL"
    return self.sota_model, f"complexity: complex ({words} words) -> SOTA"
```

On top of the per-policy decision there's an optional **per-team guardrail** (tiering): a team can be capped to LOCAL-only regardless of what the policy decided. The team comes from an `x-team` request header in this demo. And every decision is printed as a `[policy-router]` log line -- surfacing *why* a request went where it went is half the value.

Here's the complete `litellm/policy_hook.py`, including the PII/tiering helpers and the LiteLLM hook wiring (`async_pre_call_hook` makes the decision; `async_log_success_event` accumulates SOTA token usage to drive the cost budget):

```python
"""Interchangeable routing policy for the router (LiteLLM async_pre_call_hook).

The SAME pipeline runs one of three policies, selected by the ACTIVE_POLICY env var:
    privacy    -> PII/sensitive content forces LOCAL; rest -> SOTA
    cost       -> short/simple -> LOCAL; long/complex -> SOTA; SOTA token budget
                  -> once exhausted everything falls back to LOCAL
    complexity -> a lightweight heuristic assigns a tier, then routes
Tunables live in the policy/<name>.yaml files mounted next to this module.
"""

import os
import re
import threading

import yaml
import litellm
from litellm.integrations.custom_logger import CustomLogger

POLICY_DIR = os.environ.get("POLICY_DIR", "/app/litellm")
ACTIVE_POLICY = os.environ.get("ACTIVE_POLICY", "privacy").strip().lower()


def _load_policy(name):
    with open(os.path.join(POLICY_DIR, f"{name}.yaml")) as fh:
        return yaml.safe_load(fh) or {}


class PolicyRouter(CustomLogger):
    def __init__(self):
        super().__init__()
        self.policy = _load_policy(ACTIVE_POLICY)
        self.local_model = self.policy.get("local_model", "local-fast")
        self.sota_model = self.policy.get("sota_model", "sota-smart")
        self.tiering = self.policy.get("tiering", {})
        self._pii = [
            (p["name"], re.compile(p["regex"], re.IGNORECASE))
            for p in self.policy.get("pii_patterns", [])
        ]
        # in-memory SOTA token budget (cost policy); resets on pod restart
        self._lock = threading.Lock()
        self._sota_tokens_used = 0

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _last_user_text(data):
        for msg in reversed(data.get("messages") or []):
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):  # multimodal content parts
                return " ".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict)
                )
        return ""

    @staticmethod
    def _team(data):
        for src in ("metadata", "proxy_server_request"):
            headers = (data.get(src) or {}).get("headers") or {}
            team = headers.get("x-team") or headers.get("X-Team")
            if team:
                return team.strip().lower()
        return None

    # -- per-policy decisions ----------------------------------------------
    def _decide_privacy(self, text, _team):
        for name, rx in self._pii:
            if rx.search(text):
                return self.local_model, f"privacy: matched PII '{name}' -> LOCAL"
        return self.sota_model, "privacy: no PII detected -> SOTA"

    def _decide_cost(self, text, _team):
        budget = int(self.policy.get("sota_token_budget", 0))
        if budget > 0:
            with self._lock:
                used = self._sota_tokens_used
            if used >= budget:
                return self.local_model, (
                    f"cost: SOTA budget exhausted ({used}/{budget} tok) -> LOCAL"
                )
        max_chars = int(self.policy.get("max_prompt_chars_for_local", 280))
        kws = [k.lower() for k in self.policy.get("complex_keywords", [])]
        lowered = text.lower()
        is_complex = any(k in lowered for k in kws)
        if len(text) <= max_chars and not is_complex:
            return self.local_model, f"cost: short/simple ({len(text)} chars) -> LOCAL"
        return self.sota_model, "cost: long/complex -> SOTA"

    def _decide_complexity(self, text, _team):
        simple_max_words = int(self.policy.get("simple_max_words", 40))
        tiers = self.policy.get("tiers", {})
        words = len(text.split())
        if words <= simple_max_words:
            return tiers.get("simple", self.local_model), (
                f"complexity: simple ({words} words) -> LOCAL"
            )
        return tiers.get("complex", self.sota_model), (
            f"complexity: complex ({words} words) -> SOTA"
        )

    def _apply_tiering(self, target, team):
        """Per-team guardrail: a team capped to LOCAL never reaches SOTA."""
        if not team or not self.tiering:
            return target, None
        allowed = self.tiering.get(team, self.tiering.get("_default", []))
        if allowed and target not in allowed:
            return self.local_model, (
                f"tiering: team '{team}' not allowed '{target}' -> LOCAL"
            )
        return target, None

    # -- LiteLLM hooks ------------------------------------------------------
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        try:
            if call_type not in ("completion", "acompletion", "text_completion"):
                return data
            text = self._last_user_text(data)
            team = self._team(data)
            requested = data.get("model")
            decider = {
                "privacy": self._decide_privacy,
                "cost": self._decide_cost,
                "complexity": self._decide_complexity,
            }.get(ACTIVE_POLICY, self._decide_privacy)

            target, reason = decider(text, team)
            target, tier_reason = self._apply_tiering(target, team)
            data["model"] = target

            decision = {
                "policy": ACTIVE_POLICY,
                "requested": requested,
                "routed_to": target,
                "reason": tier_reason or reason,
                "team": team,
            }
            data.setdefault("metadata", {})["routing_decision"] = decision
            print(f"[policy-router] {decision}", flush=True)
        except Exception as exc:  # never break the request path; fail open
            print(f"[policy-router] error, passing through: {exc}", flush=True)
        return data

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        # accumulate SOTA token usage to drive the cost-policy budget guard
        try:
            budget = int(self.policy.get("sota_token_budget", 0))
            if budget <= 0:
                return
            # The routing decision may land under kwargs["metadata"] or under
            # kwargs["litellm_params"]["metadata"] depending on LiteLLM internals.
            md = (kwargs.get("litellm_params") or {}).get("metadata") or {}
            decision = md.get("routing_decision") or (kwargs.get("metadata") or {}).get("routing_decision") or {}
            # Robust backstop: the model that actually served the request. (The
            # "your-sota-model" literal is your SOTA model id -- match on it.)
            served = str(getattr(response_obj, "model", "") or kwargs.get("model") or "")
            is_sota = decision.get("routed_to") == self.sota_model or "your-sota-model" in served.lower()
            if not is_sota:
                return
            usage = getattr(response_obj, "usage", None)
            total = int(getattr(usage, "total_tokens", 0) or 0) if usage else 0
            if total:
                with self._lock:
                    self._sota_tokens_used += total
                    used = self._sota_tokens_used
                print(f"[policy-router] SOTA budget: {used}/{budget} tokens used", flush=True)
        except Exception as exc:
            print(f"[policy-router] success-event error: {exc}", flush=True)


proxy_handler_instance = PolicyRouter()
```

The tunables live in three small YAML files, one per policy. The `tiering` block (the per-team guardrail) is the same in all three.

`policy/privacy.yaml` -- the regexes are deliberately simple/demo-grade; a production deployment would use a proper PII classifier, but the routing mechanism is identical:

```yaml
policy: privacy
local_model: local-fast
sota_model: sota-smart
pii_patterns:
  - { name: codice_fiscale, regex: '\b[A-Z]{6}\d{2}[A-EHLMPR-T]\d{2}[A-Z]\d{3}[A-Z]\b' }
  - { name: iban,           regex: '\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b' }
  - { name: email,          regex: '\b[\w.+-]+@[\w-]+\.[\w.-]+\b' }
  - { name: italian_mobile, regex: '\b(?:\+39\s?)?3\d{2}[\s.-]?\d{6,7}\b' }
  - { name: credit_card,    regex: '\b(?:\d[ -]?){13,16}\b' }
tiering:
  legal:    [local-fast]                    # legal team: LOCAL only, never SOTA
  research: [local-fast, sota-smart]
  _default: [local-fast, sota-smart]
```

`policy/cost.yaml` -- short/simple goes LOCAL, long/complex goes SOTA, and a cumulative token budget caps SOTA spend (once exhausted, everything falls back to LOCAL). The budget is in-memory and resets on pod restart, so the demo runs with no real billing:

```yaml
policy: cost
local_model: local-fast
sota_model: sota-smart
max_prompt_chars_for_local: 280            # at/under this AND not "complex" -> LOCAL
complex_keywords:                          # any match marks the query complex -> SOTA
  - analyze
  - compare
  - explain why
  - derive
  - refactor
  - debug
  - step by step
  - reasoning
sota_token_budget: 2000                    # cumulative SOTA tokens before fallback-to-LOCAL
tiering:
  legal:    [local-fast]
  research: [local-fast, sota-smart]
  _default: [local-fast, sota-smart]
```

`policy/complexity.yaml` -- a word-count heuristic assigns a tier; a production deployment can swap in a small classifier model without changing the routing mechanism:

```yaml
policy: complexity
local_model: local-fast
sota_model: sota-smart
simple_max_words: 40                        # at/under -> simple tier -> LOCAL
tiers:
  simple: local-fast
  complex: sota-smart
tiering:
  legal:    [local-fast]
  research: [local-fast, sota-smart]
  _default: [local-fast, sota-smart]
```

### The LiteLLM config

`litellm/config.yaml` -- three logical models. Note `auto`, the entry the client actually calls: the hook rewrites its target to `local-fast` or `sota-smart` at request time. And note the **fallback**: if SOTA is unreachable or over quota, LiteLLM automatically retries on LOCAL.

```yaml
model_list:
  # LOCAL tier: the in-cluster vLLM model from Phase 1
  - model_name: local-fast
    litellm_params:
      model: openai/qwen25-05b-local
      api_base: http://qwen25-05b-local-predictor.local-models.svc.cluster.local/v1
      api_key: "in-cluster-no-auth"

  # SOTA tier: ANY external OpenAI-compatible provider. This is the only block
  # you change to swap providers -- vendor independence is one config entry.
  - model_name: sota-smart
    litellm_params:
      model: openai/your-sota-model
      api_base: https://your-sota-provider.example.com/v1
      api_key: os.environ/COMPANY_API_KEY     # injected from a Secret, never in git

  # the logical entry the client calls; the policy hook resolves the real target
  - model_name: auto
    litellm_params:
      model: openai/qwen25-05b-local
      api_base: http://qwen25-05b-local-predictor.local-models.svc.cluster.local/v1
      api_key: "in-cluster-no-auth"

litellm_settings:
  callbacks: ["policy_hook.proxy_handler_instance"]
  drop_params: true
  num_retries: 2

router_settings:
  fallbacks: [{"sota-smart": ["local-fast"]}]
```

That `os.environ/COMPANY_API_KEY` is the **one external credential you have to provide** -- your SOTA provider's API key. It's read from a Kubernetes **Secret** (`sota-provider-secret`) that we create by hand in the next step; it is deliberately **never** written into a YAML manifest or committed to git (which is why there's no Secret file to `oc apply`).

### Deploying the router

The router lives in its own namespace, `manifests/40-maas-gateway/00-namespace.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: maas-routing
  labels:
    app.kubernetes.io/part-of: mvp-routing
```

`manifests/40-maas-gateway/30-deployment-litellm.yaml` -- the Deployment and its Service. It mounts the ConfigMap at `/app/litellm`, sets `ACTIVE_POLICY=privacy` by default, and pulls the SOTA key from the Secret via `envFrom`. LiteLLM imports a lot of provider SDKs at startup, so it gets a generous `startupProbe` and a 2Gi memory limit (it OOMs under 1Gi):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: litellm
  namespace: maas-routing
  labels: { app: litellm }
spec:
  replicas: 1
  selector:
    matchLabels: { app: litellm }
  template:
    metadata:
      labels: { app: litellm }
    spec:
      containers:
        - name: litellm
          image: ghcr.io/berriai/litellm-non_root:main-stable   # community image; pin to a digest for real use
          command: ["litellm"]
          args: ["--config", "/app/litellm/config.yaml", "--port", "4000"]
          ports:
            - { name: http, containerPort: 4000 }
          env:
            - { name: ACTIVE_POLICY, value: "privacy" }   # privacy | cost | complexity
            - { name: POLICY_DIR,    value: "/app/litellm" }
            - { name: PYTHONPATH,    value: "/app/litellm" }
          envFrom:
            - secretRef: { name: sota-provider-secret }   # COMPANY_API_KEY (+ LITELLM_MASTER_KEY in 2a)
          volumeMounts:
            - { name: litellm-config, mountPath: /app/litellm, readOnly: true }
          startupProbe:
            httpGet: { path: /health/liveliness, port: 4000 }
            periodSeconds: 10
            failureThreshold: 18      # up to ~180s to become live
          readinessProbe:
            httpGet: { path: /health/liveliness, port: 4000 }
            periodSeconds: 10
          livenessProbe:
            httpGet: { path: /health/liveliness, port: 4000 }
            periodSeconds: 20
          resources:
            requests: { cpu: "200m", memory: "1Gi" }
            limits:   { cpu: "1",    memory: "2Gi" }
          securityContext:
            runAsNonRoot: true
            allowPrivilegeEscalation: false
            capabilities: { drop: ["ALL"] }
            seccompProfile: { type: RuntimeDefault }
      volumes:
        - name: litellm-config
          configMap: { name: litellm-config }
---
apiVersion: v1
kind: Service
metadata:
  name: litellm
  namespace: maas-routing
  labels: { app: litellm }
spec:
  selector: { app: litellm }
  ports:
    - { name: http, port: 80, targetPort: http }   # 80 -> container 4000
```

`manifests/40-maas-gateway/40-route-litellm.yaml` -- the single endpoint. It carries `haproxy.router.openshift.io/timeout: 180s`: the LOCAL path is a CPU vLLM model whose first-token latency easily exceeds the router's default 30s, so without this you get 504s on LOCAL-bound requests (the SOTA path is fast; this only matters for LOCAL):

```yaml
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: mvp-router
  namespace: maas-routing
  labels: { app: litellm }
  annotations:
    haproxy.router.openshift.io/timeout: "180s"
spec:
  host: mvp-router.apps.example.com
  to:
    kind: Service
    name: litellm
  port:
    targetPort: http
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
```

`manifests/40-maas-gateway/45-networkpolicy-local-models-allow-maas.yaml` -- applied into `local-models`, it lets the router's namespace reach the predictor pods (the companion to the RHOAIENG-70137 workaround from Phase 1):

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-from-maas-routing
  namespace: local-models
spec:
  podSelector:
    matchLabels:
      component: predictor
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: maas-routing
      ports:
        - protocol: TCP
          port: 8080
```

Now deploy. First the **Secret**, created out-of-band with `oc create secret` -- that's why there's no Secret YAML above: the key must never land in git. It holds two entries:

- `COMPANY_API_KEY` -- **your** SOTA provider's API key (replace the placeholder below with the real one).
- `LITELLM_MASTER_KEY` -- a random bearer token that clients use to call the router in this standalone Phase 2a. I generate it with `openssl rand`. Part 2 moves authentication to the gateway and drops this key entirely.

Then the **ConfigMap**, built from the `litellm/` and `policy/` directories -- so make sure `config.yaml`, `policy_hook.py` and the three `policy/*.yaml` files from above are sitting in those dirs first. Finally the workload:

```bash
oc apply -f manifests/40-maas-gateway/00-namespace.yaml

# the SOTA credential + a generated master key for standalone testing.
# Created via oc create secret (never from a YAML file) so no key touches git.
oc create secret generic sota-provider-secret -n maas-routing \
  --from-literal=COMPANY_API_KEY='sk-...your-sota-key...' \
  --from-literal=LITELLM_MASTER_KEY="sk-$(openssl rand -hex 24)"

# config + policy code + policy files, from the litellm/ and policy/ dirs
oc create configmap litellm-config -n maas-routing \
  --from-file=litellm/ --from-file=policy/

oc apply -f manifests/40-maas-gateway/30-deployment-litellm.yaml
oc apply -f manifests/40-maas-gateway/40-route-litellm.yaml
oc apply -f manifests/40-maas-gateway/45-networkpolicy-local-models-allow-maas.yaml
oc rollout status deploy/litellm -n maas-routing
```

### Testing the routing

Here's a little helper that calls the single endpoint with the logical model `auto`:

```bash
EP=https://mvp-router.apps.example.com
KEY=$(oc get secret sota-provider-secret -n maas-routing -o jsonpath='{.data.LITELLM_MASTER_KEY}' | base64 -d)
ask() { curl -sk --max-time 180 "$EP/v1/chat/completions" \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' "${@:2}" \
  -d "$(jq -nc --arg p "$1" '{model:"auto",messages:[{role:"user",content:$p}]}')"; echo; }
```

You can watch the decisions live in another terminal:

```bash
oc logs -n maas-routing deploy/litellm -f | grep policy-router
```

**Privacy policy (the default).** No PII goes to SOTA; anything with PII is forced LOCAL:

```bash
ask "Give me three ideas for a team offsite."      # no PII -> SOTA
ask "Save the email mario.rossi@acme.it"            # email  -> forced LOCAL
```

```
[policy-router] {'policy': 'privacy', 'routed_to': 'sota-smart', 'reason': 'privacy: no PII detected -> SOTA', 'team': None}
[policy-router] {'policy': 'privacy', 'routed_to': 'local-fast', 'reason': "privacy: matched PII 'email' -> LOCAL", 'team': None}
```

You can *feel* the difference in the answers too: the offsite question comes back with a rich, structured reply from the SOTA model, while the email one gets the little local model's much simpler response -- which is exactly the point, the sensitive request never left the cluster.

**Cost policy.** Switch it live -- no redeploy of anything, just an env flip:

```bash
oc set env deploy/litellm -n maas-routing ACTIVE_POLICY=cost
oc rollout status deploy/litellm -n maas-routing

ask "Translate good morning to Italian."                                          # short   -> LOCAL
ask "Analyze step by step microservices vs monolith and derive a recommendation." # complex -> SOTA
ask "Compare in detail the trade-offs of event-driven vs request-response."       # budget spent -> LOCAL
```

```
[policy-router] {'policy': 'cost', 'routed_to': 'local-fast', 'reason': 'cost: short/simple (34 chars) -> LOCAL', 'team': None}
[policy-router] {'policy': 'cost', 'routed_to': 'sota-smart', 'reason': 'cost: long/complex -> SOTA', 'team': None}
[policy-router] SOTA budget: 3125/2000 tokens used
[policy-router] {'policy': 'cost', 'routed_to': 'local-fast', 'reason': 'cost: SOTA budget exhausted (3125/2000 tok) -> LOCAL', 'team': None}
```

The first complex query went to SOTA and burned past the 2000-token budget; the next complex query, with the budget exhausted, fell back to LOCAL. That's a hard cost ceiling implemented in a dozen lines.

**Tiering.** Still on the cost policy, but now with an `x-team` header. The `legal` team is capped to LOCAL; `research` is allowed SOTA. (I restart first to reset the in-memory budget, otherwise the spent budget above would mask the tiering.)

```bash
oc rollout restart deploy/litellm -n maas-routing
oc rollout status deploy/litellm -n maas-routing

ask "Analyze the market outlook for storage." -H 'x-team: legal'     # capped  -> LOCAL
ask "Analyze the market outlook for storage." -H 'x-team: research'  # allowed -> SOTA
```

```
[policy-router] {'policy': 'cost', 'routed_to': 'local-fast', 'reason': "tiering: team 'legal' not allowed 'sota-smart' -> LOCAL", 'team': 'legal'}
[policy-router] {'policy': 'cost', 'routed_to': 'sota-smart', 'reason': 'cost: long/complex -> SOTA', 'team': 'research'}
```

Identical prompt, opposite routing -- decided entirely by the caller's team. Switch back to the default with `oc set env deploy/litellm -n maas-routing ACTIVE_POLICY=privacy` when you're done.

## Wrapping up (and what's next)

At this point we have a working router: **one OpenAI-compatible endpoint**, an interchangeable **privacy / cost / complexity** policy that decides LOCAL vs SOTA on every request, a per-team guardrail, an automatic fallback, and a live view of every decision. The client never changed -- it just calls `auto`.

But there's a gaping hole. Right now the endpoint is a plain Route protected by a single shared master key. There's no per-team identity at the door, no token rate limiting, and if someone reached the LiteLLM Service directly they'd bypass even that. That's fine for a lab bring-up, but it is **not** a governed front-door.

In **[Part 2](https://amedeos.github.io/openshift/2026/07/06/Routing-local-and-SOTA-LLMs-on-OpenShift-AI-part-2.html)** I fix exactly that, using **Red Hat Connectivity Link (Kuadrant)** to add API-key authentication and per-team token rate limiting at the GA gateway -- and then lock the router down so the only way in is through that governed door. See you there.
