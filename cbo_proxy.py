# ---
# 檔名：cbo_proxy.py
# 目的：(Phase 3) 實作「DB 的盾」。
# 功能：這是我們專案的「主程式」。它會接收查詢，
#      呼叫 CBO 決策演算法，並執行「最快」的計畫。
# ---

import psycopg2
from psycopg2 import sql, extras
import os
import shutil
from dotenv import load_dotenv
import time
import numpy as np # 用於處理向量的「純數學計算」
import sys
# [關鍵] 匯入我們在 Phase 2 撰寫的「矛」
import query_parser 

# --- 1. 載入設定 ---
load_dotenv() 

DB_SETTINGS = {
    "host": os.environ.get("DB_HOST"),
    "port": os.environ.get("DB_PORT"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME") # 應為 "db_project"
}

# --- 2. CBO 參數設定 ---
# [調校參數] 這是 CBO「成本模型」的常數
# 這代表我們「猜測」一次「向量數學計算」的成本，
# 大約等於 0.01 單位的「PG 成本」。
# 這需要透過 Phase 4 的實驗來「調校」。
C_VEC_CPU_COST = 0.01 

# [調校參數] 這是「計畫 B」的「固定成本」。
# 我們透過「預先實驗」得知，HNSW 撈 1000 筆的成本「大約」是 3000。
# 這也需要調校。
COST_B_FIXED = 600.0 

# [調校參數] 計畫 B (Vector-First) 要撈出的「候選人」數量
K_CANDIDATES = 1000

# --- 3. [Phase 3.1] CBO 核心決策演算法 ---
def get_cbo_decision(sql_filter_string):
    
    """
    CBO 的「大腦」。
    接收「純 SQL 篩選字串」，並「預測」計畫 A 和 B 的成本。
    回傳 "PLAN_A" 或 "PLAN_B"。
    """

    print(f"\n--- [CBO 決策開始 (Phase 3.1)] ---")
    print(f"CBO 收到 SQL 篩選：'{sql_filter_string}'")
    
    # [特殊情況] 如果 SQL 篩選為空
    # 我們「必須」走計畫 B (Vector-First)

    if sql_filter_string is None or sql_filter_string == "" or sql_filter_string == "1 = 1":
        print("CBO 偵測：無 SQL 篩選。 [決策：計畫 B (Vector-First)]")
        return "PLAN_B"

    conn = None
    try:
        # (A) 詢問 PG：執行 `EXPLAIN`
        conn = psycopg2.connect(**DB_SETTINGS)
        conn.autocommit = True
        cursor = conn.cursor()
        
        # [關鍵] 我們使用 EXPLAIN (FORMAT JSON) 來「詢問」PG：
        # 「嘿，如果你要執行這個 SQL 篩選，你的『預測成本』和『預測筆數』是多少？」
        explain_query = sql.SQL("EXPLAIN (FORMAT JSON) SELECT uniq_id FROM products WHERE {sql_filter};").format(
            sql_filter=sql.SQL(sql_filter_string) # 安全地插入 SQL 字串
        )
        
        cursor.execute(explain_query)
        explain_json = cursor.fetchone()[0] # 取得 JSON 結果
        
        # (B) 取得預測
        # 從 JSON 中解析出「預測筆數」和「SQL 成本」
        n_filtered_sql = explain_json[0]["Plan"]["Plan Rows"]
        cost_sql_only = explain_json[0]["Plan"]["Total Cost"]
        
        print(f"CBO 預測 (pg_stats)：SQL 將篩選出 ≈ {n_filtered_sql} 筆資料。")
        print(f"CBO 預測 (pg_stats)：計畫 A 的「SQL 成本」為 {cost_sql_only:.2f}")

        # (C) 套用公式：計算 Score(A)
        # Score(A) = (PG 預測的 SQL 成本) + (我們預測的 Python 計算成本)
        score_a = cost_sql_only + (n_filtered_sql * C_VEC_CPU_COST)
        
        # (D) 取得 Score(B) (在 V1 中，這是一個固定值)
        score_b = COST_B_FIXED

        print(f"CBO 成本模型計算：")
        print(f"  > 預測 Score(A) (SQL-First) = {score_a:.2f}")
        print(f"  > 預測 Score(B) (Vector-First) = {score_b:.2f}")

        # (E) 做出決策
        if score_a < score_b:
            print(f"[CBO 決策：計畫 A (SQL-First)] (因為 {score_a:.2f} < {score_b:.2f})")
            return "PLAN_A"
        else:
            print(f"[CBO 決策：計畫 B (Vector-First)] (因為 {score_a:.2f} >= {score_b:.2f})")
            return "PLAN_B"

    except Exception as e:
        print(f"CBO 決策時發生嚴重錯誤：{e}")
        print("CBO 決策失敗，將預設執行 [計畫 B] 以確保穩定性。")
        return "PLAN_B" # 發生錯誤時，預設走「固定成本」的計畫 B

    except Exception as e:
        print(f"CBO 決策時發生嚴重錯誤：{e}")
        print("CBO 決策失敗，將預設執行 [計畫 B] 以確保穩定性。")
        return "PLAN_B" # 發生錯誤時，預設走「固定成本」的計畫 B

    finally:
        if conn:
            conn.close()

# --- 4. [Phase 3.2] 計畫 A 執行器 ---
def execute_plan_a(sql_filter, v_query):
    
    #執行「計畫 A (SQL-First)」：
    #1. [DB] 執行 SQL 篩選 (使用 B-Tree 索引)
    #2. [DB] 執行向量排序 (使用 <->)
    #3. [DB] 回傳 Top 10
    
    print("--- [CBO 正在執行：計畫 A (SQL-First)] ---")
    conn = None
    try:
        conn = psycopg2.connect(**DB_SETTINGS)
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor) # 讓我們能用欄位名稱存取

        # [關鍵] 我們將「篩選」和「排序」都交給資料庫！
        # PG 的優化器會「先」用 B-Tree 索引 (WHERE) 找到少數候選人，
        # 「然後」才對這些少數人執行昂貴的 <-> (similarity) 排序。
        # (這比我們在 Python 中手動計算 50 次還快)
        
        # [注意] <-> 是「距離」(0=最像)，所以我們用 ASC (升冪) 排序
        query_a = sql.SQL("""
            SELECT uniq_id, brand, sales_price, (embedding <-> %s) AS similarity_score
            FROM products
            WHERE {sql_filter}
            ORDER BY similarity_score ASC 
            LIMIT 10;
        """).format(sql_filter=sql.SQL(sql_filter_string)) # 安全地插入 SQL 字串
        
        # `v_query` (向量) 作為第二個參數傳入，以防止 SQL 注入
        #? 我們必須將 Python 列表 (v_query) 轉換為「字串」
        #? pg_vector 才能將其轉換為「vector」類型

        cursor.execute(query_a, (str(v_query),)) 
        
        results = cursor.fetchall()
        return [dict(row) for row in results] # 將結果轉為字典列表

    except Exception as e:
        print(f"執行計畫 A 時發生錯誤：{e}")
        return []
    finally:
        if conn:
            conn.close()

