# Federated Learning Literature Review for Dissertation Citation Expansion

This note collects papers that can strengthen the dissertation's references, especially in the introduction, background, related work, and future-work discussion. The emphasis is on papers that support the dissertation's main framing: federated learning as a deployed systems problem where statistical heterogeneity, client-capacity heterogeneity, update-timing heterogeneity, and observability must be measured together.

## Recommended High-Priority Additions

### 1. Towards Federated Learning at Scale: System Design

**What it does.** Bonawitz et al. describe a production-scale FL system for mobile devices, including orchestration, client eligibility, task scheduling, aggregation, robustness, and practical open problems. It is one of the strongest systems references for arguing that FL is not just an optimizer but an end-to-end distributed training system.

**Relation to this project.** `fedctl` is a smaller, research-facing control plane rather than a production mobile-FL platform, but many motivations overlap: task orchestration, client availability, failure handling, system metrics, and a need for reproducible execution evidence.

**How to add it.** Use in the introduction when motivating why raw FedAvg-style algorithms are insufficient for deployed FL. Also cite in the implementation chapter when explaining why `fedctl` stores run/deploy configs, logs, artifacts, queue state, and deployment metadata.

**Source.** <https://proceedings.mlsys.org/paper_files/paper/2019/hash/7b770da633baf74895be22a8807f1a8f-Abstract.html>

```bibtex
@inproceedings{bonawitz2019towards,
  title     = {Towards Federated Learning at Scale: System Design},
  author    = {Bonawitz, Keith and Eichner, Hubert and Grieskamp, Wolfgang and Huba, Dzmitry and Ingerman, Alex and Ivanov, Vladimir and Kiddon, Chlo{\'e} and Kone{\v{c}}n{\'y}, Jakub and Mazzocchi, Stefano and McMahan, H. Brendan and Van Overveldt, Timon and Petrou, David and Ramage, Daniel and Roselander, Jason},
  booktitle = {Proceedings of Machine Learning and Systems},
  volume    = {1},
  pages     = {374--388},
  year      = {2019},
  url       = {https://proceedings.mlsys.org/paper_files/paper/2019/hash/7b770da633baf74895be22a8807f1a8f-Abstract.html}
}
```

### 2. LEAF: A Benchmark for Federated Settings

**What it does.** LEAF provides benchmark datasets, data partitions, and evaluation tooling for FL, meta-learning, and multi-task learning under naturally heterogeneous user data.

**Relation to this project.** The dissertation currently uses CIFAR-10 and tabular tasks rather than LEAF's core datasets, but LEAF is important background for why FL benchmarks need user-level partitions and reproducible evaluation protocols.

**How to add it.** Cite in the background section on statistical heterogeneity and in related work when explaining that many FL evaluations start from benchmark partitions, while this dissertation adds real hardware and deployment controls.

**Source.** <https://arxiv.org/abs/1812.01097>

```bibtex
@article{caldas2018leaf,
  title         = {{LEAF}: A Benchmark for Federated Settings},
  author        = {Caldas, Sebastian and Duddu, Sai Meher Karthik and Wu, Peter and Li, Tian and Kone{\v{c}}n{\'y}, Jakub and McMahan, H. Brendan and Smith, Virginia and Talwalkar, Ameet},
  journal       = {CoRR},
  volume        = {abs/1812.01097},
  year          = {2018},
  eprint        = {1812.01097},
  archivePrefix = {arXiv},
  url           = {https://arxiv.org/abs/1812.01097}
}
```

### 3. FedScale: Benchmarking Model and System Performance of Federated Learning at Scale

**What it does.** FedScale combines realistic FL datasets with a scalable runtime and system traces for benchmarking model and systems performance.

**Relation to this project.** FedScale is a natural comparison point for `fedctl`: both argue that FL evaluation should include system behavior, not only final accuracy. The distinction is that FedScale supports large-scale benchmarking and emulation, while `fedctl` focuses on controlled real Raspberry Pi deployments with typed placement and network impairment.

**How to add it.** Use in the introduction's "unanswered questions" paragraph and background platform requirements. It supports the claim that realistic FL evaluation needs data, device, network, and availability dimensions.

