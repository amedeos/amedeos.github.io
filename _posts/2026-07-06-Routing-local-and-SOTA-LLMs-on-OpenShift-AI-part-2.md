---
layout: post
title:  "Routing between local and SOTA LLMs on OpenShift AI — Part 2: a governed front-door with Connectivity Link"
date:   2026-07-06 07:00:00 +0200
toc: true
categories: [OpenShift]
tags: [openshift, openshift-ai, kuadrant, connectivity-link, rate-limiting, gateway-api, api-security, ai]
---
**Warning:** This document / project is a **lab exploration** meant **only for testing** and learning. It runs local inference on CPU and uses tiny models, so it is **not** representative of a production setup -- do **not** use it as-is for production workloads.

This is the second half of a two-part series. In **[Part 1](https://amedeos.github.io/openshift/2026/07/06/Routing-local-and-SOTA-LLMs-on-OpenShift-AI-part-1.html)** I built a router on Red Hat OpenShift AI that puts a **single OpenAI-compatible endpoint** in front of two model tiers -- a small **LOCAL** vLLM model running on CPU in the cluster, and an external **SOTA** provider -- and applies an interchangeable **privacy / cost / complexity** policy to decide, per request, where each call goes. If you haven't read it, start there; this post picks up exactly where it left off.

### The gap we're closing

Part 1 ended with a working but wide-open router. The endpoint was a plain OpenShift Route protected by a single shared **master key**. That leaves three real problems:

- **No identity at the door.** One key for everyone -- you can't tell teams apart, and you can't give them different quotas.
- **No rate limiting.** Nothing stops a caller from hammering the (paid) SOTA backend.
- **A bypass.** The LiteLLM Service was reachable directly in-cluster, so the "auth" was only as good as network luck.

The fix is to put a **governed front-door** in front of the router: authentication and per-team token rate limiting enforced at a GA gateway, with the router locked down so the *only* way to reach it is through that door. I'll do it with **[Red Hat Connectivity Link](https://developers.redhat.com/products/red-hat-connectivity-link/overview) (RHCL)**, which is the productized, Red Hat-supported build of the [Kuadrant](https://kuadrant.io/) project. Unlike the LiteLLM layer from Part 1 (community / self-operated), everything in this post -- the operator, Authorino, Limitador -- is **GA and Red Hat-supported**.

### What Kuadrant gives us

RHCL/Kuadrant plugs policy into the Gateway API. Two of its components do the work here:

- **Authorino** -- the authorization service. It backs an `AuthPolicy`; we'll use it for **API-key authentication**, with each key being a labelled Kubernetes Secret.
- **Limitador** -- the rate-limiting service. It backs a `TokenRateLimitPolicy` that counts **LLM response tokens** and enforces a per-team budget per time window.

Here's the request path we're building. Compare it with the Part 1 diagram: same router and backends, but now there's a governed gateway in front, and the direct route is gone.

```
  app ──►  Route (passthrough)  ──►  openshift-ai-inference Gateway
                                        │  AuthPolicy      (Authorino: API-key)
                                        │  TokenRateLimit  (Limitador: per-team tokens)
                                        ▼
                                     HTTPRoute  ──►  LiteLLM router  (Part 1)
                                     (strips Authorization)   │  privacy / cost / complexity
                                                    ┌─────────┴─────────┐
                                              LOCAL vLLM (CPU)      SOTA provider
```

## Phase 2b -- the governed front-door

> As in Part 1, **every manifest is inline here** -- there's no repo to clone. The `manifests/50-connectivity-link/*.yaml` paths are just my layout (the numeric prefixes set the apply order); copy each block to a file and `oc apply -f` it.

### Step 7: RHCL operator, Kuadrant, and Authorino TLS

Install the operator (channel `stable`, into `openshift-operators`):

`manifests/50-connectivity-link/00-subscription-rhcl.yaml`:

```yaml
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: rhcl-operator
  namespace: openshift-operators
spec:
  channel: stable
  name: rhcl-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
```

```bash
oc apply -f manifests/50-connectivity-link/00-subscription-rhcl.yaml
oc get csv -n openshift-operators -w | grep -i rhcl        # wait: Succeeded
```

Then create the `Kuadrant` CR, which brings up the control plane (Authorino + Limitador) in the `kuadrant-system` namespace:

`manifests/50-connectivity-link/10-kuadrant.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: kuadrant-system
---
apiVersion: kuadrant.io/v1beta1
kind: Kuadrant
metadata:
  name: kuadrant
  namespace: kuadrant-system
```

```bash
oc apply -f manifests/50-connectivity-link/10-kuadrant.yaml
oc wait Kuadrant -n kuadrant-system kuadrant --for=condition=Ready --timeout=10m
```

Authorino needs TLS on its listener. The trick is to let OpenShift's service-CA mint the certificate: annotate the Authorino Service so the platform creates the serving-cert Secret, then apply an `Authorino` CR that points at it.

```bash
oc annotate svc/authorino-authorino-authorization \
  service.beta.openshift.io/serving-cert-secret-name=authorino-server-cert -n kuadrant-system
oc apply -f manifests/50-connectivity-link/15-authorino-tls.yaml
oc wait --for=condition=ready pod -l authorino-resource=authorino -n kuadrant-system --timeout=150s
```

`manifests/50-connectivity-link/15-authorino-tls.yaml`:

```yaml
apiVersion: operator.authorino.kuadrant.io/v1beta1
kind: Authorino
metadata:
  name: authorino
  namespace: kuadrant-system
spec:
  replicas: 1
  clusterWide: true
  listener:
    tls:
      enabled: true
      certSecretRef:
        name: authorino-server-cert
  oidcServer:
    tls:
      enabled: false
```

One easy-to-miss step: the KServe controllers were installed **before** Kuadrant, so they need a one-time restart to pick up the new webhooks:

```bash
oc delete pod -n redhat-ods-applications -l app=odh-model-controller
oc delete pod -n redhat-ods-applications -l control-plane=kserve-controller-manager
```

After this, `kuadrant-system` should show both engines running:

```
NAME                                   READY   STATUS    RESTARTS   AGE
authorino-54f78684d8-9vrz9             1/1     Running   0          29s
limitador-limitador-5c84fb574f-tv64b   1/1     Running   0          30s
```

### Step 8: the front-door policies

Five objects turn the gateway into a governed door. Let's take them in order.

**1. Expose the gateway (passthrough Route).** On BareMetal the gateway Service is ClusterIP, so it needs a Route in front. TLS is *passthrough* -- the Istio gateway itself terminates HTTPS and matches by hostname. This becomes the single governed entrypoint, `router.apps.example.com`.

`manifests/50-connectivity-link/20-route-gateway.yaml`:

```yaml
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: maas-router
  namespace: openshift-ingress
spec:
  host: router.apps.example.com
  to:
    kind: Service
    name: openshift-ai-inference-openshift-default
  port:
    targetPort: 443
  tls:
    termination: passthrough
    insecureEdgeTerminationPolicy: Redirect
```

**2. Route the hostname to LiteLLM (HTTPRoute).** This attaches to the gateway and forwards to the Part 1 router Service. The crucial filter: it **strips the client `Authorization` header** after the gateway has validated it, so LiteLLM (which no longer has a master key) receives the request already-authenticated and just serves it. Single auth point = the gateway.

`manifests/50-connectivity-link/30-httproute-litellm.yaml`:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: litellm
  namespace: maas-routing
spec:
  parentRefs:
    - name: openshift-ai-inference
      namespace: openshift-ingress
  hostnames:
    - router.apps.example.com
  rules:
    - filters:
        - type: RequestHeaderModifier
          requestHeaderModifier:
            remove:
              - Authorization
      backendRefs:
        - name: litellm
          port: 80
```

**3. API-key authentication (AuthPolicy).** Valid keys are Kubernetes Secrets labelled `app: maas-litellm`. The neat part is the `response.success.filters` block: it exports the key's `maas-group` label as `auth.tier.group`, which the rate-limit policy will use to tell teams apart.

`manifests/50-connectivity-link/40-authpolicy-apikey.yaml`:

```yaml
apiVersion: kuadrant.io/v1
kind: AuthPolicy
metadata:
  name: litellm-apikey
  namespace: maas-routing
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: litellm
  rules:
    authentication:
      api-key:
        apiKey:
          allNamespaces: true
          selector:
            matchLabels:
              app: maas-litellm
        # credentials omitted -> default: Authorization header, "Bearer" prefix
    response:
      success:
        filters:
          tier:
            json:
              properties:
                group:
                  expression: auth.identity.metadata.labels["maas-group"]
```

**4. Per-team token rate limiting (TokenRateLimitPolicy).** Limitador counts response tokens and enforces a budget per 120-second window, keyed on the tier. Here `research` gets a generous 100000 tokens and `legal` a deliberately tiny 200 so the limit is easy to trip in a demo.

`manifests/50-connectivity-link/50-tokenratelimitpolicy.yaml`:

```yaml
apiVersion: kuadrant.io/v1alpha1
kind: TokenRateLimitPolicy
metadata:
  name: litellm-tokens
  namespace: maas-routing
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: litellm
  limits:
    research-tier:
      when:
        - predicate: 'auth.tier.group == "research"'
      counters:
        - expression: auth.tier.group
      rates:
        - limit: 100000
          window: 120s
    legal-tier:
      when:
        - predicate: 'auth.tier.group == "legal"'
      counters:
        - expression: auth.tier.group
      rates:
        - limit: 200
          window: 120s
```

**5. Lock the router down (NetworkPolicy).** Since auth now lives at the gateway, we must prevent anyone reaching LiteLLM directly. This policy restricts ingress to the LiteLLM pod to traffic coming from the gateway namespace (`openshift-ingress`) only.

`manifests/50-connectivity-link/60-networkpolicy-litellm-gateway-only.yaml`:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: litellm-gateway-only
  namespace: maas-routing
spec:
  podSelector:
    matchLabels:
      app: litellm
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: openshift-ingress
      ports:
        - protocol: TCP
          port: 4000
```

Apply all five:

```bash
oc apply -f manifests/50-connectivity-link/20-route-gateway.yaml
oc apply -f manifests/50-connectivity-link/30-httproute-litellm.yaml
oc apply -f manifests/50-connectivity-link/40-authpolicy-apikey.yaml
oc apply -f manifests/50-connectivity-link/50-tokenratelimitpolicy.yaml
oc apply -f manifests/50-connectivity-link/60-networkpolicy-litellm-gateway-only.yaml
```

### Step 8b: per-team API keys

Each API key is itself a Kubernetes Secret -- created out-of-band with `oc create secret`, exactly like the SOTA Secret in Part 1 (no key in git). The value under `api_key` **is** the bearer token a caller sends as `Authorization: Bearer <api_key>`. Two labels make it work: `app: maas-litellm` (so the AuthPolicy accepts it) and `maas-group: <team>` (so the rate-limit policy knows its tier). Here I create one key each for two teams, `research` and `legal`:

```bash
for grp in research legal; do
  oc create secret generic apikey-$grp-1 -n maas-routing \
    --from-literal=api_key="sk-$(openssl rand -hex 20)"
  oc label secret apikey-$grp-1 -n maas-routing \
    authorino.kuadrant.io/managed-by=authorino app=maas-litellm maas-group=$grp
done
```

### Step 8c: the cutover

Now retire the Part 1 auth. Two moves: recreate the SOTA Secret **without** the LiteLLM master key (so LiteLLM stops enforcing its own auth and trusts the gateway), and delete the direct Route. The lockdown NetworkPolicy above already closed the network path, so there's no unauthenticated window.

```bash
# recreate with ONLY the SOTA key -- see the gotcha below about delete vs apply
oc delete secret sota-provider-secret -n maas-routing
oc create secret generic sota-provider-secret -n maas-routing \
  --from-literal=COMPANY_API_KEY='sk-...your-sota-key...'
oc rollout restart deploy/litellm -n maas-routing
oc rollout status deploy/litellm -n maas-routing

# remove the direct Phase 2a route
oc delete route mvp-router -n maas-routing
```

Confirm both policies are enforced:

```bash
oc get authpolicy litellm-apikey -n maas-routing \
  -o jsonpath='{.status.conditions[?(@.type=="Enforced")].status}{"\n"}'          # True
oc get tokenratelimitpolicy litellm-tokens -n maas-routing \
  -o jsonpath='{.status.conditions[?(@.type=="Enforced")].status}{"\n"}'          # True
```

## Testing the front-door

### Authentication

No key and a bad key must be rejected; a valid key gets through:

```bash
EP=https://router.apps.example.com
KEY_R=$(oc get secret apikey-research-1 -n maas-routing -o jsonpath='{.data.api_key}' | base64 -d)
J='{"model":"sota-smart","max_tokens":100,"messages":[{"role":"user","content":"Write two sentences about storage."}]}'

curl -sk "$EP/v1/chat/completions" -H 'Content-Type: application/json' -d "$J" \
  -o /dev/null -w 'no key   -> %{http_code}\n'
curl -sk "$EP/v1/chat/completions" -H 'Authorization: Bearer nope' -H 'Content-Type: application/json' -d "$J" \
  -o /dev/null -w 'bad key  -> %{http_code}\n'
curl -sk "$EP/v1/chat/completions" -H "Authorization: Bearer $KEY_R" -H 'Content-Type: application/json' -d "$J" \
  -o /dev/null -w 'good key -> %{http_code}\n'
```

```
no key   -> 401
bad key  -> 401
good key -> 200
```

### Per-team token rate limiting

Now hammer both teams. `legal` has only 200 tokens per window, so it trips **429** almost immediately; `research` has 100000 and sails through:

```bash
KEY_L=$(oc get secret apikey-legal-1 -n maas-routing -o jsonpath='{.data.api_key}' | base64 -d)
for i in 1 2 3 4; do curl -sk "$EP/v1/chat/completions" -H "Authorization: Bearer $KEY_L" \
  -H 'Content-Type: application/json' -d "$J" -o /dev/null -w "legal $i    -> %{http_code}\n"; done
for i in 1 2;     do curl -sk "$EP/v1/chat/completions" -H "Authorization: Bearer $KEY_R" \
  -H 'Content-Type: application/json' -d "$J" -o /dev/null -w "research $i -> %{http_code}\n"; done
```

```
legal 1    -> 200
legal 2    -> 200
legal 3    -> 429
legal 4    -> 429
research 1 -> 200
research 2 -> 200
```

Two `legal` calls fit inside the 200-token window; the third is over budget and gets a 429. `research`, on its much larger budget, stays 200. The quota is **per team**, enforced at the gateway, on **response tokens** -- not on request count.

### Peeking at the Limitador counters

You can watch the live token accounting straight from Limitador. The counter namespace is `<route-namespace>/<route-name>`, i.e. `maas-routing/litellm`. Counters are created lazily and expire when the 120s window rolls, so query right after generating traffic:

```bash
oc port-forward -n kuadrant-system svc/limitador-limitador 18080:8080 >/dev/null 2>&1 &
curl -s "http://localhost:18080/counters/maas-routing%2Flitellm" \
  | jq -r '.[] | "\(.set_variables|to_entries[0].value): consumed \(.limit.max_value - .remaining)/\(.limit.max_value) tok, resets in \(.expires_in_seconds)s"'
kill %1
```

```
research: consumed 348/100000 tok, resets in 93s
legal: consumed -18446744073709552000/200 tok, resets in 94s
```

`research` shows a clean `348/100000`. `legal` shows a wild negative number -- that's not a bug, it's `remaining` being an **unsigned 64-bit integer that underflowed** when the team blew past its budget. Read that entry as simply "budget exhausted → 429". For real dashboards you'd scrape Limitador's Prometheus `/metrics` (`authorized_calls` / `limited_calls`) rather than eyeball the raw counters.

## Gotchas worth knowing

A few things bit me during bring-up; all are handled above, but they're worth calling out because they're the kind of thing you'd lose an hour to:

- **Recreate the Secret with delete + create, not `oc apply`.** During the cutover, `oc apply`/`oc patch` **merge** into the existing Secret, so the old `LITELLM_MASTER_KEY` key would survive and LiteLLM would keep enforcing its own auth. You must `oc delete` then `oc create` (or `oc replace`) to actually drop it.
- **The gateway must strip `Authorization` before LiteLLM.** That's the `RequestHeaderModifier` in the HTTPRoute. Without it, LiteLLM sees the gateway's API key and tries (and fails) to authenticate it itself.
- **`auth.identity` isn't visible to the rate-limit phase.** That's why the AuthPolicy explicitly re-exports the tier as `auth.tier.group` via `response.success.filters` -- the `TokenRateLimitPolicy` reads *that*, not the raw identity.
- **CPU vLLM is slow.** Heavy LOCAL generations can still exceed the route timeout and 504; keep LOCAL-bound prompts light in a CPU lab. This vanishes on GPU.

## Final state

Here's where we land:

- **One governed endpoint:** `https://router.apps.example.com/v1` -- API-key auth and per-team token rate limiting enforced at the GA gateway, then the Part 1 policy router deciding LOCAL vs SOTA behind it.
- **No bypass:** the direct `mvp-router` Route is gone and LiteLLM only accepts traffic from the gateway namespace.
- **Still fully interchangeable:** the routing policy is one env flip away, anytime:

```bash
oc set env deploy/litellm -n maas-routing ACTIVE_POLICY=privacy   # or cost, or complexity
```

Stepping back: the interesting engineering here was never the local model's quality (it's a 0.5B on CPU -- deliberately humble). It's the **decision layer** and the **governance around it**. The application talks to one OpenAI-compatible URL; behind that URL, an interchangeable policy sends each request to the cheapest/safest/most-capable backend that fits, and a GA gateway makes sure only the right teams can call it, within their budget. Swap the local model for a real one on GPU, point the SOTA entry at your provider of choice, and the same shape holds.