# --- 5. [Phase 3.3] 計畫 B 執行器 ---
def execute_plan_b(sql_filter, v_query, k=K_CANDIDATES):
    """
    執行「計畫 B (Vector-First)」：
    1. [DB] 執行向量搜尋 (使用 HNSW 索引)，找出 k 個候選人。
    2. [DB] 對這 k 個候選人執行 SQL 篩選。
    3. [DB] 回傳 Top 10
    """
    print(f"--- [CBO 正在執行：計畫 B (Vector-First) (k={k})] ---")
    conn = None
    try:
        conn = psycopg2.connect(**DB_SETTINGS)
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor) 
        
        # 我們使用「子查詢 (Subquery)」或「通用資料表表達式 (CTE)」
        # 讓資料庫「先」跑 HNSW 索引，「再」跑 SQL 篩選
        query_b = sql.SQL("""
            WITH VectorSearch AS (
                SELECT uniq_id, brand, sales_price, (embedding <-> %s) AS similarity_score -- <-> 是 pg_vector 的運算子，代表「向量距離」 %s 代表查詢向量cursor.execute(query_b, (str(v_query),)裡面的str(v_query)。
                FROM products
                ORDER BY similarity_score ASC 
                LIMIT {limit_k} -- 1. [AI] 先用 HNSW 索引找出 k 個
            )
            SELECT * FROM VectorSearch
            WHERE {sql_filter} -- 2. [SQL] 再從這 k 個中，篩選出符合條件的
            LIMIT 10;
        """).format(
            limit_k=sql.Literal(k), 
            sql_filter=sql.SQL(sql_filter_string)
        )
        # (str(v_query),) 是您要填進去的 「值」 (您的 $V_{query} 查詢向量) => 帶入參數的概念
        cursor.execute(query_b, (str(v_query),))

        # 如果 SQL 查詢結果有 10 筆資料，fetchall() 就會回傳一個包含 10 個項目的 List。如果沒資料，就會回傳空 List []        
        results = cursor.fetchall()

        return [dict(row) for row in results]

    except Exception as e:
        print(f"執行計畫 B 時發生錯誤：{e}")
        return []
    finally:
        if conn:
            conn.close()

