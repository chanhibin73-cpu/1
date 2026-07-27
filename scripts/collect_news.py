import os
import json
import re
import requests
import datetime
import urllib.parse
import google.generativeai as genai

def main():
    print("=== 入試ニュース収集プログラム開始 ===")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("エラー: GEMINI_API_KEY が設定されていません")
        exit(1)

    genai.configure(api_key=api_key)

    query = urllib.parse.quote("共通テスト 大学入試 変更 速報")
    url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
    
    res = requests.get(url, timeout=10)
    if res.status_code != 200:
        print("ニュース取得失敗")
        exit(1)

    from xml.etree import ElementTree as ET
    root = ET.fromstring(res.content)
    texts = []
    for item in root.findall(".//item")[:8]:
        title = item.find("title").text if item.find("title") is not None else ""
        desc = item.find("description").text if item.find("description") is not None else ""
        texts.append(f"・{title}: {desc}")
    raw_news = "\n".join(texts)

    system_prompt = "あなたは大学入試専門の新聞編集長です。提供されたニュースから、受験生向けに分かりやすく新聞記事を作成してください。重大な変更や緊急ニュースの場合はisBreakingをtrueにしてください。"
    prompt = f"以下のニュースから新聞記事を作成し、必ず以下のJSONフォーマットのみで出力してください。\n{{\"title\": \"30文字程度の見出し\", \"content\": \"300〜500文字の要約本文\", \"isBreaking\": false}}\n\n【収集ニュース】\n{raw_news}"

    model = genai.GenerativeModel(model_name="gemini-3.6-flash", system_instruction=system_prompt)
    response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
    
    raw_text = response.text.strip()
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    
    try:
        article = json.loads(cleaned)
    except Exception as e:
        print(f"JSONパースエラー: {e}")
        article = {"title": "最新入試動向について", "content": raw_text[:400], "isBreaking": False}

    now_jst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    date_str = now_jst.strftime("%Y年%m月%d日")
    
    app_id = os.environ.get("APP_ID", "nyushi-nippo-app")
    firestore_url = f"https://firestore.googleapis.com/v1/projects/nyushi-nippo/databases/(default)/documents/artifacts/{app_id}/public/data/articles"

    payload = {
        "fields": {
            "title": {"stringValue": article.get("title", "無題")},
            "content": {"stringValue": article.get("content", "")},
            "isBreaking": {"booleanValue": bool(article.get("isBreaking", False))},
            "publishDate": {"stringValue": date_str},
            "createdAt": {"timestampValue": now_jst.isoformat("T")}
        }
    }

    r = requests.post(firestore_url, json=payload, timeout=15)
    if r.status_code == 200:
        print("✓ ニュースの要約とFirestore保存に成功しました！")
    else:
        print(f"保存失敗: {r.status_code} {r.text}")
        exit(1)

if __name__ == "__main__":
    main()


