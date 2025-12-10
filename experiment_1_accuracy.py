import psycopg2
from psycopg2 import extras 
import time
import os
import shutil
from dotenv import load_dotenv
import query_parser
import cbo_proxy 

# 載入 .env
load_dotenv()
DB_SETTINGS = cbo_proxy.DB_SETTINGS

# ================= 實驗參數設定 =================
TEST_IMAGE_PATH = "img/0a11bd2bc7.jpg"
USER_TEXT_INPUT = "I want a black long skirt"
SQL_FILTER_KEYWORDS = "product_name ILIKE '%black%' AND product_name ILIKE '%skirt%'" 
SOURCE_IMG_FOLDERS = ["img/img/", "img/"] 
RESULT_BASE_DIR = "experiment_1_accuracy_result"

# [修改] 設定想要幾筆結果
TOP_K = 20  
# ===============================================

def get_db_connection():
    return psycopg2.connect(**DB_SETTINGS)

def setup_result_folders():
    """初始化結果資料夾"""
    if os.path.exists(RESULT_BASE_DIR):
        try:
            shutil.rmtree(RESULT_BASE_DIR)
        except Exception as e:
            print(f"⚠️ 無法刪除舊資料夾: {e}")
    
    os.makedirs(os.path.join(RESULT_BASE_DIR, "Method A"), exist_ok=True)
    os.makedirs(os.path.join(RESULT_BASE_DIR, "Method B"), exist_ok=True)
    os.makedirs(os.path.join(RESULT_BASE_DIR, "Method C"), exist_ok=True)
    print(f"📂 已建立結果資料夾: {RESULT_BASE_DIR}/ [Method A, Method B, Method C]")

def save_images_to_folder(method_name, results):
    target_dir = os.path.join(RESULT_BASE_DIR, method_name)
    print(f"\n💾 正在儲存 [{method_name}] 的圖片到資料夾...")
    
    if not results:
        print("   (無結果，略過)")
        return

    # [修改] 使用 TOP_K 來決定存幾張
    for rank, row in enumerate(results[:TOP_K]): 
        uniq_id = row['uniq_id'][-10:]
        img_filename = f"{uniq_id}.jpg"
        
        src_path = None
        for folder in SOURCE_IMG_FOLDERS:
            potential_path = os.path.join(folder, img_filename)
            if os.path.exists(potential_path):
                src_path = potential_path
                break
        
        if src_path:
            # 命名格式: 01_xxx.jpg (補零以便排序)
            dst_filename = f"{rank+1:02d}_{img_filename}"
            dst_path = os.path.join(target_dir, dst_filename)
            shutil.copy(src_path, dst_path)
            print(f"   ✅ Copied: {dst_filename}")
        else:
            print(f"   ⚠️ 找不到原始圖片: {img_filename}")

def show_results(title, results):
    # [修改] 只印出前 5 筆給你看就好，不然終端機太長，但圖片會存 20 張
    print(f"\n--- {title} (Showing Top 5 of {len(results)}) ---")
    if not results:
        print("  (無結果)")
        return

    for i, row in enumerate(results[:5]):
        print(f"  {i+1}. [ID:{row['uniq_id'][-10:]}] {row['product_name'][:40]}... | ColorMatch: {'black' in row['product_name'].lower()}")

def run_experiment_accuracy():
    setup_result_folders()

    print(f"\n🧪 實驗 1：準確度驗證 (Accuracy Comparison)")
    print(f"🖼️  參考圖片: {TEST_IMAGE_PATH}")
    print(f"🔤 微調指令: '{USER_TEXT_INPUT}'")
    print(f"📊 預計擷取數量: {TOP_K} 筆")
    print("=" * 60)

    print("正在生成向量 (呼叫 query_parser)...")
    v_query = query_parser.get_query_vector(TEST_IMAGE_PATH, USER_TEXT_INPUT)
    
    if v_query is None:
        return

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    # ---------------------------------------------------------
    # 🅰️ 方法 A: 純向量搜尋
    # ---------------------------------------------------------
    print("\n🔴 [Method A] 純向量搜尋 (Pure Vector)")
    
    # [關鍵修改] 這裡一定要加 f，不然資料庫會收到 "{TOP_K}" 字串而報錯
    sql_a = f"""
    SELECT uniq_id, product_name, brand 
    FROM products 
    ORDER BY embedding <-> %s 
    LIMIT {TOP_K};
    """
    cur.execute(sql_a, (str(v_query),))
    results_a = [dict(row) for row in cur.fetchall()]
    
    show_results("Method A 結果", results_a)
    save_images_to_folder("Method A", results_a)

    # ---------------------------------------------------------
    # 🅱️ 方法 B: 純關鍵字搜尋
    # ---------------------------------------------------------
    print("\n🔵 [Method B] 純關鍵字搜尋 (Pure SQL)")
    
    # [關鍵修改] 這裡也要加 f
    sql_b = f"""
    SELECT uniq_id, product_name, brand 
    FROM products 
    WHERE {SQL_FILTER_KEYWORDS}
    LIMIT {TOP_K};
    """
    cur.execute(sql_b)
    results_b = [dict(row) for row in cur.fetchall()]
    
    show_results("Method B 結果", results_b)
    save_images_to_folder("Method B", results_b)

    # ---------------------------------------------------------
    # 🟢 方法 C: CBO 混合搜尋 (Hybrid / Ours)
    print("\n🟢 [Method C] CBO 混合搜尋 (Hybrid / Ours)")
    
    cbo_sql_filter = SQL_FILTER_KEYWORDS 
    decision = cbo_proxy.get_cbo_decision(cbo_sql_filter)
    
    # [關鍵修改] 呼叫函式時，把 TOP_K 傳進去！
    if decision == "PLAN_A":
        # 告訴 Plan A 我要幾筆
        results_c = cbo_proxy.execute_plan_a(cbo_sql_filter, v_query, limit=TOP_K)
    else:
        # 告訴 Plan B 我要幾筆
        results_c = cbo_proxy.execute_plan_b(cbo_sql_filter, v_query, limit=TOP_K)
    
    results_c = cbo_proxy.rerank_by_color(results_c, USER_TEXT_INPUT)
    
    show_results("Method C 結果", results_c)
    save_images_to_folder("Method C", results_c)

    print("\n" + "=" * 60)
    print(f"✅ 實驗完成！請查看資料夾: {RESULT_BASE_DIR}")
    cur.close()
    conn.close()

if __name__ == "__main__":
    run_experiment_accuracy()