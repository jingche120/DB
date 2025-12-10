# 檔名：run_final_comprehensive.py
# 目的：一鍵執行所有專案驗證測試 (Test A, Test B, Test C)
# 功能：
#   1. 自動清除舊的 resultA/B/C 資料夾
#   2. 執行稀有查詢 (Test A)
#   3. 執行大眾查詢 (Test B)
#   4. 執行 Recall 驗證 (Test C)

import cbo_proxy
import query_parser
import os
import sys
import shutil  # 用於刪除資料夾

# --- 1. 全域參數設定 ---

# [建議] 準備兩張圖以獲得最佳視覺效果
# IMG_HIGH_PRICE: 像手錶、包包等高價品 (用於 Test A)
# IMG_LOW_PRICE:  像毛巾、衣服等平價品 (用於 Test B & C)
# 如果你只有一張圖，就暫時都填同一張
IMG_HIGH_PRICE = "img/c5cf3874db.jpg"  # 建議換成 img/watch.jpg
IMG_LOW_PRICE  = "img/062d927729.jpg"  # 建議使用原圖

# 庫外圖 (用於 Test C 的子任務)
IMG_OUT = "img/test_outside.jpg"

# 查詢設定
TEXT_MOD = "red color"              # 微調指令
EXCHANGE_RATE = 2.6                 # 匯率

# 價格區間設定 (TWD)
# [Test A] 稀有區間 (模擬高價商品，筆數少)
PRICE_NARROW_MIN = 3000
PRICE_NARROW_MAX = 4000
# [Test B] 寬鬆區間 (模擬大眾商品，筆數多)
PRICE_WIDE_MIN = 0
PRICE_WIDE_MAX = 10000

# --- 2. 輔助函式 ---

def cleanup_old_results():
    """清除所有舊的測試結果資料夾"""
    folders = ['resultA', 'resultB', 'resultC']
    print("🧹 [初始化] 正在清除舊的測試結果資料夾...")
    
    for folder in folders:
        if os.path.exists(folder):
            try:
                shutil.rmtree(folder) # 遞迴刪除資料夾與內容
                print(f"   已刪除: {folder}/")
            except Exception as e:
                print(f"   無法刪除 {folder}: {e}")
    print("="*60)

def calculate_recall(ground_truth_list, candidate_list, top_k_truth=5, top_n_candidate=20):
    truth_ids = {row['uniq_id'] for row in ground_truth_list[:top_k_truth]}
    candidate_ids = {row['uniq_id'] for row in candidate_list[:top_n_candidate]}
    
    intersection = truth_ids.intersection(candidate_ids)
    hit_count = len(intersection)
    denominator = min(top_k_truth, len(ground_truth_list))
    
    if denominator == 0: return 0.0, 0, 0
    return hit_count / denominator, hit_count, denominator

# --- 3. 測試 A：稀有查詢 (High Selectivity) ---
def run_test_a():
    print("\n" + "="*60)
    print("🧪 執行 [測試 A]：稀有查詢 (High Selectivity)")
    print("   預期結果：CBO 選擇 Plan A，圖片存入 resultA/")
    print("="*60)

    # 使用高價圖片 (以符合高價 SQL 區間)
    img_path = IMG_HIGH_PRICE
    
    v_query = query_parser.get_query_vector(img_path, TEXT_MOD)
    if not v_query: return

    # 生成 SQL (窄區間)
    inr_min = PRICE_NARROW_MIN * EXCHANGE_RATE
    inr_max = PRICE_NARROW_MAX * EXCHANGE_RATE
    sql_filter = f"sales_price BETWEEN {inr_min} AND {inr_max}"
    print(f"   圖片: {img_path}")
    print(f"   SQL 條件: {sql_filter} (約 TWD {PRICE_NARROW_MIN}-{PRICE_NARROW_MAX})")

    # CBO 決策與執行
    decision = cbo_proxy.get_cbo_decision(sql_filter)
    
    if decision == "PLAN_A":
        results = cbo_proxy.execute_plan_a(sql_filter, v_query)
    else:
        results = cbo_proxy.execute_plan_b(sql_filter, v_query)
    
    # 存檔
    cbo_proxy.save_result_images(results, target_folder="resultA")
    print(f"✅ [測試 A] 完成。決策: {decision}。結果已存入 resultA/")


