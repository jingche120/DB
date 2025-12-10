# ---
# 檔名：cbo_proxy.py
# 目的：(Phase 3) 實作「DB 的盾」。
# ---

import psycopg2
from psycopg2 import sql, extras
import os
import shutil
from dotenv import load_dotenv
import time
import numpy as np 
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
# [參數邏輯]
# 我們設定「黃金交叉點」為 2,000 筆資料。
# 當 SQL 篩選結果 < 2,000 筆 -> 認為是精確搜尋 -> Plan A (SQL Scan)
# 當 SQL 篩選結果 > 2,000 筆 -> 認為是模糊搜尋 -> Plan B (HNSW Index)

# 維持實驗測得的單筆運算成本 (稍微加一點排序權重)
C_VEC_CPU_COST = 2.0 

# 根據 1000 筆交叉點反推： 1000 * 2.0 = 2000
# 這代表去除網路延遲後，DB 內部真正的索引啟動成本約為 2000 點
COST_B_FIXED = 2000.0 

# HNSW 候選數量
K_CANDIDATES = 1000

# 預設顯示數量
DEFAULT_LIMIT = 20
"""
「我們一開始測量到 34,000，但後來發現那是包含 Client-Side Latency (網路來回時間) 的數值。
CBO 是在資料庫內部運作的，不應該考慮網路延遲。
所以我們透過 逆向校準 (Reverse Calibration)，設定當資料量超過 2,000 筆 (臨界點) 時切換策略，推導出內部的 Fixed Cost 應約為 4,000。
這讓我們的 CBO 能更準確地反映資料庫內部的真實負載。」

"""

# --- 3. [Phase 3.1] CBO 核心決策演算法 ---
def get_cbo_decision(sql_filter_string):
    """
    CBO 的「大腦」。接收「純 SQL 篩選字串」，並「預測」計畫 A 和 B 的成本。
    """
    print(f"\n--- [CBO 決策開始 (Phase 3.1)] ---")
    print(f"CBO 收到 SQL 篩選：'{sql_filter_string}'")
    
    if sql_filter_string is None or sql_filter_string == "" or sql_filter_string == "1 = 1":
        print("CBO 偵測：無 SQL 篩選。 [決策：計畫 B (Vector-First)]")
        return "PLAN_B"

    conn = None
    try:
        conn = psycopg2.connect(**DB_SETTINGS)
        conn.autocommit = True
        cursor = conn.cursor()
        
        safe_sql_filter = sql_filter_string.replace("%", "%%")

        explain_query = sql.SQL("EXPLAIN (FORMAT JSON) SELECT uniq_id FROM products WHERE {sql_filter};").format(
            sql_filter=sql.SQL(safe_sql_filter) 
        )
        
        cursor.execute(explain_query)
        explain_json = cursor.fetchone()[0] 
        
        n_filtered_sql = explain_json[0]["Plan"]["Plan Rows"]
        cost_sql_only = explain_json[0]["Plan"]["Total Cost"]
        
        print(f"CBO 預測 (pg_stats)：SQL 將篩選出 ≈ {n_filtered_sql} 筆資料。")
        print(f"CBO 預測 (pg_stats)：計畫 A 的「SQL 成本」為 {cost_sql_only:.2f}")

        score_a = cost_sql_only + (n_filtered_sql * C_VEC_CPU_COST)
        score_b = COST_B_FIXED

        print(f"CBO 成本模型計算：")
        print(f"  > 預測 Score(A) (SQL-First) = {score_a:.2f}")
        print(f"  > 預測 Score(B) (Vector-First) = {score_b:.2f}")

        if score_a < score_b:
            print(f"[CBO 決策：計畫 A (SQL-First)] (因為 {score_a:.2f} < {score_b:.2f})")
            return "PLAN_A"
        else:
            print(f"[CBO 決策：計畫 B (Vector-First)] (因為 {score_a:.2f} >= {score_b:.2f})")
            return "PLAN_B"

    except Exception as e:
        print(f"CBO 決策時發生嚴重錯誤：{e}")
        print("CBO 決策失敗，將預設執行 [計畫 B] 以確保穩定性。")
        return "PLAN_B"
    finally:
        if conn:
            conn.close()