**Source.** <https://proceedings.mlr.press/v162/lai22a.html>

```bibtex
@inproceedings{lai2022fedscale,
  title     = {{FedScale}: Benchmarking Model and System Performance of Federated Learning at Scale},
  author    = {Lai, Fan and Dai, Yinwei and Singapuram, Sanjay and Liu, Jiachen and Zhu, Xiangfeng and Madhyastha, Harsha and Chowdhury, Mosharaf},
  booktitle = {Proceedings of the 39th International Conference on Machine Learning},
  pages     = {11814--11827},
  year      = {2022},
  volume    = {162},
  series    = {Proceedings of Machine Learning Research},
  publisher = {PMLR},
  url       = {https://proceedings.mlr.press/v162/lai22a.html}
}
```

### 4. Oort: Efficient Federated Learning via Guided Participant Selection

**What it does.** Oort improves time-to-accuracy by selecting clients based on both statistical utility and system speed.

**Relation to this project.** Oort is directly relevant to the dissertation's slow-device representation theme. It optimizes participant selection, whereas this dissertation mostly fixes experimental topologies and measures how methods treat faster and slower devices. That contrast helps explain why the dissertation reports update share and aggregate weight share instead of only time-to-target.

**How to add it.** Add to related work near update-timing heterogeneity and systems-aware FL. It can also motivate a future-work paragraph on adaptive client selection in `fedctl`.

**Source.** <https://www.usenix.org/conference/osdi21/presentation/lai>

```bibtex
@inproceedings{lai2021oort,
  title     = {Oort: Efficient Federated Learning via Guided Participant Selection},
  author    = {Lai, Fan and Zhu, Xiangfeng and Madhyastha, Harsha V. and Chowdhury, Mosharaf},
  booktitle = {15th {USENIX} Symposium on Operating Systems Design and Implementation ({OSDI} 21)},
  pages     = {19--35},
  year      = {2021},
  publisher = {{USENIX} Association},
  url       = {https://www.usenix.org/conference/osdi21/presentation/lai}
}
```

### 5. Federated Optimization in Heterogeneous Networks

**What it does.** This is the FedProx paper. It frames FL heterogeneity as both statistical and systems heterogeneity, and modifies FedAvg with a proximal term plus variable local work tolerance.

**Relation to this project.** It is highly relevant background because it explicitly joins statistical and systems heterogeneity. The dissertation's contribution differs by evaluating device-capacity and timing effects on real hardware rather than proposing a general optimizer for non-IID and variable-work settings.

**How to add it.** Add to background where heterogeneity axes are defined. Also use in related work as an optimization-side baseline that motivates but is not the main evaluated method family.

**Note.** The current bibliography has a related-looking `li2020heterogeneous` entry with a different title/authorship. Add this as a separate FedProx entry or replace the existing entry if it was intended to cite FedProx.

**Source.** <https://proceedings.mlsys.org/paper/2020/file/1f5fe83998a09396ebe6477d9475ba0c-Paper.pdf>

```bibtex
@inproceedings{li2020fedprox,
  title     = {Federated Optimization in Heterogeneous Networks},
  author    = {Li, Tian and Sahu, Anit Kumar and Zaheer, Manzil and Sanjabi, Maziar and Talwalkar, Ameet and Smith, Virginia},
  booktitle = {Proceedings of Machine Learning and Systems},
  volume    = {2},
  pages     = {429--450},
  year      = {2020},
  url       = {https://proceedings.mlsys.org/paper/2020/file/1f5fe83998a09396ebe6477d9475ba0c-Paper.pdf}
}
```

### 6. Measuring the Effects of Non-Identical Data Distribution for Federated Visual Classification

**What it does.** Hsu, Qi, and Brown study how non-IID label distributions affect FL visual classification, including common synthetic non-IID constructions.

**Relation to this project.** It is useful for grounding the dissertation's IID/non-IID CIFAR-10 regimes. It supports a more precise explanation that non-IID data is an experimental axis rather than a vague property of FL.

**How to add it.** Cite in background's statistical heterogeneity subsection and in evaluation setup when explaining CIFAR-10 IID/non-IID partitions.

