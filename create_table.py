# --- 
# 檔名：create_table.py
# 目的：(Phase 1.1 / 1.2 / 1.4) 建立我們專案所需的資料庫表格和索引。
# 執行時機：在「乾淨重裝」並手動「createdb db_project」之後「第一個」執行。
# ---

import psycopg2
from psycopg2 import sql # 用於安全地組合 SQL 查詢
import os
from dotenv import load_dotenv # 用於讀取 .env 檔案

# --- 1. 載入設定 ---

# 載入 .env 檔案 (DB_NAME, DB_USER, DB_PASSWORD...)
load_dotenv()

# 從環境變數讀取資料庫連線設定
DB_SETTINGS = {
    "host": os.environ.get("DB_HOST"),
    "port": os.environ.get("DB_PORT"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME") # 應為 "db_project"
}

# [AI 模型設定]
# 我們必須在這裡定義「向量維度」
# 我們的 AI 模型 (CLIP-ViT-L-14) 輸出的是 768 維
EMBEDDING_DIM = 768 

# --- 2. 主函式 ---
def create_database_schema():
    """
    連線到資料庫，並建立 'products' 表格、啟用 'vector' 擴充、建立 B-Tree 索引。
    """
    conn = None # 初始化連線變數
    try:
        # --- 3. 連線到資料庫 ---
        # 腳本會使用 .env 檔案中的設定來連線
        print(f"正在連線至資料庫 '{DB_SETTINGS['database']}'...")
        conn = psycopg2.connect(**DB_SETTINGS)
        
        # [關鍵] 設定為「自動提交」
        # 這讓我們不需要在每個 cursor.execute() 之後都手動 commit()
        conn.autocommit = True 
        
        # 建立一個「遊標 (cursor)」，用來傳送 SQL 指令
        cursor = conn.cursor()
        
        # --- 4. 步驟 1/3：啟用 pg_vector 擴充 (「矛」的基礎) ---
        # 這是我們「AI 矛」的「必要基礎」。
        # 只有執行了這一步，PostgreSQL 才「認得」 VECTOR(768) 這種欄位類型。
        # IF NOT EXISTS 確保我們重複執行此腳本時不會報錯。
        print("步驟 1/3：啟用 'vector' 擴充 (CREATE EXTENSION IF NOT EXISTS vector)...")
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        
        # --- 5. 步驟 2/3：建立 'products' 資料表 (「矛」與「盾」的家) ---
        # 這是我們專案「唯一」的主資料表。
        # 我們「刻意」選擇了這些欄位，以同時滿足「矛」和「盾」的需求。
        print(f"步驟 2/3：建立 'products' 資料表 (向量維度 {EMBEDDING_DIM})...")
        
        # [注意] PostgreSQL 會自動將未加引號的 'Products' 轉為 'products' (小寫)
        # 我們在這裡統一使用小寫，以避免混淆。
        create_table_query = sql.SQL("""
        CREATE TABLE IF NOT EXISTS products (
            -- 來自 .ldjson 的唯一 ID，作為主鍵
            uniq_id VARCHAR(255) PRIMARY KEY,
            
            -- [矛] 用於 Phase 1.3「烘焙」多模態向量的文字來源
            product_name TEXT, 
            
            -- [盾] CBO (計畫 A) 需要的「結構化」欄位
            brand VARCHAR(255),
            sales_price NUMERIC(10, 2),
            rating NUMERIC(3, 1),
            amazon_prime_y_or_n CHAR(1),
            
            -- [矛] AI 向量的「家」，使用 pg_vector 提供的 VECTOR 類型
            embedding VECTOR({}) 
        );
        """).format(sql.Literal(EMBEDDING_DIM)) # 使用 .format() 安全地傳入 768 維度
        
        # 執行建立表格的 SQL 指令
        cursor.execute(create_table_query)
        
        # --- 6. 步驟 3/3：建立 B-Tree 索引 (「盾」的武器) ---
        # 這是「DB 盾 (CBO)」的「關鍵準備」。
        # 這是為了「武裝」我們的 CBO「計畫 A (SQL-First)」。
        # 有了這些索引，`WHERE brand = 'Gucci'` 才能在毫秒級完成。
        print("步驟 3/3：建立 'B-Tree' 索引 (為了 CBO)...")
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_brand ON products USING btree(brand);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_price ON products USING btree(sales_price);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_rating ON products USING btree(rating);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_amazon_prime ON products USING btree(amazon_prime_y_or_n);")

        print("\n" + "="*40)
        print("【成功！】資料庫結構建立完畢！")
        print(f" - 已在 '{DB_SETTINGS['database']}' 中啟用 'vector'")
        print(f" - 已建立 'products' 表格")
        print(f" - 已建立 4 個 B-Tree 索引 (用於 CBO)")
        print("="*40)
        print("\n下一步：請執行 'offline_vectorize_and_insert.py'")

    except psycopg2.OperationalError as e:
        # 捕捉「連線」錯誤 (例如 Postgres.app 沒開、.env 密碼錯誤)
        print("\n[致命錯誤] 無法連線至 PostgreSQL 資料庫。")
        print(f"1. 請確保 Postgres.app (大象) 正在 'Running'。")
        print(f"2. 請確保您的 .env 檔案設定正確 (DB_NAME, DB_USER, DB_PASSWORD)。")
        print(f"錯誤訊息：{e}")
    except Exception as e:
        # 捕捉其他所有未預期的錯誤
        print(f"發生未預期錯誤：{e}")
    finally:
        # --- 7. 清理 ---
        # 無論成功或失敗，最後都要「關閉」連線
        if conn:
            conn.close()
            print("資料庫連線已關閉。")

# --- 8. 執行主函式 ---
# 只有當這個檔案被「直接執行」(python create_table.py) 時，
# 才會呼叫 create_database_schema() 函式。
if __name__ == "__main__":
    create_database_schema()