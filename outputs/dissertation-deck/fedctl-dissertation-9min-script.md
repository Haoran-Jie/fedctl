# Fedctl Dissertation Presentation: 7-Minute Script + Q&A Prep

## Overview Pass

The current exported deck has 14 slides and a tight research arc:

1. Title and thesis frame: heterogeneous FL needs deployment-aware evidence.
2. Rationale: simulation, homogeneous hardware, and heterogeneous hardware expose different effects.
3. fedctl lifecycle: Flower projects become reproducible, inspectable deployed runs.
4. fedctl controls: typed placement and network profiles make heterogeneity controllable.
5. Physical cluster: the worker pool makes real heterogeneous execution, repeatable deployment, shared-lab control, and extensible devices practical.
6. Submodel FL background: HeteroFL, FedRolex, and FIARSE address compute heterogeneity.
7. Asynchronous FL background: FedAsync, FedBuff, and FedStaleWeight address straggler timing.
8. Coverage mismatch: asynchronous submodel updates can have partial parameter coverage.
9. FedCover correction: coverage mass and capped gain correct observed under-covered deltas.
10. Weak-client inclusion: reduced-rate submodels include weak clients without full-model runtime.
11. Local submodel diagnostics: per-client submodel quality exposes fairness differences.
12. Asynchronous FL under stragglers: asynchronous FL helps only with genuine timing skew.
13. FedCover time to target: coverage correction improves target attainment and speedup.
14. Conclusions: evaluate model performance and deployment behaviour together.

## Main Script


Slide 1: Title

[Target: 0:25]

Good morning, I’m Haoran Jie. Today I am presenting fedctl: a testbed for evaluating heterogeneous federated learning as a deployed system.

⸻

Slide 2: Heterogeneous FL Needs Deployment-Aware Evaluation

[Target: 0:35]

Prior work has proposed many methods for heterogeneous FL, but most of them are evaluated in simulation or on homogeneous hardware.

In simulation, clients are often just data splits on the same device. In homogeneous deployments, clients may run on equal devices over one network.

But in real edge deployments, clients differ in hardware, networks, availability, and update timing. These differences affect not only model performance, but also runtime, participation, submodel quality, and fairness.

⸻

Slide 3: fedctl Run Lifecycle

[Target: 0:25]

To enable realistic evaluation of heterogeneous FL, I developed fedctl.

fedctl runs Flower projects on a heterogenous cluster. The project is packaged with configurations, submitted through a queue to the submit service, rendered into Nomad jobs to deploy, and executed across the cluster.

During execution, it records metrics, preserves logs and artifacts, and provides a web interface for inspection.
⸻

Slide 4: Controlling Heterogeneity

[Target: 0:30]

fedctl exposes two deployment-side controls for heterogeneity.

Typed client placement assigns logical clients to device classes, so user can control which devices run which clients.

Network impairment allows user to define network profiles like bandwidth, latency, and packet loss. Then applying those profiles to each clients, using linux traffic control. 

⸻

Slide 5: Physical Heterogeneous Cluster

[Target: 0:25]

This is the physical cluster behind those controls.

First, it makes experiments repeatable. I can run the same workload again with different device placements or network conditions and compare the results fairly.

Second, it simplifies running experiments on a shared cluster. Instead of manually connecting to devices and coordinating access, I can submit a run and let fedctl handle deployment, resource allocation, and result collection.

Third, it is easy to extend. If I add a new device type, such as NVIDIA Jetsons, I can use the same deployment and placement controls without changing the rest of the system.

⸻

Slide 6: Submodel FL for Compute Heterogeneity

[Target: 0:25]

The first method family is submodel FL for compute heterogeneity.

Compute heterogeneity means clients differ in processor speed and memory, so some devices cannot afford the same local workload as stronger clients. Submodel FL keeps one global model, but sends smaller parameter subsets to weaker devices.

HeteroFL uses fixed nested submodels, FedRolex rotates the selected window, and FIARSE selects parameters by importance.

⸻

Slide 7: Asynchronous FL for Straggler-Induced Heterogeneity

[Target: 0:25]

The second method family is asynchronous FL for straggler-induced heterogeneity.

In synchronous FL, one slow client can delay the whole round. Asynchronous FL avoids that wait, but now updates may be stale.

FedAsync applies each arrival immediately, FedBuff uses a buffer plus stale decay, and FedStaleWeight upweights stale replies.

⸻

Slide 8: Coverage Mismatch in Asynchronous Submodel FL

[Target: 0:25]

FedCover comes from combining these two families.

In asynchronous submodel FL, replies arrive at different times, cover different parameter blocks, and have different staleness. The coverage mismatch means some parameters receive more updates than others, and some may receive none.

As a result, the buffered update is not only smaller; it can point in a different direction from the full-coverage case.

⸻

Slide 9: FedCover Coverage Correction

[Target: 0:30]

FedCover is the server-side correction I propose for that coverage mismatch.

For each accepted reply, the server computes the usual stale-weighted buffer weight. Then, for each parameter, it sums only the weights of replies that actually contain that parameter. That gives the observed coverage mass.

FedCover then applies a capped gain to boost the under-covered parameters. 

⸻

