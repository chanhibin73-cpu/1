import os
import json
import re
import requests
import datetime
import urllib.parse
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore

print("=== プログラムの実行を開始します ===")

# --- 1. 環境変数の取得と検証 ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")

if not GEMINI_API_KEY:
    print("【エラー】GEMINI_API_KEY がSecretsに設定されていません。")
    exit(1)

if not FIREBASE_SERVICE_ACCOUNT_JSON:
    print("【エラー】FIREBASE_SERVICE_ACCOUNT_JSON がSecretsに設定されていません。")
    exit(1)

# SecretsのJSONフォーマットチェックと魔法のおまじない（改行コード修正）
try:
    raw_json = FIREBASE_SERVICE_ACCOUNT_JSON.strip()
    cred_dict = json.loads(raw_json)
    
    # 【重要】GitHub Secretsを通すと秘密鍵の改行(\n)が壊れることがあるため修復します
    if "private_key" in cred_dict:
        cred_dict["private_key"] = cred_dict["private_key"].replace('\\n', '\n')
        
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("✓ Firebaseの認証・接続に成功しました。")
except json.JSONDecodeError as e:
    print("【重大エラー】FIREBASE_SERVICE_ACCOUNT_JSON の貼り付け内容が正しいJSON形式ではありません。")
    print(f"詳細エラー: {e}")
    print("★対策: Firebaseからダウンロードした.jsonファイルの中身（{から}まで）をすべてそのままSecretsに貼り直してください。")
    exit(1)
except Exception as e:
    print(f"【エラー】Firebase初期化失敗: {e}")
    exit(1)

# Gemini初期化
genai.configure(api_key=GEMINI_API_KEY)

# --- 2. Webニュース・入試情報の収集 (RSS) ---
def fetch_latest_exam_news():
    query = urllib.parse.quote("共通テスト 大学入試 情報")
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
    
    try:
        response = requests.get(rss_url, timeout=10)
        if response.status_code != 200:
            print("ニュースの取得に失敗しました。")
            return ""
        
        from xml.etree import ElementTree as ET
        root = ET.fromstring(response.content)
        
        articles_text = []
        for item in root.findall('.//item')[:8]:
            title = item.find('title').text if item.find('title') is not None else ""
            description = item.find('description').text if item.find('description') is not None else ""
            articles_text.append(f"・{title}: {description}")
            
        return "\n".join(articles_text)
    except Exception as e:
        print(f"ニュース取得エラー: {e}")
        return ""

# --- 3. Geminiによる要約と新聞生成 ---
def generate_newspaper_article(raw_news):
    system_instruction = """
    あなたは大学入試専門の新聞編集長です。
    与えられた最新ニュース・入試情報データから、受験生や保護者が知るべき最も重要なトピックを厳選し、
    新聞記事用の「見出し（タイトル）」と「要約本文」を作成してください。
    また、重大な変更点や緊急ニュースが含まれる場合は「isBreaking」をtrueにしてください。
    """
    
    prompt = f"""
    以下のニューステキストから新聞記事を作成してください。
    
    【取得ニュースデータ】
    {raw_news}
    
    【出力フォーマット】
    必ず以下のJSON形式のみで出力してください。
    {{
        "title": "新聞の見出し（簡潔でインパクトのある30文字程度）",
        "content": "ニュース全体の要約本文（300文字〜500文字程度。段落をわかりやすく記述）",
        "isBreaking": true または false（緊急の速報事項がある場合のみtrue）
    }}
    """
    
    try:
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash-preview-09-2025",
            system_instruction=system_instruction
        )
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        raw_text = response.text.strip()
    except Exception as e:
        print(f"Gemini呼び出しエラー、フォールバック実行: {e}")
        model = genai.GenerativeModel(model_name="gemini-1.5-flash")
        response = model.generate_content(prompt)
        raw_text = response.text.strip()

    cleaned_text = re.sub(r'^    cleaned_text = re.sub(r'\s*```$', '', cleaned_text, flags=re.MULTILINE).strip()
    
    return json.loads(cleaned_text)

# --- 4. Firestoreへの保存 ---
def save_to_firestore(article_data):
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    date_str = now.strftime("%Y年%m月%d日")
    
    doc_data = {
        "title": article_data.get("title", "無題"),
        "content": article_data.get("content", ""),
        "isBreaking": article_data.get("isBreaking", False),
        "publishDate": date_str,
        "createdAt": firestore.SERVER_TIMESTAMP
    }
    
    app_id = os.environ.get("APP_ID", "nyushi-nippo-app")
    collection_ref = db.collection("artifacts").document(app_id).collection("public").document("data").collection("articles")
    
    _, doc_ref = collection_ref.add(doc_data)
    print(f"✓ 記事をFirestoreに正常保存しました: 文書ID [{doc_ref.id}]")

def main():
    print("1. 最新入試ニュースの収集を開始...")
    raw_news = fetch_latest_exam_news()
    
    if not raw_news:
        print("有効なニュースが見つかりませんでした。")
        return
        
    print("2. Geminiによる要約と新聞記事作成...")
    article = generate_newspaper_article(raw_news)
    print(f"★生成された新聞タイトル: 【{article.get('title')}】")
    
    print("3. Firestoreへ書き込み中...")
    save_to_firestore(article)
    print("=== 全処理が正常に完了しました ===")

if __name__ == "__main__":
    main()





