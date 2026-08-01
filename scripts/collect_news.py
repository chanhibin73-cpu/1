import os
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

def fetch_article_content(url):
    """ニュースのリンク先に実際にアクセスして、本文を深く取得する"""
    try:
        # リダイレクト対応などのため、少し長めのタイムアウトを設定
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            # <p>タグ（段落）の中身を抽出して本文とする
            p_tags = re.findall(r'<p[^>]*>(.*?)</p>', html, re.IGNORECASE | re.DOTALL)
            text = " ".join([clean_html(p) for p in p_tags if p])
            
            # 本文が長すぎる場合はAIの制限を超えないよう2000文字程度でカット
            return text[:2000]
    except Exception as e:
        print(f"    ※本文の深掘り取得をスキップしました: {e}")
        return ""

def fetch_news():
    print("-> Googleニュースから記事を検索し、リンク先の内容を深く読み込んでいます（時間がかかります）...")
    query = urllib.parse.quote("共通テスト OR 大学入試 (変更 OR 速報 OR 発表)")
    url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            root = ET.fromstring(response.read())
            texts = []
            
            # 深く読み込むため、最新の5件に絞って処理
            for item in root.findall(".//item")[:5]:
                title = item.find("title").text if item.find("title") is not None else ""
                link = item.find("link").text if item.find("link") is not None else ""
                desc = item.find("description").text if item.find("description") is not None else ""
                
                clean_title = clean_html(title)
                print(f"  - 記事取得中: {clean_title[:30]}...")
                
                # ここで時間をかけてリンク先の本文を取得する
                content = fetch_article_content(link)
                
                # もしリンク先から本文が取れなければ、RSSの概要で代用
                if not content or len(content) < 50:
                    content = clean_html(desc)
                    content = re.sub(r'http\S+', '', content)
                    
                if clean_title or content:
                    texts.append(f"【タイトル】{clean_title}\n【詳細内容】{content}\n")
                    
            print(f"-> 詳細検索完了: {len(texts)}件の記事内容を深く取得しました。")
            return "\n".join(texts)
    except Exception as e:
        print(f"【エラー】ニュース自動検索失敗: {e}")
        return ""

def get_gemini_summary(raw_news, api_key, is_regular_time):
    print("-> Gemini APIによるニュースの自動要約を実行中...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    if is_regular_time:
        mode_instruction = "今回は「定例のニュース要約」です。取得した記事の詳細内容をしっかりと読み込み、何がどう変わるのか、受験生にとってどんな影響があるのかを具体的に深く要約してください。isBreakingは基本的に false にしてください。"
    else:
        mode_instruction = "今回は「速報チェック」です。取得した記事の中に、直近で起きた非常に重要かつ新しい入試関連の変更があるか確認し、あれば詳しく要約して `isBreaking` を true にしてください。新しい重要情報がなければ `isBreaking` を false にし、contentを「更新なし」としてください。"

    prompt = f"""以下のニュースの【詳細内容】を読み込み、指定されたJSONフォーマットで出力してください。
見出しの羅列ではなく、記事の「中身・内容」を具体的に解説するような要約を作成してください。
URLやHTMLタグは一切含めず、純粋な日本語の文章だけで要約してください。
Markdownの記号（```json や ``` など）は絶対に含めず、必ず正しいJSONオブジェクトのみを返してください。

{mode_instruction}

【期待するJSONフォーマット】
{{
  "title": "30文字程度の見出し",
  "content": "400〜600文字の詳しい要約本文（内容の解説）",
  "isBreaking": falseまたはtrueの真偽値
}}

【収集したニュース情報（深く取得した内容）】
{raw_news}"""

    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {
            "parts": [{"text": "あなたは大学入試専門の新聞編集長です。提供されたニュースの『内容』を深く理解し、具体的に何が起きているのかを受験生に分かりやすく要約してJSON形式で出力してください。"}]
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
        with urllib.request.urlopen(req, timeout=90) as response:
            res_body = response.read().decode('utf-8')
            res_json = json.loads(res_body)
            if 'candidates' in res_json and len(res_json['candidates']) > 0:
                text = res_json['candidates'][0]['content']['parts'][0]['text']
                print("-> Geminiによる詳細な自動要約に成功しました。")
                return text
    except Exception as e:
        print(f"【エラー】Gemini API要約失敗: {e}")
    return None

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
    print("=== 入試ニュース自動検索・深掘り要約プログラム開始 ===")
    api_key = os.environ.get("GEMINI_API_KEY")
    firebase_cert_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    app_id = os.environ.get("APP_ID", "nyushi-nippo-app")

    if not api_key or not firebase_cert_json:
        print("【エラー】APIキーまたはFirebase秘密鍵が設定されていません。")
        return

    try:
        cert_dict = json.loads(firebase_cert_json)
        cred = credentials.Certificate(cert_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
    except Exception as e:
        print(f"【エラー】Firebase初期化失敗: {e}")
        return
    
    now_jst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    today_str = now_jst.strftime("%Y年%m月%d日")
    weekday = now_jst.weekday()
    
    # 定例日時の判定: 火(1), 木(3), 土(5), 日(6) の 朝8時台〜9時台
    is_regular_time = (weekday in [1, 3, 5, 6]) and (8 <= now_jst.hour <= 9)

    print(f"-> 実行日時(JST): {now_jst.strftime('%Y-%m-%d %H:%M:%S')}, 曜日: {weekday}, 定例時間: {is_regular_time}")

    existing_count, has_today_regular = check_existing_articles_admin(db, app_id, today_str)
    is_first_issue = (existing_count == 0)

    raw_news = fetch_news()
    article_data = None

    if raw_news:
        gemini_text = get_gemini_summary(raw_news, api_key, is_regular_time)
        if gemini_text:
            try:
                cleaned = gemini_text.replace("```json", "").replace("```", "").strip()
                article_data = json.loads(cleaned)
            except Exception as e:
                print(f"【警告】JSONパース失敗: {e}")
                article_data = {"title": "最新の入試動向と対策", "content": clean_html(gemini_text[:450]), "isBreaking": False}
    
    if not article_data:
        if is_first_issue:
            article_data = {
                "title": "入試日報新聞 創刊",
                "content": "本紙は毎週火・木・土・日の朝9時に、入試情報を深く要約してお届けします。",
                "isBreaking": False
            }
        else:
            return # 何も取得できなかった場合はスキップ

    is_breaking = bool(article_data.get("isBreaking", False))
    content_text = clean_html(article_data.get("content", ""))

    if is_regular_time:
        if has_today_regular and not is_breaking:
            print("✓ 本日の朝刊はすでに発行済みです。スキップします。")
            return
    else:
        if not is_breaking or "更新なし" in content_text:
            print("✓ 新しい重大な速報ニュースはありませんでした。スキップします。")
            return

    # 発行日時の表示設定 (定例なら朝9時発行とする)
    issue_label = "（創刊号）" if is_first_issue else f"（第{existing_count + 1}号）"
    time_label = "朝9時発行" if is_regular_time else now_jst.strftime("%H時%M分発行")
    publish_date_str = f"{today_str} {time_label} {issue_label}"

    try:
        articles_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('articles')
        articles_ref.add({
            "title": article_data.get("title", "無題"),
            "content": content_text,
            "isBreaking": is_breaking,
            "publishDate": publish_date_str,
            "createdAt": firestore.SERVER_TIMESTAMP
        })
        print(f"✓ 【成功】記事を発行しました！(号外速報: {is_breaking})")
    except Exception as e:
        print(f"【エラー】Firestore保存失敗: {e}")

if __name__ == "__main__":
    main()


