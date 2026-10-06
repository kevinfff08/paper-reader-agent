# 跨论文真实试读

评价目标是博士生能否说清楚研究问题、思想转折、论证为何成立、贡献的位置，以及下一步值得研究什么；不以篇幅、关键词命中或工程步骤完整度代替理解质量。

固定开发集为 [DPO](https://arxiv.org/html/2305.18290v3)、[IPO](https://arxiv.org/html/2310.12036v2)、[Lost in the Middle](https://arxiv.org/html/2307.03172v3)。[LoRA](https://arxiv.org/html/2106.09685v2) 用于冻结改动后的留出试读。DPO/IPO 是直接相关的比较；长上下文研究用于检查能否识别不同研究问题，不强行排优劣。

先看未修改系统的实际输出，再修改；使用同一模型和同一版本原文。人工逐段阅读输出并回看原文，检查：

- 问题与贡献：解决的学术问题是什么，改变了已有工作的哪一个假设或理解？
- 思想与论证：解释关键推导、受控比较或反例，而非只列训练流程；区分定理前提、观察和猜想。
- 结论范围：读者能否理解结论在哪些条件下成立、什么还不知道？
- 研究启发：后续问题是否来自本文具体未决问题，是否有可区分不同解释的验证思路？
- 跨论文关系：哪些论文可直接对比，哪些仅有互补关系？不用不同实验的数字制造排名。

内容核对锚点（只用于评价，不写入产品提示词）：DPO 的奖励重参数化与有限数据训练不是同一层面的保证；IPO 的确定性偏好反例、有限目标间隔、采样损失与小规模示例；Lost in the Middle 的位置控制、检索与问答任务的差异、机制仍未完全解释；LoRA 的低秩对象是更新矩阵，而非预训练权重，实证发现不是任意任务上的定理。

运行示例（会实际调用配置模型并消耗额度）：

```sh
python scripts/evaluate_research_reading.py --label baseline --compare
python scripts/evaluate_research_reading.py --label revised
python scripts/evaluate_research_reading.py --label holdout --papers lora
python scripts/evaluate_research_reading.py --label comparison --papers dpo ipo --compare --reuse-guides .tmp-tests/research-reading/revised
```

使用官方 arXiv HTML 规范化输入，调用产品的单篇导读和跨篇综合函数；**不覆盖 PDF 解析、完整前台动作循环或 UI**。保留数学公式、章节、来源版本和哈希；原文和输出存于隔离的 `.tmp-tests/research-reading/`，不提交第三方全文。每次使用不同 label，避免覆盖失败记录。这里只做定性案例评估，不能证明普遍效果或真实用户学习提升。

## 2026-10-06：第一项，正文论证覆盖

模型为配置代理中的 `gpt-5.5`。基线目录 `baseline`，改后目录 `context-balanced`；提示词不变，只调整上下文取材。

| 论文 | 实际基线问题 | 改后观察 |
| --- | --- | --- |
| DPO | 选入附录实验细节，正文后部讨论覆盖不足 | 纳入分布外摘要结果及评价限制；仍把参考模型项解释成阻止概率无限增长，需下一项改进理论讲解 |
| IPO | 未读到 §5.2、后部示例和结论；输出称完整实验设置不可见，把 sampled loss 延后到复现时再读 | 输出实际平方损失及有限目标 `1/(2τ)`，解释确定性偏好反例，并区分小规模示例与大模型结论 |
| Lost in the Middle | 已能认出实证诊断，不能声称基线完全误判论文类型 | 复查位置干预、两类任务与机制解释的区别，避免只用篇幅判定改善 |

自动回归 44 项通过。这里的改善是上述具体内容恢复，不是统计显著的跨论文质量提升；DPO 的过强断言仍是未解决问题。
