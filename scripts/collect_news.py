import os
import json
import re
import requests
import datetime
import urllib.parse
import google.generativeai as genai
import firebase_admin
from firebase_admin import credentials, firestore

# --- 1. 環境変数と設定 ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY が設定されていません。GitHub Secretsを確認してください。")

if not FIREBASE_SERVICE_ACCOUNT_JSON:
    raise ValueError("FIREBASE_SERVICE_ACCOUNT_JSON が設定されていません。GitHub Secretsを確認してください。")

# Gemini初期化
genai.configure(api_key=GEMINI_API_KEY)

# Firebase初期化
try:
    cred_dict = json.loads(FIREBASE_SERVICE_ACCOUNT_JSON.strip())
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    print("【エラー】FIREBASE_SERVICE_ACCOUNT_JSON の読み込みに失敗しました。")
    print("Secretsに登録したJSONテキストが正しいか確認してください。")
    raise e

# --- 2. Webニュース・入試情報の収集 (RSS) ---
def fetch_latest_exam_news():
    """大学入試・共通テストに関連する最新ニュースを取得"""
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
        for item in root.findall('.//item')[:8]: # 上位8件を取得
            title = item.find('title').text if item.find('title') is not None else ""
            description = item.find('description').text if item.find('description') is not None else ""
            articles_text.append(f"・{title}: {description}")
            
        return "\n".join(articles_text)
    except Exception as e:
        print(f"ニュース取得中にエラー発生: {e}")
        return ""

# --- 3. Geminiによる新聞記事化 ---
def generate_newspaper_article(raw_news):
    """取得したテキストをGeminiに入力し、新聞記事形式のJSONを生成"""
    
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
    必ず以下のJSON形式のみで出力してください。余計な解説は不要です。
    {{
        "title": "新聞の見出し（簡潔でインパクトのある30文字程度）",
        "content": "ニュース全体の要約本文（300文字〜500文字程度。段落をわかりやすく記述）",
        "isBreaking": true または false（緊急の速報事項がある場合のみtrue）
    }}
    """
    
    # 互換性・安定性の高いモデル名指定
    model_name = "gemini-2.5-flash-preview-09-2025"
    try:
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_instruction
        )
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        raw_text = response.text.strip()
    except Exception as e:
        print(f"モデル {model_name} での生成エラー、フォールバックを試みます: {e}")
        model = genai.GenerativeModel(model_name="gemini-1.5-flash")
        response = model.generate_content(prompt)
        raw_text = response.text.strip()

    # レスポンスからマークダウン装飾（```json ... ```）を除去する堅牢なパース処理
    cleaned_text = re.sub(r'^cleaned_text = re.sub(r'\s*```$', '', cleaned_text, flags=re.MULTILINE).strip()
    
    try:
        return json.loads(cleaned_text)
    except json.JSONDecodeError as err:
        print("GeminiからのレスポンスをJSONとして解析できませんでした。")
        print(f"生レスポンス: {raw_text}")
        raise err

# --- 4. Firestoreへの保存 ---
def save_to_firestore(article_data):
    """生成した新聞記事をFirestoreに保存"""
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))) # JST
    date_str = now.strftime("%Y年%m月%d日")
    
    doc_data = {
        "title": article_data["title"],
        "content": article_data["content"],
        "isBreaking": article_data.get("isBreaking", False),
        "publishDate": date_str,
        "createdAt": firestore.SERVER_TIMESTAMP
    }
    
    app_id = os.environ.get("APP_ID", "nyushi-nippo-app")
    collection_ref = db.collection("artifacts").document(app_id).collection("public").document("data").collection("articles")
    
    _, doc_ref = collection_ref.add(doc_data)
    print(f"記事を正常に保存しました: ID {doc_ref.id}")

def main():
    print("ニュース収集を開始します...")
    raw_news = fetch_latest_exam_news()
    
    if not raw_news:
        print("有効なニュースデータがありませんでした。処理を終了します。")
        return
        
    print("Geminiによる要約・記事編集を開始します...")
    article = generate_newspaper_article(raw_news)
    print(f"生成タイトル: {article.get('title')}")
    
    print("Firestoreへ保存中...")
    save_to_firestore(article)
    print("更新完了！")

if __name__ == "__main__":
    main()



