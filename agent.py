"""採購比價 Agent：LLM 透過工具讀取報價、比價、評估風險，產出採購建議。

用法：
  python agent.py --dry-run                      # 不呼叫 LLM，只驗證工具
  python agent.py "電源模組 PSU-65W 要 1000 個，30 天內到貨"
"""
import argparse
import csv
import json
import os
from pathlib import Path

DATA = Path(__file__).parent / "data" / "quotes.csv"
MODEL = os.getenv("MODEL", "claude-sonnet-5-5")
MAX_STEPS = 8  # 防止 Agent 無限迴圈
DEFECT_LIMIT = 0.02  # 不良率警戒線


# ---------- 工具（純函式，可獨立測試） ----------
def _load() -> list[dict]:
    with open(DATA, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["unit_price"] = float(r["unit_price"])
        r["moq"] = int(r["moq"])
        r["lead_days"] = int(r["lead_days"])
        r["defect_rate"] = float(r["defect_rate"])
    return rows


def list_parts() -> list[str]:
    return sorted({r["part"] for r in _load()})


def compare_prices(part: str, qty: int) -> list[dict]:
    """列出可滿足 MOQ 的供應商，依總價由低到高排序。"""
    rows = [r for r in _load() if r["part"] == part and r["moq"] <= qty]
    for r in rows:
        r["total_cost"] = round(r["unit_price"] * qty, 2)
    return sorted(rows, key=lambda r: r["total_cost"])


def assess_risk(part: str, qty: int, deadline_days: int) -> list[dict]:
    """逐一檢查供應商：交期、不良率、MOQ。"""
    out = []
    for r in [r for r in _load() if r["part"] == part]:
        flags = []
        if r["moq"] > qty:
            flags.append(f"MOQ {r['moq']} 高於需求量")
        if r["lead_days"] > deadline_days:
            flags.append(f"交期 {r['lead_days']} 天超過期限 {deadline_days} 天")
        if r["defect_rate"] > DEFECT_LIMIT:
            flags.append(f"不良率 {r['defect_rate']:.1%} 超過 {DEFECT_LIMIT:.0%}")
        out.append({"supplier": r["supplier"], "risk_flags": flags or ["無"]})
    return out


TOOL_FUNCS = {
    "list_parts": lambda **_: list_parts(),
    "compare_prices": lambda part, qty: compare_prices(part, int(qty)),
    "assess_risk": lambda part, qty, deadline_days: assess_risk(
        part, int(qty), int(deadline_days)
    ),
}

TOOL_SPECS = [
    {
        "name": "list_parts",
        "description": "列出資料庫中所有零件名稱。",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "compare_prices",
        "description": "針對指定零件與數量，回傳符合 MOQ 的供應商及總價（由低到高）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "part": {"type": "string", "description": "零件名稱，須與 list_parts 一致"},
                "qty": {"type": "integer"},
            },
            "required": ["part", "qty"],
        },
    },
    {
        "name": "assess_risk",
        "description": "檢查各供應商的交期、不良率與 MOQ 風險。",
        "input_schema": {
            "type": "object",
            "properties": {
                "part": {"type": "string"},
                "qty": {"type": "integer"},
                "deadline_days": {"type": "integer", "description": "需求到貨天數上限"},
            },
            "required": ["part", "qty", "deadline_days"],
        },
    },
]

SYSTEM = (
    "你是採購分析助理。必須先用工具取得資料，再給建議；不可自行編造價格或交期。"
    "輸出格式：1) 建議供應商 2) 總價 3) 取捨理由 4) 風險與備援方案。使用繁體中文。"
)


# ---------- Agent 迴圈 ----------
def run_agent(task: str) -> str:
    import anthropic  # 延遲匯入，--dry-run 不需安裝

    client = anthropic.Anthropic()  # 讀取環境變數 ANTHROPIC_API_KEY
    messages = [{"role": "user", "content": task}]
    for step in range(MAX_STEPS):
        resp = client.messages.create(
            model=MODEL, max_tokens=1500, system=SYSTEM,
            tools=TOOL_SPECS, messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")
        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            try:
                output = TOOL_FUNCS[block.name](**block.input)
                content, is_error = json.dumps(output, ensure_ascii=False), False
            except Exception as e:  # 工具錯誤回傳給模型，讓它自行修正
                content, is_error = f"工具錯誤：{e}", True
            print(f"[step {step + 1}] {block.name}({block.input})")
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": content, "is_error": is_error})
        messages.append({"role": "user", "content": results})
    return "已達最大步數，未完成。"


def dry_run() -> None:
    part = "電源模組 PSU-65W"
    print("零件：", list_parts())
    print("比價：", json.dumps(compare_prices(part, 1000), ensure_ascii=False, indent=1))
    print("風險：", json.dumps(assess_risk(part, 1000, 30), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("task", nargs="?", help="採購需求描述")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.dry_run or not args.task:
        dry_run()
    else:
        print(run_agent(args.task))