**Source.** <https://research.google/pubs/measuring-the-effects-of-non-identical-data-distribution-for-federated-visual-classification/>

```bibtex
@article{hsu2019measuring,
  title         = {Measuring the Effects of Non-Identical Data Distribution for Federated Visual Classification},
  author        = {Hsu, Tzu-Ming Harry and Qi, Hang and Brown, Matthew},
  journal       = {CoRR},
  volume        = {abs/1909.06335},
  year          = {2019},
  eprint        = {1909.06335},
  archivePrefix = {arXiv},
  url           = {https://arxiv.org/abs/1909.06335}
}
```

## Related-Work Additions for Statistical Heterogeneity

### 7. SCAFFOLD: Stochastic Controlled Averaging for Federated Learning

**What it does.** SCAFFOLD uses control variates to correct client drift under heterogeneous data and client sampling.

**Relation to this project.** It strengthens the related-work taxonomy by showing that non-IID robustness can be attacked algorithmically without changing device capacity or timing. This helps clarify why the dissertation separates statistical heterogeneity from systems heterogeneity.

**How to add it.** Cite in related work when distinguishing data-heterogeneity optimizers from the evaluated submodel and asynchronous methods. Mention as a potential future baseline if the dissertation later extends the method suite.

**Source.** <https://arxiv.org/abs/1910.06378>

```bibtex
@inproceedings{karimireddy2020scaffold,
  title     = {{SCAFFOLD}: Stochastic Controlled Averaging for Federated Learning},
  author    = {Karimireddy, Sai Praneeth and Kale, Satyen and Mohri, Mehryar and Reddi, Sashank J. and Stich, Sebastian U. and Suresh, Ananda Theertha},
  booktitle = {Proceedings of the 37th International Conference on Machine Learning},
  pages     = {5132--5143},
  year      = {2020},
  volume    = {119},
  series    = {Proceedings of Machine Learning Research},
  publisher = {PMLR},
  url       = {https://proceedings.mlr.press/v119/karimireddy20a.html}
}
```

### 8. Tackling the Objective Inconsistency Problem in Heterogeneous Federated Optimization

**What it does.** FedNova analyzes objective inconsistency caused by heterogeneous local update counts and proposes normalized averaging.

**Relation to this project.** It is relevant because `fedctl` evaluates cases where client runtime and local work differ. FedNova gives a clean theoretical angle on why variable local computation is not just a wall-clock issue; it can alter the effective objective.

**How to add it.** Add to background or related work near client-capacity heterogeneity. It can also support future work on adding more optimizer baselines once the control plane is stable.

**Source.** <https://papers.nips.cc/paper_files/paper/2020/hash/564127c03caab942e503ee6f810f54fd-Abstract.html>

```bibtex
@inproceedings{wang2020fednova,
  title     = {Tackling the Objective Inconsistency Problem in Heterogeneous Federated Optimization},
  author    = {Wang, Jianyu and Liu, Qinghua and Liang, Hao and Joshi, Gauri and Poor, H. Vincent},
  booktitle = {Advances in Neural Information Processing Systems},
  volume    = {33},
  pages     = {7611--7623},
  year      = {2020},
  url       = {https://papers.nips.cc/paper_files/paper/2020/hash/564127c03caab942e503ee6f810f54fd-Abstract.html}
}
```

### 9. FedBN: Federated Learning on Non-IID Features via Local Batch Normalization

**What it does.** FedBN keeps batch-normalization statistics local to address feature-shift non-IID settings.

**Relation to this project.** The current dissertation mostly uses label/data partition heterogeneity, but FedBN is a good reference for explaining that statistical heterogeneity has multiple forms. It can prevent the background from over-identifying non-IID with label skew alone.

**How to add it.** Cite in background's statistical heterogeneity subsection and optionally in future work as a direction for feature-shift experiments on camera/sensor-style edge data.

**Source.** <https://arxiv.org/abs/2102.07623>

```bibtex
@inproceedings{li2021fedbn,
  title     = {{FedBN}: Federated Learning on Non-{IID} Features via Local Batch Normalization},
  author    = {Li, Xiaoxiao and Jiang, Meirui and Zhang, Xiaofei and Kamp, Michael and Dou, Qi},
  booktitle = {International Conference on Learning Representations},
  year      = {2021},
  url       = {https://openreview.net/forum?id=6YEQUn0QICG}
}
```