## What's next

To keep this series focused I stopped at a working, governed router. Plenty of natural extensions are out of scope here, but worth knowing about if you take this further:

- **Real models on GPU.** The single biggest change: move the LOCAL tier off CPU onto GPU nodes with a proper model. Only then does it make sense to add *KV-cache-aware* routing on the self-hosted branch (the [Gateway API Inference Extension](https://gateway-api-inference-extension.sigs.k8s.io/) / `InferencePool` + endpoint picker), which needs real vLLM replicas under load.
- **Persistence / a database for LiteLLM.** Today the cost budget is in-memory (it resets on pod restart) and the Limitador counters are per-window. A DB-backed LiteLLM gives durable per-user/per-team spend tracking, virtual keys, and real budgets that survive restarts.
- **Observability.** Wire up Prometheus/Grafana for LiteLLM and Limitador metrics (`authorized_calls` / `limited_calls`, tokens per tier), plus request tracing, so routing decisions and spend are visible over time rather than tailed from logs.
- **Smarter policies.** Swap the demo heuristics for the real thing: a proper PII/NER classifier for the privacy policy instead of regexes, and a small complexity classifier instead of word-count -- the routing mechanism doesn't change, only the decision function. Semantic response caching is a cheap win on top.
- **RAG / Llama Stack.** Add retrieval-augmented generation. Note that on RHOAI this pulls in extra pieces (a vector store, Service Mesh, Llama Stack) and is Technology Preview -- a bigger commitment than the lean setup here.
- **GitOps & secret management.** Manage all these manifests declaratively with **Argo CD** instead of imperative `oc apply`, and handle the Secrets properly with **External Secrets** or **Sealed Secrets** (so even the "never in git" keys get a real lifecycle) rather than `oc create secret` by hand.
- **Production hardening.** Multiple LiteLLM replicas for HA, image digests pinned instead of `:main-stable`, API-key rotation, request/response guardrails and content safety, and an audit trail of who asked what and where it was routed.

## Wrapping up

If you missed it, **[Part 1](https://amedeos.github.io/openshift/2026/07/06/Routing-local-and-SOTA-LLMs-on-OpenShift-AI-part-1.html)** covers building the router itself. Thanks for reading -- and, as always, this was a lab: tear it down when you're done.
