import os
import json
import urllib.request
import urllib.parse
import datetime
import xml.etree.ElementTree as ET

def get_gemini_response(prompt, api_key):
    print("-> Gemini APIへ要約をリクエスト中...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={api_key}"
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {
            "parts": [{"text": "あなたは大学入試専門の新聞編集長です。提供されたニュースから、受験生向けに分かりやすく新聞記事を作成してください。重大な変更や緊急ニュースの場合はisBreakingをtrueにしてください。"}]
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
        with urllib.request.urlopen(req, timeout=30) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            text = res_json['candidates'][0]['content']['parts'][0]['text']
            print("-> Gemini APIからの応答取得に成功しました。")
            return text
    except Exception as e:
        print(f"【エラー】Gemini API通信失敗: {e}")
        return None

def fetch_news():
    print("-> GoogleニュースからRSSを取得中...")
    query = urllib.parse.quote("共通テスト 大学入試 変更 速報")
    url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
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
    print("=== 入試ニュース収集プログラム（初号対応版）開始 ===")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("【エラー】GEMINI_API_KEY が設定されていません。")
        return

    # ★ご自身のFirebaseプロジェクトIDに合わせてください
    project_id = "nyushi-nippo-app"
    app_id = os.environ.get("APP_ID", "nyushi-nippo-app")
    
    raw_news = fetch_news()
    
    # 初回起動時やニュースが取得できない場合の「創刊号（初号）」データ
    if not raw_news:
        print("-> 初回のため【創刊号】としてデータを生成します。")
        article_data = {
            "title": "入試日報新聞 創刊の辞：受験生を支える確かな情報へ",
            "content": "本日ここに、大学入試および共通テストの最新動向を自動集約してお伝えする「入試日報新聞」の初号を発刊いたします。本紙は毎週月曜日および木曜日の週2回、最新の入試情報を分かりやすく要約して皆様にお届けします。また、入試に関する重大な変更や速報が入った場合には、曜日を問わず号外速報として随時お届けいたします。受験生一人ひとりの進路実現に向け、信頼性の高い情報インフラとなるべく尽力してまいります。左上のカウントダウンを励みに、毎日の学習計画にお役立てください。",
            "isBreaking": False
        }
    else:
        prompt = f"以下のニュースから新聞記事を作成し、必ず以下のJSONフォーマットのみで出力してください。\n{{\"title\": \"30文字程度の見出し\", \"content\": \"300〜500文字の要約本文\", \"isBreaking\": false}}\n\n【収集ニュース】\n{raw_news}"
        gemini_text = get_gemini_response(prompt, api_key)
        
        article_data = {"title": "最新入試動向について", "content": raw_news[:400], "isBreaking": False}
        if gemini_text:
            try:
                cleaned = gemini_text.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("\n", 1)[-1]
                if cleaned.endswith("```"):
                    cleaned = cleaned.rsplit("\n", 1)[0]
                article_data = json.loads(cleaned)
                print("-> JSONの解析に成功しました。タイトル:", article_data.get("title"))
            except Exception as e:
                print(f"【警告】JSONパース失敗、テキストをそのまま使用します: {e}")
                article_data["content"] = gemini_text[:400]

    now_jst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/artifacts/{app_id}/public/data/articles"
    
    payload = {
        "fields": {
            "title": {"stringValue": article_data.get("title", "無題")},
            "content": {"stringValue": article_data.get("content", "")},
            "isBreaking": {"booleanValue": bool(article_data.get("isBreaking", False))},
            "publishDate": {"stringValue": now_jst.strftime("%Y年%m月%d日") + "（初号）"},
            "createdAt": {"timestampValue": now_jst.isoformat("T")}
        }
    }
    
    print("-> Firestoreへデータを送信中...")
    req = urllib.request.Request(
        url, 
        data=json.dumps(payload).encode('utf-8'), 
        headers={'Content-Type': 'application/json'}, 
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status == 200:
                print("✓ 【成功】初号（記事）のFirestore保存が完了しました！")
    except Exception as e:
        print(f"【エラー】Firestore保存失敗: {e}")

if __name__ == "__main__":
    main()