## Related-Work Additions for Systems Heterogeneity and Client Selection

### 10. Client Selection for Federated Learning with Heterogeneous Resources in Mobile Edge

**What it does.** FedCS selects clients under mobile-edge resource constraints to maximize useful updates within round deadlines.

**Relation to this project.** It is an early systems-aware FL paper and maps closely to `fedctl`'s concern with device resources and completion time. The dissertation differs by not optimizing selection online; it controls placement and measures method behavior under chosen topologies.

**How to add it.** Use in related work before Oort/TiFL as an early resource-aware client-selection reference. It also belongs in future work for adaptive scheduling or deadline-aware placement.

**Source.** <https://arxiv.org/abs/1804.08333>

```bibtex
@article{nishio2018fedcs,
  title         = {Client Selection for Federated Learning with Heterogeneous Resources in Mobile Edge},
  author        = {Nishio, Takayuki and Yonetani, Ryo},
  journal       = {CoRR},
  volume        = {abs/1804.08333},
  year          = {2018},
  eprint        = {1804.08333},
  archivePrefix = {arXiv},
  url           = {https://arxiv.org/abs/1804.08333}
}
```

### 11. TiFL: A Tier-based Federated Learning System

**What it does.** TiFL groups clients into tiers based on observed training performance and selects within tiers to mitigate stragglers.

**Relation to this project.** TiFL is directly relevant to the update-timing and client-capacity axes. It supports the idea that resource heterogeneity materially changes both training time and accuracy. It also provides contrast: TiFL adapts selection; this dissertation exposes the performance and representation consequences under controlled fixed topologies.

**How to add it.** Cite in related work under systems-aware FL and in the future-work section as a possible extension to `fedctl`'s scheduler.

**Source.** <https://research.ibm.com/publications/tifl-a-tier-based-federated-learning-system>

```bibtex
@inproceedings{chai2020tifl,
  title     = {{TiFL}: A Tier-based Federated Learning System},
  author    = {Chai, Zheng and Ali, Ahsan and Zawad, Syed and Truex, Stacey and Anwar, Ali and Baracaldo, Nathalie and Zhou, Yi and Ludwig, Heiko and Yan, Feng and Cheng, Yue},
  booktitle = {Proceedings of the 29th International Symposium on High-Performance Parallel and Distributed Computing},
  pages     = {125--136},
  year      = {2020},
  publisher = {ACM},
  url       = {https://research.ibm.com/publications/tifl-a-tier-based-federated-learning-system}
}
```

### 12. FedBalancer: Data and Pace Control for Efficient Federated Learning on Heterogeneous Clients

**What it does.** FedBalancer selects informative local samples and adapts round deadlines to improve time-to-accuracy on heterogeneous clients.

**Relation to this project.** It is important because it explicitly couples data utility and pace/deadline control. This dissertation measures time-to-target and slow-device influence; FedBalancer is a natural future-work route for making those controls adaptive.

**How to add it.** Add to related work after Oort/TiFL. In future work, cite it when discussing adaptive per-round deadlines, client pacing, or sample selection.

**Source.** <https://arxiv.org/abs/2201.01601>

```bibtex
@inproceedings{shin2022fedbalancer,
  title     = {{FedBalancer}: Data and Pace Control for Efficient Federated Learning on Heterogeneous Clients},
  author    = {Shin, Jaemin and Li, Yuanchun and Liu, Yunxin and Lee, Sung-Ju},
  booktitle = {Proceedings of the 20th Annual International Conference on Mobile Systems, Applications and Services},
  pages     = {436--449},
  year      = {2022},
  publisher = {ACM},
  url       = {https://arxiv.org/abs/2201.01601}
}
```

### 13. FedCompass: Efficient Cross-Silo Federated Learning on Heterogeneous Client Devices using a Computing Power Aware Scheduler

**What it does.** FedCompass is a semi-asynchronous method that schedules different amounts of local work according to client computing power so that grouped updates arrive with reduced staleness.