# --- 4. [Phase 3.2] 計畫 A 執行器 ---
def execute_plan_a(sql_filter_string, v_query, limit=DEFAULT_LIMIT): # <--- [修改] 增加 limit 參數
    
    safe_sql_filter = sql_filter_string.replace("%", "%%")

    print(f"--- [CBO 正在執行：計畫 A (SQL-First) | Limit {limit}] ---")
    conn = None
    try:
        conn = psycopg2.connect(**DB_SETTINGS)
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # [修改] LIMIT 使用變數注入
        query_a = sql.SQL("""
            SELECT uniq_id, brand, product_name, sales_price, (embedding <-> %s) AS similarity_score
            FROM products
            WHERE {sql_filter}
            ORDER BY similarity_score ASC 
            LIMIT {limit_val}; 
        """).format(
            sql_filter=sql.SQL(safe_sql_filter),
            limit_val=sql.Literal(limit) # 使用 sql.Literal 安全地放入數字
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
def execute_plan_b(sql_filter_string, v_query, k=K_CANDIDATES, limit=DEFAULT_LIMIT): # <--- [修改] 增加 limit 參數
    
    safe_sql_filter = sql_filter_string.replace("%", "%%")

    print(f"--- [CBO 正在執行：計畫 B (Vector-First) (k={k}) | Limit {limit}] ---")
    conn = None
    try:
        conn = psycopg2.connect(**DB_SETTINGS)
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor) 
        
        # [修改] LIMIT 使用變數注入
        query_b = sql.SQL("""
            WITH VectorSearch AS (
                SELECT uniq_id, brand, product_name, sales_price, (embedding <-> %s) AS similarity_score 
                FROM products
                ORDER BY similarity_score ASC 
                LIMIT {limit_k}
            )
            SELECT * FROM VectorSearch
            WHERE {sql_filter}
            LIMIT {limit_final}; 
        """).format(
            limit_k=sql.Literal(k), 
            sql_filter=sql.SQL(safe_sql_filter),
            limit_final=sql.Literal(limit) # 使用 sql.Literal 安全地放入數字
        )
        
        cursor.execute(query_b, (str(v_query),))

        results = cursor.fetchall()
        return [dict(row) for row in results]

    except Exception as e:
        print(f"執行計畫 B 時發生錯誤：{e}")
        return []
    finally:
        if conn:
            conn.close()

# === 顏色關鍵字表與 Re-ranking 邏輯 ===
COLOR_KEYWORDS = {
    "red":   ["red", "burgundy", "crimson", "wine", "紅"],
    "blue":  ["blue", "navy", "indigo", "藍"],
    "black": ["black", "黑"],
    "white": ["white", "ivory", "off-white", "白"],
    "green": ["green", "綠"],
    "pink":  ["pink", "粉"],
    "yellow":["yellow", "黃"],
}

def detect_target_color_from_text(text: str):
    if not text:
        return None
    t = text.lower()
    for color, keywords in COLOR_KEYWORDS.items():
        for kw in keywords:
            if kw in t:
                return color
    return None

def product_matches_color(row: dict, target_color: str) -> bool:
    if not target_color:
        return False
    title = (row.get("product_name") or "").lower()
    for kw in COLOR_KEYWORDS.get(target_color, []):
        if kw in title:
            return True
    return False

def rerank_by_color(results: list, user_text: str) -> list:
    target_color = detect_target_color_from_text(user_text)
    if not target_color:
        return results

    def sort_key(row):
        match = product_matches_color(row, target_color)
        sim = row.get("similarity_score", 0.0)
        return (0 if match else 1, sim)

    reranked = sorted(results, key=sort_key)
    return reranked