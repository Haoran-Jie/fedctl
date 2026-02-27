# FedCtl: A Heterogeneous Testbed for Realistic Federated Learning  
**Part III Project Proposal**  
**Haoran Jie (hj376), Robinson College**  
**Supervisor:** Nicholas D. Lane  
**Co-Supervisor:** Javier Fernandez-Marques  

---

## Abstract

This project tackles the challenge of evaluating federated learning in realistic, heterogeneous edge environments. Most existing studies rely on simulations or cloud clusters that overlook the network variability, hardware diversity, and failures found in real-world deployments.

To address this gap, we build a large-scale, reproducible cluster of Raspberry Pi and Jetson devices orchestrated by Nomad, and develop **fedctl**, a tool for managing and running distributed AI workloads.

By integrating network shaping and monitoring, the platform enables controlled experimentation on how system heterogeneity affects federated learning (FL) performance, providing a practical foundation for research on robust, real-world federated learning systems.

---

# 1. Introduction, Approach and Outcomes

The proliferation of edge devices such as Raspberry Pis and Jetson Orin modules has opened new opportunities for executing distributed AI workloads directly at the network edge. However, evaluating federated learning (FL) in such heterogeneous, resource-constrained environments remains challenging.

Much of the existing FL literature relies on simulations or homogeneous cloud clusters that fail to capture:

- Bandwidth variability  
- Computational diversity  
- Intermittent connectivity  
- Hardware failures  

This project addresses this gap by building a unified experimental platform for running and analysing FL across a large cluster of physical edge devices.

---

## Core Idea

Construct a scalable and reproducible **Mega Cluster of Devices for Distributed AI**, enabling controlled, systematic experimentation using real hardware.

### Cluster Components

- Management node  
- Raspberry Pi 5 boards  
- Jetson Orin units  
- Local network interconnection  
- Docker containerisation  
- Flower runtime  
- Nomad orchestration  

Nomad will manage:

- Scheduling  
- Device allocation  
- Process isolation  
- Fault recovery  

This allows the entire cluster to behave as a cohesive distributed AI testbed.

---

## fedctl: Federation Control Tool

A central contribution of the project is **fedctl**, a command-line orchestration tool for managing federated experiments.

### Key Features

- Device discovery  
- Federation grouping  
- Flower workload deployment  
- Controlled system/network variation  
- Multi-client per device support  
- Reproducible experiment launching  
- Monitoring & results collection via Nomad API  

---

## Network Heterogeneity & Fault Simulation

To study the impact of network variability and unreliability on FL performance, the project integrates network-simulation and impairment tools.

### Tools Used

- `tc/netem` → latency, jitter, bandwidth caps  
- Toxiproxy → packet loss, disconnections, transient failures  

These enable rigorous evaluation of:

- Convergence speed  
- System stability  
- Client fairness  
- Communication robustness  

---

## Expected Outcomes

- A fully operational heterogeneous distributed AI cluster  
- The fedctl orchestration tool  
- Monitoring stack (Prometheus + Grafana or equivalent structured metrics pipeline)  
- Reproducible benchmark experiments  
- Open-sourced benchmark suite and documentation  

Together, these outcomes provide a foundation for reproducible research on real-world federated learning systems and distributed AI under realistic edge-computing conditions.

---

# 2. Project Structure

---

## Phase 1: Infrastructure & Fabric Bring-Up

**Objective:** Build a reliable, reproducible, and heterogeneous distributed AI testbed spanning a management node and multiple edge devices (Raspberry Pi 5 and Jetson Orin), orchestrated via Docker and Nomad.

Tasks:

- Deploy heterogeneous cluster of Raspberry Pi 5 and Jetson Orin devices  
- Containerised Flower workloads  
- Nomad orchestration layer  
- Baseline monitoring pipeline (Prometheus/Grafana or structured metrics exports)  
- Baseline distributed AI workload validation  

Outcome: A reproducible multi-device testbed capable of running federated workloads under realistic resource constraints.

---

## Phase 2: Federation Control & Network/Scale Simulation

**Objective:** Develop the fedctl control plane to manage federations, impose network/topology constraints, and scale logical clients beyond physical devices.

Tasks:

- CLI architecture design  
- Nomad API integration  
- Logical client oversubscription  
- Controlled network shaping  
- Failure simulation (netem baseline, Toxiproxy optional extension)  

Outcome: A controllable, heterogeneous, failure-prone experimental platform.

---

## Phase 3: Benchmarking and Evaluation

**Objective:** Systematically evaluate convergence, robustness, fairness, and scalability of federated learning under controlled heterogeneity.

Metrics collected:

- Round time  
- Throughput  
- Accuracy  
- Client fairness  
- System stability  

Deliverables:

- Benchmark suite  
- Dashboards  
- Reproducible experiment descriptors  
- Documentation  

---

# 3. Workplan

---

## Weeks 1–2: Project Setup and Background Review

- Review Flower deployment runtime  
- Study Nomad orchestration model  
- Survey network-simulation tools  
- Finalise device inventory and topology  

---

## Weeks 3–4: Infrastructure and Device Preparation

- Flash and configure devices  
- Install Docker and NVIDIA Container Toolkit  
- Establish SSH connectivity  
- Baseline hardware profiling  

---

## Weeks 5–6: Flower Runtime Deployment

- Deploy Flower runtime  
- Validate with simple FedAvg task  
- Integrate Prometheus and Grafana  

---

## Weeks 7–8: Nomad Orchestration Integration

