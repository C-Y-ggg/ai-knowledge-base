import json
import time
import httpx
import os
from datetime import datetime

# ==================== 配置 ====================
API_URL = "http://127.0.0.1:8026/api/v1/chat/stream"
CONVERSATION_URL = "http://127.0.0.1:8026/api/v1/conversations"
TEST_SET_PATH = os.path.join(os.path.dirname(__file__), "test_set.json")


# ==================== 工具函数 ====================
def create_conversation() -> int:
    """创建一个新会话，返回 conversation_id"""
    res = httpx.post(CONVERSATION_URL, timeout=10)
    return res.json()["id"]


def ask_question(query: str, conversation_id: int) -> dict:
    """
    向 RAG 系统提问，返回：
    - answer: 完整回答
    - ttft: 首字延迟（秒）
    - total_time: 总耗时（秒）
    - has_sources: 是否返回了引用来源
    """
    payload = {"query": query, "conversation_id": conversation_id}

    start = time.time()
    ttft = None
    answer = ""
    has_sources = False

    with httpx.stream("POST", API_URL, json=payload, timeout=60) as response:
        buffer = ""
        for chunk in response.iter_text():
            if ttft is None and chunk.strip():
                ttft = time.time() - start  # 记录首字延迟

            buffer += chunk
            parts = buffer.split("\n\n")
            buffer = parts.pop()

            for part in parts:
                if part.startswith("data: "):
                    data_str = part[6:]
                    if data_str == "[DONE]":
                        continue
                    try:
                        data = json.loads(data_str)
                        if "content" in data:
                            answer += data["content"]
                        if "sources" in data and len(data["sources"]) > 0:
                            has_sources = True
                    except json.JSONDecodeError:
                        pass

    total_time = time.time() - start
    return {
        "answer": answer,
        "ttft": ttft or total_time,
        "total_time": total_time,
        "has_sources": has_sources
    }


def evaluate_answer(answer: str, expected_keywords: list, should_reject: bool) -> dict:
    """根据关键词和是否应拒答，判断回答是否正确"""
    # 判断是否命中了预期关键词
    hit_keywords = [kw for kw in expected_keywords if kw in answer]
    keyword_hit_rate = len(hit_keywords) / len(expected_keywords) if expected_keywords else 0

    # 判断是否触发了拒答
    is_rejected = any(phrase in answer for phrase in ["无法回答", "未找到", "抱歉", "现有文档无法回答"])

    # 最终判定
    if should_reject:
        # 应该拒答的问题：如果被拒答了，算正确
        passed = is_rejected
    else:
        # 不应该拒答的问题：既要命中关键词，又没有被误拒答
        passed = keyword_hit_rate >= 0.5 and not is_rejected

    return {
        "passed": passed,
        "keyword_hit_rate": round(keyword_hit_rate, 2),
        "is_rejected": is_rejected
    }


# ==================== 主流程 ====================
def main():
    with open(TEST_SET_PATH, "r", encoding="utf-8") as f:
        test_set = json.load(f)

    print(f"🧪 开始评估，共 {len(test_set)} 条测试用例...\n")

    results = []
    for case in test_set:
        print(f"[{case['id']}/{len(test_set)}] {case['question']}")

        # 每条用例用一个新会话，避免上下文干扰
        conv_id = create_conversation()
        response = ask_question(case["question"], conv_id)
        evaluation = evaluate_answer(
            response["answer"],
            case["expected_keywords"],
            case["should_reject"]
        )

        result = {
            "id": case["id"],
            "category": case["category"],
            "question": case["question"],
            "answer": response["answer"][:200] + "..." if len(response["answer"]) > 200 else response["answer"],
            "ttft": round(response["ttft"], 2),
            "total_time": round(response["total_time"], 2),
            "has_sources": response["has_sources"],
            **evaluation
        }
        results.append(result)

        status = "✅ 通过" if evaluation["passed"] else "❌ 失败"
        print(f"   {status} | TTFT: {result['ttft']}s | 命中率: {evaluation['keyword_hit_rate']}\n")

    # ==================== 汇总统计 ====================
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    in_kb = [r for r in results if r["category"] == "知识库内"]
    out_kb = [r for r in results if r["category"] == "知识库外"]
    misleading = [r for r in results if r["category"] == "误导性"]

    summary = {
        "评估时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "总用例数": total,
        "通过数": passed,
        "总通过率": f"{round(passed / total * 100, 1)}%",
        "知识库内通过率": f"{round(sum(1 for r in in_kb if r['passed']) / len(in_kb) * 100, 1)}%" if in_kb else "N/A",
        "知识库外拒答率": f"{round(sum(1 for r in out_kb if r['passed']) / len(out_kb) * 100, 1)}%" if out_kb else "N/A",
        "误导性问题通过率": f"{round(sum(1 for r in misleading if r['passed']) / len(misleading) * 100, 1)}%" if misleading else "N/A",
        "平均首字延迟(TTFT)": f"{round(sum(r['ttft'] for r in results) / total, 2)}s",
        "平均总耗时": f"{round(sum(r['total_time'] for r in results) / total, 2)}s",
        "引用来源覆盖率": f"{round(sum(1 for r in results if r['has_sources']) / total * 100, 1)}%"
    }

    # ==================== 输出报告 ====================
    print("\n" + "=" * 50)
    print("📊 评估报告")
    print("=" * 50)
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print("=" * 50)

    # 保存 JSON 报告
    report = {"summary": summary, "details": results}
    report_path = os.path.join(os.path.dirname(__file__), "report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n📄 详细报告已保存到: {report_path}")


if __name__ == "__main__":
    main()