# Flower Monthly fedctl Talk Script

Target: 10 minutes total.

- Slides 1-10: about 6 minutes.
- Live demo: about 4 minutes.
- Style: informal preview, not a dissertation defense. Do not explain FL basics in depth; this audience already knows Flower and the usual FL motivation.

## One-Sentence Throughline

`fedctl` is a tool for taking ordinary Flower projects and running them on a shared Raspberry Pi edge cluster, where device type, placement, network conditions, logs, and artifacts are explicit parts of the experiment rather than ad hoc cluster work.

## Slide 1: fedctl

Hi everyone, I am Samuel. I am going to give a very short preview of a tool I have been building called `fedctl`.

The short version is: `fedctl` lets you take a normal Flower project and submit it to a shared Raspberry Pi cluster. The reason I care about that is that federated learning is usually motivated by real distributed systems, but a lot of experimentation still happens in a purely local or simulated setup.

So the talk is not really about a new FL algorithm. It is about the control plane around Flower that makes real-device experiments easier to run, share, and inspect.

## Slide 2: Federated Learning Runs on Real Systems

The starting point is the usual FL motivation: data often cannot just be moved into one central place because of privacy, governance, ownership, bandwidth, or institutional boundaries.

But once clients are remote, the client is no longer just a dataset partition. It is also a device. It has a CPU, memory pressure, a network path, and some availability pattern.

That means two runs can use the same algorithm and the same dataset split, but have different timing behavior. Some clients finish later, some updates arrive in a different order, and the same final accuracy can have a very different wall-clock cost.

For me, that is the motivation for running Flower projects on actual devices, not only as local processes.

## Slide 3: Heterogeneity Changes the Training Loop

The dissertation framing separates two axes.

The first is compute heterogeneity. A Raspberry Pi 4 and a Raspberry Pi 5 can run the same client code, but they have different compute budgets. A smaller device might train more slowly, or it might need a smaller local model. So the deployment condition affects both runtime and the quality of what can actually be deployed on that device.

The second is network and availability heterogeneity. This changes when updates arrive. In synchronous FL, slow clients can dominate round time. In asynchronous FL, fast clients can appear more often or with less staleness.

The important thing for `fedctl` is that these conditions should be explicit. I want to be able to say: this run used this device mix, this placement policy, and this network profile, rather than discovering those details after the fact.

## Slide 4: Simulation Hides Deployment Effects

Simulation is very useful, and I am not arguing against it. But it often hides the exact things I want to measure here.

If every client is just a local process, timing is either homogeneous, or it is injected as a model. That is good for algorithm development, but it does not tell you what happens when the clients are actually different machines.

On a real edge-style testbed, slow devices, bandwidth limits, queueing, logs, and failures are all visible. The problem is that this can quickly become cluster operations rather than FL research.

So the question becomes: can we make this kind of testbed accessible to Flower users without asking every user to hand-write scheduler jobs and debug infrastructure?

## Slide 5: A Shared Raspberry Pi Testbed Is Feasible

This is the current hardware pool: 50 Raspberry Pi workers, split into 30 Raspberry Pi 4s and 20 Raspberry Pi 5s.

That is big enough to run non-trivial edge-style FL experiments, but still small and concrete enough that we can reason about the system.

The hard part is not only owning the devices. The hard part is sharing them. Multiple researchers need to queue work, request typed slices like "give me some RPi4s and some RPi5s", repeat a run under the same conditions, and inspect what happened afterwards.

That is the gap `fedctl` fills.

## Slide 6: Submitting Flower Projects to the Cluster

At a high level, the workflow is: submit, deploy, inspect.

The user starts with a Flower project. `fedctl` packages it, builds or selects the run image, sends a submission to the submit service, and then the cluster side renders and starts the Nomad jobs.

After that, the user can inspect the run through the CLI or through the web UI. The key point is that the user does not need to manually translate the Flower project into cluster jobs.

The Flower project remains the thing the researcher works on. `fedctl` wraps the system mechanics around it.

## Slide 7: High-Level Execution Stack

This is the execution stack.

On the left, there are two specifications. The run config is Flower-facing: model, task, partitioner, method, hyperparameters, seed, evaluation choices. The deploy config is system-facing: device counts, placement policy, resource requests, registry settings, and network profiles.

In the middle is the control plane: the CLI, submit service, registry, Nomad renderer, and submit runner. This is the part that turns a user submission into a scheduled distributed Flower run.

Then Flower runs in its normal distributed roles, with SuperLink and SuperNodes, plus the user's app code.

