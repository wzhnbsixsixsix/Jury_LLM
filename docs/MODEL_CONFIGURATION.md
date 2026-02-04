# Model Configuration Guide

## 概述 (Overview)

Jury LLM 现在使用统一的模型配置管理系统，支持**按角色名称配置模型**。你可以为每个评委角色（逻辑、表达、实用、道德）以及首席法官分别指定不同的模型。

The Jury LLM now uses a unified model configuration management system with **role-based model assignment**. You can specify different models for each judge role (Logic, Expression, Utility, Moral) and the Chief Justice.


## 为什么需要两种配置方式？
Config (YAML 文件) - 基础配置层
- 用途: 项目的默认配置和团队共享配置
- 特点: 
  - 提交到版本控制（Git）
  - 团队成员共享相同配置
  - 适合稳定的、长期的配置
  - 修改后需要重启应用
Env (环境变量) - 覆盖配置层
- 用途: 环境特定和临时覆盖
- 特点:
  - 不提交到版本控制（.env 在 .gitignore 中）
  - 每个开发者/环境可以不同
  - 适合敏感信息（API Keys）和临时测试
  - 可以快速切换，不影响共享配置
---
---

## 🏛️ 评委角色说明

系统包含 **4 个专业评委 + 1 个首席法官**：

| 角色 | 英文名称 | 职责 | 配置键 |
|------|---------|------|--------|
| 逻辑评委 | Logic Judge | 评估逻辑严谨性和事实准确性 | `logic` |
| 表达评委 | Expression Judge | 评估语言表达和结构组织 | `expression` |
| 实用评委 | Utility Judge | 评估实用价值和可操作性 | `utility` |
| 道德评委 | Moral Judge | 评估道德伦理和社会责任 | `moral` |
| 首席法官 | Chief Justice | 综合各方意见，生成最终报告 | `chief` |

---

## 配置优先级 (Configuration Priority)

系统按照以下优先级加载模型配置：

1. **环境变量** (Environment Variables) - 最高优先级(你可以自定义)
2. **YAML 配置文件** (config/jury_config.yaml) - 中等优先级
3. **默认值** (Hardcoded Defaults) - 最低优先级

---

## 方法 1: 在 YAML 文件中按角色配置（推荐）

**最灵活的方法** - 编辑 `config/jury_config.yaml` 文件：

```yaml
# 为每个评委角色指定独立的模型
judge_models:
  chief: "qwen-max"         # 首席法官 - 用最强的模型
  logic: "qwen-plus"        # 逻辑评委 - 需要强推理能力
  expression: "qwen-turbo"  # 表达评委 - 快速响应即可
  utility: "qwen-max"       # 实用评委 - 需要深度分析
  moral: "qwen-plus"        # 道德评委 - 平衡性能

# 系统设置
system_settings:
  debate_threshold: 15
  max_debate_rounds: 2

# 可选: 设置默认模型
model_settings:
  default_model: "qwen-max"
```

**优点:**
- ✅ 直观明确 - 一目了然每个角色用什么模型
- ✅ 灵活配置 - 每个评委可以用不同模型
- ✅ 配置持久化 - 设置保存在文件中
- ✅ 团队协作友好 - 配置易于分享和理解

**使用场景:**
- 🎯 逻辑评委用强模型，表达评委用快速模型
- 🎯 首席法官用最强模型生成综合报告
- 🎯 根据评委职责分配不同性能级别的模型

---

## 方法 2: 使用环境变量（灵活覆盖）

编辑 `.env` 文件来临时覆盖配置：

```bash
# 覆盖默认模型 (所有未指定的地方都用这个)
DEFAULT_MODEL=qwen-turbo

# 覆盖特定评委的模型（推荐方式）
CHIEF_MODEL=qwen-max              # 首席法官
LOGIC_JUDGE_MODEL=qwen-plus       # 逻辑评委
EXPRESSION_JUDGE_MODEL=qwen-turbo # 表达评委
UTILITY_JUDGE_MODEL=qwen-max      # 实用评委
MORAL_JUDGE_MODEL=qwen-plus       # 道德评委
```

