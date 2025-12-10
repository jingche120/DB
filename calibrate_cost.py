# 檔名：calibrate_cost.py
# 目的：(Phase 4 前置) 參數校準
# 功能：執行線性回歸實驗，計算 CBO 成本模型中的「單一向量計算成本係數 (C_vec)」
# 原理：Time = a * N + b
#       - N: 資料筆數
#       - a: 斜率 (我們要求的 C_vec)
#       - b: 固定開銷

import psycopg2
import os
import time
import numpy as np
from dotenv import load_dotenv

# 1. 載入資料庫設定
load_dotenv()
DB_SETTINGS = {
    "host": os.environ.get("DB_HOST"),
    "port": os.environ.get("DB_PORT"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME")
}

# 設定向量維度 (依據你的 clip-ViT-L-14 模型)
VECTOR_DIM = 768

def generate_random_vector(dim):
    """生成一個隨機的單位向量，用於測試計算"""
    vec = np.random.rand(dim)
    vec = vec / np.linalg.norm(vec) # 正規化
    return vec.tolist()

def run_calibration():
    print("開始執行 CBO 參數校準實驗 (Linear Regression Calibration)...")
    
    conn = None
    try:
        conn = psycopg2.connect(**DB_SETTINGS)
        conn.autocommit = True
        cursor = conn.cursor()

        # 測試不同的資料筆數規模 (N)
        # 我們模擬 SQL 篩選後分別剩下這些筆數的情況
        N_values = [100, 500, 1000, 2000, 5000, 10000, 20000]
        measured_times = []

        # 生成一個固定的隨機查詢向量
        query_vec = generate_random_vector(VECTOR_DIM)
        query_vec_str = str(query_vec)

        print(f"{'資料筆數 (N)':<15} | {'平均耗時 (ms)':<15}")
        print("-" * 35)

        for n in N_values:
            # 針對每個 N，跑 5 次取平均，減少波動誤差
            trials = []
            for _ in range(5):
                # [關鍵 SQL]
                # 我們使用子查詢 (Subquery) + LIMIT 來模擬「SQL 篩選後剩下 N 筆」的情況
                # 然後對這 N 筆資料執行 <-> (向量距離) 排序
                # EXPLAIN (ANALYZE, FORMAT JSON) 讓我們拿到 DB 內部真實的執行時間 (排除 Python 網路開銷)
                sql = f"""
                    EXPLAIN (ANALYZE, FORMAT JSON)
                    SELECT uniq_id 
                    FROM (
                        SELECT uniq_id, embedding FROM products LIMIT {n}
                    ) as sub
                    ORDER BY embedding <-> '{query_vec_str}'
                    LIMIT 10;
                """
                cursor.execute(sql)
                plan = cursor.fetchone()[0]
                
                # 取得 "Execution Time" (單位是毫秒 ms)
                exec_time = plan[0]['Execution Time']
                trials.append(exec_time)
            
            avg_time = sum(trials) / len(trials)
            measured_times.append(avg_time)
            print(f"{n:<15} | {avg_time:.4f} ms")

        # --- 進行線性回歸計算 ---
        # 使用 numpy.polyfit 找出最佳擬合直線: y = ax + b
        # x = N_values (筆數)
        # y = measured_times (耗時)
        # deg = 1 (一次方程式/線性)
        slope, intercept = np.polyfit(N_values, measured_times, 1)

        print("\n" + "="*40)
        print("📊 校準結果 (Calibration Result)")
        print("="*40)
        print(f"方程式: Time = {slope:.6f} * N + {intercept:.6f}")
        print(f"斜率 (Slope, a): {slope:.6f} ms/row")
        print(f"截距 (Intercept, b): {intercept:.6f} ms")
        print("-" * 40)
        
        # 這裡的 slope 是毫秒 (ms)，我們的 Cost Model 如果是用「單位成本」
        # 通常建議直接把這個值當作 C_VEC_CPU_COST
        
        print(f"\n✅ 建議更新 cbo_proxy.py 中的參數：")
        print(f"C_VEC_CPU_COST = {slope:.6f}")
        print("="*40)
        
        # 額外檢查：如果斜率是負的或極小，代表測試數據有問題
        if slope <= 0:
            print("⚠️ 警告：計算出的斜率不合理，請檢查資料庫連線或資料量是否足夠。")

    except Exception as e:
        print(f"❌ 發生錯誤: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    run_calibration()