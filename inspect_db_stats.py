import psycopg2
import os
from dotenv import load_dotenv
import decimal # 用來檢查型別

# 1. 匯率設定 (1 TWD ≈ 2.6 INR)
EXCHANGE_RATE = 2.6 

# 2. 載入資料庫設定
load_dotenv()
DB_SETTINGS = {
    "host": os.environ.get("DB_HOST"),
    "port": os.environ.get("DB_PORT"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME")
}

def inspect_price_stats():
    conn = None
    try:
        conn = psycopg2.connect(**DB_SETTINGS)
        cursor = conn.cursor()

        print("--- [1. 資料庫價格總體分佈 (INR)] ---")
        cursor.execute("SELECT MIN(sales_price), AVG(sales_price), MAX(sales_price), COUNT(*) FROM products;")
        min_p, avg_p, max_p, count = cursor.fetchone()
        
        # [修正點 1] 將 Decimal 轉為 float 後再除以 EXCHANGE_RATE
        print(f"總筆數: {count}")
        print(f"最低價: ₹{min_p} (約 TWD {float(min_p)/EXCHANGE_RATE:.0f})")
        print(f"最高價: ₹{max_p} (約 TWD {float(max_p)/EXCHANGE_RATE:.0f})")
        print(f"平均價: ₹{avg_p:.2f} (約 TWD {float(avg_p)/EXCHANGE_RATE:.0f})")
        
        print("\n--- [2. Postgres 統計直方圖 (pg_stats)] ---")
        query = """
            SELECT histogram_bounds 
            FROM pg_stats 
            WHERE tablename = 'products' AND attname = 'sales_price';
        """
        cursor.execute(query)
        result = cursor.fetchone()
        
        if result and result[0]:
            raw_bounds = result[0]
            
            # [修正點 2] 判斷回傳的是 List 還是字串
            if isinstance(raw_bounds, list):
                # 如果 psycopg2 已經幫你轉成 list 了，直接用
                bounds = [float(x) for x in raw_bounds]
            else:
                # 如果是字串 "{10,20,30}"，才需要 replace
                bounds = [float(x) for x in raw_bounds.replace('{','').replace('}','').split(',')]
            
            print(f"Postgres 將價格切分為 {len(bounds)-1} 個區間 (Buckets)。")
            print("部分邊界值範例 (INR):")
            print(f"  前 5 個邊界: {bounds[:5]}")
            # 安全切片 (防止 list 長度不足)
            mid = len(bounds)//2
            print(f"  中 5 個邊界: {bounds[mid : mid+5]}")
            print(f"  後 5 個邊界: {bounds[-5:]}")
            
            rows_per_bucket = count / (len(bounds) - 1) if len(bounds) > 1 else count
            print(f"\n[分析]：每個區間大約包含 {int(rows_per_bucket)} 筆資料 (Equi-depth)。")
            
        else:
            print("無法取得直方圖數據。請確認是否有執行過 'ANALYZE products;'")

# ... (前面的程式碼不用動) ...

        print("\n--- [3. 模擬 CBO 預估準確度測試] ---")
        # 測試：輸入台幣 100-500
        twd_min, twd_max = 100, 500
        inr_min = twd_min * EXCHANGE_RATE
        inr_max = twd_max * EXCHANGE_RATE
        
        print(f"測試查詢: TWD {twd_min}-{twd_max} => SQL INR {inr_min:.2f}-{inr_max:.2f}")
        
        # A. 問 CBO
        explain_sql = f"EXPLAIN (FORMAT JSON) SELECT * FROM products WHERE sales_price BETWEEN {inr_min} AND {inr_max};"
        cursor.execute(explain_sql)
        
        # [修正點] Postgres 回傳的是一個 List，結構是 [{ "Plan": { ... } }]
        plan_list = cursor.fetchone()[0] 
        estimated_rows = plan_list[0]['Plan']['Plan Rows'] # 這裡多加一個 [0]
        
        # B. 問 真實
        count_sql = f"SELECT COUNT(*) FROM products WHERE sales_price BETWEEN {inr_min} AND {inr_max};"
        cursor.execute(count_sql)
        actual_rows = cursor.fetchone()[0]
        
        print(f"CBO 預估筆數: {estimated_rows}")
        print(f"實際 筆數: {actual_rows}")
        
        if actual_rows > 0:
            error_rate = abs(estimated_rows - actual_rows) / actual_rows * 100
            print(f"誤差率: {error_rate:.2f}%")
        else:
            print("實際筆數為 0，無法計算誤差率")

    except Exception as e:
        print(f"發生錯誤: {e}")
        # import traceback
        # traceback.print_exc()
    finally:
        if conn:
            conn.close()
if __name__ == "__main__":
    inspect_price_stats()