**优点:**
- ✅ 开发测试时快速切换
- ✅ 不同环境使用不同配置
- ✅ 不会修改版本控制的文件
- ✅ 优先级最高

---

## 方法 3: 代码中使用（高级用法）

如果你需要在代码中动态获取模型配置：

```python
from src.config import ModelConfig

# 获取配置实例
config = ModelConfig()

# 按角色获取模型（推荐）
logic_model = config.get_judge_model("logic")
expression_model = config.get_judge_model("expression")
utility_model = config.get_judge_model("utility")
moral_model = config.get_judge_model("moral")
chief_model = config.get_chief_model()  # 或 config.get_judge_model("chief")

# 获取所有评委模型（字典格式）
all_models = config.get_all_jury_models()
# 返回: {"logic": "qwen-max", "expression": "qwen-plus", ...}

# 获取默认模型
default_model = config.get_default_model()

# 查看完整配置摘要
summary = config.get_config_summary()
print(summary)
```

---

## 常见使用场景

### 场景 1: 所有评委使用相同模型

**最简单！** 编辑 `config/jury_config.yaml`:

```yaml
judge_models:
  chief: "qwen-turbo"
  logic: "qwen-turbo"
  expression: "qwen-turbo"
  utility: "qwen-turbo"
  moral: "qwen-turbo"
```

---

### 场景 2: 根据评委职责分配不同性能的模型

```yaml
judge_models:
  chief: "qwen-max"         # 首席法官 - 最强模型
  logic: "qwen-max"         # 逻辑评委 - 需要强推理
  expression: "qwen-turbo"  # 表达评委 - 快速响应
  utility: "qwen-plus"      # 实用评委 - 平衡性能
  moral: "qwen-plus"        # 道德评委 - 平衡性能
```

**原因说明:**
- **逻辑评委**需要强大的推理能力 → 用最强模型
- **表达评委**主要评估语言 → 快速模型即可
- **实用/道德评委**需要适中的分析能力 → 平衡模型
- **首席法官**综合所有意见 → 用最强模型

---

### 场景 3: 测试环境临时切换某个评委

不修改 YAML 文件，只在 `.env` 中添加：

```bash
# 临时测试逻辑评委用 gpt-4
LOGIC_JUDGE_MODEL=gpt-4
```

测试完成后，直接注释掉这行，就恢复到 YAML 配置。

---

### 场景 4: 混合使用多个 AI 提供商

```yaml
# config/jury_config.yaml
judge_models:
  chief: "qwen-max"                          # DashScope
  logic: "anthropic/claude-3.5-sonnet"      # OpenRouter
  expression: "qwen-turbo"                  # DashScope
  utility: "openai/gpt-4"                   # OpenRouter
  moral: "qwen-plus"                        # DashScope
```

或者用环境变量：

```bash
# .env
CHIEF_MODEL=qwen-max
LOGIC_JUDGE_MODEL=anthropic/claude-3.5-sonnet
EXPRESSION_JUDGE_MODEL=qwen-turbo
UTILITY_JUDGE_MODEL=openai/gpt-4
MORAL_JUDGE_MODEL=qwen-plus
```

---

## 支持的模型名称

### DashScope (阿里云)
- `qwen-max` - 最强大的模型 💪
- `qwen-plus` - 平衡性能和成本 ⚖️
- `qwen-turbo` - 最快速的模型 ⚡
- 更多模型见: https://dashscope.console.aliyun.com/

### OpenRouter (通过 API)
- `anthropic/claude-3.5-sonnet` - Claude 最新模型
- `openai/gpt-4` - GPT-4
- `openai/gpt-3.5-turbo` - GPT-3.5
- `google/gemini-pro` - Gemini Pro
- 更多模型见: https://openrouter.ai/models

---

## 向后兼容说明

旧的配置格式仍然支持（使用索引列表）：

```yaml
# 旧格式（仍然有效）
judge_model: "qwen-max"  # 首席法官

jury_models:  # 按顺序：logic, expression, utility, moral
  - "qwen-max"
  - "qwen-plus"
  - "qwen-turbo"
  - "qwen-max"
```

