---
layout: post
title:  "I Watched My LLM Router Leak 174 Sensitive Prompts — Here's What Finally Stopped It (Part 3)"
date:   2026-07-13 08:00:00 +0200
toc: true
categories: [OpenShift]
tags: [openshift, openshift-ai, presidio, pii, privacy, ner, llm-routing, litellm, ai]
---
**Warning:** This document / project is a **lab exploration** meant **only for testing** and learning. The numbers below come from a **synthetic corpus I wrote myself**, measured on a lab cluster -- they show how this gate behaves, **not** how a production privacy control would perform on real traffic. Do **not** treat this gate as a validated privacy/compliance control.

In [Part 1](https://amedeos.github.io/openshift/2026/07/06/Routing-local-and-SOTA-LLMs-on-OpenShift-AI-part-1.html) I built a router on OpenShift AI that sends each request either to a **LOCAL** model (self-hosted, data never leaves the cluster) or to a **SOTA** (state-of-the-art) model (external provider, stronger, sees everything you send). In [Part 2](https://amedeos.github.io/openshift/2026/07/06/Routing-local-and-SOTA-LLMs-on-OpenShift-AI-part-2.html) I put a governed front-door in front of it. Both posts ended with the same honest caveat: the *privacy* policy deciding "does this prompt contain something that must not leave the cluster?" was a handful of regexes.

So I did what you should always do with a privacy control before trusting it: I **attacked it with a corpus and counted the bodies**. I wrote **332 test prompts, in both English and Italian** (664 cases total), each labeled with where it *should* route, and ran the whole matrix against the live gate.

Of those 664 cases, **382 are sensitive** (they must stay LOCAL) and 282 are benign traffic that must keep flowing to SOTA -- both kinds are needed, because a gate is only as good as its errors in *both* directions. The rules-based gate leaked **174 of the 382 sensitive prompts** -- prompts about a person's diagnosis, a divorce, a firing -- straight to the external provider. This post is about how I measured that, what actually fixed it (spoiler: a small **local** LLM acting as a second-opinion classifier), what I tried and *discarded* along the way, and why the Italian word *"ciao"* forced me to rebuild a container image.

Everything is reproducible from the published data: the [test corpora and per-case CSV results](/files/privacy-plus-eval/) are in this site's repo, together with the [chart script](/files/privacy-plus-eval/make_charts.py) that generated every figure below.

## The gate under test: one score, several detectors

First, a definition, because the whole post hangs on it:

> **Leak** = a prompt labeled *sensitive* (`expect: local`) that the gate routed to the external SOTA model. A **false positive** is the opposite: a benign prompt needlessly kept LOCAL. A leak is a privacy failure; a false positive just wastes some local capacity. They are **not** symmetric errors.

The hardened policy (I call it `privacy-plus`) replaces the binary regex gate from Part 1 with a small scoring engine. Several **detectors** each emit weighted *signals*; the signals combine into a single `privacy_score` in `[0,1]` via **noisy-OR**, and a fixed threshold makes the decision deterministic and explainable:

```
score = 1 - Π(1 - wᵢ)          # noisy-OR over every fired signal
score >= 0.50  ->  LOCAL        # one knob tunes conservativeness
```

The detector chain, in the order it runs:

- **A -- structured PII (Personally Identifiable Information), via deterministic rules + validators.** Regexes for codice fiscale, IBAN, credit cards, API keys, JWTs, private-key headers... but with a twist that kills a whole class of false positives: a match only scores if its **validator** passes -- the [Luhn algorithm](https://en.wikipedia.org/wiki/Luhn_algorithm) for cards (the mod-10 checksum every real card number satisfies by construction; a random 16-digit string passes it only ~10% of the time), [mod-97](https://en.wikipedia.org/wiki/International_Bank_Account_Number#Validating_the_IBAN) for IBAN, the real codice fiscale checksum. A 16-digit number that fails Luhn contributes *nothing*.
- **B -- weighted lexicons.** Sensitive *topics* with no formal identifier: health (GDPR special category, weight 0.80), finance, legal, sensitive-HR, credentials. Bilingual (IT + EN) term lists.
- **C1 -- local NER (Named-Entity Recognition).** A [Microsoft Presidio](https://microsoft.github.io/presidio/) analyzer running **in-cluster on CPU**, catching what regexes cannot enumerate: person names, locations. Each entity contributes its weight only above a confidence floor.
- **C2 -- a semantic classifier (LLM), advisory and optional.** More on this later -- it is the thing that actually fixed the leaks.

The full policy file and engine are published with this post ([`code/privacy-plus.yaml`](/files/privacy-plus-eval/code/privacy-plus.yaml), [`code/privacy_scoring.py`](/files/privacy-plus-eval/code/privacy_scoring.py)); here is the shape of it:

```yaml
# code/privacy-plus.yaml (excerpt)
aggregation: noisy_or
scan: whole_payload      # system + every user turn + tool args, not just the last message
fail_closed: true        # any detector error -> route LOCAL (the safe side)
threshold: 0.50
thresholds:              # per-team override, from the gateway-injected identity
  legal: 0.30            # very conservative
  research: 0.70         # more permissive
  _default: 0.50

pii_patterns:
  - name: credit_card
    regex: '\b(?:\d[ -]?){13,19}\b'
    validator: luhn      # match counts ONLY if the checksum passes
    weight: 0.85

lexicons:
  health:
    weight: 0.80         # GDPR special category
    terms: [diagnosi, referto, "cartella clinica", diagnosis, "chronic condition", ...]

ner:
  enabled: true
  url: http://presidio-analyzer.maas-routing.svc.cluster.local:3000/analyze
  supported_languages: [en, it]
  min_confidence: 0.60
  entity_weights: { PERSON: 0.60, LOCATION: 0.40, IBAN_CODE: 0.80, ... }
```

Two design choices worth calling out, because they shape every number below:

1. **Fail-closed.** Any detector error, timeout, or unparseable response routes the request LOCAL. For a privacy control, "I couldn't check it" must mean "keep it home", not "let it through".
2. **Noisy-OR is monotonic.** Signals can only *raise* the score. This matters for C2 later: an advisory LLM can add a signal, but it can mathematically never overrule the deterministic rules and *release* something they flagged.

## The "ciao" problem, or why I had to rebuild the Presidio image

Early smoke tests produced something embarrassing. The stock Presidio analyzer image models **English only**, and when you feed Italian text to an English spaCy pipeline, it doesn't politely decline -- it hallucinates. The single word:

```
ciao
```

was flagged as a `PERSON` entity, scoring 0.60 and pushing every casual Italian prompt over the threshold. *"ciao, aiutami a sviluppare un microservizio"* -- a completely benign coding request -- was being forced LOCAL. A privacy gate that cries wolf on the most common Italian greeting is a gate people will turn off, and a disabled privacy gate protects nobody.

The fix has two parts, one per image -- and note that they live in **two different pods**:

1. **A custom multilingual Presidio analyzer image** ([Containerfile](/files/privacy-plus-eval/containerfiles/presidio-multilang/Containerfile) + [nlp-config.yaml](/files/privacy-plus-eval/containerfiles/presidio-multilang/nlp-config.yaml)). It's a small delta on the community analyzer: `python -m spacy download it_core_news_md` at **build time**, so the Italian model sits alongside the bundled English `en_core_web_lg`, plus an NLP config declaring `supported_languages: [en, it]`. No runtime downloads -- which also means the analyzer pod needs **zero egress** (that matters later).
2. **Language detection in front of the NER call -- in the router pod, not in Presidio.** The scoring engine runs inside the LiteLLM pod, and that's where [fastText LID](https://fasttext.cc/docs/en/language-identification.html) lives: fastText is a compiled dependency plus a model file (`lid.176.ftz`, ~1 MB, sub-millisecond), so it can't ride in the ConfigMap that carries the Python hooks -- it gets its own custom LiteLLM image ([Containerfile](/files/privacy-plus-eval/containerfiles/litellm-fasttext/Containerfile)) that bakes the model at `/opt/models/lid.176.ftz`. On every request the engine detects the payload language and then:
   - **confident + supported language** -> query Presidio with *that* model only (cheap, precise -- this is the "ciao" fix: Italian text goes to the Italian model, which knows "ciao" is not a name);
   - **confident + unsupported language** -> configurable: `skip` C1 (rely on detectors A+B, which are language-agnostic regexes and bilingual lexicons) or `force_local`;
   - **uncertain** (short or mixed text) -> query **all** supported models and union the entities. For a privacy gate, "when unsure, check everything" is the right bias.

Both images are prebuilt and public, if you want to try this without building anything: [`quay.io/asalvati/presidio-analyzer-multilang:0.1`](https://quay.io/repository/asalvati/presidio-analyzer-multilang?tab=tags&tag=0.1) and [`quay.io/asalvati/litellm-privacy-plus:0.1`](https://quay.io/repository/asalvati/litellm-privacy-plus?tab=tags&tag=0.1).

After the fix, the two demo prompts behave the way a user would expect:

```bash
# Italian person name -> fastText detects 'it', Italian NER finds PERSON -> LOCAL
"Scrivi una lettera di ringraziamento per Mario Rossi."   ->  local-fast

# plain Italian greeting -> Italian model, no phantom PERSON -> SOTA
"ciao, aiutami a sviluppare un microservizio."            ->  sota-smart
```

One honest generalization from this detour: **a multilingual user base means per-language NER configuration** -- a model per language, plus decisions about what to do with languages you *don't* model. This lab deliberately scopes to **Italian and English only**, and the evaluation below tests exactly (and only) those two languages. If your users write in five languages, you have five of these problems.

A smaller trade-off inside the same decision: spaCy ships `it_core_news_md` (~43 MB) and `it_core_news_lg` (~700 MB, a few F1 points better on rare names, +0.5-1 GB resident RAM). On a CPU-only cluster already holding the large English model in memory, I ship `md` -- the recall gain of `lg` doesn't repay the RAM on this substrate, and switching later is a config-and-rebuild, not a redesign.

## The corpus: 332 cases × 2 languages

You cannot claim a privacy gate works because it caught your three demo prompts. I wrote an evaluation corpus of **332 cases per language** -- the [Italian](/files/privacy-plus-eval/privacy-plus-italian.yaml) and [English](/files/privacy-plus-eval/privacy-plus-english.yaml) files are published -- each case a realistic prompt with the routing it *should* get:

```yaml
- {id: health-01, category: health, expect: local,
   text: "The patient received a diabetes diagnosis; prepare the treatment plan."}
- {id: benign-12, category: benign, expect: sota,
   text: "Write an SQL query to count orders per month."}
- {id: implicit-03, category: implicit, expect: local,
   text: "I need help getting through a difficult separation from my husband."}
```

The categories are the interesting part:

| category | what it probes |
|---|---|
| `pii_strong` / `pii_invalid` | real identifiers vs **checksum-invalid lookalikes** (a card number that fails Luhn must NOT trigger) |
| `secret` | API keys, JWTs, private keys, password assignments |
| `health`, `finance`, `legal`, `hr` | sensitive topics with no formal PII |
| `person`, `location`, `combined` | NER territory |
| `implicit` | **keyword-less, PII-less, name-less** personally-sensitive prompts -- "help me tell a colleague he's no longer part of the team" |
| `implicit_benign` | the trap in the other direction: sounds confidential but is business/technical -- roadmaps, budgets -- and must **stay** SOTA |
| `benign`, `edge` | ordinary traffic and deliberate near-misses |

All PII in the corpus is **synthetic** (the checksums are valid, the people are not). The `implicit` category exists because that is where real privacy risk lives: most emotionally sensitive text about a human contains no regex-matchable token at all. And `implicit_benign` keeps the test honest -- a gate that routes *everything* LOCAL would ace `implicit` and be useless.

Every run in this post scores each of the 664 cases with the **real engine and the live policy** (the same code paths as production traffic, executed in the router pod against the in-cluster Presidio), and dumps one CSV row per case: [`data/`](/files/privacy-plus-eval/data/) holds the canonical runs, [`data-c1/`](/files/privacy-plus-eval/data-c1/) the NER-backend experiments.

## Headline numbers: the rules leak, badly

Three configurations, both languages ([`data/*.csv`](/files/privacy-plus-eval/data/)):

| configuration | lang | correct | **leaks** | false pos |
|---|---|---|---|---|
| rules only (A+B+C1) | EN | 227/332 (68%) | **101** | 4 |
| rules only (A+B+C1) | IT | 254/332 (77%) | **73** | 5 |
| + C2 Granite-2B | EN | 280/332 (84%) | **39** | 13 |
| + C2 Granite-2B | IT | 301/332 (91%) | **19** | 12 |
| + C2 Qwen-7B | EN | 286/332 (86%) | **42** | 4 |
| + C2 Qwen-7B | IT | 315/332 (95%) | **11** | 6 |

![Leaks and false positives per configuration](/images/privacy-plus-eval-leaks-by-config.png)

Three things jump out:

1. **Rules alone are not a privacy gate.** 174 pooled leaks (101 EN + 73 IT) means the deterministic stack -- validated regexes, curated lexicons, *and* a real NER service -- waves through nearly **half of the sensitive prompts**. If you take one number away from this post, take that one.
2. **The false-positive count stays civilized in every configuration** (4-13 out of ~140 benign cases per language). The gate fails almost exclusively in the dangerous direction -- which is exactly why you must measure leaks specifically, not "accuracy": a 68%-correct gate *sounds* mediocre; "it leaks nearly 1 in 2 sensitive prompts" sounds like what it is.
3. **English leaks more than Italian at every single configuration.** Consistently, and by a lot (101 vs 73; 42 vs 11). I did not expect that from an English-first NLP stack, and it's what pushed me into the NER experiments later in this post.

So where do 174 leaks come from? Break them down by category and the answer is unambiguous:

![Leaks per category, rules-only vs +C2](/images/privacy-plus-eval-leaks-by-category.png)

The structured categories behave: `pii_strong`, `secret` (mostly), `person`, `combined` are caught, and `pii_invalid` correctly does **not** fire -- the validators do their job. The rules die on **`implicit`**: 119 of the 174 pooled leaks are prompts whose sensitivity is *situational*, not lexical. "My marriage is ending and I need to tell the kids." No PII, no lexicon term, no named entity. Every rule scores it 0.00, and 0.00 routes SOTA.

You cannot regex your way out of this category. Which brings us to C2.

## C2: a small LLM as a second opinion -- with the rules staying sovereign

The C2 detector is an LLM classifier bolted onto the *end* of the chain, with three hard constraints that make it safe to add:

- **Gray-zone only.** It runs only when the rules are unsure (score below the threshold). Anything the rules already route LOCAL skips it entirely -- no cost, no new failure mode for the easy cases.
- **Advisory, monotonic.** Its verdict is just one more weighted signal into the noisy-OR. It can *raise* a 0.00 to 0.80; it can never lower a score or overrule detector A finding an IBAN. The deterministic rules remain the floor.
- **Fail-closed.** Timeout, error, unparseable JSON -> the gray-zone prompt is treated as sensitive.

```python
# code/privacy_scoring.py (excerpt) -- the whole C2 contract in four lines
if rules_score >= threshold or rules_score < gray_low:
    return []                          # rules already decided, or confident benign
...on any error/timeout/bad JSON:
    return [("classifier", "error", weight)]   # fail-closed: treat as sensitive
```

The classifier prompt is worth showing, because it encodes the one distinction the whole eval hinges on -- **personal-sensitive vs confidential-business**:

```text
Mark sensitive=true not only for explicit personal data (PII, health, finance,
legal, credentials) but also for SITUATIONAL personal matters even with NO
keyword: employment termination or someone leaving/losing their job;
disciplinary action, complaints or accusations about a person's conduct;
grief or bereavement; illness; family or marital difficulties...

Mark sensitive=false for: generic technical / coding / general-knowledge
questions, and CONFIDENTIAL-BUSINESS content that is not about a person's
private life (product launches, roadmaps, budgets, marketing) -- 'confidential'
business is NOT personal privacy.
```

The results are the difference between a demo and a defensible gate. Pooled leaks drop **174 -> 53** with Qwen-7B (**-70%**), and the `implicit` category goes **119 -> 4**. Crucially, the trap category holds: `implicit_benign` prompts (confidential *business*) were **not** dragged LOCAL -- with Qwen the false-positive count stays at rules-only levels (4 EN / 6 IT). The classifier learned the distinction the prompt teaches, not "when in doubt, hoard everything".

Two model-level observations from the table above:

- **Qwen2.5-VL-7B-Instruct** is the better classifier overall (53 pooled leaks, no FP cost). In the lab it is served by an external OpenAI-compatible endpoint, purely as a stand-in to validate the mechanism.
- **Granite-Vision-3.2 (2B)** -- a model **3.5× smaller** -- reaches 58 pooled leaks, at the cost of some benign over-flagging (13/12 FPs). And this is the number I care most about, because of what comes next: *the production version of C2 must be a small local model*, and the 2B-class result says that's viable, not aspirational.

### Why C2 must live inside the cluster

Stop and notice the irony of the lab setup: to decide whether a prompt is too sensitive to leave the cluster, I... sent it out of the cluster to an external classifier. For measuring recall/precision of the *mechanism*, fine -- the corpus is synthetic. As an architecture, it obviously **voids the guarantee it implements**. In production, C2 has to be a **local, trusted, fast** model, and OpenShift makes the "trusted" part enforceable rather than aspirational:

- **Latency budget.** The C2 call costs a median **~700 ms** in my runs, vs **~21 ms** for the whole rules path (see below) -- and let's be precise about what that number *is*: it is dominated by the **round-trip to the external endpoint**, not by model inference. That doesn't make it less real; it makes it the measured price of an *out-of-cluster* classifier, which is exactly the argument. It is tolerable *only* because C2 is gray-zone-only; make it a local in-cluster hop and the network share of those ~700 ms disappears -- latency you can spend on a slightly larger local model. A 2B model on modest hardware serves this fine: the classifier emits a ~20-token JSON verdict, not prose.
- **NetworkPolicy isolation.** An in-cluster classifier can be locked down the same way the Presidio analyzer already is in this lab: **deny all egress** (the model is baked into the image, it needs no outbound network, so inspected text *cannot* leave the pod at the network layer) and **allow ingress only from the router pod**. The component that reads your most sensitive prompts becomes a dead end for data:

```yaml
# same pattern as the Presidio analyzer's lockdown policy
spec:
  podSelector: { matchLabels: { app: c2-classifier } }
  policyTypes: [Ingress, Egress]
  ingress:
    - from: [ { podSelector: { matchLabels: { app: litellm } } } ]
      ports: [ { protocol: TCP, port: 8000 } ]
  # no egress: block -> ALL outbound traffic denied
```

- **Swap is config, not code.** The engine reads the classifier's `base_url` / `model` / key from a Secret. Pointing C2 at an in-cluster vLLM `InferenceService` instead of the external stand-in is a Secret change and a rollout -- the eval harness, policy, and engine don't change, so you can re-run this exact corpus before and after and *prove* the swap didn't regress the gate.

> **A war story: deny-all egress is a design constraint, not just a firewall rule.** Presidio's `EMAIL_ADDRESS` recognizer tries to *validate the domain* of every address it finds. With all egress denied, that lookup doesn't fail fast -- it hangs (~30 s observed), and since the analyzer image runs a **single sync gunicorn worker**, the stuck `/analyze` also starved `/health`: the liveness probe started killing the pod, restart count climbing into double digits. The tactical fix was gunicorn `gthread` + a worker `--timeout` (a stuck request now returns 500 and the engine **fail-closes** that one prompt, instead of the whole pod dying). But the real decision was the strategic one: **drop the email check rather than allow egress**. Email is weak PII in this policy (weight 0.40, below the 0.50 threshold -- it never routes LOCAL on its own), so the recognizer bought almost nothing; an egress allowance from the pod that reads every prompt would have cost the core guarantee. When a detector fights your isolation, weaken the detector, not the isolation.

![Rules path vs classifier call latency](/images/privacy-plus-eval-latency.png)

*(The chart deliberately pools Granite and Qwen into a single box: both sat behind the same external endpoint, so their per-model latency differences are noise -- this figure measures the cost of leaving the cluster, not model speed. The portable datum is the **~33× ratio** to the in-cluster rules path, not the absolute milliseconds.)*

One config note for reproducers: catching `implicit` cases requires running C2 even on prompts the rules score **0.00** (`gray_low: 0` in these runs) -- a keyword-less sensitive prompt *is* a zero-score prompt, and a positive `gray_low` would skip it as "confident benign". The price is a classifier call on every sub-threshold prompt; cheap once the model is local, another reason it should be.

### Is 0.50 the right threshold?

Since every CSV row carries its `privacy_score`, the threshold choice can be inspected rather than asserted -- sweep it and watch both error types:

![Leaks vs false positives across the decision threshold](/images/privacy-plus-eval-threshold-sweep.png)

The curves are step-shaped because the score is a noisy-OR of a few discrete weights, not a smooth probability -- and that's fine: the flat shelf between ~0.45 and ~0.50 means the operating point is **stable**, not knife-edge. The sweep also keeps the tuning honest: it shows exactly what moving the knob in either direction costs *on this corpus* -- and that the trade is not symmetric, so any per-team threshold override should be justified by a chart like this one, not by gut feeling.

There is, however, a case where tuning a score is simply the wrong tool: a team, application, or user that you *already know* will routinely handle privacy-sensitive matters (legal counsel, HR, healthcare workflows). The per-team threshold you saw in the policy excerpt (`legal: 0.30`) is the *soft* version of caution -- it still lets a score decide. For that kind of team, don't ask a classifier to be right every time: **take the decision away from the score entirely and force LOCAL**, via a `tiering` guardrail that pins the team to the local tier:

```yaml
tiering:
  legal: [local-fast]                  # legal team: LOCAL only, never SOTA
  research: [local-fast, sota-smart]
  _default: [local-fast, sota-smart]
```

For this to be a guarantee rather than a convention, the team identity must be **non-spoofable** -- and this is where the current setup improves on [Part 1](https://amedeos.github.io/openshift/2026/07/06/Routing-local-and-SOTA-LLMs-on-OpenShift-AI-part-1.html), where the demo trusted an `x-team` header sent *by the client* (any caller could have claimed to be `research` and shipped legal documents to the external provider). Now the tier is derived from **which API key authenticated**, at the gateway, using the [Part 2](https://amedeos.github.io/openshift/2026/07/06/Routing-local-and-SOTA-LLMs-on-OpenShift-AI-part-2.html) stack (Red Hat Connectivity Link): the `AuthPolicy` resolves the authenticated key's `maas-group` label and **injects** `x-team` itself, while the `HTTPRoute` **strips any client-supplied `x-team`** before it can reach the router:

```yaml
# AuthPolicy (excerpt) -- x-team comes from the KEY's label, not from the caller
response:
  success:
    headers:
      x-team:
        plain:
          expression: auth.identity.metadata.labels["maas-group"]
```

No score, no gray zone, no header to forge, no residual leak probability for that team -- the scoring engine described in this post is for the traffic where the answer genuinely isn't known in advance.

## The C1 experiments: trying to buy recall at the NER layer

That persistent EN > IT leak gap made me suspect the C1 layer -- maybe general-purpose spaCy NER (what Presidio uses by default) was the bottleneck, and a **purpose-trained multilingual PII model** would catch more. The engine only ever speaks Presidio's `/analyze` contract, so I wrote a ~150-line shim exposing that same contract in front of two candidates, and re-ran the **same 664 cases** with **zero engine changes** -- swap the URL, measure, done. (This is a deliberately boring integration story: define the detector boundary as an API contract and A/B-testing a component becomes an afternoon, not a fork.)

The candidates, both Apache-2.0:

| candidate | architecture |
|---|---|
| **OpenMed privacy-filter multilingual** | 1.4B MoE (Mixture-of-Experts; 50M active), token classification, 16 languages |
| **GLiNER2 privacy-filter PII** | 205M encoder, span extraction, 7 languages |

One mapping decision matters before the numbers make sense: these models emit their own label taxonomies, and I map **only the contextual entity types** (person, location, IP...) into the engine, dropping their structured-PII labels (card numbers, IBANs, national IDs). Why: detector A already validates those with real checksums, while a NER model happily tags a **checksum-invalid** card lookalike at 0.99 -- mapping those labels flipped every `pii_invalid` trap case into a false positive in the first run. Structured PII belongs to the validators; C1's job is only what A *cannot* see. (The `full` mapping runs are in the published CSVs if you want to see the damage.)

![C1 shootout — leaks per NER backend](/images/privacy-plus-eval-c1-shootout.png)

**OpenMed: discarded.** On English it is an exact photocopy of the spaCy baseline -- 101 leaks, same as Presidio, zero cases recovered, zero regressed. On Italian it is *worse*: 75 leaks *plus* doubled false positives (10 vs 5), driven by `PERSON`-hallucinations at 0.99 confidence on benign Italian nouns. Add 2.5-3× GLiNER2's latency at 7× its size, plus a `trust_remote_code` requirement (the model loads custom Python from its repo -- a supply-chain consideration all by itself for a privacy component), and there is no redeeming trade: discarded without ceremony. Negative results are results; this measurement cost one afternoon and prevents a much more expensive mistake.

**GLiNER2 (contextual mapping): the real challenger.** Rules-only leaks drop 101 -> 68 (EN) and 73 -> 57 (IT) -- a genuine recall gain over Presidio+spaCy at a seventh of OpenMed's size. Where it gets interesting is *composition*: with C2 stacked on top, the system reaches **30 EN / 9 IT** leaks (vs 42/11 for Presidio+C2 -- EN leaks down another 29%), and because a better C1 shrinks the gray zone, it does so with **about a third fewer C2 calls**. Better first-stage recall doesn't just catch more -- it makes the expensive stage cheaper. The cost is visible and honest: false positives rise from 4-6 to 11-12 per language, essentially all bare-`person` hits on role nouns ("the candidate", "my neighbor") -- the harmless direction, but real. A variant with the bare `person` label dropped (`gliner2-names` in the CSVs) removes those FPs and, in exchange, loses exactly the recall edge -- under C2 it converges back to Presidio's numbers. The relational/role mentions *are* where GLiNER2's value lives; you take them with the FPs or you don't take them at all.

**So why is Presidio still the default C1 in this lab?** Because "wins the benchmark" and "earns the slot" are different tests, and the trade-off is the image. The Presidio path is a well-known OSS service with official images, a documented multi-language mechanism, and a boring, reproducible customization story (bake spaCy models, done). Adopting GLiNER2 means building and *owning* a custom inference image for a niche model -- PyTorch base, weights baked at build time to preserve the no-egress guarantee, CPU latency still unproven on this GPU-less cluster (the shim runs used a desktop GPU), and every future security patch and model update is on me. For a lab whose next reader might be future-me, the measured decision is: **Presidio stays the default; GLiNER2-class models are the documented, quantified upgrade path** -- the numbers above say exactly what you'd buy and what it costs, when the recall requirement justifies owning that image.

## What this eval does NOT say

A privacy eval that oversells itself is worse than none, so, explicitly:

| it may look like... | it actually is |
|---|---|
| `privacy_score` is a probability | a **policy score** -- noisy-OR of hand-set weights. 0.80 means "strong signals fired", not "80% likely sensitive". Rank-ordering (threshold sweeps) is valid; calibration is not claimed. |
| a benchmark of models | a benchmark of **this gate on this corpus**. I wrote the 664 cases *and* the rules; some overfitting of the corpus to my own threat model is unavoidable. Your traffic differs. |
| production latency numbers | a CPU lab cluster and, for C2, an external stand-in endpoint. Medians (~21 ms rules, ~700 ms C2 call) are indicative of the *ratio*, not of your SLO (Service Level Objective) -- the latency target you'd commit to in production. |
| "the gate is 95% correct" | correctness on **synthetic, single-turn** prompts in **two languages** (IT/EN), with labels that encode *my* judgment of what should stay local. Multi-turn accumulation, adversarial rephrasing, and other languages are untested here. |
| a solved problem | one measured configuration. Every policy/prompt/model change moves these numbers -- which is the actual lesson: keep the corpus in CI and **re-run it on every change**, like any other regression suite. |

## Wrapping up

The one-sentence version of 664 test cases: **deterministic rules -- even with validators, curated lexicons, and a real NER service -- leaked 174 of 382 sensitive prompts, and a small advisory LLM in the gray zone cut that to 53, with a 2B local-viable model close behind.** The residual leaks are the most euphemistic implicit phrasings ("...tell a collaborator he won't be part of the team going forward"), which suggests the next cheap lever is a few targeted few-shot examples in the classifier prompt, not a bigger model.

What I'd take away as design rules, in order of how much they surprised me:

1. **Measure leaks, not accuracy.** The failure modes of a privacy gate are asymmetric; a single "correct%" number hides exactly the errors that matter.
2. **The implicit category is the whole game.** Anything lexical (PII, secrets, keywords) is table stakes; the sensitive prompts that hurt are the ones with no token to match. Only the semantic layer (C2) touched them -- and its **prompt** was a bigger lever than its parameter count.
3. **Keep the LLM advisory and the rules sovereign.** Monotonic scoring (raise-only), gray-zone-only invocation, fail-closed errors: these three constraints are what make it safe to put a probabilistic component inside a deterministic control.
4. **Language support is a real decision, not a default.** The "ciao" bug is what an unexamined English-only default looks like in production: a gate that erodes its own users' trust. Per-language models, an explicit unsupported-language policy, and *tests in every supported language* are the minimum.
5. **Define detector boundaries as API contracts.** The entire C1 shootout -- including confidently discarding a candidate -- cost a small shim and an afternoon of runs, because the engine never knew what was behind `/analyze`.

Data, corpora, engine code, policy, and the chart script are all in [`/files/privacy-plus-eval/`](/files/privacy-plus-eval/) -- if you rebuild something like this gate, steal the corpus first: writing the 664 cases was the most valuable part of the whole exercise.

Thanks for reading -- and, as always, this was a lab: tear it down when you're done.
