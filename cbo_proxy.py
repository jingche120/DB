# ---
# 檔名：cbo_proxy.py
# 狀態：最終修正版 (包含 Plan A, Plan B, 圖片輸出, 參數校準)
# ---

import psycopg2
from psycopg2 import sql, extras
import os
import shutil
from dotenv import load_dotenv
import time
import sys
import query_parser 

# --- 1. 載入設定 ---
load_dotenv() 

DB_SETTINGS = {
    "host": os.environ.get("DB_HOST"),
    "port": os.environ.get("DB_PORT"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME")
}

# --- 2. CBO 參數設定 ---

# [校準結果] 單一向量計算成本 (ms/row)
C_VEC_CPU_COST = 0.0016 

# [調整後參數] HNSW 索引搜尋的固定成本 (ms)
# K=200 時預估約 9.0ms
COST_B_FIXED = 9.0 

# [兩階段篩選參數]
K_CANDIDATES = 5  # HNSW 內部召回數量
N_RESULTS = 20      # 最終回傳數量

# [匯率設定] 1 TWD = 2.6 INR
EXCHANGE_RATE = 2.6

# --- 3. [Phase 3.1] CBO 核心決策演算法 ---
def get_cbo_decision(sql_filter_string):
    print(f"\n--- [CBO 決策開始] ---")
    
    if not sql_filter_string or sql_filter_string.strip() == "":
        print("CBO 偵測：無 SQL 篩選。 [決策：計畫 B (Vector-First)]")
        return "PLAN_B"

    conn = None
    try:
        conn = psycopg2.connect(**DB_SETTINGS)
        conn.autocommit = True
        cursor = conn.cursor()
        
        # 使用 EXPLAIN 獲取預估筆數
        explain_query = sql.SQL("EXPLAIN (FORMAT JSON) SELECT uniq_id FROM products WHERE {sql_filter};").format(
            sql_filter=sql.SQL(sql_filter_string)
        )
        
        cursor.execute(explain_query)
        explain_plan = cursor.fetchone()[0]
        # 注意：有些 Postgres 版本回傳結構可能是 List，這裡做個防呆
        if isinstance(explain_plan, list):
            plan_data = explain_plan[0]
        else:
            plan_data = explain_plan
            
        n_filtered_sql = plan_data["Plan"]["Plan Rows"]
        
        print(f"CBO 預測 (pg_stats)：SQL 將篩選出 ≈ {n_filtered_sql} 筆資料。")

        # 套用成本公式
        score_a = n_filtered_sql * C_VEC_CPU_COST
        score_b = COST_B_FIXED

        print(f"CBO 成本模型計算 (單位: ms)：")
        print(f"  > 預測 Score(A) (SQL-First)    = {score_a:.4f} ms")
        print(f"  > 預測 Score(B) (Vector-First) = {score_b:.4f} ms")

        if score_a < score_b:
            print(f"[CBO 決策：計畫 A (SQL-First)] (因為 A < B)")
            return "PLAN_A"
        else:
            print(f"[CBO 決策：計畫 B (Vector-First)] (因為 A >= B)")
            return "PLAN_B"

    except Exception as e:
        print(f"CBO 決策時發生錯誤：{e}")
        return "PLAN_B"
    finally:
        if conn:
            conn.close()

# --- 4. [Phase 3.2] 計畫 A 執行器 ---
def execute_plan_a(sql_filter_string, v_query, limit_n=N_RESULTS):
    print("--- [執行：計畫 A (SQL-First)] ---")
    conn = None
    try:
        conn = psycopg2.connect(**DB_SETTINGS)
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        query_a = sql.SQL("""
            SELECT uniq_id, brand, sales_price, (embedding <-> %s) AS similarity_score
            FROM products
            WHERE {sql_filter}
            ORDER BY similarity_score ASC 
            LIMIT {limit_n};
        """).format(
            sql_filter=sql.SQL(sql_filter_string),
            limit_n=sql.Literal(limit_n)
        )
        
        cursor.execute(query_a, (str(v_query),))
        results = cursor.fetchall()
        return [dict(row) for row in results]

    except Exception as e:
        print(f"執行計畫 A 時發生錯誤：{e}")
        return []
    finally:
        if conn:
            conn.close()

# --- 5. [Phase 3.3] 計畫 B 執行器 ---
def execute_plan_b(sql_filter_string, v_query, k_candidates=K_CANDIDATES, limit_n=N_RESULTS):
    print(f"--- [執行：計畫 B (Vector-First) (K={k_candidates} -> N={limit_n})] ---")
    conn = None
    try:
        conn = psycopg2.connect(**DB_SETTINGS)
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor) 
        
        query_b = sql.SQL("""
            WITH VectorCandidates AS (
                SELECT uniq_id, brand, sales_price, embedding, (embedding <-> %s) AS similarity_score
                FROM products
                ORDER BY embedding <-> %s
                LIMIT {limit_k}
            )
            SELECT * FROM VectorCandidates
            WHERE {sql_filter}
            ORDER BY similarity_score ASC
            LIMIT {limit_n};
        """).format(
            limit_k=sql.Literal(k_candidates),
            sql_filter=sql.SQL(sql_filter_string),
            limit_n=sql.Literal(limit_n)
        )
        
        v_str = str(v_query)
        cursor.execute(query_b, (v_str, v_str))
        results = cursor.fetchall()
        return [dict(row) for row in results]

    except Exception as e:
        print(f"執行計畫 B 時發生錯誤：{e}")
        return []
    finally:
        if conn:
            conn.close()

# --- 新增功能：儲存圖片 ---
# [重要] 這個函式必須在主程式區塊之外，且縮排不能錯
def save_result_images(results, source_folder="img", target_folder="result"):
    """
    將查詢結果的圖片複製到 result 資料夾
    """
    if not os.path.exists(target_folder):
        os.makedirs(target_folder)
        # print(f"已建立資料夾: {target_folder}/")

    print(f"正在輸出 {len(results)} 張圖片到 {target_folder}/ ...")
    
    for i, row in enumerate(results):
        # 根據 uniq_id 取得原始檔名 (取後10碼)
        if 'uniq_id' in row:
            original_filename = f"{row['uniq_id'][-10:]}.jpg"
            source_path = os.path.join(source_folder, original_filename)
            
            # 新檔名：排名_原始檔名.jpg
            new_filename = f"{i+1}_{original_filename}"
            target_path = os.path.join(target_folder, new_filename)
            
            try:
                if os.path.exists(source_path):
                    shutil.copy(source_path, target_path)
                else:
                    print(f"  [遺失] 找不到原始圖片: {source_path}")
            except Exception as e:
                print(f"  [錯誤] 複製失敗: {e}")
        else:
            print("  [錯誤] 資料列中找不到 uniq_id")

# --- 主程式區塊 (僅供直接執行本檔測試用) ---
if __name__ == "__main__":
    print("請直接執行 run_final_test.py 來進行整合測試。")