# ---
# 檔名：offline_vectorize_and_insert.py
# 目的：(Phase 1.3) 讀取 .ldjson 和 img/，執行 AI 向量化，並將資料寫入 PostgreSQL。
# 執行時機：在「create_table.py」成功執行「之後」執行。
# ---

import json
import os
import psycopg2
from psycopg2.extras import execute_batch # 用於「批次」寫入，速度更快
from sentence_transformers import SentenceTransformer # 用於載入 CLIP AI 模型
from PIL import Image # Pillow 函式庫，用於開啟圖片
import numpy as np
import time
from dotenv import load_dotenv # 用於讀取 .env 檔案

# --- 1. 載入設定 ---
load_dotenv() 

# [!! 您的要求 !!]
# 我們先設定一個「測試上限」，只處理 10 筆資料來驗證流程是否成功。
# 驗證成功後，您可以將此值改為 None，來處理全部 3 萬筆資料。
#RECORDS_TO_PROCESS = 10 # <-- [!!] 只處理 10 筆來測試
RECORDS_TO_PROCESS = None # (當您要跑全部時，請註解掉上面那行，改用這行)

# 1. 資料庫連線 (必須與 .env 一致)
DB_SETTINGS = {
    "host": os.environ.get("DB_HOST"), 
    "port": os.environ.get("DB_PORT"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME") # 應為 "db_project"
}

# 2. 相關檔案路徑
LDJSON_FILE_PATH = 'marketing_sample_for_amazon_com-amazon_fashion_products__20200201_20200430__30k_data.ldjson'
IMG_DIR = "img" # 您下載圖片的資料夾
ERROR_LOG_FILE = "download_errors.txt" # 我們在下載階段建立的錯誤日誌

# 3. AI 模型設定
MODEL_NAME = 'clip-ViT-L-14'
EMBEDDING_DIM = 768 # 必須與 DB 中的 VECTOR(768) 匹配

# 4. 批次處理設定 (一次打包 100 筆資料再寫入 DB，速度較快)
BATCH_SIZE = 5 # 既然只處理 10 筆，我們 BATCH_SIZE 設小一點


def load_error_ids(error_file):
    """
    [輔助功能] 讀取 download_errors.txt，
    建立一個「跳過列表 (Set)」，我們將「不」處理這些下載失敗的 ID。
    """
    if not os.path.exists(error_file):
        print(f"警告：找不到錯誤日誌 {error_file}，將嘗試處理所有資料。")
        return set()
    
    print(f"正在讀取錯誤日誌 {error_file}...")
    error_ids = set()
    with open(error_file, 'r', encoding='utf-8') as f:
        for line in f:
            # 假設錯誤日誌的第一個詞是 uniq_id
            uniq_id = line.split(':')[0].split(' ')[0].strip()
            if len(uniq_id) > 10: # 確保它是一個 ID
                error_ids.add(uniq_id)
    print(f"讀取完畢，將跳過 {len(error_ids)} 筆已知錯誤資料。")
    return error_ids

def parse_price(price_str):
    """[輔助功能] 一個安全的函式，用於將價格字串轉換為數字"""
    if price_str is None: return None
    try:
        cleaned_str = str(price_str).replace(',', '').replace('$', '').strip()
        if cleaned_str: return float(cleaned_str)
        else: return None
    except (ValueError, TypeError): return None

def parse_rating(rating_str):
    """[輔助功能] 一個安全的函式，用於將評分字串轉換為數字"""
    if rating_str is None: return None
    try: return float(rating_str)
    except (ValueError, TypeError): return None

# --- 主函式 ---
def vectorize_and_insert():
    
    # [步驟 A] 載入「跳過列表」
    error_ids = load_error_ids(ERROR_LOG_FILE)
    
    # [步驟 B] 載入 AI 模型 (這一步會花一點時間，並可能下載模型)
    print(f"正在載入 AI 模型 '{MODEL_NAME}'... (第一次執行可能需要幾分鐘)")
    model = SentenceTransformer(MODEL_NAME)
    print("AI 模型載入完畢。")
    
    conn = None
    data_to_insert = [] # 批次寫入的暫存區
    processed_count = 0
    insert_count = 0
    skip_count = 0

    try:
        # [步驟 C] 連線到資料庫
        print(f"正在連線至資料庫 '{DB_SETTINGS['database']}'...")
        conn = psycopg2.connect(**DB_SETTINGS)
        cursor = conn.cursor()
        
        print(f"開始處理 {LDJSON_FILE_PATH}...")
        print(f"[!! 驗證模式 !!] 本次執行將只處理 {RECORDS_TO_PROCESS} 筆資料。")
        
        # [步驟 D] 逐行讀取 .ldjson 檔案
        with open(LDJSON_FILE_PATH, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                
                if RECORDS_TO_PROCESS is not None and processed_count >= RECORDS_TO_PROCESS:
                    print(f"\n已達到 {RECORDS_TO_PROCESS} 筆的處理上限，停止讀取檔案。")
                    break 
                
                try:
                    data = json.loads(line)
                    uniq_id = data.get("uniq_id")

                    # --- D1. 檢查是否應跳過 (前置檢查) ---
                    if not uniq_id:
                        print(f"警告：第 {i+1} 行沒有 uniq_id，跳過。")
                        continue
                    
                    if uniq_id in error_ids:
                        skip_count += 1
                        continue # 跳過下載失敗的 ID

                    # --- D2. 找到「已下載」的圖片檔案 ---
                    filename_base = uniq_id[-10:]
                    filename_jpg = f"{filename_base}.jpg"
                    image_path = os.path.join(IMG_DIR, filename_jpg)
                    
                    if not os.path.exists(image_path):
                        # print(f"警告：ID {uniq_id} 的圖片 {filename_jpg} 不存在於 {IMG_DIR}，跳過。")
                        skip_count += 1
                        continue # 跳過（圖片不存在）

                    # --- D3. [AI 核心] 執行「多模態烘焙」(The "Good Method") ---
                    
                    v_img = None
                    v_text = None
                    
                    # C1. 處理圖片 (我們「讀取」本地檔案)
                    image = Image.open(image_path)
                    embedding = model.encode(image, normalize_embeddings=True)
                    embedding_list = embedding.tolist()        
                    # --- D4. 準備 SQL 資料 ---
                    
                    record = (
                        uniq_id,
                        data.get("product_name"),
                        data.get("brand"),
                        parse_price(data.get("sales_price")),
                        parse_rating(data.get("rating")),
                        data.get("amazon_prime__y_or_n", "N")[0], # 只取第一個字元 (Y/N)
                        embedding_list # 將 numpy 陣列轉為 Python 列表
                    )
                    
                    data_to_insert.append(record)
                    processed_count += 1

                    # --- D5. 批次寫入 ---
                    if len(data_to_insert) >= BATCH_SIZE:
                        insert_query = """
                        INSERT INTO products (uniq_id, product_name, brand, sales_price, rating, amazon_prime_y_or_n, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (uniq_id) DO NOTHING;
                        """
                        execute_batch(cursor, insert_query, data_to_insert)
                        conn.commit() # 提交事務
                        insert_count += len(data_to_insert)
                        print(f"進度：已處理 {processed_count} 筆, 已寫入 {insert_count} 筆資料...")
                        data_to_insert = [] # 清空批次

                except Exception as e:
                    print(f"錯誤：處理第 {i+1} 行 (ID: {data.get('uniq_id', 'N/A')}) 時發生錯誤：{e}")
            
            # [步驟 E] 處理最後一批不足 BATCH_SIZE 的資料
            if data_to_insert:
                insert_query = """
                INSERT INTO products (uniq_id, product_name, brand, sales_price, rating, amazon_prime_y_or_n, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (uniq_id) DO NOTHING;
                """
                execute_batch(cursor, insert_query, data_to_insert)
                conn.commit()
                insert_count += len(data_to_insert)
                print(f"處理最後一批資料，共寫入 {insert_count} 筆資料。")

    except Exception as e:
        print(f"發生未預期錯誤：{e}")
    finally:
        # [步驟 F] 清理
        if conn:
            conn.close()
        print("\n" + "-" * 40)
        print("離線向量化與寫入腳本執行完畢。")
        print(f"  總共處理：{processed_count} 筆有效資料")
        print(f"  成功寫入：{insert_count} 筆資料")
        print(f"  已知錯誤/跳過：{skip_count} 筆")

# --- 執行主函式 ---
if __name__ == "__main__":
    start_time = time.time()
    vectorize_and_insert()
    end_time = time.time()
    print(f"總共花費時間：{ (end_time - start_time):.2f} 秒。")