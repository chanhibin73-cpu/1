import os
import sys
import json
import urllib.request
import urllib.parse
import urllib.error
import datetime
import xml.etree.ElementTree as ET
import re
import time
import firebase_admin
from firebase_admin import credentials, firestore

def clean_html(raw_html):
    if not raw_html: return ""
    cleanr = re.compile('<.*?>')
    cleandText = re.sub(cleanr, '', raw_html)
    return cleandText.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').strip()

def fetch_article_content(url):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        })
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode('utf-8', errors='ignore')
            p_tags = re.findall(r'<p[^>]*>(.*?)</p>', html, re.IGNORECASE | re.DOTALL)
            text = " ".join([clean_html(p) for p in p_tags if p])
            return text[:2000]
    except Exception as e:
        return ""

def fetch_news():
    print("-> Googleニュースから過去1ヶ月の最新記事を検索しています...")
    query = urllib.parse.quote("共通テスト OR 大学入試 (変更 OR 速報 OR 発表) when:30d")
    url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        })
        with urllib.request.urlopen(req, timeout=20) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
            texts = []
            for item in root.findall(".//item")[:5]:
                title = clean_html(item.find("title").text if item.find("title") is not None else "")
                link = item.find("link").text if item.find("link") is not None else ""
                desc = item.find("description").text if item.find("description") is not None else ""
                content = fetch_article_content(link)
                if not content or len(content) < 50:
                    content = re.sub(r'http\S+', '', clean_html(desc))
                if title or content:
                    texts.append(f"【タイトル】{title}\n【詳細内容】{content}\n")
            return "\n".join(texts)
    except Exception as e:
        print(f"【警告】ニュース自動検索でエラーが発生しました: {e}")
        return ""

def get_gemini_summary(raw_news, api_key, is_regular_time):
    print("-> Gemini API によるニュース自動要約を実行中...")
    
    primary_model = "gemini-3.6-flash"
    fallback_model = "gemini-1.5-flash"
    
    url_primary = f"https://generativelanguage.googleapis.com/v1beta/models/{primary_model}:generateContent?key={api_key}"
    url_fallback = f"https://generativelanguage.googleapis.com/v1beta/models/{fallback_model}:generateContent?key={api_key}"
    
    if is_regular_time:
        mode = "今回は「定例のニュース要約」です。記事の詳細内容を読み込み、具体的に深く要約してください。isBreakingは false にしてください。"
    else:
        mode = "今回は「速報チェック」です。非常に重要かつ新しい変更があれば詳しく要約して isBreaking を true に。なければ false にし、contentを「更新なし」としてください。"

    prompt = f"""あなたは入試新聞の編集長です。
以下のニュースの【詳細内容】を読み込み、指定されたJSONフォーマットで出力してください。
見出しの羅列ではなく、記事の「中身・内容」を具体的に解説する要約を作成してください。
Markdownの記号（```json 等）は絶対に含めず、純粋なJSONオブジェクトのみを返してください。
{mode}
【期待するJSON】\n{{\n  "title": "見出し",\n  "content": "要約本文",\n  "isBreaking": false\n}}\n【ニュース情報】\n{raw_news}"""

    data = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    req_data = json.dumps(data).encode('utf-8')
    
    try:
        req = urllib.request.Request(url_primary, data=req_data, headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=90) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            return res_json['candidates'][0]['content']['parts'][0]['text'], ""
    except urllib.error.HTTPError as e:
        if e.code in [404, 400, 503, 429, 500, 502, 504]:
            if e.code in [503, 429]:
                print(f"【お知らせ】APIサーバーが混雑しています（HTTP {e.code}）。3秒待機してから予備ルートで再試行します...")
                time.sleep(3)
            try:
                req2 = urllib.request.Request(url_fallback, data=req_data, headers={'Content-Type': 'application/json'}, method='POST')
                with urllib.request.urlopen(req2, timeout=90) as response2:
                    res_json2 = json.loads(response2.read().decode('utf-8'))
                    return res_json2['candidates'][0]['content']['parts'][0]['text'], ""
            except urllib.error.HTTPError as e2:
                err_msg = e2.read().decode('utf-8', errors='ignore')
                return None, f"Fallback API HTTP {e2.code}: {err_msg}"
            except Exception as e2:
                return None, f"Fallback API Error: {str(e2)}"
        
        err_msg = e.read().decode('utf-8', errors='ignore')
        return None, f"API HTTP {e.code}: {err_msg}"
    except Exception as e:
        return None, f"Network Error: {str(e)}"

