1.  我們**要做什麼** (核心概念)。
2.  我們**為什麼**要這麼做 (CBO 的價值)。
3.  我們**如何**做到 (技術架構)。
4.  我們**已經完成**了什麼 (您的 `Phase 1` 成果)。
5.  我們**下一步**要做什麼 (Phase 2, 3, 4)。

我已經為您準備好了這份**「專案 README」**檔案。它總結了我們到目前為止的所有討論，並為我們接下來的實作鋪平了道路。


http://googleusercontent.com/immersive_entry_chip/0
* **CBO 的挑戰：** 資料庫有兩種執行路徑，效能天差地遠：
    1.  **計畫 A (SQL-First)：** 「精確」但「危險」。先跑 SQL 篩選（如果撈出 10 萬筆就會**災難性地慢**）。
    2.  **計畫 B (Vector-First)：** 「近似」但「穩定」。先跑 AI 索引（永遠只撈 `k=1000` 筆），但可能**「錯過」**第 1001 名的完美答案。

* **我們的解決方案 (Janus AI-CBO)：**
    我們**「正在實作」**（`Phase 3`）一個「智慧 CBO 代理」。它**不是**兩個都跑，而是會**「預測」**：
    1.  CBO **「詢問」** PG 的 `EXPLAIN` 指令，並讀取 `pg_stats`（統計資料）。
    2.  CBO **「預測」** `WHERE brand = 'Gucci'` 只會撈出 `N_filtered = 50` 筆。
    3.  CBO **「計算」** `Cost(A)` (極低) vs. `Cost(B)` (固定高)。
    4.  CBO **「決策」**：自動選擇「計畫 A」，以「最低成本」達到「100% 準確度」。
    5.  （反之，如果 SQL 是 `price < 5000`，`Cost(A)` 飆高，CBO 就會**自動切換**到「計畫 B」，以「犧牲 1% 準確度」來「保證」效能。）

---

## 2. 專案狀態 (Current Status)

我們目前已經**「完成」**了所有最困難的**「基礎建設 (Phase 1)」**。

### 【已完成 (DONE)】

* **[環境]** `Postgres.app` (v16 引擎) 已「乾淨重裝」並在 `port 5432` 運作。
* **[環境]** `PATH` 已設定，`psql` 和 `createdb` 指令可被終端機辨識。
* **[環境]** `.env` 檔案已設定為「正確」的使用者（`lin`）和「空密碼」。
* **[Phase 1.2]** `createdb db_project`：已建立「空白」資料庫。
* **[Phase 1.1/1.2/1.4]** `create_table.py`：已執行。
    * [✓] `products` 資料表（含 `embedding VECTOR(768)`）已建立。
    * [✓] `pg_vector` 擴充已啟用。
    * [✓] `B-Tree` 索引（`idx_brand`, `idx_price` 等）已建立 (為「計畫 A」準備)。
* **[Phase 1.3]** `offline_vectorize_and_insert.py`：已執行。
    * [✓] `...30k_data.ldjson` 已被讀取。
    * [✓] 3 萬筆資料的「圖片」和「文字」已「烘焙」成 `embedding` 向量。
    * [✓] 3 萬筆資料已**「全部寫入」** `db_project` 資料庫。
* **[Phase 1.4/1.5]** `finalize_database.py`：已執行。
    * [✓] `HNSW` 索引（`idx_embedding_hnsw`）已建立 (為「計畫 B」準備)。
    * [✓] `ANALYZE products;` 已執行 (為 CBO 預測準備 `pg_stats`)。
* **[分析]** `visualize_vectors.py` / `analyze_distribution.py`：
    * [✓] 我們已成功「視覺化」3D 向量群集。
    * [✓] 我們已成功「繪製」出 CBO 所需的「長條圖」（`brand`, `price` 分佈）。

---

## 3. 【下一步】(To-Do) - 實作「查詢」

**我們的「基礎建設」已經 100% 完工。**

我們現在要開始「蓋房子」，也就是實作「查詢」的核心邏輯。我們的下一步是**「依序」**完成 `Phase 2` 和 `Phase 3` 的程式碼。

### [ ] Phase 2: 「矛」- 實作 AI 查詢生成器
* **檔案：** `query_parser.py`
* **任務 1 (2.1)：** 實作 `get_query_vector(image_path, text_mod)` 函式。
    * *功能：* 載入 CLIP，將「圖片」和「微調文字」組合（加權平均）成**「一個」** `$V_{query}$` 向量。
* **任務 2 (2.2)：** 實作 `get_sql_filter(full_prompt_text)` 函式。
    * *功能：* 使用「正則表達式 (Regex)」，從使用者的完整句子中，**「萃取」**出 `brand = '...'` 或 `price < ...` 這樣的「純 SQL 字串」。

### [ ] Phase 3: 「盾」- 實作 CBO 智慧代理 (專案核心)
* **檔案：** `cbo_proxy.py` (這將是我們的「主」執行檔)
* **任務 1 (3.1)：** 實作 `get_cbo_decision(sql_filter_string)` 函式。
    * *功能：* 這就是 CBO 的「大腦」。它會：
        1.  **「詢問」** PG $\rightarrow$ `EXPLAIN (FORMAT JSON) ...`
        2.  **「解析」** JSON $\rightarrow$ 取得 `N_filtered` (預測筆數) 和 `Cost_SQL` (SQL 成本)。
        3.  **「計算」** $\rightarrow$ `Score(A) = Cost_SQL + (N_filtered * C_vec)`
        4.  **「決策」** $\rightarrow$ `if Score(A) < COST_B_FIXED: return "PLAN_A"`

* **任務 2 (3.2)：** 實作 `execute_plan_a(sql_filter, v_query)` 函式。
    * *功能：* 執行「精確」查詢（`WHERE ... ORDER BY ... LIMIT 10`）。

* **任務 3 (3.3)：** 實作 `execute_plan_b(sql_filter, v_query, k)` 函式。
    * *功能：* 執行「近似」查詢（`WITH VectorSearch AS (ORDER BY ... LIMIT k) SELECT * ... WHERE ...`）。

* **任務 4 (3.4)：** 撰寫 `if __name__ == "__main__":` 主程式。
    * *功能：* 模擬使用者輸入，並**「依序」**呼叫 `Phase 2` 和 `Phase 3` 的所有函式，最後印出結果。

### [ ] Phase 4: 客觀驗證 (The "Benchmark")
* **檔案：** `benchmark.py`
* **任務：**
    1.  建立「天真 A」、「天真 B」、「智慧 CBO」三個客戶端。
    2.  設計「高選擇性 (`brand = 'LA' Facon'`)」和「低選擇性 (`price < 500`)」的查詢。
    3.  執行效能測試，記錄 P95 延遲。
    4.  **[最終成果]** 繪製「金錢圖表」（CBO 的綠線貼著 A 和 B 的最小值）。
```