**但强烈建议使用新的角色配置格式：**

```yaml
# 新格式（推荐）
judge_models:
  chief: "qwen-max"
  logic: "qwen-max"
  expression: "qwen-plus"
  utility: "qwen-turbo"
  moral: "qwen-max"
```

---

## 测试配置

查看当前加载的模型配置:

```bash
python -c "from src.config import ModelConfig; import json; print(json.dumps(ModelConfig().get_config_summary(), indent=2, ensure_ascii=False))"
```

测试环境变量覆盖:

```bash
LOGIC_JUDGE_MODEL=qwen-plus python -c "from src.config import ModelConfig; print('Logic Judge:', ModelConfig().get_judge_model('logic'))"
```

运行示例查看各评委使用的模型:

```bash
python src/config.py
```

---

## 故障排除

### 问题: 配置文件找不到

**解决:** 确保 `config/jury_config.yaml` 文件存在

### 问题: 环境变量不生效

**解决:** 
1. 确保 `.env` 文件在项目根目录
2. 检查变量名拼写是否正确（例如：`LOGIC_JUDGE_MODEL`）
3. 重启应用或重新加载环境

### 问题: 模型名称不匹配

**解决:** 
1. 检查 API 提供商的模型列表
2. 确保模型名称格式正确
   - DashScope: `qwen-max`
   - OpenRouter: `provider/model` (例如 `anthropic/claude-3.5-sonnet`)

### 问题: 想恢复默认配置

**解决:**
1. 注释掉 `.env` 中的所有模型覆盖
2. 或删除 `.env` 文件，从 `.env.example` 重新创建

---

## 配置建议

### 💰 成本优化配置
```yaml
judge_models:
  chief: "qwen-plus"       # 平衡性能
  logic: "qwen-turbo"      # 快速模型
  expression: "qwen-turbo" # 快速模型
  utility: "qwen-turbo"    # 快速模型
  moral: "qwen-turbo"      # 快速模型
```

### ⚡ 速度优先配置
```yaml
judge_models:
  chief: "qwen-turbo"
  logic: "qwen-turbo"
  expression: "qwen-turbo"
  utility: "qwen-turbo"
  moral: "qwen-turbo"
```

### 🎯 质量优先配置
```yaml
judge_models:
  chief: "qwen-max"
  logic: "qwen-max"
  expression: "qwen-plus"
  utility: "qwen-max"
  moral: "qwen-plus"
```

### 🌟 平衡配置（推荐）
```yaml
judge_models:
  chief: "qwen-max"         # 首席法官用最强
  logic: "qwen-plus"        # 逻辑评委用较强
  expression: "qwen-turbo"  # 表达评委用快速
  utility: "qwen-plus"      # 实用评委用较强
  moral: "qwen-turbo"       # 道德评委用快速
```

---

## 文件修改摘要

以下文件已更新为支持角色配置:

| 文件 | 修改内容 |
|------|---------|
| `src/config.py` | 添加 `get_judge_model(role)` 支持按角色获取 |
| `src/agentscope_jury.py` | 更新为按角色创建评委模型 |
| `config/jury_config.yaml` | 添加 `judge_models` 字典配置 |
| `.env` | 更新环境变量示例为角色名称 |
| `.env.example` | 更新模板为角色配置方式 |
| `docs/MODEL_CONFIGURATION.md` | 完整重写为角色配置文档 |

---

## 总结

现在你可以:

1. ✅ **按角色名称配置模型** (`judge_models.logic`, `judge_models.chief`, etc.)
2. ✅ **为每个评委配置不同模型** (逻辑用强模型，表达用快速模型)
3. ✅ **使用环境变量覆盖** (`.env` 中的 `LOGIC_JUDGE_MODEL` 等)
4. ✅ **配置更直观** (不需要记住索引顺序)
5. ✅ **向后兼容** (旧的 `jury_models` 列表仍然有效)
6. ✅ **灵活切换 AI 提供商** (DashScope, OpenRouter, etc.)

享受更灵活、更直观的模型管理! 🎉

## 配置优先级 (Configuration Priority)

