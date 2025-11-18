# 目的：(Phase 1.4 & 1.5) 建立 AI (HNSW) 索引並執行 ANALYZE。
import psycopg2
import time
import os
from dotenv import load_dotenv

load_dotenv()
DB_SETTINGS = {
    "host": os.environ.get("DB_HOST"),
    "port": os.environ.get("DB_PORT"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME") # 應為 "db_project"
}

def finalize_database():
    """
    執行 Phase 1 的最後兩個步驟：
    1. 建立 HNSW 索引 (為了「計畫 B」的效能)
    2. 執行 ANALYZE (為了「計畫 A」的 CBO 預測)
    """
    conn = None
    try:
        # --- 2. 連線到資料庫 ---
        # [注意] 建立索引和 ANALYZE 不能在事務 (transaction) 中執行
        # 我們必須設定 conn.autocommit = True
        print(f"正在連線至資料庫 '{DB_SETTINGS['database']}'...")
        conn = psycopg2.connect(**DB_SETTINGS)
        conn.autocommit = True
        cursor = conn.cursor()
        
        # --- 3. 步驟 1.4：建立「AI 索引 (HNSW)」 ---
        # 這是「盾」的「計畫 B (Vector-First)」的關鍵武器。
        # 沒有這個，`ORDER BY embedding <-> ...` 會掃描 3 萬筆資料，導致計畫 B 永遠不可行。
        print("\n步驟 1/2：建立 'HNSW' 向量索引 (為了計畫 B)...")
        print("[注意] 這一過程可能需要幾分鐘（取決於資料量），請耐心等候...")
        
        start_time = time.time()
        
        # 我們使用 HNSW 索引，它是目前 pg_vector 中最快最強的
        # m = 16, ef_construction = 64 是推薦的預設值
        # <-> (餘弦相似度) 使用 `vector_cosine_ops`
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_embedding_hnsw 
        ON products 
        USING HNSW (embedding vector_cosine_ops) 
        WITH (m = 16, ef_construction = 64);
        """)
        # 請先找出** 64 個**『可能的』鄰居，然後再從這 64 個中，挑選出最好的 16 個來當作永久連結。」
        end_time = time.time()
        print(f"向量索引建立完畢！花費時間：{ (end_time - start_time) / 60:.2f} 分鐘。")

        # --- 4. 步驟 1.5：產生 CBO 統計資料 ---
        # 這是「盾」的「計畫 A (SQL-First)」的「大腦食物」。
        # 執行 ANALYZE，PostgreSQL 才會去計算 `brand = 'Gucci'` 佔了 0.01%
        # 這樣 CBO 在 Phase 3 才能「預測」`N_filtered`。
        print("\n步驟 2/2：執行 'ANALYZE' (為了讓 CBO 能夠預測)...")
        
        start_time = time.time()
        # [注意] 我們使用小寫的 'products'
        cursor.execute("ANALYZE products;")
        end_time = time.time()
        
        print(f"資料庫分析 (ANALYZE) 完畢！花費時間：{ (end_time - start_time):.2f} 秒。")

        
        print("\n" + "=" * 40)
        print("【專案 Phase 1 已完成！】")
        print("您的資料庫現在已完全準備好，可以執行 CBO 混合查詢了。")
        print("=" * 40)

    except psycopg2.OperationalError as e:
        print(f"\n[致命錯誤] 無法連線至 PostgreSQL 資料庫。")
        print(f"請檢查您的 .env 檔案是否正確，以及資料庫服務是否在執行。")
        print(f"錯誤訊息：{e}")
    except Exception as e:
        print(f"發生錯誤：{e}")
    finally:
        # --- 5. 清理 ---
        if conn:
            conn.close()
            print("資料庫連線已關閉。")

# --- 執行主函式 ---
if __name__ == "__main__":
    finalize_database()