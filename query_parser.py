# ---
# 檔名：query_parser.py
# 目的：(Phase 2) 實作「AI 的矛」。
# 功能：擔任「翻譯官」，將使用者的「多模態輸入」轉換為 CBO 能理解的「向量」和「SQL 字串」。
# ---

from sentence_transformers import SentenceTransformer
from PIL import Image
import numpy as np
import re # 匯入「正則表達式」函式庫，用於解析文字

# --- 1. 載入 AI 模型 ---
# 載入我們在 Phase 1.3 使用的「同一個」CLIP 模型
# (它會從 ~/.cache/torch... 的「快取」中載入，所以很快)
print("[Query Parser] 正在載入 AI (CLIP) 模型...")
try:
    model = SentenceTransformer('clip-ViT-L-14')
    print("[Query Parser] AI 模型載入成功。")
except Exception as e:
    print(f"[Query Parser] 致命錯誤：無法載入 AI 模型。 {e}")
    model = None

# --- 2. AI 向量組合 (Vector Composition) ---
# 這就是您「向量微調」的核心概念

# [AI 的關鍵] 多模態烘焙的權重


#IMG_WEIGHT = 0.85
#TEXT_WEIGHT = 0.15


IMG_WEIGHT = 1
TEXT_WEIGHT = 0



def slerp(val, low, high):
    """
    球面線性插值 (Spherical Linear Interpolation)
    這是處理高維向量 (如 CLIP embedding) 的標準數學方法。
    比簡單的加權平均更能保留原始特徵。
    
    val: 插值權重 (0.0 ~ 1.0)，這裡是 TEXT_WEIGHT
    low: 起點向量 (圖片)
    high: 終點向量 (文字)
    """
    low_norm = low / np.linalg.norm(low)
    high_norm = high / np.linalg.norm(high)
    
    omega = np.arccos(np.clip(np.dot(low_norm, high_norm), -1, 1))
    so = np.sin(omega)
    
    if so == 0:
        return (1.0 - val) * low + val * high # 如果向量平行，退回線性插值
    
    return (np.sin((1.0 - val) * omega) / so) * low + (np.sin(val * omega) / so) * high




def get_query_vector(base_image_path, modification_text):
    """
    (Phase 2.1) 實作「AI 向量微調」
    接收「基準圖片」和「微調文字」，回傳一個「組合」後的查詢向量。
    """
    if not model:
        print("錯誤：AI 模型未載入。")
        return None

    try:
        # A. 將「基準圖片」轉換為向量
        image = Image.open(base_image_path)
        v_img = model.encode(image, normalize_embeddings=True)
        
        # B. 將「微調文字」轉換為向量
        v_text = model.encode(modification_text, normalize_embeddings=True)
        
        # C. [AI 核心] 執行「向量算術」(加權平均)
        v_query = (v_img * IMG_WEIGHT) + (v_text * TEXT_WEIGHT)
        # 高維度的方式 球面線性插值
        #v_query = slerp(TEXT_WEIGHT, v_img, v_text)
        # D. 再次標準化 (確保向量長度為 1)
        v_query_normalized = v_query / np.linalg.norm(v_query)
        
        print(f"[Query Parser] 成功生成查詢向量 (V_query)。")
        return v_query_normalized.tolist() # 轉為 Python 列表，方便傳輸

    except FileNotFoundError:
        print(f"錯誤：找不到圖片檔案 {base_image_path}")
        return None
    except Exception as e:
        print(f"錯誤：在 get_query_vector 中發生錯誤：{e}")
        return None

# --- 3. SQL 篩選解析 (SQL Filter Parsing) ---

def get_sql_filter(full_prompt_text):
    """
    (Phase 2.2) 實作「SQL 篩選解析」
    從使用者的完整提示中「萃取」結構化條件。
    
    [注意] 
    這是一個「簡易版」的解析器，只處理 'price' 和 'brand'。
    一個「真正」的專案會在這裡使用 LLM (大型語言模型) 來做「自然語言轉 SQL」。
    但對於我們的 CBO 專案，這個「簡易版」就足夠驗證了。
    """
    print(f"[Query Parser] 正在解析 SQL 篩選條件：'{full_prompt_text}'")
    
    sql_conditions = [] # 用來存放所有找到的 SQL 條件

    # 1. 搜尋「價格 (Price)」
    # 're.search' 會尋找 'price < 500' 或 'price > 1000' 或 'price 1000-2000'
    price_match = re.search(r"price\s*(<|>|BETWEEN)\s*(\d+)(\s*AND\s*(\d+))?", full_prompt_text, re.IGNORECASE)
    if price_match:
        operator = price_match.group(1) # <, > 或 BETWEEN
        val1 = price_match.group(2)     # 500
        val2 = price_match.group(4)     # (可選) 2000
        
        if operator.upper() == "BETWEEN" and val2:
            sql_conditions.append(f"sales_price BETWEEN {val1} AND {val2}")
        elif operator in ["<", ">"]:
            sql_conditions.append(f"sales_price {operator} {val1}")

    # 2. 搜尋「品牌 (Brand)」
    # 're.search' 會尋找 'brand = Gucci' 或 'brand is Nike' 或 'brand Gucci'
    brand_match = re.search(r"brand\s*(=|is)?\s*\'?([a-zA-Z0-9\s']+)\'?", full_prompt_text, re.IGNORECASE)
    if brand_match:
        # .strip() 用於去除 'Gucci' 前後的潛在空格
        brand_name = brand_match.group(2).strip()
        # [安全] 我們必須在品牌名稱周圍加上「單引號」，SQL 才認得
        sql_conditions.append(f"brand = '{brand_name}'")

    # 3. 組合所有條件
    if not sql_conditions:
        print("[Query Parser] 未找到 SQL 篩選條件。")
        return "1 = 1" # 回傳一個「永遠為真」的條件，代表「不過濾」
    
    sql_filter_string = " AND ".join(sql_conditions)
    print(f"[Query Parser] 成功解析 SQL 篩選：'{sql_filter_string}'")
    return sql_filter_string