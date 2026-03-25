# Dissertation Experiment Plan: `fedctl`, HeteroFL, and FedBuff

Updated: 2026-03-25

## 1. Purpose

This document is the working reference for the dissertation plan.

It reframes the dissertation around the system that was actually built:

- `fedctl` as the core systems contribution
- a heterogeneous Raspberry Pi cluster as the experimental platform
- HeteroFL as the main experimental study
- FedBuff-style buffered asynchronous aggregation as the extension study

This replaces the earlier `StratoFL`-style framing, which does not match the current implementation or testbed.

## 2. Recommended Dissertation Positioning

### 2.1 Proposed title

Suggested working title:

- `fedctl: A Framework for Evaluating Federated Learning on Heterogeneous Edge Clusters`

Alternative variants:

- `fedctl: Reproducible Federated Learning Evaluation on Heterogeneous Edge Devices`
- `Evaluating Federated Learning under Compute and Network Heterogeneity with fedctl`

### 2.2 Central research question

Recommended central question:

- How can federated learning be deployed and evaluated reproducibly on a heterogeneous edge cluster, and how do compute and network heterogeneity affect training efficiency and model utility?

### 2.3 Sub-questions

The dissertation can then be decomposed into three concrete sub-questions:

1. Systems question:
   - Can `fedctl` provide a reproducible, extensible, and observable framework for running federated learning experiments on heterogeneous edge hardware?
2. Compute heterogeneity question:
   - Does HeteroFL improve efficiency or utility relative to synchronous homogeneous baselines on mixed-capability devices such as `rpi4` and `rpi5`?
3. Network heterogeneity question:
   - Does buffered asynchronous aggregation improve efficiency or robustness under controlled network impairment relative to synchronous baselines?

## 3. Core and Extension Scope

The dissertation should have a strict split between core and extension scope.

### 3.1 Core scope

These are the parts that should be treated as essential and non-negotiable.

1. Build and document `fedctl` as the orchestration and experimentation framework.
2. Build and validate the heterogeneous edge testbed.
3. Support reproducible deployment, submission, monitoring, log retrieval, and experiment control.
4. Run the main HeteroFL study on mixed `rpi4` and `rpi5` clients.
5. Compare HeteroFL against strong synchronous baselines.

### 3.2 Extension scope

These are valuable additions, but should not be required for the dissertation to stand.

1. Add controlled network impairment studies using `netem`.
2. Implement buffered asynchronous aggregation inspired by FedBuff.
3. Evaluate whether buffered asynchronous aggregation helps under network asymmetry or straggler conditions.

### 3.3 Why this split is correct

This split is technically and academically defensible.

- HeteroFL directly matches the hardware available in the cluster.
- The `rpi4` and `rpi5` device mix gives a natural and concrete source of compute heterogeneity.
- FedBuff is relevant and interesting, but it is a larger algorithmic lift and is better presented as an extension enabled by the platform.
- This keeps the dissertation coherent: the main contribution is the platform and the primary evaluation is the most natural use of that platform.

## 4. Revised Aims

## 4.1 Core aims

Recommended core aims:

1. To design and implement `fedctl`, an extensible framework for deploying, scheduling, monitoring, and collecting results from federated learning experiments on heterogeneous edge devices.
2. To construct a reproducible heterogeneous Raspberry Pi testbed using `rpi4` and `rpi5` nodes, with device-aware scheduling, controllable networking, and reliable experiment execution.
3. To systematically evaluate the impact of compute heterogeneity on federated learning by comparing homogeneous synchronous baselines against HeteroFL on mixed-capability devices.
4. To quantify trade-offs in final utility, convergence speed, round duration, communication cost, and straggler effects under realistic edge-cluster conditions.

## 4.2 Extension aims

Recommended extension aims:

1. To extend `fedctl` with controlled network impairment support for latency, bandwidth, and packet-loss experiments.
2. To implement and evaluate buffered asynchronous aggregation inspired by FedBuff.
3. To assess whether buffered asynchronous aggregation improves time-to-accuracy and robustness under network heterogeneity relative to synchronous baselines.

## 5. Revised Contributions

Recommended contribution list for the dissertation:

