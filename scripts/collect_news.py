import os
import json
import re
import requests
import datetime
import urllib.parse
import google.generativeai as genai

print("=== プログラムの実行を開始します ===")

# --- 1. 環境変数の取得と検証 ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("【エラー】GEMINI_API_KEY がSecretsに設定されていません。")
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

    cleaned_text = re.sub(r'^