**Relation to this project.** It is very close to the dissertation's intersection of update timing and client capacity. It differs from `FedCover` because it adapts local task assignment/scheduling, whereas `FedCover` adjusts aggregation when clients train different submodels.

**How to add it.** Add to related work near asynchronous FL and future work. It is a good bridge into "adaptive deployment and method co-design" as a future direction.

**Source.** <https://openreview.net/forum?id=msXxrttLOi>

```bibtex
@inproceedings{li2024fedcompass,
  title     = {{FedCompass}: Efficient Cross-Silo Federated Learning on Heterogeneous Client Devices using a Computing Power Aware Scheduler},
  author    = {Li, Zilinghan and Chaturvedi, Pranshu and He, Shilan and Chen, Han and Singh, Gagandeep and Kindratenko, Volodymyr and Huerta, E. A. and Kim, Kibaek and Madduri, Ravi},
  booktitle = {International Conference on Learning Representations},
  year      = {2024},
  url       = {https://openreview.net/forum?id=msXxrttLOi}
}
```

## Related-Work Additions for Model Heterogeneity and Submodel FL

### 14. FjORD: Fair and Accurate Federated Learning under heterogeneous targets with Ordered Dropout

**What it does.** FjORD uses ordered dropout to create nested submodels tailored to heterogeneous client capabilities.

**Relation to this project.** FjORD is a strong related-work reference for nested submodel ideas and fairness under system heterogeneity. It should sit alongside HeteroFL, FedRolex, and FIARSE as a closely related model-heterogeneous FL method.

**How to add it.** Add to related work in the submodel FL section. It can also help explain why nested submodels are a natural design family before introducing the dissertation's coverage-aware asynchronous extension.

**Source.** <https://proceedings.neurips.cc/paper/2021/hash/6aed000af86a084f9cb0264161e29dd3-Abstract.html>

```bibtex
@inproceedings{horvath2021fjord,
  title     = {{FjORD}: Fair and Accurate Federated Learning under heterogeneous targets with Ordered Dropout},
  author    = {Horv{\'a}th, Samuel and Laskaridis, Stefanos and Almeida, M{\'a}rio and Leontiadis, Ilias and Venieris, Stylianos I. and Lane, Nicholas D.},
  booktitle = {Advances in Neural Information Processing Systems},
  volume    = {34},
  pages     = {12876--12889},
  year      = {2021},
  url       = {https://proceedings.neurips.cc/paper/2021/hash/6aed000af86a084f9cb0264161e29dd3-Abstract.html}
}
```

### 15. Adaptive Federated Dropout: Improving Communication Efficiency and Generalization for Federated Learning

**What it does.** Adaptive Federated Dropout reduces communication by sending and training submodels, with client-specific dropout rates.

**Relation to this project.** It is relevant background for submodel-style communication/computation reduction, even though the dissertation's focus is not only communication cost. It helps situate submodel FL as part of a broader tradition of partial-model training.

**How to add it.** Mention in related work before HeteroFL/FedRolex/FIARSE, or in a short paragraph on federated dropout and partial-model methods.

**Source.** <https://arxiv.org/abs/2011.04050>

```bibtex
@article{bouacida2020adaptive,
  title         = {Adaptive Federated Dropout: Improving Communication Efficiency and Generalization for Federated Learning},
  author        = {Bouacida, Nader and Mohapatra, Prasant},
  journal       = {CoRR},
  volume        = {abs/2011.04050},
  year          = {2020},
  eprint        = {2011.04050},
  archivePrefix = {arXiv},
  url           = {https://arxiv.org/abs/2011.04050}
}
```

## Future-Work Additions

### 16. Fair Resource Allocation in Federated Learning

**What it does.** q-FFL changes the optimization objective to encourage more uniform accuracy across clients, rather than optimizing only average performance.

**Relation to this project.** The dissertation already measures slow-device representation. q-FFL provides a principled fairness framing that could strengthen discussion of why update share and aggregate weight share matter.

**How to add it.** Cite in future work where discussing fairness-aware metrics, slow-device representation, and device/data correlated evaluations. It can also support a short introduction sentence that average accuracy is insufficient in heterogeneous FL.

