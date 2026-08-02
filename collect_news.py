import os
import sys
import json
import urllib.request
import urllib.parse
import urllib.error
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
    print("-> Googleニュースから記事を検索しています...")
    query = urllib.parse.quote("共通テスト OR 大学入試 (変更 OR 速報 OR 発表)")
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

    # AIが混乱しないよう、もっともシンプルなリクエスト構造に変更しました
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
        if e.code in [404, 400]:
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
    print("=== 入試ニュース強制発行プログラム開始 ===")
    
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
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
    is_regular_time = (now_jst.weekday() in [1, 3, 5, 6]) and (8 <= now_jst.hour <= 9)
    
    try:
        articles_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('articles')
        docs = articles_ref.get()
        existing_count = len(docs)
    except Exception as e:
        print(f"【重大エラー】Firestore読み込み失敗:\n{e}")
        sys.exit(1)

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
            # ★ AIエラーの詳細をそのまま記事の本文に載せます！ ★
            error_details = f"【AI要約エラーが発生しました】\n原因: {error_msg}\n\n【生のニュースデータ】\n{clean_html(raw_news[:1000])}"
            article_data = {"title": "最新の入試動向（AI要約エラー）", "content": error_details, "isBreaking": False}
    
    if not article_data:
        article_data = {"title": "入試日報新聞 発行テスト", "content": "ニュースが見つかりませんでした。この記事が見えていればプログラムとデータベースは正常に接続されています！", "isBreaking": True}

    issue_label = f"（第{existing_count + 1}号 強制発行）"
    publish_date_str = f"{today_str} {now_jst.strftime('%H時%M分発行')} {issue_label}"

    print("-> 記事をFirestoreに強制保存します...")
    try:
        articles_ref.add({
            "title": article_data.get("title", "無題"),
            "content": clean_html(article_data.get("content", "")),
            "isBreaking": bool(article_data.get("isBreaking", False)),
            "publishDate": publish_date_str,
            "createdAt": firestore.SERVER_TIMESTAMP
        })
        print("✓ 【大成功】記事を強制発行しました！Webページを更新して確認してください。")
    except Exception as e:
        print(f"【重大エラー】Firestore保存失敗:\n{e}")
        sys.exit(1)

if __name__ == "__main__":
    main()


