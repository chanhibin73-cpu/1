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
            "parts": [{"text": "あなたは大学入試専門の新聞編集長です。提供されたニュースから、受験生向けに分かりやすく新聞記事を作成してください。入試情報だけでなく、災害や重要な国家決定などの速報も学生に関わる重要事項としてまとめてください。本当に重大な変更や緊急ニュース（試験の延期や大幅な制度変更、災害、重要な国家決定など）の場合のみisBreakingをtrueにしてください。それ以外はfalseにしてください。"}]
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
    # 検索範囲に災害や国家決定を追加
    query = urllib.parse.quote("共通テスト OR 大学入試 OR 災害 OR 国家決定 速報")
    url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            root = ET.fromstring(response.read())
            texts = []
            for item in root.findall(".//item")[:12]: # 検索件数を少し拡張
                title = item.find("title").text if item.find("title") is not None else ""
                desc = item.find("description").text if item.find("description") is not None else ""
                texts.append(f"・{title}: {desc}")
            print(f"-> ニュースの取得数: {len(texts)}件")
            return "\n".join(texts)
    except Exception as e:
        print(f"【エラー】ニュース取得失敗: {e}")
        return ""

def check_existing_articles(project_id, app_id, target_date_str):
    url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/artifacts/{app_id}/public/data/articles"
    req = urllib.request.Request(url, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            documents = res_json.get('documents', [])
            
            count = len(documents)
            has_target_regular = False
            for doc in documents:
                fields = doc.get("fields", {})
                is_breaking = fields.get("isBreaking", {}).get("booleanValue", False)
                pub_date = fields.get("publishDate", {}).get("stringValue", "")
                
                # 指定日の定例号がすでにあるか確認
                if target_date_str in pub_date and not is_breaking:
                    has_target_regular = True
                    break
                    
            return count, has_target_regular
    except Exception as e:
        print(f"既存記事の取得スキップ (初回判定): {e}")
        return 0, False

def main():
    print("=== 入試ニュース収集プログラム（週4回更新・災害速報対応版）開始 ===")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("【エラー】GEMINI_API_KEY が設定されていません。")
        return

    project_id = "nyushi-nippo"
    app_id = os.environ.get("APP_ID", "nyushi-nippo-app")
    
    raw_news = fetch_news()
    
    now_jst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    
    prompt = f"以下のニュースから新聞記事を作成し、必ず以下のJSONフォーマットのみで出力してください。\n{{\"title\": \"30文字程度の見出し\", \"content\": \"300〜500文字の要約本文\", \"isBreaking\": false}}\n\n【収集ニュース】\n{raw_news if raw_news else '共通テストおよび各大学入試に向けた最新動向と対策情報'}"
    gemini_text = get_gemini_response(prompt, api_key)
    
    article_data = {"title": "最新入試動向について", "content": "要約記事を取得中です。", "isBreaking": False}
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
            print(f"【警告】JSONパース失敗: {e}")
            article_data["content"] = gemini_text[:400]

    is_breaking = bool(article_data.get("isBreaking", False))

    # 発行日のラベル設定 (定例号は前日収集なので翌日の日付にする)
    if not is_breaking:
        publish_target_time = now_jst + datetime.timedelta(days=1)
    else:
        publish_target_time = now_jst
        
    publish_date_str_base = publish_target_time.strftime("%Y年%m月%d日")

    existing_count, has_regular = check_existing_articles(project_id, app_id, publish_date_str_base)
    is_first_issue = (existing_count == 0)

    # 速報ではなく、該当日の定例号がすでにある場合はスキップ (1日1回制限)
    if not is_breaking and has_regular:
        print(f"✓ {publish_date_str_base} の定例号はすでに発行済みです。速報ニュースではないため保存をスキップします。")
        return

    if is_first_issue:
        issue_label = "（創刊号）"
    else:
        issue_label = f"（第{existing_count + 1}号）"
        
    publish_date_str = publish_date_str_base + f" {issue_label}"

    url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/artifacts/{app_id}/public/data/articles"
    
    payload = {
        "fields": {
            "title": {"stringValue": article_data.get("title", "無題")},
            "content": {"stringValue": article_data.get("content", "")},
            "isBreaking": {"booleanValue": is_breaking},
            "publishDate": {"stringValue": publish_date_str},
            "createdAt": {"timestampValue": now_jst.isoformat("T")}
        }
    }
    
    print(f"-> Firestoreへデータを送信中... 発行日ラベル: {publish_date_str}")
    req = urllib.request.Request(
        url, 
        data=json.dumps(payload).encode('utf-8'), 
        headers={'Content-Type': 'application/json'}, 
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status == 200:
                print("✓ 【成功】記事のFirestore保存が完了しました！")
    except Exception as e:
        print(f"【エラー】Firestore保存失敗: {e}")

if __name__ == "__main__":
    main()