def main():
    print("=== 入試ニュース発行プログラム開始 ===")
    
    raw_api_key = os.environ.get("GEMINI_API_KEY", "")
    api_key = re.sub(r'[\r\n\t ]', '', raw_api_key)
    
    firebase_cert_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
    app_id = "nyushi-nippo-app"

    if not api_key or not firebase_cert_json:
        print("【重大エラー】APIキー または Firebase秘密鍵 が設定されていません。")
        sys.exit(1)

    try:
        firebase_cert_json = firebase_cert_json.replace("\\n", "\n")
        cert_dict = json.loads(firebase_cert_json, strict=False)
        cred = credentials.Certificate(cert_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
    except Exception as e:
        print(f"【重大エラー】Firebase初期化失敗:\n{e}")
        sys.exit(1)
    
    now_jst = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    today_str = now_jst.strftime("%Y年%m月%d日")
    
    # 11:00〜11:59は正規の定例時間、14:30〜14:59はリカバリー（再挑戦）の定例時間
    is_regular_time_primary = (11 <= now_jst.hour <= 11)
    is_regular_time_recovery = (now_jst.hour == 14 and 30 <= now_jst.minute <= 59)
    
    # いずれかの時間帯なら、AIの要約指示は「定例モード」として動かす
    is_regular_time = is_regular_time_primary or is_regular_time_recovery
    
    try:
        articles_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('articles')
        docs = articles_ref.get()
        
        # 本日の「成功した定例号」がすでにあるかチェック（AIエラーや号外はノーカウント）
        has_today_regular_success = False
        for doc in docs:
            data = doc.to_dict()
            pub_date = data.get("publishDate", "")
            is_breaking = data.get("isBreaking", False)
            content = data.get("content", "")
            # 今日発行 ＆ 号外ではない ＆ AIエラー文が含まれていない
            if today_str in pub_date and not is_breaking and "AI要約エラー" not in content:
                has_today_regular_success = True
                break
                
        existing_count = len(docs)
    except Exception as e:
        print(f"【重大エラー】Firestore読み込み失敗:\n{e}")
        sys.exit(1)

    is_first_issue = (existing_count == 0)

    if is_first_issue:
        print("-> 記事が0件のため、創刊号の挨拶記事を発行します。")
        article_data = {
            "title": "入試日報新聞 創刊号", 
            "content": "毎日午前11時に、過去1ヶ月の入試情報を深く要約してお届けします。現在新しい情報を収集中です。", 
            "isBreaking": False
        }
    else:
        raw_news = fetch_news()
        article_data = None

        if raw_news:
            gemini_text, error_msg = get_gemini_summary(raw_news, api_key, is_regular_time)
            if gemini_text:
                cleaned = gemini_text.replace("```json", "").replace("```", "").strip()
                try:
                    article_data = json.loads(cleaned, strict=False)
                except Exception:
                    cleaned_escaped = cleaned.replace('\n', '\\n').replace('\r', '')
                    try:
                        article_data = json.loads(cleaned_escaped, strict=False)
                    except Exception:
                        article_data = {"title": "最新の入試動向", "content": clean_html(gemini_text[:450]), "isBreaking": False}
            else:
                error_details = f"【AI要約エラーが発生しました】\n原因: {error_msg}\n\n【生のニュースデータ】\n{clean_html(raw_news[:1000])}"
                article_data = {"title": "最新の入試動向（AI要約エラー）", "content": error_details, "isBreaking": False}
        
        if not article_data:
            print("✓ 新しいニュースがないため終了します。")
            return

    is_breaking = bool(article_data.get("isBreaking", False))
    content_text = clean_html(article_data.get("content", ""))

    if not is_first_issue:
        if is_regular_time_primary:
            if has_today_regular_success and not is_breaking:
                print("✓ 本日の11時の定例号はすでに成功して発行済みです。スキップします。")
                return
        elif is_regular_time_recovery:
            if has_today_regular_success and not is_breaking:
                print("✓ 本日の定例号はすでに成功しているため、14:30の再実行はスキップします。")
                return
            else:
                print("-> 本日の定例号がまだ成功していないため、リカバリー（再挑戦）として定例号を発行します！")
        else:
            # それ以外の時間（速報チェック）
            if not is_breaking or "更新なし" in content_text:
                print("✓ 新しい重大な速報ニュースはありませんでした。スキップします。")
                return

    issue_label = "（創刊号）" if is_first_issue else f"（第{existing_count + 1}号）"
    
    # 発行時刻のラベル付け
    if is_regular_time_primary:
        time_label = "午前11時発行"
    elif is_regular_time_recovery:
        time_label = "午後2時30分発行"
    else:
        time_label = now_jst.strftime('%H時%M分発行')
        
    publish_date_str = f"{today_str} {time_label} {issue_label}"

    print(f"-> 記事をFirestoreに保存します... タイトル: {article_data.get('title')}")
    try:
        articles_ref.add({
            "title": article_data.get("title", "無題"),
            "content": clean_html(article_data.get("content", "")),
            "isBreaking": bool(article_data.get("isBreaking", False)),
            "publishDate": publish_date_str,
            "createdAt": firestore.SERVER_TIMESTAMP
        })
        print("✓ 【大成功】記事を発行しました！")
    except Exception as e:
        print(f"【重大エラー】Firestore保存失敗:\n{e}")
        sys.exit(1)

if __name__ == "__main__":
    main()