- Install Nomad cluster  
- Define job specifications  
- Validate scheduling and recovery  

---

## Weeks 9–10: fedctl Tool Design

Implement core commands:

- `discover`
- `deploy` / `configure`
- `run`
- `destroy`
- `submit`

Connect CLI to Nomad API.

---

## Weeks 11–12: Network Simulation Module

- Integrate `tc/netem`  
- Add Toxiproxy proxies (optional stretch)  
- Validate impairment behaviour  

---

## Weeks 13–14: Scaling and Multi-Client Simulation

- Enable oversubscription  
- Evaluate contention  
- Study scaling behaviour  

---

## Weeks 15–16: Monitoring and Data Collection

- Automate metric scraping  
- Archive logs and metadata  
- Ensure experiment reproducibility  

---

## Weeks 17–18: Benchmark Design

- Define heterogeneity tiers  
- Create YAML-based experiment descriptors  
- Standardise output structure  

---

## Weeks 19–20: Performance Evaluation

Analyse:

- Convergence behaviour  
- Robustness under impairment  
- Scalability across device classes  

---

## Weeks 21–22: Contingency and Refinement

- Address hardware/network issues  
- Improve cluster stability  
- Refine fedctl and dashboards  

---

## Weeks 23–24: Dissertation Drafting – Technical Chapters

- Write Methodology chapter  
- Document system design  
- Produce architecture diagrams  
- Describe orchestration and simulation mechanisms  

---

## Weeks 25–26: Dissertation Drafting – Evaluation and Submission

- Complete Evaluation, Discussion, and Conclusion  
- Finalise experiment results  
- Add appendices (Nomad jobs, CLI examples)  
- Proofread and prepare submission  

---

# 4. Implementation Alignment Update (as of 2026-02-26)

This section maps the proposal against the current implementation to keep scope and deliverables consistent.

## 4.1 What Matches the Proposal

1. Core cluster + orchestration stack is in place
   - Nomad and Docker deployment are automated via Ansible roles and inventory.
   - Node classes and scheduling constraints are used in deployment flows (`submit`, `link`, `node`).

2. fedctl orchestration tooling exists and is operational
   - `fedctl` supports end-to-end deployment workflows and a production submit path.
   - CLI help shows all commands, with `submit` listed first.

3. A central submit control plane is implemented
   - `submit_service` provides API-backed submission lifecycle management.
   - Queue dispatching, status transitions, cancellation, logs, inventory, and result reporting are implemented.
   - Token-based auth and ownership scoping are implemented (user/admin roles).

4. Network heterogeneity support is implemented at the `tc/netem` layer
   - `--net` policies are parsed and rendered into Nomad jobs.
   - Netem application is integrated in deployment rendering for experiment control.

## 4.2 What Does Not Yet Match the Original Proposal

1. Hardware heterogeneity is currently partial
   - Active inventory is Raspberry Pi-centric in current production inventory.
   - Jetson support exists in config/design, but Jetson-backed experimental runs are not yet a stable baseline.

2. Toxiproxy failure injection is not implemented
   - Proposal included Toxiproxy for disconnections/transient faults.
   - Current implementation focuses on `tc/netem`; Toxiproxy is still a planned extension.

3. Prometheus + Grafana integration is not complete
   - Proposal expected an integrated monitoring stack.
   - Current system has logs/artifacts/inventory visibility, but no finalized Prometheus/Grafana pipeline committed as a standard workflow.

4. Benchmark suite and evaluation packaging are not yet fully standardized
   - Proposal targeted reproducible benchmark descriptors and systematic evaluation outputs.
   - Current implementation supports execution and artifact capture, but benchmark matrix automation and reporting templates still need consolidation.

## 4.3 Scope Adaptation

To reflect actual progress and maximize dissertation value, project scope is adapted as follows:

1. Primary contribution focus
   - A reliable, submit-service-centered FL experiment platform on Nomad with queueing, ownership-aware auth, reproducible job mapping, and post-run log/result retention.

2. Secondary contribution focus
   - Controlled network heterogeneity via netem profiles integrated in deployment workflows.

3. Deferred/optional contribution
   - Toxiproxy-based fault injection as a V2 extension if time permits after evaluation baseline is complete.

---

# 5. Revised Next-Step Plan (Aligned to Original Phases)

The next step should now transition from "build core system" to "evaluation-grade experimentation".

## Step 2: Freeze Benchmark Protocol

Goal: complete the benchmark-design objective from Phase 3.

- Define 3-4 benchmark scenarios with fixed seeds and config:
  - baseline LAN
  - moderate network impairment
  - high network impairment
  - oversubscription stress case
- Standardize experiment descriptor format and output folder schema.
- Lock dataset/model/task versions for comparability.

## Step 3: Run Evaluation Campaign

Goal: produce dissertation-grade evidence.

- Execute repeated trials per scenario.
- Collect:
  - accuracy/convergence behavior
  - runtime/throughput
  - fairness/participation consistency
  - failure and recovery observations
- Summarize with tables + plots + reproducibility metadata.

## Step 4: Final Write-up Integration

- Update methodology chapter to reflect submit-first architecture.
- Explicitly document scope decision:
  - netem completed
  - Toxiproxy deferred (or added if completed later)
- Link final claims to benchmark evidence and operational logs/artifacts.

---

## Recommended Immediate Action

Start with **Step 2: Freeze Benchmark Protocol**, because it is the smallest remaining blocker between a working platform and a defensible evaluation chapter.
