# 快速入门：按角色配置模型

## 🎯 一分钟配置指南

### 第一步：了解评委角色

Jury LLM 有 **5 个角色**：

| 角色 | 配置键 | 职责 |
|------|-------|------|
| 逻辑评委 | `logic` | 评估逻辑和事实 |
| 表达评委 | `expression` | 评估语言表达 |
| 实用评委 | `utility` | 评估实用价值 |
| 道德评委 | `moral` | 评估道德伦理 |
| 首席法官 | `chief` | 综合生成报告 |

### 第二步：编辑配置文件

打开 `config/jury_config.yaml`：

```yaml
judge_models:
  chief: "qwen-max"         # 你的模型
  logic: "qwen-plus"        # 你的模型
  expression: "qwen-turbo"  # 你的模型
  utility: "qwen-max"       # 你的模型
  moral: "qwen-plus"        # 你的模型
```

### 第三步：运行测试

```bash
# 查看当前配置
python src/config.py

# 启动应用
jupyter notebook notebooks/interactive_lab.ipynb
```

## 💡 常见配置

### 全部用同一个模型
```yaml
judge_models:
  chief: "qwen-max"
  logic: "qwen-max"
  expression: "qwen-max"
  utility: "qwen-max"
  moral: "qwen-max"
```

### 根据职责分配
```yaml
judge_models:
  chief: "qwen-max"         # 首席用最强
  logic: "qwen-plus"        # 逻辑需要推理
  expression: "qwen-turbo"  # 表达快速即可
  utility: "qwen-max"       # 实用需要分析
  moral: "qwen-turbo"       # 道德快速即可
```

## 🔧 临时测试（不修改文件）

在 `.env` 中添加：

```bash
LOGIC_JUDGE_MODEL=qwen-plus
EXPRESSION_JUDGE_MODEL=qwen-turbo
```

## 📚 详细文档

查看 `docs/MODEL_CONFIGURATION.md` 获取完整文档。

## ✅ 验证配置

```bash
# 查看当前使用的模型
python -c "from src.config import ModelConfig; import json; print(json.dumps(ModelConfig().get_config_summary(), indent=2))"
```

输出示例：
```json
{
  "chief_model": "qwen-max",
  "judge_models": {
    "logic": "qwen-plus",
    "expression": "qwen-turbo",
    "utility": "qwen-max",
    "moral": "qwen-plus"
  }
}
```

完成！🎉