1. `fedctl`, an extensible framework for orchestrating federated learning experiments on heterogeneous edge clusters.
2. A reproducible Raspberry Pi federated learning testbed with mixed `rpi4` and `rpi5` clients, device-aware placement, and controllable network conditions.
3. A systematic empirical study of HeteroFL on real heterogeneous edge hardware.
4. An extension study of buffered asynchronous aggregation under controlled network impairment.
5. Open-source deployment assets, orchestration logic, and experimental workflows for reproducible edge federated learning research.

## 6. Recommended Chapter Structure

The dissertation can keep the current chapter file layout, but the content should be rewritten to match the actual project.

### 6.1 `1_introduction.tex`

Purpose:
- introduce the problem
- motivate real-hardware FL evaluation
- state the research questions and aims
- summarize the key contributions

Recommended content:
- Why simulated FL is often insufficient for systems questions.
- Why edge clusters introduce realistic compute and network heterogeneity.
- Why reproducibility and orchestration are hard in practice.
- Why `fedctl` was built.
- Why HeteroFL is the natural main study.
- Why FedBuff is an appropriate extension.

### 6.2 `2_preparation.tex`

Purpose:
- provide the background required to understand the system and experiments

Recommended sections:
1. Federated learning fundamentals
2. Synchronous vs asynchronous FL
3. Compute heterogeneity in FL
4. Network heterogeneity in FL
5. HeteroFL background
6. FedBuff background
7. Edge systems and orchestration background
8. Network emulation background

Important note:
- non-IID data can still be discussed, but it should no longer be the dominant conceptual axis of the dissertation unless the experiments truly center it

### 6.3 `3_implementation.tex`

Purpose:
- explain what was built and how it works

Recommended sections:
1. `fedctl` overview
2. Cluster architecture
3. Provisioning and deployment
4. Nomad integration
5. Submit service and observability
6. Log retrieval and archival design
7. Device-aware scheduling and metadata
8. Network impairment support
9. HeteroFL integration
10. Buffered async / FedBuff-style extension integration

### 6.4 `4_evaluation.tex`

Purpose:
- present the experimental results in a staged, defensible order

Recommended structure:
1. Testbed validation
2. Device characterization
3. Main HeteroFL study
4. Network impairment sensitivity study
5. Buffered asynchronous aggregation extension
6. Threats to validity

### 6.5 `5_conclusions.tex`

Purpose:
- conclude with the systems contribution first, then the main empirical findings

Recommended sections:
1. What was built
2. What the main HeteroFL study showed
3. What the extension showed
4. Limitations
5. Future work

## 6.6 Chapter-to-aim mapping

This mapping is useful later when justifying structure.

| Chapter | Primary role | Main aims addressed |
| --- | --- | --- |
| `1_introduction.tex` | Motivation, framing, research questions, summary of contributions | all aims introduced |
| `2_preparation.tex` | Background on FL, heterogeneity, HeteroFL, FedBuff, and edge systems | supports all aims |
| `3_implementation.tex` | Design and implementation of `fedctl`, cluster, scheduling, logging, and experimental controls | Core Aim 1, Core Aim 2, Extension Aim 1, Extension Aim 2 |
| `4_evaluation.tex` | Empirical validation of platform, HeteroFL study, impairment study, and async extension | Core Aim 3, Core Aim 4, Extension Aim 2, Extension Aim 3 |
| `5_conclusions.tex` | Answer research questions, summarize evidence, state limitations and future work | all aims concluded |

## 7. Experimental Strategy Overview

The experiments should be run in phases. Each phase has a specific purpose and should not be merged conceptually with the others.

### Phase 0: Testbed validation

Goal:
- demonstrate that the platform itself is correct and reproducible before making FL claims

This is part of the core dissertation, not optional setup work.

### Phase 1: Device characterization

Goal:
- quantify the actual capability gap between `rpi4` and `rpi5`

This justifies the heterogeneity assumptions used later in HeteroFL.

### Phase 2: Main HeteroFL study

Goal:
- evaluate whether heterogeneous local model allocation improves efficiency and utility on mixed hardware

This is the main empirical study.

### Phase 3: Network impairment study

Goal:
- understand how controlled communication impairment affects FL behavior

This can be brief in core form and deeper in extension form.

### Phase 4: Buffered async / FedBuff extension

Goal:
- assess whether buffered asynchronous aggregation improves performance under network heterogeneity

