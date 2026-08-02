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
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            p_tags = re.findall(r'<p[^>]*>(.*?)</p>', html, re.IGNORECASE | re.DOTALL)
            text = " ".join([clean_html(p) for p in p_tags if p])
            return text[:2000]
    except Exception as e:
        return ""

def fetch_news():
    print("-> Googleニュースから入試・災害情報を検索しています...")
    # 入試情報と、入試に関連しそうな災害情報の両方を検索
    queries = [
        "共通テスト OR 大学入試 (変更 OR 速報 OR 発表)",
        "共通テスト OR 大学入試 (災害 OR 地震 OR 台風 OR 警報)"
    ]
    texts = []
    urls_seen = set()
    
    for q in queries:
        query = urllib.parse.quote(q)
        url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
            })
            with urllib.request.urlopen(req, timeout=15) as response:
                root = ET.fromstring(response.read())
                for item in root.findall(".//item")[:3]: # 各クエリ上位3件を抽出
                    link = item.find("link").text if item.find("link") is not None else ""
                    if not link or link in urls_seen:
                        continue
                    urls_seen.add(link)
                    
                    title = clean_html(item.find("title").text if item.find("title") is not None else "")
                    desc = item.find("description").text if item.find("description") is not None else ""
                    content = fetch_article_content(link)
                    if not content or len(content) < 50:
                        content = re.sub(r'http\S+', '', clean_html(desc))
                    if title or content:
                        texts.append(f"【タイトル】{title}\n【詳細内容】{content}\n")
        except Exception as e:
            print(f"【警告】検索エラー: {e}")
            
    return "\n".join(texts)

def get_gemini_summary(raw_news, api_key):
    print("-> Gemini API によるニュース自動要約を実行中...")
    
    # ユーザーご指定のモデルを優先
    primary_model = "gemini-3.6-flash"
    fallback_model = "gemini-1.5-flash"
    
    url_primary = f"https://generativelanguage.googleapis.com/v1beta/models/{primary_model}:generateContent?key={api_key}"
    url_fallback = f"https://generativelanguage.googleapis.com/v1beta/models/{fallback_model}:generateContent?key={api_key}"
    
    prompt = f"""あなたは入試新聞の編集長です。以下のニュースを読み込み、指定されたJSONフォーマットで1つの記事にまとめて出力してください。

【記事の構成ルール】
1. ニュースの中に「入試情報」と「災害・天候情報」がある場合、基本的には「入試情報」を先に書き、その下に「災害情報」を書いてください。
2. ただし、緊急性がある災害（直近の大きな地震や台風など）がある場合は、例外として「災害情報」を記事の1番上に表示させてください。
3. すべての情報を統合し、内容を具体的に解説する「1つの記事」としてまとめてください。
4. Markdownの記号（```json 等）は絶対に含めず、純粋なJSONのみを返してください。

【期待するJSON】\n{{\n  "title": "本日の入試・速報まとめ",\n  "content": "要約本文",\n  "isBreaking": false\n}}\n【ニュース情報】\n{raw_news}"""

    data = {"contents": [{"parts": [{"text": prompt}]}]}
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
            except Exception as e2:
                return None, f"Fallback API Error: {str(e2)}"
        return None, f"API HTTP {e.code}"
    except Exception as e:
        return None, f"Network Error: {str(e)}"

def main():
    print("=== 入試ニュース更新プログラム開始 ===")
    
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
    today_str_id = now_jst.strftime("%Y%m%d")
    today_str_display = now_jst.strftime("%Y年%m月%d日")
    
    # 1日1記事制：ドキュメントIDを本日の日付にする
    doc_id = f"article_{today_str_id}"

    raw_news = fetch_news()
    article_data = None

    if raw_news:
        gemini_text, error_msg = get_gemini_summary(raw_news, api_key)
        if gemini_text:
            cleaned = gemini_text.replace("```json", "").replace("```", "").strip()
            try:
                article_data = json.loads(cleaned, strict=False)
            except Exception:
                cleaned_escaped = cleaned.replace('\n', '\\n').replace('\r', '')
                try:
                    article_data = json.loads(cleaned_escaped, strict=False)
                except Exception:
                    article_data = {"title": "最新の入試・災害情報まとめ", "content": clean_html(gemini_text[:450]), "isBreaking": False}
        else:
            article_data = {"title": "入試情報（AI要約エラー）", "content": f"原因: {error_msg}\n\n{clean_html(raw_news[:1000])}", "isBreaking": False}
    
    if not article_data:
        article_data = {"title": f"{today_str_display}の入試日報", "content": "現在新しい入試・災害情報はありません。", "isBreaking": False}

    publish_date_str = f"{today_str_display} {now_jst.strftime('%H時%M分')} 更新"

    print(f"-> 記事をFirestoreに保存します (ID: {doc_id}) ...")
    try:
        doc_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('articles').document(doc_id)
        # 上書きまたは追記更新 (merge=True により、同日内なら同じ記事が更新され続ける)
        doc_ref.set({
            "title": article_data.get("title", "無題"),
            "content": clean_html(article_data.get("content", "")),
            "isBreaking": bool(article_data.get("isBreaking", False)),
            "publishDate": publish_date_str,
            "createdAt": firestore.SERVER_TIMESTAMP
        }, merge=True)
        print("✓ 【成功】本日の記事を更新・発行しました！")
    except Exception as e:
        print(f"【重大エラー】Firestore保存失敗:\n{e}")
        sys.exit(1)

if __name__ == "__main__":
    main()


