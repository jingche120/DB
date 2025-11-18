# ---
# 檔名：analyze_distribution.py
# 目的：(Phase 1.6 - 額外分析步驟)
#      在 'finalize_database.py' 執行完畢後，執行此腳本。
#      用來「親眼驗證」我們資料庫中的資料分佈，
#      這能幫助我們「預測」CBO 在 Phase 3 會如何決策。
# ---

# --- 1. 匯入必要的函式庫 ---
import psycopg2               # 用於連線 PostgreSQL
import pandas as pd             # 用於資料處理和分析 (建立 DataFrame)
import plotly.express as px   # 用於快速繪製「互動式」的統計圖表
import os                     # 用於讀取系統環境變數
from dotenv import load_dotenv  # 用於讀取 .env 檔案中的密碼
import time                   # 用於計算腳本執行時間
import sys                    # 用於在 .env 檢查失敗時退出腳本

# --- 2. 載入設定 ---

# 讀取 .env 檔案 (DB_NAME, DB_USER, DB_PASSWORD...)
load_dotenv() 

# 從 .env 檔案將設定讀取到 Python 變數中
DB_SETTINGS = {
    "host": os.environ.get("DB_HOST"),
    "port": os.environ.get("DB_PORT"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME") # 應為 "db_project"
}

# --- 3. [輔助函式] 檢查環境變數 ---
def check_env_vars():
    """
    這是一個「防呆機制」。
    在連線資料庫前，先檢查 .env 檔案是否都已正確載入。
    """
    print("步驟 1/5：檢查 .env 環境變數...")

    vars_to_check = {
        "DB_NAME (在 .env)": DB_SETTINGS["database"],
        "DB_USER (在 .env)": DB_SETTINGS["user"],
        "DB_PASSWORD (在 .env)": DB_SETTINGS["password"],
        "DB_HOST (在 .env)": DB_SETTINGS["host"],
        "DB_PORT (在 .env)": DB_SETTINGS["port"]
    }


    # 找出所有值是 'None' (未設定) 的變數
    missing_vars = [key for key, value in vars_to_check.items() if value is None]
    
    if missing_vars:
        # 如果有任何一個變數缺失，就印出錯誤並停止程式
        print(f"    [錯誤] 致命錯誤：環境變數 {', '.join(missing_vars)} 未設定。")
        print("    請檢查您的 .env 檔案是否包含所有必要的設定。")
        return False
    
    print(f"    [成功] 所有環境變數均已載入 (DB_USER: {DB_SETTINGS['user']}, DB_NAME: {DB_SETTINGS['database']})。")
    return True

# --- 4. [主函式] ---
def analyze_distribution():
    """
    連線到資料庫，讀取 CBO 相關欄位，並繪製分佈直方圖。
    """
    conn = None # 初始化連線變數
    try:
        # --- 5. 連線並讀取「所有」CBO 相關欄位 ---
        print(f"\n步驟 2/5：正在連線至資料庫 '{DB_SETTINGS['database']}'...")
        conn = psycopg2.connect(**DB_SETTINGS)
        
        # [關鍵] 為了 CBO 分析，我們需要「全部」的資料，而不只是抽樣
        # [優化] 我們「只」讀取 CBO (盾) 需要的「結構化」欄位。
        #       我們「不需要」讀取 `embedding` (矛) 欄位，這會讓這個查詢快非常多！
        query = "SELECT brand, sales_price, rating, amazon_prime_y_or_n FROM products;"
        
        
        start_time = time.time()
        # 'pandas.read_sql_query' 是一個超棒的函式，
        # 它會自動執行 query，並將「所有」結果直接打包成一個 DataFrame (df)。
        df = pd.read_sql_query(query, conn)
        end_time = time.time()
        
        print(f"    [成功] 成功讀取 {len(df)} 筆資料。花費時間：{end_time - start_time:.2f} 秒。")

        # --- 6. 資料清理 ---
        print("\n步驟 4/5：正在清理資料 (填補空值)...")
        
        # .fillna(0.0) 會將所有 None/NaN (空值) 替換為 0.0
        # `errors='coerce'` 會將無法轉換的價格（例如空字串）變為 NaN，然後再被 fillna 捕捉
        # 這是為了避免 'plot_3d' 中發生的 TypeError
        df['sales_price'] = pd.to_numeric(df['sales_price'], errors='coerce').fillna(0.0)
        df['brand'] = df['brand'].fillna('N/A') # 將空品牌設為 'N/A' 字串
        df['rating'] = pd.to_numeric(df['rating'], errors='coerce').fillna(0.0)
        df['amazon_prime_y_or_n'] = df['amazon_prime_y_or_n'].fillna('N')
        print("    [成功] 資料清理完畢。")

        # --- 7. 繪製「價格 (sales_price)」直方圖 ---
        # 這是 CBO「預測」`WHERE price < 5000` 的依據
        print("\n步驟 5/5：正在生成互動式圖表...")
        print("    正在生成 'sales_price' 直方圖...")
        
        # 我們將價格 > 10000 的視為極端值 (outliers)，暫時濾掉以便觀察
        # (PostgreSQL 的 `ANALYZE` 在建立直方圖時也會做類似的「離群值」處理)
        # 並且濾掉 0 元的商品（通常是錯誤資料或免費商品）
        df_filtered_price = df[ (df['sales_price'] < 10000) & (df['sales_price'] > 0) ] 
        
        # 使用 Plotly Express (px) 快速繪圖
        fig_price = px.histogram(
            df_filtered_price, 
            x="sales_price",    # X 軸使用 'sales_price' 欄位
            nbins=100,          # 將價格切成 100 個「長條」
            title="商品價格分佈直方圖 (sales_price) [已過濾 0 元與 >5000 元]"
        )
        
        # 儲存為 HTML 檔案
        price_output_file = "price_histogram.html"
        fig_price.write_html(price_output_file)
        print(f"    【成功！】已儲存價格直方圖： {price_output_file}")


        # --- 8. 繪製「品牌 (brand)」直方圖 ---
        # 這是 CBO「預測」`WHERE brand = 'Gucci'` 的依據
        print("    正在生成 'brand' 直方圖 (Top 30)...")
        
        # 計算前 30 大的品牌 (我們排除 'N/A'，因為它不是一個真實品牌)
        top_30_brands = df[df['brand'] != 'N/A']['brand'].value_counts().nlargest(30).index
        df_top_brands = df[df['brand'].isin(top_30_brands)]
        
        fig_brand = px.histogram(
            df_top_brands, 
            x="brand", # X 軸使用 'brand' 欄位
            title="商品品牌分佈直方圖 (Top 30 品牌)"
        ).update_xaxes(categoryorder="total descending") # 讓圖表從「最多」排到「最少」
        
        # 儲存為 HTML
        brand_output_file = "brand_histogram.html"
        fig_brand.write_html(brand_output_file)
        print(f"    【成功！】已儲存品牌直方圖： {brand_output_file}")
        
        print("\n" + "="*40)
        print("【分析完畢】")
        print("請在瀏覽器中開啟 .html 檔案，查看 CBO 的『大腦食物』。")
        print("="*40)


    except psycopg2.OperationalError as e:
        print(f"\n[致命錯誤] 無法連線至 PostgreSQL 資料庫。")
        print(f"1. 請確保 Postgres.app (大象) 正在 'Running'。")
        print(f"2. 請確保您的 .env 檔案設定正確。")
        print(f"錯誤訊息：{e}")
    except Exception as e:
        print(f"發生未預期錯誤：{e}")
    finally:
        # --- 9. 清理 ---
        # 無論成功或失敗，最後都要「關閉」連線
        if conn:
            conn.close()
            print("資料庫連線已關閉。")

# --- 執行主函式 ---
if __name__ == "__main__":
    if check_env_vars(): # 步驟 1: 檢查 .env 設定
        analyze_distribution() # 步驟 2: 執行主程式
    else:
        sys.exit(1) # 如果 .env 設定有誤，則退出