# --- 4. 測試 B：大眾查詢 (Low Selectivity) ---
def run_test_b():
    print("\n" + "="*60)
    print("🧪 執行 [測試 B]：大眾查詢 (Low Selectivity)")
    print("   預期結果：CBO 選擇 Plan B，圖片存入 resultB/")
    print("="*60)

    # 使用平價圖片 (因為寬鬆區間包含平價品)
    img_path = IMG_LOW_PRICE
    
    v_query = query_parser.get_query_vector(img_path, TEXT_MOD)
    if not v_query: return

    # 生成 SQL (寬區間)
    inr_min = PRICE_WIDE_MIN * EXCHANGE_RATE
    inr_max = PRICE_WIDE_MAX * EXCHANGE_RATE
    sql_filter = f"sales_price BETWEEN {inr_min} AND {inr_max}"
    print(f"   圖片: {img_path}")
    print(f"   SQL 條件: {sql_filter} (約 TWD {PRICE_WIDE_MIN}-{PRICE_WIDE_MAX})")

    # CBO 決策與執行
    decision = cbo_proxy.get_cbo_decision(sql_filter)
    
    if decision == "PLAN_A":
        results = cbo_proxy.execute_plan_a(sql_filter, v_query)
    else:
        results = cbo_proxy.execute_plan_b(sql_filter, v_query)
    
    # 存檔
    cbo_proxy.save_result_images(results, target_folder="resultB")
    print(f"✅ [測試 B] 完成。決策: {decision}。結果已存入 resultB/")


# --- 5. 測試 C：Recall 驗證 (In & Out Dataset) ---
def run_test_c_logic(subtask_name, img_path):
    print(f"\n   --- 子任務：{subtask_name} ({img_path}) ---")
    
    v_query = query_parser.get_query_vector(img_path, TEXT_MOD)
    if not v_query:
        print(f"❌ 錯誤：找不到圖片 {img_path}，跳過。")
        return

    # 使用寬鬆 SQL (模擬 Plan B 發揮的場景)
    inr_min = PRICE_WIDE_MIN * EXCHANGE_RATE
    inr_max = PRICE_WIDE_MAX * EXCHANGE_RATE
    sql_filter = f"sales_price BETWEEN {inr_min} AND {inr_max}"

    # 定義資料夾結構
    base_folder = f"resultC/{subtask_name}"
    folder_a = os.path.join(base_folder, "PlanA")
    folder_b = os.path.join(base_folder, "PlanB")

    # 強制執行 Plan A (Ground Truth)
    print("   正在執行 Plan A (標準答案)...")
    results_a = cbo_proxy.execute_plan_a(sql_filter, v_query, limit_n=20)
    cbo_proxy.save_result_images(results_a, target_folder=folder_a)

    # 強制執行 Plan B (Candidate)
    print("   正在執行 Plan B (挑戰者)...")
    results_b = cbo_proxy.execute_plan_b(sql_filter, v_query, limit_n=20)
    cbo_proxy.save_result_images(results_b, target_folder=folder_b)

    # 計算 Recall
    recall, hit, denom = calculate_recall(results_a, results_b)
    print(f"   📊 Recall 分析: Plan A Top-{denom} 中有 {hit} 個出現在 Plan B Top-20。")
    print(f"   🏆 Recall = {recall*100:.2f}%")
    print(f"   圖片已存入: {base_folder}/")


def run_test_c():
    print("\n" + "="*60)
    print("🧪 執行 [測試 C]：Recall 驗證 (Plan A vs Plan B)")
    print("   目的：證明 Plan B 在犧牲些微準確度下，仍能保持高召回率")
    print("="*60)

    # 5.1 測試庫內圖 (使用平價圖)
    run_test_c_logic("1_InDataset", IMG_LOW_PRICE)

    # 5.2 測試庫外圖 (如果有檔案的話)
    if os.path.exists(IMG_OUT):
        run_test_c_logic("2_OutDataset", IMG_OUT)
    else:
        print(f"\n⚠️ [跳過] 找不到庫外測試圖 {IMG_OUT}。")
        print("   若需測試 Out-of-Dataset，請準備圖片並命名為 img/test_outside.jpg")


# --- 主程式進入點 ---
if __name__ == "__main__":
    # [新增] 執行前先清理舊資料
    cleanup_old_results()

    print("🚀 [Hybrid Search Optimizer] 全面驗證腳本啟動...")
    
    # 依序執行所有測試
    run_test_a()  # 產出 resultA
    run_test_b()  # 產出 resultB
    run_test_c()  # 產出 resultC (含子資料夾)
    
    print("\n🎉🎉🎉 所有測試執行完畢！請查看 resultA, resultB, resultC 資料夾。")