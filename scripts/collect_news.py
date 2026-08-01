import os
import sys
import json
import urllib.request
import urllib.parse
import datetime
import xml.etree.ElementTree as ET
import re
import firebase_admin
from firebase_admin import credentials, firestore

def clean_html(raw_html):
    """HTMLタグや特殊文字を完全に除去してテキストだけにする"""
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    cleandText = re.sub(cleanr, '', raw_html)
    cleandText = cleandText.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return cleandText.strip()

def get_gemini_summary(raw_news, api_key, is_regular_time):
    print("-> Gemini APIによるニュースの自動検索・内容自動要約を実行中...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    if is_regular_time:
        mode_instruction = "今回は定例のニュース要約です。提供されたニュースを元に、受験生向けの分かりやすい要約記事を作成してください。isBreakingは基本的に false にしてください。"
    else:
        mode_instruction = "今回は【速報チェック】です。提供されたニュースの中に、直近で起きた非常に重要かつ新しい入試関連の変更や発表があるか確認してください。もし重要な新情報があれば、要約記事を作成し、`isBreaking` を true にしてください。もし特に新しい重要情報がなければ、`isBreaking` を false にし、contentを「更新なし」としてください。"

    prompt = f"""以下のニュース内容を読み込み、指定されたJSONフォーマットで出力してください。
URLやHTMLタグは一切含めず、純粋な日本語の文章だけで要約してください。
Markdownの記号（```json や ``` など）は絶対に含めず、必ず正しいJSONオブジェクトのみを返してください。

{mode_instruction}

【期待するJSONフォーマット】
{{
  "title": "30文字程度の見出し",
  "content": "300〜500文字の要約本文",
  "isBreaking": falseまたはtrueの真偽値
}}

【収集したニュース内容】
{raw_news}"""

    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {
            "parts": [{"text": "あなたは大学入試専門の新聞編集長です。提供されたニュースからHTMLタグやURLを取り除き、内容を分かりやすく要約してJSON形式で出力してください。"}]
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
        with urllib.request.urlopen(req, timeout=60) as response:
            res_body = response.read().decode('utf-8')
            res_json = json.loads(res_body)
            if 'candidates' in res_json and len(res_json['candidates']) > 0:
                text = res_json['candidates'][0]['content']['parts'][0]['text']
                print("-> Geminiによる自動要約に成功しました。")
                return text
    except Exception as e:
        print(f"【エラー】Gemini API要約失敗: {e}")
    return None

def fetch_news():
    print("-> Googleニュースの自動検索中...")
    query = urllib.parse.quote("共通テスト OR 大学入試 (変更 OR 速報 OR 発表)")
    url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            root = ET.fromstring(response.read())
            texts = []
            for item in root.findall(".//item")[:10]:
                title = item.find("title").text if item.find("title") is not None else ""
                desc = item.find("description").text if item.find("description") is not None else ""
                clean_title = clean_html(title)
                clean_desc = clean_html(desc)
                clean_desc = re.sub(r'http\S+', '', clean_desc)
                if clean_title or clean_desc:
                    texts.append(f"・{clean_title}: {clean_desc}")
            print(f"-> 検索ヒット数: {len(texts)}件")
            return "\n".join(texts)
    except Exception as e:
        print(f"【エラー】ニュース自動検索失敗: {e}")
        return ""

def check_existing_articles_admin(db, app_id, today_str):
    try:
        articles_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('articles')
        docs = articles_ref.get()
        count = len(docs)
        has_today_regular = False
        for doc in docs:
            data = doc.to_dict()
            is_breaking = data.get("isBreaking", False)
            pub_date = data.get("publishDate", "")
            
            if today_str in pub_date and not is_breaking:
                has_today_regular = True
                break
        return count, has_today_regular
    except Exception as e:
        print(f"既存記事の取得スキップ: {e}")
        return 0, False

def main():
    print("=== 入試ニュース自動検索・要約プログラム開始 ===")
    api_key = os.environ.get("GEMINI_API_KEY")
    firebase_cert_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    app_id = os.environ.get("APP_ID", "1:376024106499:web:108b0a027015c782c97036") # appIdを直接指定

    if not api_key:
        print("【エラー】GEMINI_API_KEY が設定されていません。")
        sys.exit(1) # GitHub Actionsを失敗させる
    if not firebase_cert_json:
        print("【エラー】FIREBASE_SERVICE_ACCOUNT (Firebase秘密鍵) が設定されていません。")
        sys.exit(1)

    try:
        cert_dict = json.loads(firebase_cert_json)
        cred = credentials.Certificate(cert_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("-> Firebase管理者権限での接続に成功しました。")
    except Exception as e:
        print(f"【エラー】Firebase初期化失敗: {e}")
        sys.exit(1)
    
    now_jst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    today_str = now_jst.strftime("%Y年%m月%d日")
    weekday = now_jst.weekday()
    is_regular_time = (weekday in [1, 3, 5, 6]) and (12 <= now_jst.hour <= 13)

    print(f"-> 実行日時(JST): {now_jst.strftime('%Y-%m-%d %H:%M:%S')}, 曜日: {weekday}, 定例時間: {is_regular_time}")

    existing_count, has_today_regular = check_existing_articles_admin(db, app_id, today_str)
    is_first_issue = (existing_count == 0)

    raw_news = fetch_news()
    article_data = None

    if not raw_news and is_first_issue:
        article_data = {
            "title": "入試日報新聞 創刊の辞：受験生を支える確かな情報へ",
            "content": "本日ここに、大学入試および共通テストの最新動向を自動集約してお伝えする「入試日報新聞」の創刊号を発刊いたします。本紙は毎週火曜・木曜・土曜・日曜の週4回、最新の入試情報を分かりやすく要約して皆様にお届けします。また、重大な変更や速報が入った場合には随時お届けいたします。",
            "isBreaking": False
        }
    else:
        if raw_news:
            gemini_text = get_gemini_summary(raw_news, api_key, is_regular_time)
            if gemini_text:
                try:
                    cleaned = gemini_text.replace("```json", "").replace("```", "").strip()
                    article_data = json.loads(cleaned)
                    print("-> 自動要約データの解析に成功しました。")
                except Exception as e:
                    print(f"【警告】JSONパース失敗のためテキストを整形して使用します: {e}")
                    article_data = {
                        "title": "最新の入試動向と対策まとめ",
                        "content": clean_html(gemini_text[:450]),
                        "isBreaking": False
                    }
        
        if not article_data:
            fallback_content = "【入試最新動向まとめ】\n\n" + raw_news[:450] if raw_news else "現在新しい入試関連のニュースはありません。"
            article_data = {"title": "最新の入試動向と対策まとめ", "content": fallback_content, "isBreaking": False}

    is_breaking = bool(article_data.get("isBreaking", False))
    content_text = clean_html(article_data.get("content", ""))

    # ==========================================
    # 【修正箇所】保存スキップの判定を改善
    # 記事が1件もない（創刊号）の場合は無条件で作成する
    # ==========================================
    if not is_first_issue:
        if is_regular_time:
            if has_today_regular and not is_breaking:
                print("✓ 本日の定例号はすでに発行済みです。スキップします。")
                return
        else:
            if not is_breaking or "更新なし" in content_text:
                print("✓ 新しい重大な速報ニュースはありませんでした。スキップします。")
                return

    issue_label = "（創刊号）" if is_first_issue else f"（第{existing_count + 1}号）"
    publish_date_str = today_str + f" {issue_label}"

    try:
        articles_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('articles')
        articles_ref.add({
            "title": article_data.get("title", "無題"),
            "content": content_text,
            "isBreaking": is_breaking,
            "publishDate": publish_date_str,
            "createdAt": firestore.SERVER_TIMESTAMP
        })
        print(f"✓ 【成功】記事のFirestore保存が完了しました！(号外速報: {is_breaking})")
    except Exception as e:
        print(f"【エラー】Firestore保存失敗: {e}")
        sys.exit(1) # GitHub Actionsをエラーとして終了させる

if __name__ == "__main__":
    main()


