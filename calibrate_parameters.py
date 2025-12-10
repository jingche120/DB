import psycopg2
import time
import os
import numpy as np
from dotenv import load_dotenv

# --- 載入設定 ---
load_dotenv()

DB_SETTINGS = {
    "host": os.environ.get("DB_HOST"),
    "port": os.environ.get("DB_PORT"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME")
}

def get_db_connection():
    return psycopg2.connect(**DB_SETTINGS)

def get_random_vector_str(dim=768):
    """產生一個隨機向量字串"""
    return str(np.random.rand(dim).tolist())

def run_benchmark():
    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    print("🧪 開始實驗：透過時間差測量向量計算成本")
    print("=" * 60)

    # 1. 準備隨機向量
    v_query = get_random_vector_str()
    
    # 2. 定義兩個測試量級
    SMALL_BATCH = 100    # 少量
    LARGE_BATCH = 10000  # 大量 (建議大一點，差異才明顯)

    print(f"📊 測試情境 1: 計算 {SMALL_BATCH} 筆向量距離")
    print(f"📊 測試情境 2: 計算 {LARGE_BATCH} 筆向量距離")
    print("-" * 60)

    # ==========================================
    # 步驟 A: 測量時間 (ms)
    # ==========================================
    
    # 定義 SQL：強制資料庫只做計算，不走索引，確保測到的是 CPU 時間
    # 使用子查詢 LIMIT 來控制筆數
    sql_template = """
    SELECT sum(embedding <-> %s) 
    FROM (SELECT embedding FROM products LIMIT %s) as sub
    """

    # --- 測量小 Batch ---
    # 先熱身一次
    cur.execute(sql_template, (v_query, SMALL_BATCH))
    
    start = time.perf_counter()
    cur.execute(sql_template, (v_query, SMALL_BATCH))
    cur.fetchone()
    end = time.perf_counter()
    time_small = (end - start) * 1000 # ms

    # --- 測量大 Batch ---
    # 先熱身一次
    cur.execute(sql_template, (v_query, LARGE_BATCH))

    start = time.perf_counter()
    cur.execute(sql_template, (v_query, LARGE_BATCH))
    cur.fetchone()
    end = time.perf_counter()
    time_large = (end - start) * 1000 # ms

    print(f"   ⏱️  Time({SMALL_BATCH} rows): {time_small:.4f} ms")
    print(f"   ⏱️  Time({LARGE_BATCH} rows): {time_large:.4f} ms")

    # ==========================================
    # 步驟 B: 計算「每筆向量的純運算時間」
    # ==========================================
    
    delta_time = time_large - time_small
    delta_rows = LARGE_BATCH - SMALL_BATCH
    
    ms_per_row = delta_time / delta_rows
    
    print("-" * 60)
    print(f"🧮 計算過程: ({time_large:.2f} - {time_small:.2f}) / ({LARGE_BATCH} - {SMALL_BATCH})")
    print(f"🚀 每筆向量平均耗時: {ms_per_row:.6f} ms")
    
    if ms_per_row <= 0:
        print("⚠️ 異常：測量結果為負或零，可能是資料量太少或快取干擾。請增加 LARGE_BATCH。")
        return

    # ==========================================
    # 步驟 C: 換算成 PG Cost (匯率轉換)
    # ==========================================
    print("-" * 60)
    print("💰 正在計算 PG Cost 匯率 (Cost <-> ms)...")
    
    # 我們跑一個簡單的 EXPLAIN 來取得基準 Cost
    cur.execute("EXPLAIN (FORMAT JSON) SELECT 1")
    cost_base = cur.fetchone()[0][0]['Plan']['Total Cost'] # 應該很接近 0.01 或 0
    
    # 為了準確，我們用全表掃描來算匯率
    cur.execute("EXPLAIN (FORMAT JSON) SELECT count(*) FROM products")
    plan = cur.fetchone()[0][0]['Plan']
    predicted_cost = plan['Total Cost']
    
    start = time.perf_counter()
    cur.execute("SELECT count(*) FROM products")
    cur.fetchone()
    end = time.perf_counter()
    real_time = (end - start) * 1000
    
    # 匯率：1 Cost = 多少 ms
    exchange_rate = real_time / predicted_cost
    print(f"   -> 匯率: 1 PG Cost ≈ {exchange_rate:.6f} ms")
    
    # 最終轉換
    final_c_vec_cost = ms_per_row / exchange_rate
    
    print("=" * 60)
    print("✅ 實驗結果：建議參數值")
    print(f"C_VEC_CPU_COST = {final_c_vec_cost:.5f}")
    print("(請將此數值填入 cbo_proxy.py)")

    cur.close()
    conn.close()

def run_fixed_cost_experiment():
    conn = get_db_connection()
    conn.autocommit = True
    cur = conn.cursor()

    print("🧪 開始實驗：測量 COST_B_FIXED (HNSW 起步價)")
    print("=" * 60)

    # 1. 準備隨機向量
    v_query = get_random_vector_str()

    # ==========================================
    # 步驟 A: 測量時間 (ms) - HNSW Index Scan
    # ==========================================
    print("1️⃣  測量 HNSW LIMIT 1 耗時 (起步價)...")
    
    # 查詢：只找 1 筆，強迫 DB 啟動索引但幾乎不花時間遍歷
    # 注意：這裡假設你的 DB 已經有 HNSW 索引，如果沒有會變成全表掃描，數據會錯。
    sql_index = f"""
    SELECT uniq_id FROM products 
    ORDER BY embedding <-> '{v_query}' 
    LIMIT 1;
    """

    # 熱身 (Warmup) - 讓索引載入記憶體
    cur.execute(sql_index)
    
    # 正式測量 (跑 5 次取平均比較準)
    times = []
    for _ in range(5):
        start = time.perf_counter()
        cur.execute(sql_index)
        cur.fetchone()
        end = time.perf_counter()
        times.append((end - start) * 1000)
    
    avg_index_time_ms = sum(times) / len(times)
    print(f"   ⏱️  平均耗時: {avg_index_time_ms:.4f} ms")

    # ==========================================
    # 步驟 B: 計算匯率 (Cost <-> ms)
    # ⚠️ 必須跟上一個實驗用一樣的邏輯，才能對齊單位
    # ==========================================
    print("-" * 60)
    print("2️⃣  計算 PG Cost 匯率...")
    
    # 使用全表掃描來基準化
    explain_sql = "EXPLAIN (FORMAT JSON) SELECT count(*) FROM products"
    run_sql = "SELECT count(*) FROM products"

    cur.execute(explain_sql)
    predicted_cost = cur.fetchone()[0][0]['Plan']['Total Cost']

    # 測量執行時間
    start = time.perf_counter()
    cur.execute(run_sql)
    cur.fetchone()
    end = time.perf_counter()
    real_time_ms = (end - start) * 1000

    exchange_rate = real_time_ms / predicted_cost
    print(f"   -> 匯率: 1 PG Cost ≈ {exchange_rate:.6f} ms")

    # ==========================================
    # 步驟 C: 換算結果
    # ==========================================
    
    # 公式：起步價(Cost) = 起步時間(ms) / 匯率
    final_fixed_cost = avg_index_time_ms / exchange_rate

    print("=" * 60)
    print("✅ 實驗結果：建議參數值")
    print(f"COST_B_FIXED = {final_fixed_cost:.2f}")
    print("(請將此數值填入 cbo_proxy.py)")

    cur.close()
    conn.close()


if __name__ == "__main__":
    print("🚀 開始全自動參數校準程序...")
    print("=" * 60)
    
    # 1. 執行運算成本測試
    # 注意：這裡我微調了一下，讓函式回傳數值會更方便 (即使不改，看 Log 也可以)
    run_benchmark()
    
    print("\n" + "=" * 60 + "\n")
    
    # 2. 執行固定成本測試
    run_fixed_cost_experiment()

    print("\n" + "=" * 60)
    print("🎉 校準完成！請將上方兩個 [建議參數值] 填入 cbo_proxy.py")