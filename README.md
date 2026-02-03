# Jury LLM: 多模型 + 人类参与评估系统

Jury LLM 通过多个不同的大模型组成“评审团”，对给定主题进行打分与辩论，并在匿名理由上进行盲投；人类用户也参与给分与投票。最终由“首席法官模型”综合各方的加权结果，生成 Markdown 形式的终稿报告。

## 特性
- 多模型协作：聚合来自不同供应商/架构的模型，降低单模型偏差。
- 人类参与：人类不仅打分，还在“匿名理由”上进行盲投，提高可信度与可解释性。
- 可配置：评审团模型列表、辩论阈值与轮次、法官模型均在配置文件中可调整。
- 可中断流程：在“模型投票前”中断执行，让人类插入投票后再继续。

## 架构概览
- 流程框架：使用 agentscope 定义有条件节点流与中断点。
- 模型调用：通过 LiteLLM 使用 OpenRouter 路由调用不同模型。
- 前端交互：提供 Jupyter Notebook `interactive_lab.ipynb`，进行输入、观察辩论日志与匿名投票。

主要节点与状态：
- `JuryState`：包含主题、人类打分/理由、模型输出、辩论日志、匿名映射、投票与最终结论。
- 节点流：
  1. `human_authority`：根据用户履历对人类赋权（系数 `0.5–1.5`）。
  2. `initial_eval`：评审团所有模型对主题进行初评打分与理由。
  3. `node_debate_check`：根据分数标准差是否超过阈值决定是否辩论或进入投票；超过最大轮次则直接投票。
  4. `debate`：对与均值差异较大者发起“再考虑”提示（以均值为对手观点），模型可调整打分与理由，并记录辩论日志。
  5. `prepare_vote`：汇总人类与模型的“分数+理由”，匿名化成 `Option 1/2/...` 并保存真实映射。
  6. 中断点：在“模型投票”前挂起，Notebook 展示匿名选项让人类投票。
  7. `model_vote`：各模型基于匿名理由进行盲投（提示中要求不得投自己）。
  8. `synthesis`：统计投票，给获胜方加权（模型 +0.5 或人类 +0.5），由法官模型生成最终报告（Markdown）。

## 目录结构
jury-llm/
├── .env
├── config/
│   └── jury_config.yaml
├── notebooks/
│   └── interactive_lab.ipynb
├── requirements.txt
└── src/
    ├── __init__.py
    ├── agents.py        # 提示词：人类权威、初评、辩论、盲投、综合报告
    ├── graph.py         # agentscope 流程与中断点
    ├── llm_provider.py  # OpenRouter/LiteLLM 模型调用封装
    └── utils.py         # 加权计算、辩论触发、匿名化、JSON 解析


## 安装与配置
1. Python 版本：建议 `>=3.9`
2. 安装依赖：
   ```bash
   python3 -m venv /Users/Thomas/Desktop/Jury/jury-llm/juryenv && source /Users/Thomas/Desktop/Jury/jury-llm/juryenv/bin/activate && pip install -r /Users/Thomas/Desktop/Jury/jury-llm/requirements.txt
   ```
3. 设置环境变量：
   - 在 `jury-llm/.env` 写入你的 OpenRouter API Key：
     ```
     OPENROUTER_API_KEY=your_openrouter_key_here
     ```
4. 配置模型：
   - 编辑 `jury-llm/config/jury_config.yaml`，填入你可用的模型路由：
     ```yaml
     judge_model: "openai/gpt-4o"
     jury_models:
       - "anthropic/claude-3.5-sonnet"
       - "openai/gpt-4-turbo"
       - "google/gemini-1.5-pro"
       - "meta-llama/llama-3-70b-instruct"
       - "mistral/mistral-large"
     system_settings:
       debate_threshold: 15
       max_debate_rounds: 2
     ```
   - 注意：这些值需要与你的 OpenRouter 账号实际可用的模型一致。

## 快速使用（Notebook）
1. 启动 Notebook 并打开交互界面：
   ```bash
   jupyter notebook jury-llm/notebooks/interactive_lab.ipynb
   ```
2. 在页面中：
   - 输入主题（Topic）、个人履历（Bio）、人类打分（0–100）与理由（Reason）。
   - 点击开始，系统会：
     - 计算人类权重；
     - 进行评审团初评；
     - 根据分歧触发 0–N 轮辩论；
     - 准备匿名选项并中断。
   - 在中断点进行人类盲投（选择最好的理由），系统恢复：
     - 进行模型盲投；
     - 输出最终判决报告（Markdown）。

## 工作流细节
- 分歧判定：`utils.check_debate_condition` 使用分数的标准差与阈值比较（默认 15）来判断是否需要辩论。
- 匿名盲投：`utils.anonymize_options` 将 `{作者: 内容}` 随机打散为 `{Option X: 内容}` 并保存映射 `{Option X: 作者}`。
- 加权策略：
  - 初始：人类权重由法官模型评估（0.5–1.5），模型初始权重为 1.0。
  - 盲投获胜者：额外加权 +0.5（模型或人类），影响最终综合。
- 终稿生成：在 `synthesis` 汇总人类与模型的分数与权重，交由法官模型生成最终 Markdown 报告。

## 开发建议
- 并发提速：当前初评与投票是顺序执行，可改为并发以提升速度。
- JSON 严格解析：当模型未返回纯 JSON 时可增加重试或自校正策略，减少空解析。
- 本地加权计算：可以将最终加权分从“提示内计算”迁移到代码内（用 `utils.calculate_weighted_score`），提高可控性与可测试性。
- 辩论策略：从“均值对抗”扩展到“最大分歧互辩”“小组交叉辩论”等，以获得更稳健的结果。

## 常见问题
- 没有 `OPENROUTER_API_KEY`：`llm_provider.py` 会警告且调用失败，请在 `.env` 写入有效 Key。
- 模型路由不可用：请在 `jury_config.yaml` 使用你有权限的模型路由名。
- 模型输出非 JSON：`utils.parse_json_output` 会尝试清理代码块并解析；必要时增加重试或改进提示词。
- 超时与速率限制：多模型调用可能触发限流，建议减少并发或调整模型数量。

---
如需我帮你：可以把最终加权分计算迁移到本地代码、改造初评/投票为并发、或新增一个 CLI 入口，支持在终端运行整个流程。

TODO List:

- [ ] 支持批量输入文本，最终评测结果放到一个csv文件中