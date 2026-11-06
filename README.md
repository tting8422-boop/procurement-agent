# 採購比價 Agent

LLM 以 tool use 呼叫三個工具（列零件、比價、風險檢查），依需求量與交期產出採購建議。
資料為虛構範例（`data/quotes.csv`）。

## 執行
```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=你的金鑰
python agent.py --dry-run          # 只測工具，不呼叫 LLM
python agent.py "電源模組 PSU-65W 要 1000 個，30 天內到貨"
```

## 設計重點
- 工具是純函式，與 LLM 解耦，可單獨測試
- `MAX_STEPS` 限制迴圈；工具錯誤回傳給模型而非中斷
- System prompt 禁止編造數據，必須先呼叫工具

## 已知限制與下一步
- 資料為靜態 CSV，尚未接 ERP / 供應商 API
- 無評測集：下一步建立 10–20 題標準答案，量測建議正確率
- 無成本與延遲記錄：下一步加入 token 用量統計
- 風險規則為硬編碼，可改為可設定的政策檔