This is the main extension study.

## 8. Phase 0: Testbed Validation

## 8.1 Objective

Before making algorithmic claims, the dissertation should establish that the experimental platform is valid.

This phase demonstrates that `fedctl` provides:

- reproducible deployment
- reliable experiment submission
- correct job placement
- usable observability and logs
- controllable network impairment

## 8.2 Questions answered

1. Can experiments be repeatedly deployed and executed with low failure rate?
2. Are job logs and results recoverable in a consistent way?
3. Are configured network impairments actually applied on the target interfaces?
4. Is the orchestration overhead small enough that later FL measurements remain meaningful?

## 8.3 Suggested experiments

### A. Deployment reproducibility

Repeat:
- deploy
- submit
- observe
- clean up

Track:
- success/failure count
- mean setup time
- mean teardown time
- number of manual interventions required

### B. Log and result collection validation

Validate:
- submit-service logs
- task stdout/stderr
- archived post-run logs
- reproducibility of log retrieval by job and task

### C. Network impairment fidelity

Apply known `netem` profiles and verify them with:
- `tc qdisc show`
- `ping`
- throughput measurement
- application-level round timing changes

## 8.4 Metrics

Recommended metrics:

- deployment success rate
- submission success rate
- orchestration overhead time
- log retrieval success rate
- observed latency vs configured latency
- observed throughput vs configured bandwidth cap

## 8.5 Expected outcome

This phase should justify the claim that the cluster is a credible experimental platform for the remaining chapters.

## 9. Phase 1: Device Characterization

## 9.1 Objective

Measure the practical performance gap between `rpi4` and `rpi5` under representative local training workloads.

This is necessary because HeteroFL assumes clients differ in compute capability in ways that matter to training.

## 9.2 Questions answered

1. How large is the training-speed gap between `rpi4` and `rpi5`?
2. Is the gap stable across repeated runs?
3. Does the gap justify assigning different model sizes or widths to the two device classes?

## 9.3 Suggested experiments

Run the same local training job on each device type under controlled conditions.

Recommended workloads:
- one small CNN or MLP workload
- one representative HeteroFL local training workload

Per device type, collect multiple runs.

## 9.4 Metrics

- time per local epoch
- samples per second
- local training completion time
- CPU utilization
- memory usage
- optional thermal indicators if available

## 9.5 Expected outcome

This phase should establish a concrete device capability hierarchy such as:

- `rpi5` can sustain a larger local model or wider subnetwork than `rpi4`
- synchronous training on equal model sizes produces measurable straggler effects

## 10. Phase 2: Main HeteroFL Study

This is the core experimental chapter.

## 10.1 Central question

Does HeteroFL improve training efficiency and/or utility on a mixed `rpi4` and `rpi5` cluster compared with homogeneous synchronous baselines?

## 10.2 Recommended methods

Use three methods.

### 1. Homogeneous FedAvg with full model

All clients train the same model.

Purpose:
- strong baseline
- exposes straggler behavior on slower devices

### 2. Homogeneous FedAvg with reduced model

All clients train a uniformly smaller model.

Purpose:
- fairer baseline when compute is constrained
- tests whether a global simplification is enough without HeteroFL

### 3. HeteroFL

Assign larger local model capacity to `rpi5` and smaller local model capacity to `rpi4`.

Purpose:
- main method under evaluation

## 10.3 Recommended datasets

Pick datasets that are defensible and tractable on the current cluster.

Recommended:
- `Fashion-MNIST` for a lighter, reliable baseline workload
- `CIFAR-10` for a more demanding workload

Reason:
- these are standard, easy to explain, and practical for repeated edge experiments

## 10.4 Recommended data partitions

Keep this simple.

Recommended:
- IID partitioning
- one non-IID partitioning setting, such as Dirichlet with `alpha = 0.3` or `0.5`

Reason:
- the primary axis here is device heterogeneity, not a full benchmark of statistical heterogeneity

## 10.5 Recommended device configuration

Main condition:
- mixed `rpi4` and `rpi5`

Optional reference conditions:
- `rpi5` only subset
- `rpi4` only subset

These reference conditions are useful if time permits, but the mixed cluster should remain the main focus.

## 10.6 Metrics

