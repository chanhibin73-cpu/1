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
    if not raw_html: return ""
    cleanr = re.compile('<.*?>')
    cleandText = re.sub(cleanr, '', raw_html)
    return cleandText.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').strip()

def fetch_article_content(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            p_tags = re.findall(r'<p[^>]*>(.*?)</p>', html, re.IGNORECASE | re.DOTALL)
            text = " ".join([clean_html(p) for p in p_tags if p])
            return text[:2000]
    except Exception as e:
        print(f"    ※本文の深掘り取得スキップ: {e}")
        return ""

def fetch_news():
    print("-> Googleニュースから記事を検索し、深く読み込んでいます...")
    query = urllib.parse.quote("共通テスト OR 大学入試 (変更 OR 速報 OR 発表)")
    url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            root = ET.fromstring(response.read())
            texts = []
            for item in root.findall(".//item")[:5]:
                title = clean_html(item.find("title").text if item.find("title") is not None else "")
                link = item.find("link").text if item.find("link") is not None else ""
                desc = item.find("description").text if item.find("description") is not None else ""
                print(f"  - 記事取得中: {title[:30]}...")
                content = fetch_article_content(link)
                if not content or len(content) < 50:
                    content = re.sub(r'http\S+', '', clean_html(desc))
                if title or content:
                    texts.append(f"【タイトル】{title}\n【詳細内容】{content}\n")
            return "\n".join(texts)
    except Exception as e:
        print(f"【エラー】ニュース自動検索失敗: {e}")
        return ""

def get_gemini_summary(raw_news, api_key, is_regular_time):
    print("-> Gemini APIによるニュース自動要約を実行中...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    
    if is_regular_time:
        mode_instruction = "今回は「定例のニュース要約」です。取得した記事の詳細内容を読み込み、具体的に深く要約してください。isBreakingは false にしてください。"
    else:
        mode_instruction = "今回は「速報チェック」です。非常に重要かつ新しい入試関連の変更があれば詳しく要約して isBreaking を true に。なければ false にし、contentを「更新なし」としてください。"

    prompt = f"""以下のニュースの【詳細内容】を読み込み、指定されたJSONフォーマットで出力してください。
見出しの羅列ではなく、記事の「中身・内容」を具体的に解説するような要約を作成してください。
Markdownの記号（```json 等）は絶対に含めず、純粋なJSONオブジェクトのみを返してください。
{mode_instruction}
【期待するJSON】\n{{\n  "title": "見出し",\n  "content": "詳しい要約本文（内容の解説）",\n  "isBreaking": false\n}}\n【ニュース情報】\n{raw_news}"""

    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": "あなたは大学入試専門の新聞編集長です。"}]},
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            return res_json['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        print(f"【エラー】Gemini API要約失敗: {e}")
        return None

def check_existing_articles_admin(db, app_id, today_str):
    try:
        articles_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('articles')
        docs = articles_ref.get()
        has_today = any(today_str in doc.to_dict().get("publishDate", "") and not doc.to_dict().get("isBreaking", False) for doc in docs)
        return len(docs), has_today
    except Exception as e:
        return 0, False

def main():
    print("=== 入試ニュース自動検索プログラム開始 ===")
    api_key = os.environ.get("GEMINI_API_KEY")
    firebase_cert_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    app_id = os.environ.get("APP_ID", "nyushi-nippo-app")

    if not api_key or not firebase_cert_json:
        print("【重大エラー】APIキーまたはFirebase秘密鍵が設定されていません。GitHub Secretsを確認してください。")
        return

    try:
        cred = credentials.Certificate(json.loads(firebase_cert_json))
        firebase_admin.initialize_app(cred)
        db = firestore.client()
    except Exception as e:
        print(f"【重大エラー】Firebase初期化失敗。JSONの形式が間違っている可能性があります: {e}")
        return
    
    now_jst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    today_str = now_jst.strftime("%Y年%m月%d日")
    is_regular_time = (now_jst.weekday() in [1, 3, 5, 6]) and (8 <= now_jst.hour <= 9)
    
    existing_count, has_today_regular = check_existing_articles_admin(db, app_id, today_str)
    is_first_issue = (existing_count == 0)

    raw_news = fetch_news()
    article_data = None

    if raw_news:
        gemini_text = get_gemini_summary(raw_news, api_key, is_regular_time)
        if gemini_text:
            try:
                article_data = json.loads(gemini_text.replace("```json", "").replace("```", "").strip())
            except:
                article_data = {"title": "最新の入試動向", "content": clean_html(gemini_text[:450]), "isBreaking": False}
    
    if not article_data:
        if is_first_issue:
            article_data = {"title": "入試日報新聞 創刊", "content": "本紙は毎週火・木・土・日の朝9時に、入試情報を深く要約してお届けします。", "isBreaking": False}
        else:
            return

    is_breaking = bool(article_data.get("isBreaking", False))
    content_text = clean_html(article_data.get("content", ""))

    if not is_first_issue:
        if is_regular_time and has_today_regular and not is_breaking:
            print("✓ 本日の朝刊は発行済みです。スキップします。")
            return
        elif not is_regular_time and (not is_breaking or "更新なし" in content_text):
            print("✓ 新しい重大な速報ニュースはありませんでした。スキップします。")
            return

    issue_label = "（創刊号）" if is_first_issue else f"（第{existing_count + 1}号）"
    publish_date_str = f"{today_str} {'朝9時発行' if is_regular_time else now_jst.strftime('%H時%M分発行')} {issue_label}"

    try:
        db.collection('artifacts').document(app_id).collection('public').document('data').collection('articles').add({
            "title": article_data.get("title", "無題"),
            "content": content_text,
            "isBreaking": is_breaking,
            "publishDate": publish_date_str,
            "createdAt": firestore.SERVER_TIMESTAMP
        })
        print("✓ 【成功】記事を発行しました！")
    except Exception as e:
        print(f"【エラー】Firestore保存失敗: {e}")

if __name__ == "__main__":
    main()