Slide 10: Weak-Client Inclusion Without Full-Model Cost

[Target: 0:35]

The first evaluation asks how to include weak clients when they hold useful data.

Here, ten rpi4 clients hold valuable non-IID partitions. Case A excludes them, so it is fast, but it only uses five of the fifteen data partitions. Case B includes everyone with the full model, but it is much slower and more memory-intensive.

The reduced-rate cases keep all partitions while reducing the weak-client runtime. That is the practical value of submodel FL in this setting.

⸻

Slide 11: Local Submodel Performance Diagnostics

[Target: 0:35]

Here I evaluated whether reduced submodels are useful for the clients that receive them. I measured the local submodel performance on each client.

The show a fairness issue: for HeteroFL and FedRolex, smaller-rate clients often get weaker local submodels.

FIARSE mitigates this by producing higher and more balanced local submodel quality.
⸻

Slide 12: Asynchronous FL Under Stragglers

[Target: 0:35]

This slides tests asynchronous FL under different timing conditions.

In the homogeneous case, there is no major straggler problem. Since all clients have similar speed, FedAvg does not spend much time waiting, and it actually reaches the target faster than the asynchronous methods.

But in the mixed setting, slow clients create real waiting time. FedAvg has to wait for rpi4 clients each round, while FedAsync can keep updating as soon as replies arrive. That is why the result flips.

⸻

Slide 13: FedCover Improves Time to Target

[Target: 0:40]

Finally, I evaluate the combined setting.

The table compares synchronous HeteroFL, uncorrected Async-HeteroFL, and FedCover. Across different settings, FedCover reaches the task target fastest.

The ablation on the right further tests the mechanism: as the coverage correction becomes stronger, speedup generally increases.

This supports the claim that FedCover improves target time by correcting under-covered parameters, .

⸻

Slide 14: Conclusions

[Target: 0:30]

To conclude, heterogeneous FL should be evaluated through both model performance and deployment behaviour.

fedctl provides the repeatable testbed for doing that on real heterogeneous cluster. 

FedCover addresses the aggregation problem that appears when asynchronous updates are also partial.

## Timing Check

Total target time: `7:00`.

| Slide | Target |
|---|---:|
| 1 | 0:25 |
| 2 | 0:35 |
| 3 | 0:25 |
| 4 | 0:30 |
| 5 | 0:25 |
| 6 | 0:25 |
| 7 | 0:25 |
| 8 | 0:25 |
| 9 | 0:30 |
| 10 | 0:35 |
| 11 | 0:35 |
| 12 | 0:35 |
| 13 | 0:40 |
| 14 | 0:30 |

## Q&A Questions To Invite

### Why real hardware instead of simulation?
Because the dissertation claim is deployment-aware evaluation. Simulation can approximate algorithmic behaviour, but it often misses memory pressure, actual local execution time, dense-kernel overhead, slow-client exclusion, fast-client over-representation, and network-path effects.

### What does fedctl contribute beyond Flower?
Flower provides the FL roles and application framework. fedctl adds the reproducible deployment control plane around it: packaging, queueing, Nomad rendering, typed placement, network profiles, preserved configs, logs, metrics, artifacts, and web/CLI inspection.

### Why separate run config and deploy config?
The run config defines the scientific workload: task, model, method, partitioner, seed, and local budget. The deploy config defines the execution condition: device placement, resources, images, network profile, and submit settings. That separation prevents method comparisons from being confounded by hidden deployment changes.

### Why is final accuracy insufficient?
Final accuracy hides how the score was obtained. A method can look good by excluding weak clients, taking far longer, over-representing fast devices, producing unusable small submodels, or relying on unrealistic timing assumptions.

### Why does FIARSE improve quality but not necessarily speed?
FIARSE improves local submodel utility in the diagnostics, especially for low-rate clients. But in this deployment path, sparse masks are still executed through dense PyTorch kernels on Raspberry Pi CPUs. So the result separates submodel quality from the need for hardware-aware sparse execution.

### When is asynchronous FL beneficial?
It is beneficial when timing is genuinely heterogeneous. The homogeneous control shows FedAvg remains strong when clients complete at similar times. In mixed rpi4/rpi5 topologies, slow clients stretch synchronous rounds, and asynchronous FL can reduce time to target.

### What does FedStaleWeight fix?
It improves applied slow-device influence after slow replies arrive. It does not make slow clients arrive more often, and it does not solve all fairness effects from device-correlated data skew.

### What is FedCover's novelty?
FedCover targets the server-side aggregation problem in asynchronous submodel FL: accepted buffered replies can have different parameter coverage. It measures coverage mass per parameter block and applies a capped gain to observed under-covered deltas.

### Does FedCover improve fairness or target time?
The demonstrated result is target-time improvement. FedCover is not primarily a fairness method. Its mechanism is coverage-aware aggregation, not slow-client reweighting.

### What are the strongest threats to validity?
The workload and device set are bounded: CPU-only Raspberry Pis, selected datasets, controlled network profiles, and no full real-world trace replay. FIARSE speed also depends on the current dense-execution deployment path.

### What would you do next?
I would add trace-driven replay, broader workloads and devices, hardware-aware sparse submodel execution, and representation-aware asynchronous training.