Primary metrics:
- final test accuracy
- time-to-target accuracy
- round duration
- end-to-end runtime

Secondary metrics:
- per-client training time
- straggler gap per round
- communication volume
- client completion rate
- round duration variance

## 10.7 Hypotheses

Recommended hypotheses:

1. Homogeneous full-model FedAvg will suffer from straggler effects on mixed hardware.
2. Homogeneous reduced-model FedAvg will improve round time but may sacrifice utility.
3. HeteroFL will reduce round time and improve time-to-accuracy relative to homogeneous full-model FedAvg.
4. HeteroFL will outperform homogeneous reduced-model FedAvg when compute heterogeneity is significant.

## 10.8 Recommended core matrix

Keep the run matrix manageable.

Recommended main matrix:

- datasets: 2
- partition settings: 2
- methods: 3
- seeds: 3

Total:
- `2 x 2 x 3 x 3 = 36 runs`

This is large enough to be meaningful and still feasible on the cluster.

## 10.9 Concrete core experiment matrix

This is the recommended minimum matrix for the dissertation body.

| Axis | Values |
| --- | --- |
| Datasets | `Fashion-MNIST`, `CIFAR-10` |
| Partition settings | `IID`, `Dirichlet(alpha=0.3 or 0.5)` |
| Methods | `FedAvg-full`, `FedAvg-small`, `HeteroFL` |
| Seeds | `3` |
| Cluster condition | mixed `rpi4` + `rpi5` |

Recommended reporting table:

| Dataset | Partition | Method | Final accuracy | Time-to-target | Mean round time | Mean straggler gap |
| --- | --- | --- | --- | --- | --- | --- |
| Fashion-MNIST | IID | FedAvg-full |  |  |  |  |
| Fashion-MNIST | IID | FedAvg-small |  |  |  |  |
| Fashion-MNIST | IID | HeteroFL |  |  |  |  |
| Fashion-MNIST | Dirichlet | FedAvg-full |  |  |  |  |
| Fashion-MNIST | Dirichlet | FedAvg-small |  |  |  |  |
| Fashion-MNIST | Dirichlet | HeteroFL |  |  |  |  |
| CIFAR-10 | IID | FedAvg-full |  |  |  |  |
| CIFAR-10 | IID | FedAvg-small |  |  |  |  |
| CIFAR-10 | IID | HeteroFL |  |  |  |  |
| CIFAR-10 | Dirichlet | FedAvg-full |  |  |  |  |
| CIFAR-10 | Dirichlet | FedAvg-small |  |  |  |  |
| CIFAR-10 | Dirichlet | HeteroFL |  |  |  |  |

## 11. Phase 3: Network Impairment Study

This phase studies communication heterogeneity directly.

## 11.1 Objective

Understand how FL performance changes when communication conditions are degraded in a controlled way.

## 11.2 Questions answered

1. How sensitive is synchronous FL to latency and bandwidth impairment?
2. Are some methods more robust than others under asymmetric network conditions?
3. Does compute-aware heterogeneity management remain useful when communication becomes the bottleneck?

## 11.3 Methods

Recommended methods:
- homogeneous FedAvg full model
- homogeneous reduced-model FedAvg
- HeteroFL

## 11.4 Network profiles

Keep the profiles simple and defensible.

Recommended profiles:
1. `none`
2. `mild latency`
3. `moderate latency`
4. `asymmetric latency`
5. optional `bandwidth cap`
6. optional `packet loss`

The most important conditions are:
- no impairment baseline
- moderate impairment
- asymmetric impairment

## 11.5 Metrics

Primary metrics:
- time-to-accuracy
- round duration
- end-to-end runtime

Secondary metrics:
- idle time at server and fast clients
- round duration variance
- communication throughput
- failed or delayed rounds

## 11.6 Expected outcome

Likely expected pattern:
- synchronous FL degrades as latency asymmetry increases
- HeteroFL may still help with compute bottlenecks but cannot remove communication bottlenecks

## 11.7 Compact impairment matrix

Recommended compact matrix:

| Axis | Values |
| --- | --- |
| Dataset | `Fashion-MNIST` or one faster representative workload |
| Methods | `FedAvg-full`, `FedAvg-small`, `HeteroFL` |
| Profiles | `none`, `moderate latency`, `asymmetric latency` |
| Seeds | `3` |

