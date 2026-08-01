import os
import json
import urllib.request
import urllib.parse
import datetime
import xml.etree.ElementTree as ET

def get_gemini_response(prompt, api_key):
    print("-> Gemini APIへ要約をリクエスト中...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {
            "parts": [{"text": "あなたは大学入試専門の新聞編集長です。提供されたニュースから、受験生向けに分かりやすく新聞記事を作成してください。出力を速報扱いにしたいのでisBreakingはtrueに設定してください。"}]
        },
        "generationConfig": {"responseMimeType": "application/json"}
    }
    req = urllib.request.Request(
        url, 
        data=json.dumps(data).encode('utf-8'), 
        headers={'Content-Type': 'application/json'}, 
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=50) as response:
            res_body = response.read().decode('utf-8')
            res_json = json.loads(res_body)
            if 'candidates' in res_json and len(res_json) > 0:
                candidate = res_json['candidates'][0]
                if 'content' in candidate and 'parts' in candidate['content']:
                    text = candidate['content']['parts'][0]['text']
                    print("-> Gemini APIからの応答取得に成功しました。")
                    return text
            print(f"【エラー】予期しないAPIレスポンス: {res_body}")
            return None
    except Exception as e:
        print(f"【エラー】Gemini API通信失敗: {e}")
        return None

def fetch_news():
    print("-> GoogleニュースからRSSを取得中...")
    query = urllib.parse.quote("共通テスト 大学入試 変更 速報")
    url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            root = ET.fromstring(response.read())
            texts = []
            for item in root.findall(".//item")[:8]:
                title = item.find("title").text if item.find("title") is not None else ""
                desc = item.find("description").text if item.find("description") is not None else ""
                texts.append(f"・{title}: {desc}")
            print(f"-> ニュースの取得数: {len(texts)}件")
            return "\n".join(texts)
    except Exception as e:
        print(f"【エラー】ニュース取得失敗: {e}")
        return ""

def main():
    print("=== 入試ニュース収集プログラム開始 ===")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("【エラー】GEMINI_API_KEY が設定されていません。GitHubのSecretsを確認してください。")
        return

    # 正しいプロジェクトIDを設定
    project_id = "nyushi-nippo"
    app_id = os.environ.get("APP_ID", "nyushi-nippo-app")
    
    now_jst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    today_str = now_jst.strftime("%Y年%m月%d日 %H:%M")

    raw_news = fetch_news()
    if not raw_news:
        raw_news = "大学入試および共通テストに向けた最新動向です。学習計画を立てて準備を進めましょう。"

    prompt = f"以下のニュースから新聞記事を作成し、必ず以下のJSONフォーマットのみで出力してください。\n{{\"title\": \"30文字程度の見出し\", \"content\": \"300〜500文字の要約本文\", \"isBreaking\": true}}\n\n【収集ニュース】\n{raw_news}"
    
    gemini_text = get_gemini_response(prompt, api_key)
    
    # ニュースの初期生成（フォールバック）
    article_data = {
        "title": "【速報】最新の大学入試動向・共通テスト速報",
        "content": raw_news[:450],
        "isBreaking": True
    }
    
    if gemini_text:
        try:
            cleaned = gemini_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("\n", 1)[0]
            parsed = json.loads(cleaned)
            article_data["title"] = parsed.get("title", article_data["title"])
            article_data["content"] = parsed.get("content", article_data["content"])
            article_data["isBreaking"] = True
            print("-> AI要約成功:", article_data["title"])
        except Exception as e:
            print(f"【警告】JSONパース失敗、ニューステキストを使用します: {e}")

    publish_date_str = f"{now_jst.strftime('%Y年%m月%d日')} 【号外速報】"

    url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/artifacts/{app_id}/public/data/articles"
    
    payload = {
        "fields": {
            "title": {"stringValue": article_data["title"]},
            "content": {"stringValue": article_data["content"]},
            "isBreaking": {"booleanValue": True},
            "publishDate": {"stringValue": publish_date_str},
            "createdAt": {"timestampValue": now_jst.isoformat("T")}
        }
    }
    
    print(f"-> Firestoreへデータ送信中... {publish_date_str}")
    req = urllib.request.Request(
        url, 
        data=json.dumps(payload).encode('utf-8'), 
        headers={'Content-Type': 'application/json'}, 
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status == 200:
                print("✓ 【成功】号外速報のFirestore保存が完了しました！")
    except Exception as e:
        print(f"【エラー】Firestore保存失敗: {e}")

if __name__ == "__main__":
    main()