On the right, observability collects metrics, artifacts, and logs. For a shared cluster this is important, because if a run fails or behaves oddly, you need evidence after the terminal session is gone.

## Slide 8: Two Configs Keep the Experiment and the System Separate

The reason for splitting run config and deploy config is reproducibility.

If I change an FL method, that belongs in the run config. If I change the device mix from 10 RPi4s and 10 RPi5s to all RPi5s, that belongs in the deploy config.

That means the same learning experiment can be moved across topologies, and the same topology can be reused for different methods.

This also makes the demo simpler: I can submit the same Flower project, but change how many RPi4 and RPi5 workers it gets, or add network constraints, without editing the training code.

## Slide 9: Placement and Network Conditions Are Explicit

Here the important bit is that logical clients are mapped onto typed workers.

So I can ask for, say, RPi4 clients and RPi5 clients separately, and those assignments are recorded. This lets us connect algorithm behavior back to the deployment condition.

The same idea applies to network profiles. A profile can describe delay, jitter, loss, or bandwidth limits, and it can be assigned per logical client or per device type.

For Flower users, the useful part is that this becomes a config or CLI option, not an SSH session on every machine.

## Slide 10: What fedctl Makes Possible

So the summary is three things.

First, use real devices. You can start from a normal Flower project and run it on Raspberry Pi workers rather than local processes.

Second, share the cluster. The submit service queues work across users and lets people request typed slices from the 30 RPi4 plus 20 RPi5 pool.

Third, change the deployment conditions. Placement, resources, network profiles, logs, configs, and artifacts are all part of the recorded run.

The useful part is not just having a cluster. It is making that cluster usable as a repeatable Flower workflow.

## Slide 11: Demo

Transition:

I will switch to a quick demo now. The flow is: install `fedctl` and Flower, create a Flower quickstart project, register a token, submit a run, check status and logs from the CLI and UI, then show how the deploy config controls device mix and network conditions.

### Demo Commands

Install:

```bash
python -m pip install fedctl flwr
```

Create a Flower project:

```bash
flwr new @flwrlabs/quickstart-pytorch
cd quickstart-pytorch
```

Register a submit-service token:

```bash
fedctl submit register-token --name <username>
```

Say:

This saves a user-scoped bearer token locally, so future submit commands can authenticate without pasting a token every time.

Submit the project:

```bash
fedctl submit run .
```

Say:

This packages the Flower project, sends it to the submit service, and streams the submit-runner output while the cluster starts the jobs.

Check the queue and status:

```bash
fedctl submit ls --active
fedctl submit status <submission-id>
```

Inspect logs:

```bash
fedctl submit logs <submission-id> --job submit --follow
fedctl submit logs <submission-id> --job superlink --stderr
fedctl submit logs <submission-id> --job supernodes --index 1
```

Open the UI:

```text
http://fedctl.cl.cam.ac.uk
```

Say:

The UI is the same information for people who do not want to keep everything in the terminal: queue state, run details, logs, nodes, and results.

Show device and network controls:

```bash
fedctl submit run . \
  --supernodes rpi4=2 \
  --supernodes rpi5=2
```

Then show a deploy-config-backed version:

```bash
fedctl submit run . \
  --deploy-config path/to/deploy.yaml
```

Then show network overrides:

```bash
fedctl submit run . \
  --deploy-config path/to/deploy.yaml \
  --net 'rpi4[*]=med' \
  --net 'rpi5[*]=none'
```

Say:

The deploy config is where the system choices live. It can define the device counts, resource requests, placement behavior, and named network profiles. The `--net` flags are just a convenient override for assigning those profiles from the command line.

Close:

That is the main idea: a normal Flower project goes in, but the run comes out with explicit device placement, network conditions, queue state, logs, and artifacts. For me, this makes real-device FL experiments much easier to share and repeat.

## If the Demo Is Slow

Use this fallback wording:

The cluster submission can take a little while because it is building or pulling images and waiting for placement. The important thing to notice is the submission record: even if I close the terminal, the run remains visible in the UI, with logs and artifacts attached to that submission.

Then show:

```bash
fedctl submit ls --active
fedctl submit status <known-submission-id>
fedctl submit logs <known-submission-id> --job submit
```

## Timing Guardrails

- Slide 1: 30 seconds.
- Slides 2-4: 2 minutes total.
- Slides 5-7: 2 minutes total.
- Slides 8-10: 1.5 minutes total.
- Demo: 4 minutes.
- Closing sentence: 15 seconds.

If running late, skip detailed explanation of Slide 7 and move straight to the demo. The stack diagram is useful as a mental model, but the demo proves the tool.