Total recommended size:
- `1 x 3 x 3 x 3 = 27 runs`

This is enough to show the systems effect without consuming the whole schedule.

## 12. Phase 4: Buffered Async / FedBuff Extension

This is the main extension study.

## 12.1 Objective

Evaluate whether buffered asynchronous aggregation improves efficiency under communication heterogeneity.

## 12.2 Central question

Does a buffered asynchronous FL method improve time-to-accuracy or robustness under network impairment relative to synchronous baselines?

## 12.3 Recommended methods

Compare:
- synchronous FedAvg baseline
- HeteroFL baseline
- buffered asynchronous aggregation inspired by FedBuff

## 12.4 Recommended scope

Do not explode the matrix here.

Recommended scope:
- one dataset
- one or two partition settings
- two or three network profiles
- three seeds

This is enough for a strong extension without taking over the whole dissertation.

## 12.5 Metrics

Primary metrics:
- final test accuracy
- time-to-target accuracy
- end-to-end runtime

Secondary metrics:
- update staleness
- buffer waiting time
- server throughput
- client utilization
- fraction of stale updates incorporated

## 12.6 Hypotheses

Recommended hypotheses:

1. Buffered asynchronous aggregation will help most under network asymmetry.
2. The benefit may be small or absent under low-latency stable networking.
3. Buffered async may trade off freshness for throughput, creating a utility vs speed trade-off.

## 12.7 Recommended extension matrix

| Axis | Values |
| --- | --- |
| Dataset | `Fashion-MNIST` or the most stable dataset from Phase 2 |
| Partition settings | `IID` and optionally one non-IID setting |
| Methods | `FedAvg-full`, `HeteroFL`, `FedBuff-style buffered async` |
| Profiles | `none`, `asymmetric latency`, optional `bandwidth cap` |
| Seeds | `3` |

Keep this smaller than the core HeteroFL matrix. The aim is to make one convincing extension argument, not a second dissertation.

## 13. Recommended Evaluation Chapter Layout

A strong `4_evaluation.tex` structure would be:

### 4.1 Testbed validation

Purpose:
- demonstrate platform correctness and reproducibility

### 4.2 Device characterization

Purpose:
- quantify the `rpi4` versus `rpi5` capability gap

### 4.3 Main HeteroFL study

Purpose:
- present the core compute heterogeneity results

### 4.4 Network impairment sensitivity

Purpose:
- show how communication heterogeneity affects the baselines and HeteroFL

### 4.5 Buffered asynchronous extension

Purpose:
- test whether FedBuff-style buffering helps under impaired links

### 4.6 Threats to validity

Purpose:
- state the limitations explicitly

## 14. Threats to Validity

This section should be planned early, because it constrains how strong the claims can be.

Recommended threats to discuss:

1. Small-scale physical cluster
   - the cluster is realistic but not internet-scale
2. Hardware scope
   - results apply to the tested `rpi4` and `rpi5` classes, not all edge devices
3. Workload scope
   - chosen datasets may not capture all FL workloads
4. Controlled networking
   - `netem` captures important impairment types, but not the full complexity of real internet paths
5. Implementation scope
   - the buffered async method is a practical implementation inspired by FedBuff, not necessarily a full reproduction of every paper detail

## 15. Recommended Minimal Deliverables

These are the minimum deliverables the dissertation should be able to claim.

### Core deliverables

1. `fedctl` framework with documented orchestration workflow
2. Heterogeneous edge cluster with reproducible provisioning
3. Main HeteroFL experiment results on mixed hardware
4. Reproducible experiment configurations and logs

### Extension deliverables

1. Controlled network impairment support
2. Buffered asynchronous FL implementation
3. Comparative evaluation under impairment

## 15.1 Success criteria

The dissertation should be considered successful if the following are true.

### Core success criteria

1. `fedctl` can reproducibly deploy, run, and collect results from FL workloads on the cluster.
2. The cluster supports mixed `rpi4` and `rpi5` scheduling with stable metadata and log retrieval.
3. Device characterization shows a measurable and defensible compute gap between `rpi4` and `rpi5`.
4. The main HeteroFL study completes with repeated runs and yields analyzable results for at least one standard dataset and one mixed-hardware condition.
5. The evaluation supports a concrete conclusion about the usefulness or limits of HeteroFL on this platform.

