這是一份為你量身打造的最新版 **README.md**。

這份文檔整合了你已經完成的 **Phase 1 (DB 基礎建設)**、**Phase 2 (Query Parser - 矛)** 以及 **Phase 3 (CBO Proxy - 盾)** 的所有技術細節。它不僅說明了「如何使用」，更強調了你程式碼中 **Slerp 插值** 與 **CBO 成本模型** 的技術含金量。

你可以直接複製以下 Markdown 內容到你的 GitHub 首頁。

---

# 🛡️ Janus AI-CBO: Postgres 智慧型混合搜尋優化器

> **一個基於成本 (Cost-Based) 的動態決策代理人，解決 Vector Search 與 SQL 篩選的經典效能兩難。**

目前的進度：**Phase 3 完成 (CBO 核心邏輯已實作)** 🚀

## 📖 專案背景與痛點

在現代的 AI 電商搜尋系統中，我們經常面臨「混合查詢 (Hybrid Search)」的效能瓶頸。當使用者輸入：「*找像這張圖的商品，但品牌要是 Gucci*」時，資料庫面臨兩難：

1.  **精確優先 (Plan A - SQL First):** 先篩出 Gucci，再算向量相似度。
    *   🛑 **缺點：** 如果 Gucci 有 10 萬件商品，即時計算 10 萬次向量距離會導致 CPU 爆炸，速度極慢。
2.  **速度優先 (Plan B - Vector First):** 先用 HNSW 索引找最像的 1000 件，再過濾出 Gucci。
    *   🛑 **缺點：** 如果那 1000 件裡面沒有 Gucci (或很少)，會產生「漏斗效應」，導致搜尋結果掛零或不準確。

**本專案 (Janus AI-CBO)** 引入了一個 **Python 中介層 (Proxy)**，它會在查詢執行前「詢問」資料庫統計數據，並動態決定要走哪一條路。

---

## 🏗️ 系統架構

### 核心組件
*   **⚔️ The Spear (Phase 2): `query_parser.py`**
    *   負責處理多模態輸入 (圖片 + 文字)。
    *   使用 **CLIP 模型** 生成向量，並透過 **球面線性插值 (SLERP)** 融合特徵。
    *   將自然語言解析為 SQL `WHERE` 子句 (如 `price < 500`)。
*   **🛡️ The Shield (Phase 3): `cbo_proxy.py`**
    *   系統的大腦。攔截查詢，計算執行計畫成本。
    *   利用 Postgres `EXPLAIN (FORMAT JSON)` 獲取預測行數。
    *   自動切換 **SQL-First** 或 **Vector-First** 策略。

### 決策邏輯 (CBO Logic)

系統會即時計算兩個分數，並選擇成本較低者：

*   **Score A (SQL-First):**
    $$ Cost_{PG} + (N_{rows} \times C_{vec\_cpu}) $$
    *(Postgres 的 I/O 成本 + Python 預估的向量計算成本)*
*   **Score B (Vector-First):**
    $$ Cost_{Fixed} $$
    *(HNSW 索引搜尋的固定攤提成本，通常較低但有精度風險)*

---

## 🛠️ 安裝與設定

### 1. 環境需求
*   Python 3.8+
*   PostgreSQL 15+ (需安裝 `pgvector` 擴充套件)
*   必要的 Python 套件：
    ```bash
    pip install psycopg2-binary sentence-transformers numpy pillow python-dotenv
    ```

### 2. 環境變數 (.env)
請在專案根目錄建立 `.env` 檔案：
```env
DB_HOST=localhost
DB_PORT=5432
DB_USER=your_user
DB_PASSWORD=your_password
DB_NAME=db_project
```

### 3. 資料庫準備
確保資料庫已建立 `products` 表格，並已建立 B-Tree (針對 metadata) 與 HNSW (針對 embedding) 雙重索引。

---

## 🚀 使用方式

### 執行 CBO 主程式
直接執行 `cbo_proxy.py`，它會模擬使用者查詢並展示決策過程：

```bash
python cbo_proxy.py
```

### 預期輸出範例
程式會顯示它如何根據 SQL 條件的寬鬆程度做出決策：

**情境 1：高選擇性 (High Selectivity) - 例如 `brand='稀有品牌'`**
```text
CBO 收到 SQL 篩選：'brand = 'RareBrand''
CBO 預測 (pg_stats)：SQL 將篩選出 ≈ 12 筆資料。
CBO 成本模型計算：
  > Score(A) = 15.20 (便宜！因為只要算 12 次向量)
  > Score(B) = 600.00
[CBO 決策：計畫 A (SQL-First)]
```

**情境 2：低選擇性 (Low Selectivity) - 例如 `price < 10000`**
```text
CBO 收到 SQL 篩選：'sales_price < 10000'
CBO 預測 (pg_stats)：SQL 將篩選出 ≈ 25000 筆資料。
CBO 成本模型計算：
  > Score(A) = 5000.50 (太貴！要算 2萬次向量)
  > Score(B) = 600.00
[CBO 決策：計畫 B (Vector-First)]
```

---

## 📂 檔案結構說明

```text
.
├── cbo_proxy.py       # [Phase 3] 主程式：CBO 決策代理人
├── query_parser.py    # [Phase 2] 查詢解析器：處理多模態向量與 SQL 轉換
├── img/               # 測試用的圖片庫
├── review/            # 搜尋結果圖片輸出目錄
├── .env               # 資料庫連線設定
└── README.md          # 專案說明檔
```

## 🧠 技術亮點 (Code Highlights)

### 1. 球面線性插值 (SLERP)
在 `query_parser.py` 中，我們不使用傳統的加權平均來混合「圖片向量」與「文字向量」，而是使用幾何上更正確的 **SLERP**。這能確保合成後的向量保持在單位球面上，大幅提升語義搜尋的準確度。

```python
# 來自 query_parser.py
def slerp(val, low, high):
    # ... (幾何運算確保特徵不丟失) ...
    return (np.sin((1.0 - val) * omega) / so) * low + ...
```

### 2. 即時成本預測
在 `cbo_proxy.py` 中，我們即時呼叫資料庫的核心統計數據：

```python
# 來自 cbo_proxy.py
explain_query = sql.SQL("EXPLAIN (FORMAT JSON) SELECT ... WHERE {sql_filter};")
n_filtered_sql = explain_json[0]["Plan"]["Plan Rows"]
# 動態決定是否切換執行路徑
if score_a < score_b:
    return "PLAN_A"
```

---

## 🔮 Future Roadmap (Phase 4)

目前 Phase 2 與 Phase 3 已完成實作。接下來的 **Phase 4** 將專注於：

1.  **Benchmark 壓力測試：** 建立 100 組不同分佈的測試案例。
2.  **參數調校 (Hyperparameter Tuning)：** 優化 `C_VEC_CPU_COST` 與 `COST_B_FIXED` 參數，使其更符合硬體實際表現。
3.  **自動化 SQL 生成：** 將 `query_parser` 接上 LLM (如 GPT-4o mini)，實現真正的自然語言轉 SQL。

---
*Created by Jingche | Repository for DB Embedding Optimization*