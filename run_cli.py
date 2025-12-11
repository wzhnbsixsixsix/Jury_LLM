import os
from dotenv import load_dotenv

# 先加载 .env，确保 OPENROUTER_API_KEY 等环境变量已注入
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# 再导入 app，避免在环境变量未就绪时构建 LLMProvider
from src.graph import app

def main():
    # 加载 .env（包含 OPENROUTER_API_KEY、LANGCHAIN_* 等）
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

    # 初始输入（可按需修改或改成 argparse 接收参数）
    initial_state = {
        "topic": "Evaluate the impact of AI on software engineering.",
        "human_bio": "Senior Python Developer, 10 years exp.",
        "human_score": 70.0,
        "human_reason": "Strong productivity gains, but risks in maintainability.",
        "model_outputs": {},
        "debate_logs": [],
        "votes": {}
    }

    # LangChain 运行配置：线程ID + 标签 + 元数据（便于在 LangSmith 里筛选）
    config = {
        "configurable": {"thread_id": "cli-1"},
        "tags": ["jury-llm", "cli"],
        "metadata": {"source": "cli", "topic": initial_state["topic"]}
    }

    print("Starting Jury LLM (CLI)...")
    print("OPENROUTER_API_KEY present:", os.getenv("OPENROUTER_API_KEY") is not None)
    # 第一段：跑到中断（prepare_vote 后，model_vote 前）
    for event in app.stream(initial_state, config, stream_mode="values"):
        if "human_weight" in event:
            print(f"[human_weight] {event['human_weight']}")
        if "debate_logs" in event and event["debate_logs"]:
            print("[debate_logs]")
            for log in event["debate_logs"]:
                print(" -", log)

    # 处理中断：给一个自动化的人类盲投
    state_snapshot = app.get_state(config)
    if state_snapshot.next:
        print("Paused before model_vote. Submitting human vote automatically...")
        values = state_snapshot.values
        anon = values.get("anonymized_reasons", {})
        # 简单策略：选第一个选项（你也可做更复杂的规则）
        selected_option_id = next(iter(anon.keys())) if anon else None

        current_votes = values.get("votes", {})
        current_votes["human"] = selected_option_id
        app.update_state(config, {"votes": current_votes})

        # 恢复执行到终局
        print("Resuming to synthesis...")
        for event in app.stream(None, config, stream_mode="values"):
            if "final_verdict" in event:
                print("\n=== Final Verdict (Markdown) ===\n")
                print(event["final_verdict"])
                print("\n=== End ===\n")

if __name__ == "__main__":
    main()