### Extension success criteria

1. `netem`-based network profiles can be applied and validated on the experimental path.
2. A buffered asynchronous method can be run end-to-end through the same platform.
3. At least one controlled comparison between synchronous and buffered asynchronous FL is completed under impaired networking.

## 16. Suggested Figure and Table Plan

This section is useful later when writing.

### Suggested implementation figures

1. `fedctl` system architecture
2. Cluster topology and node roles
3. Submission and log retrieval workflow
4. Network impairment control path

### Suggested evaluation figures

1. Device characterization plot: `rpi4` vs `rpi5` local training speed
2. HeteroFL main result: time-to-accuracy curves
3. Round duration boxplots by method
4. Straggler gap comparison by method
5. Network impairment sensitivity plots
6. Buffered async vs synchronous comparison under asymmetry

### Suggested tables

1. Cluster inventory and device classes
2. Experiment method matrix
3. Metrics collected per phase
4. Summary of main findings

## 17. Recommended Appendix Structure

The appendices should support reproducibility and reduce clutter in the main text.

Recommended appendices:

- `Appendix_Cluster_Inventory.tex`
- `Appendix_Deployment_and_Provisioning.tex`
- `Appendix_Network_Profiles.tex`
- `Appendix_HeteroFL_Configuration.tex`
- `Appendix_FedBuff_Configuration.tex`
- `Appendix_Experiment_Commands.tex`
- `Appendix_Unit_Tests.tex`

## 18. Practical Run Plan

This is the recommended practical sequence for carrying out the work.

### Step 1: Lock the dissertation framing

Decide that the dissertation is fundamentally about:
- building `fedctl`
- validating the platform
- evaluating HeteroFL on heterogeneous hardware
- extending with FedBuff under impairment

### Step 2: Finish platform validation artifacts

Ensure the system can cleanly support:
- deployment
- submission
- logging
- result retrieval
- impairment control

### Step 3: Run device characterization

Collect the benchmark evidence needed to justify device-type-aware heterogeneous training.

### Step 4: Run the core HeteroFL matrix

This is the highest-priority experiment block.

### Step 5: Run a compact impairment study

Show that communication heterogeneity materially affects the system.

### Step 6: Run the buffered async extension

Keep this constrained and clearly labeled as an extension.

## 18.1 Recommended execution order by priority

If time becomes constrained, prioritize in this exact order:

1. `fedctl` platform correctness and chapter-ready implementation evidence
2. device characterization
3. core HeteroFL matrix on one dataset
4. expansion of HeteroFL matrix to a second dataset or second partition setting
5. compact impairment study
6. buffered async extension

This ordering protects the dissertation core if the extension slips.

## 18.2 Writing order recommendation

The most practical writing order is not chapter order.

Recommended writing order:

1. `3_implementation.tex`
2. `4.1` testbed validation and `4.2` device characterization
3. `4.3` main HeteroFL study
4. `1_introduction.tex`
5. `2_preparation.tex`
6. `4.4` and `4.5` extension sections
7. `5_conclusions.tex`

Reason:
- the implementation and evaluation sections depend least on unresolved framing
- once those are solid, the introduction and conclusion become easier to write accurately

## 19. What Not to Do

These scope failures should be avoided.

1. Do not try to fully reproduce every claim from both HeteroFL and FedBuff.
2. Do not make large-scale mobile FL claims from a small edge cluster.
3. Do not let the extension dominate the dissertation at the expense of the platform and main study.
4. Do not let the dissertation drift back into the earlier `StratoFL` drug-discovery framing unless the actual implementation and experiments support that.

## 20. Final Summary

The dissertation should be argued in this order:

1. Real-world federated learning evaluation needs better experimental infrastructure.
2. `fedctl` provides that infrastructure on a heterogeneous edge cluster.
3. The cluster enables a main study of compute heterogeneity using HeteroFL.
4. The same platform also enables an extension study of communication heterogeneity and buffered asynchronous aggregation.

In short:

- core systems contribution: `fedctl`
- core experiment: HeteroFL on mixed `rpi4` and `rpi5`
- extension experiment: FedBuff-style buffered async under `netem`

This is the cleanest, most coherent, and most defensible dissertation plan for the project in its current state.