**Source.** <https://arxiv.org/abs/1905.10497>

```bibtex
@article{li2019qffl,
  title         = {Fair Resource Allocation in Federated Learning},
  author        = {Li, Tian and Sanjabi, Maziar and Beirami, Ahmad and Smith, Virginia},
  journal       = {CoRR},
  volume        = {abs/1905.10497},
  year          = {2019},
  eprint        = {1905.10497},
  archivePrefix = {arXiv},
  url           = {https://arxiv.org/abs/1905.10497}
}
```

### 17. Ditto: Fair and Robust Federated Learning Through Personalization

**What it does.** Ditto introduces a personalized FL framework designed to improve fairness and robustness under statistical heterogeneity.

**Relation to this project.** `FedCover` and submodel FL still target shared global/submodel structure. Ditto is useful future-work context for client-specific adaptation when global accuracy and per-client utility diverge.

**How to add it.** Cite in future work under personalization and fairness. It can also help frame deployed submodel quality as a step toward client-specific utility rather than only global-model utility.

**Source.** <https://proceedings.mlr.press/v139/li21h>

```bibtex
@inproceedings{li2021ditto,
  title     = {Ditto: Fair and Robust Federated Learning Through Personalization},
  author    = {Li, Tian and Hu, Shengyuan and Beirami, Ahmad and Smith, Virginia},
  booktitle = {Proceedings of the 38th International Conference on Machine Learning},
  pages     = {6357--6368},
  year      = {2021},
  volume    = {139},
  series    = {Proceedings of Machine Learning Research},
  publisher = {PMLR},
  url       = {https://proceedings.mlr.press/v139/li21h.html}
}
```

## Suggested Chapter-Level Integration

### Introduction

Add citations to make the motivation less self-contained:

- Cite Bonawitz et al. and FedScale after the claim that FL evaluation is a systems problem.
- Cite Oort or FedBalancer when saying final accuracy alone misses time-to-accuracy and client participation effects.
- Cite q-FFL or Ditto when motivating why average global accuracy may hide unfairness across devices or clients.

Possible prose direction:

> Production and benchmark systems for FL emphasize that the training algorithm is only one part of the deployed system: client eligibility, scheduling, availability, and system performance all affect the model that is ultimately learned.

### Background

Use the background to define the axes with stronger literature support:

- Statistical heterogeneity: LEAF, Hsu et al., FedBN.
- Systems/client-capacity heterogeneity: FedProx, FedScale, FedCS, TiFL.
- Update-timing heterogeneity: FedCS, TiFL, Oort, FedBalancer, FedCompass.

Possible prose direction:

> The dissertation separates statistical heterogeneity from systems heterogeneity because prior work shows that non-IID objectives, variable local work, resource limits, and client availability each change the effective optimization problem in different ways.

### Related Work

Add one short paragraph before the evaluated method families:

- "Optimization methods for statistical heterogeneity" with FedProx, SCAFFOLD, FedNova.
- "Systems-aware selection and pacing" with FedCS, TiFL, Oort, FedBalancer, FedScale.
- "Partial-model/submodel training" with Adaptive Federated Dropout and FjORD before HeteroFL/FedRolex/FIARSE.

This prevents related work from looking like it only covers the methods implemented in the dissertation.

### Future Work

The most natural additions are:

- Adaptive scheduling/client selection in `fedctl`: Oort, TiFL, FedBalancer, FedCompass.
- Fairness-aware objectives/metrics: q-FFL, Ditto.
- Feature-shift and personalization experiments: FedBN, Ditto.
- Larger benchmark interoperability: FedScale and LEAF-style datasets.

## Minimal BibTeX Import Set

If time is short, add these first:

1. `bonawitz2019towards`
2. `caldas2018leaf`
3. `lai2022fedscale`
4. `lai2021oort`
5. `li2020fedprox`
6. `karimireddy2020scaffold`
7. `wang2020fednova`
8. `nishio2018fedcs`
9. `chai2020tifl`
10. `shin2022fedbalancer`
11. `horvath2021fjord`
12. `li2019qffl`

That set would already broaden the dissertation from the currently implemented method families to the wider FL systems, heterogeneity, and fairness literature.
