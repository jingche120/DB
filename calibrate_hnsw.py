# 檔名：calibrate_hnsw.py
# 目的：(Phase 4 前置) HNSW 成本校準
# 功能：測量 HNSW 索引召回 K=1000 筆資料的「固定成本」
# 輸出：COST_B_FIXED 的建議值

import psycopg2
import os
import numpy as np
from dotenv import load_dotenv

load_dotenv()
DB_SETTINGS = {
    "host": os.environ.get("DB_HOST"),
    "port": os.environ.get("DB_PORT"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME")
}

# 這是我們在 cbo_proxy.py 裡設定的 K 值
K_CANDIDATES = 1000
VECTOR_DIM = 768

def generate_random_vector(dim):
    vec = np.random.rand(dim)
    vec = vec / np.linalg.norm(vec)
    return vec.tolist()

def calibrate_hnsw():
    print(f"🚀 開始校準 HNSW 索引成本 (K={K_CANDIDATES})...")
    
    conn = None
    try:
        conn = psycopg2.connect(**DB_SETTINGS)
        conn.autocommit = True
        cursor = conn.cursor()

        measurements = []
        # 跑 10 次取平均
        for i in range(10):
            query_vec = generate_random_vector(VECTOR_DIM)
            
            # [關鍵 SQL]
            # 這裡不加任何 WHERE 條件，純粹測量 HNSW 索引抓取 Top-K 的時間
            sql = f"""
                EXPLAIN (ANALYZE, FORMAT JSON)
                SELECT uniq_id 
                FROM products 
                ORDER BY embedding <-> '{query_vec}'
                LIMIT {K_CANDIDATES};
            """
            
            cursor.execute(sql)
            plan = cursor.fetchone()[0]
            exec_time = plan[0]['Execution Time']
            measurements.append(exec_time)
            print(f"  測試 {i+1}: {exec_time:.4f} ms")

        avg_time = sum(measurements) / len(measurements)
        
        print("\n" + "="*40)
        print("📊 HNSW 校準結果")
        print("="*40)
        print(f"平均搜尋時間: {avg_time:.4f} ms")
        print(f"建議 COST_B_FIXED = {avg_time:.4f}")
        print("="*40)

    except Exception as e:
        print(f"❌ 錯誤: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    calibrate_hnsw()