# --- 6. [主程式] 測試 CBO ---
if __name__ == "__main__":

    # --- 模擬使用者輸入 ---
    # 為了測試 CBO，我們需要兩個「乾淨」的範例：
    # 1. 一個「高選擇性」的 SQL (預期 CBO 選擇 A)
    # 2. 一個「低選擇性」的 SQL (預期 CBO 選擇 B)
    # 
    # 您可以「註解掉」其中一個來切換測試。
    #
    # ----------------------------------------------------
    # 範例 1：高選擇性 SQL (預期 CBO 應選擇「計畫 A」)
    # (您設計的範例：`brand = 'Max' AND price > 2000`)
    # ----------------------------------------------------
    TEST_CASE_NAME = "高選擇性查詢 (High Selectivity)"
    # 我們使用 .ldjson 檔案中的第一筆資料 '26d41bdc1495de290bc8e6062d927729'
    # 它對應的檔案名稱是 '062d927729.jpg' (uniq_id 的末 10 碼 + .jpg)
    USER_IMAGE_PATH = "img/062d927729.jpg" # (LA' Facon)
    
    #USER_TEXT_MOD = "a different color"
    USER_TEXT_MOD = ""
    # [!! 關鍵修改 !!] 我們「直接」提供 SQL 篩選字串
    # (注意：'Max' 周圍的單引號 '' 必須有)
    # USER_SQL_FILTER = "brand = 'LA'' Facon' AND sales_price > 100"
    USER_SQL_FILTER = "brand = 'LA'' Facon'"
    # ----------------------------------------------------
    # 範例 2：低選擇性 SQL (預期 CBO 應選擇「計畫 B」)
    # (您設計的範例：`brand = 'Max'`)
    # ----------------------------------------------------
    #TEST_CASE_NAME = "低選擇性查詢 (Low Selectivity)"
    #USER_IMAGE_PATH = "img/062d927729.jpg" # (LA' Facon)
    #USER_TEXT_MOD = "a different color"
    # # [!! 關鍵修改 !!] 我們「直接」提供 SQL 篩選字串
    #USER_SQL_FILTER = "brand = 'Max'"
    # ----------------------------------------------------



    print("="*40)
    print(f"測試案例：{TEST_CASE_NAME}")
    print(f"  圖片: {USER_IMAGE_PATH}")
    print(f"  微調: {USER_TEXT_MOD}")
    print(f"  SQL篩選: {USER_SQL_FILTER}") # <--- [!! 已修改 !!]
    print("="*40)
    
    # --- [Phase 2] 執行「矛」 ---
    v_query = query_parser.get_query_vector(USER_IMAGE_PATH, USER_TEXT_MOD)
    sql_filter_string = USER_SQL_FILTER
    
    if v_query is None:
        print("錯誤：無法生成查詢向量，任務終止。")
        sys.exit(1)

    # --- [Phase 3] 執行「盾」 ---
    
    # 3.1 取得 CBO 決策
    start_time = time.time()
    decision = get_cbo_decision(sql_filter_string)
    decision_time = time.time() - start_time
    
    # 3.2 執行 CBO 選擇的計畫
    start_time = time.time()
    if decision == "PLAN_A":
        results = execute_plan_a(sql_filter_string, v_query)
    else:
        results = execute_plan_b(sql_filter_string, v_query)
    execution_time = time.time() - start_time
    
    # --- 4. 顯示結果 ---
    print("\n" + "="*40)
    print("【查詢完成】")
    print(f"  CBO 決策耗時：{decision_time:.4f} 秒")
    print(f"  查詢執行耗時：{execution_time:.4f} 秒")
    print(f"  共找到 {len(results)} 筆結果：")
    
    if results:
        for i, row in enumerate(results):
            # 距離轉相似度
            score = row['similarity_score']
            print(f"  {i+1}. ID: {row['uniq_id'][-10:]}, Brand: {row['brand']}, Price: {row['sales_price']}, Score: {(1 - score):.4f}")
    
            # Copy image to review folder
            id10 = row['uniq_id'][-10:]
            src = f"img/{id10}.jpg"
            dst = f"review/{id10}.jpg"
            if os.path.exists(src):
                shutil.copy(src, dst)
                print(f"  Copied {id10}.jpg to review/")
            else:
                print(f"  Image {src} not found, skipping.")
    else:
        print("  (未找到符合所有條件的商品)")
    print("="*40)
