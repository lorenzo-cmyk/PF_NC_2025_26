# Replicating: "eTran: extensible kernel transport with eBPF"

**Team Members:**  
Pierluigi Grossi, 10618314@polimi.it;  
Matteo Franken, 10831046@polimi.it;  
Lorenzo Chiroli, 10797603@polimi.it

---

**Source Paper:**
Zhongjie Chen, Qingkai Meng, ChonLam Lao, Yifan Liu, Fengyuan Ren, Minlan Yu,
and Yang Zhou: eTran: Extensible Kernel Transport with eBPF. In "22nd USENIX
Symposium on Networked Systems Design and Implementation (NSDI 25)", pages
407-425, Philadelphia, PA, 2025. USENIX Association.

Paper link: https://www.usenix.org/conference/nsdi25/presentation/chen-zhongjie


**Project:**
Project repository: https://github.com/lorenzo-cmyk/PF_NC_2025_26. The repository
contains the CloudLab profile used to set up the cluster, Ansible playbooks
for configuring it, and runbooks documenting the procedures used to run the
experiments and collect measurements.

---

# 1. Introduction

Introduce the paper by summarizing:

- The problem the paper addresses and its importance
- The key ideas behind its solution and its approach
- The main contributions

# 2. Selected Result

Mention which result of the paper you are reproducing, and explain its importance.

For example:

> “Figure 1 shows that method A improves throughput by 35% over method B under workload *W*. This experiment shows that paper can effectively overcome the motivated challenge.”

![The figure shows that method A improves throughput compared to method B](figures/one_bar.png){width=30%}

# 3. Environment Setup

*Note:* This section should contain enough information to allow someone else to
reproduce *your* report. Share hardware and/or software setup relevant to your
experiment. For example:

**Hardware Environment:**
CPU, Memory, Storage, Network, Cloud / local / cluster, Any relevant micro-architectural details

**Software Environment**
OS version, Kernel version, Compiler version, Libraries, Dependencies, Paper artifact used (Yes/No; version/commit hash)

**Configuration Parameters:**

- Workload configuration
- Dataset
- Runtime parameters and flags

**Deviations from the Original Setup:**

Clearly describe any difference between papers and your experiment environment.

- Hardware differences
- Software version differences
- Dataset substitutions
- Unavailable components

Explain why these deviations were necessary.

If something was **missing in the original paper**, state it. For example:

> The paper does not specify X. We assumed Y (or explored range *a* to *b*).

# 4. Experiment Result

> Explain how your experiment was conducted and then what results you acquired. 
Afterwards, compare your results with those of the paper and state your
takeaways.

Step-by-step description:

1. Execution procedure
1. Measurement method
1. Number of runs
1. Statistical treatment (mean, median, CI, etc.)

Also Describe:

- How did you ensure correctness (did you check also other metrics to make sure the experiment is running correctly?)
- Did you do any debugging? Discuss issues you faced and how you overcame them (if applicable consider allocating a subsection for this item) 

Share your result and compare them with the paper's. Then discuss your takeaways.

For comparison include:

- Graph(s) or table(s)
- Matching axes and units with the source paper
- Error bars if applicable
- You may want to report difference with the original results (e.g., absolute
number or percentage).

For example:

![The figure shows that method A improves throughput compared to method B](figures/one_bar.png){width=30%}

![Our reproduction of Figure 1 shows results with the similar trend as claimed by the paper](figures/two_bar.png){width=30%}

> **Reminder:** the goal is not achieve the exact results of the paper, but to do a rigorous experiment with similar assumptions from the source paper and gain insight. The insight can be correctness of work, failure to reproduce same results, or even infeasibility of doing such experiment for interesting reasons.

# 5. Further Exploration

In this project you are required to also explore a research question of your own. Either:

1. Take the same test with different input workload or a variation of a test that is not present in the paper and comment the results you obtain
1. Implement a new feature on top of the system you evaluated and show a figure showing the performance

Discuss which approach you take, and what you explored. Explain what was your
motivation and importance of your question.

## 5.1. Methodology and Result

Report the experiment you designed for answering the question and share the
result you got.

Include:

- Graph(s) or table(s)
- How the experiment was conducted (share the details)
- What did you discover?

# 6. Reproducibility Assessment of the Paper

Evaluate the paper itself:

- Was the methodology clearly described?
- Was the artifact usable?
- How difficult was reproduction?

# 7. Conclusion

Conclude the report by mentioning the takeaways of experiments you did


---

# Appendix

You are asked to write this report using Markdown. You can find a cheat sheet
of Markdown syntax at this [link](https://rust-lang.github.io/mdBook/format/markdown.html).

For generating a PDF file from your report you can use a tool of your choice.
*md2pdf* is one such tool. See this [link](https://pypi.org/project/md2pdf/)
for more information about it. You can also use an online editor such as [this](https://www.md2pdf.io/).

