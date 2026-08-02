import os
import sys
import json
import urllib.request
import urllib.parse
import urllib.error
import datetime
import xml.etree.ElementTree as ET
import re
import traceback
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
        print(f"    ※本文の深掘り取得スキップ: {e}")
        return ""

def fetch_news():
    print("-> Googleニュースから記事を検索し、深く読み込んでいます...")
    query = urllib.parse.quote("共通テスト OR 大学入試 (変更 OR 速報 OR 発表)")
    url = f"https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*'
        })
        with urllib.request.urlopen(req, timeout=20) as response:
            xml_data = response.read()
            root = ET.fromstring(xml_data)
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
    except urllib.error.HTTPError as e:
        print(f"【警告】Googleニュースにアクセスをブロックされました (HTTP {e.code})。ニュースなしとして続行します。")
        return ""
    except Exception as e:
        print(f"【警告】ニュース自動検索でエラーが発生しました: {e}。ニュースなしとして続行します。")
        return ""

def get_gemini_summary(raw_news, api_key, is_regular_time):
    print("-> Gemini API によるニュース自動要約を実行中...")
    
    primary_model = "gemini-3.6-flash"
    fallback_model = "gemini-1.5-flash"
    
    url_primary = f"https://generativelanguage.googleapis.com/v1beta/models/{primary_model}:generateContent?key={api_key}"
    url_fallback = f"https://generativelanguage.googleapis.com/v1beta/models/{fallback_model}:generateContent?key={api_key}"
    
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
    
    req_data = json.dumps(data).encode('utf-8')
    
    try:
        req = urllib.request.Request(url_primary, data=req_data, headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=90) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            return res_json['candidates'][0]['content']['parts'][0]['text']
    except urllib.error.HTTPError as e:
        if e.code in [404, 400]:
            print(f"【お知らせ】API側で {primary_model} が未提供（エラー {e.code}）のため、自動的に安定版 ({fallback_model}) に切り替えて実行を継続します。")
            try:
                req2 = urllib.request.Request(url_fallback, data=req_data, headers={'Content-Type': 'application/json'}, method='POST')
                with urllib.request.urlopen(req2, timeout=90) as response2:
                    res_json2 = json.loads(response2.read().decode('utf-8'))
                    return res_json2['candidates'][0]['content']['parts'][0]['text']
            except Exception as e2:
                print(f"【重大エラー】予備モデルでの要約にも失敗: {e2}")
                sys.exit(1)
        else:
            print(f"【重大エラー】Gemini API通信エラー ({e.code})")
            sys.exit(1)
    except Exception as e:
        print(f"【重大エラー】Gemini API要約失敗: {e}")
        sys.exit(1)

def main():
    print("=== 入試ニュース自動検索プログラム開始 ===")
    
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
    
    # 記事数のチェックと「本日すでに定例号が出ているか」の確認
    try:
        articles_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('articles')
        docs = articles_ref.get()
        # 今日の日付が含まれており、かつ isBreaking(速報) ではない記事を探す
        has_today_regular = any(today_str in doc.to_dict().get("publishDate", "") and not doc.to_dict().get("isBreaking", False) for doc in docs)
        existing_count = len(docs)
    except Exception as e:
        print(f"【重大エラー】Firestore読み込み失敗:\n{e}")
        sys.exit(1)
        
    is_first_issue = (existing_count == 0)

    # ★変更点: 定例号を出すかどうかの判定（9時以降でも未発行なら出す）
    # 火(1), 木(3), 土(5), 日(6) の 朝8時以降 で、まだ今日の定例号が出ていない場合は定例号として扱う
    is_regular_day = now_jst.weekday() in [1, 3, 5, 6]
    is_regular_time = is_regular_day and (now_jst.hour >= 8) and not has_today_regular

    raw_news = fetch_news()
    article_data = None

    if raw_news:
        gemini_text = get_gemini_summary(raw_news, api_key, is_regular_time)
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
    
    if not article_data:
        if is_first_issue:
            article_data = {"title": "入試日報新聞 創刊号", "content": "本紙は毎週火・木・土・日の朝に、入試情報を深く要約してお届けします。現在新しい情報を収集中です。", "isBreaking": False}
        else:
            print("✓ 新しいニュースがないため終了します。")
            return

    is_breaking = bool(article_data.get("isBreaking", False))
    content_text = clean_html(article_data.get("content", ""))

    # ★変更点: 発行のスキップ判定をシンプル化
    if not is_first_issue:
        if is_regular_time:
            # まだ出ていない定例号を出すタイミングなので、そのまま進める
            pass
        else:
            # 定例のタイミングではない（速報チェックのみ）
            if not is_breaking or "更新なし" in content_text:
                print("✓ 新しい重大な速報ニュースはありませんでした。スキップします。")
                return

    # 発行日時の表示ラベル設定
    issue_label = "（創刊号）" if is_first_issue else f"（第{existing_count + 1}号）"
    if is_regular_time:
        # 定例号の場合（9時までの発行なら「朝9時発行」、それ以降に遅れて発行されたら「〇時〇分発行(定例)」とする）
        time_label = "朝9時発行" if now_jst.hour <= 9 else now_jst.strftime('%H時%M分発行(定例)')
    else:
        # 速報の場合
        time_label = now_jst.strftime('%H時%M分発行(速報)')
        
    publish_date_str = f"{today_str} {time_label} {issue_label}"

    try:
        articles_ref.add({
            "title": article_data.get("title", "無題"),
            "content": content_text,
            "isBreaking": is_breaking,
            "publishDate": publish_date_str,
            "createdAt": firestore.SERVER_TIMESTAMP
        })
        print("✓ 【成功】記事を発行しました！")
    except Exception as e:
        print(f"【重大エラー】Firestore保存失敗:\n{e}")
        sys.exit(1)

if __name__ == "__main__":
    main()


