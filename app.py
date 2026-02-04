import os
import json
import time
import tweepy
import threading
from flask import Flask

# 1. Renderの監視を回避するためのダミーサーバー(Flask)
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running", 200

# 2. 実際の削除ロジック
def start_delete():
    # 起動直後にサーバーが立ち上がるのを少し待つ
    time.sleep(10)
    
    file_path = 'delete_list.json'
    if not os.path.exists(file_path):
        print("Error: delete_list.json が見つかりません。")
        return

    with open(file_path, 'r') as f:
        target_ids = json.load(f)

    if not target_ids:
        print("削除対象のツイートはありません。")
        return

    print(f"削除作業を開始します。残り: {len(target_ids)}件")

    count = 0
    remaining_ids = target_ids.copy()

    for tweet_id in target_ids:
        if count >= 45: break
        try:
            # 環境変数からカギを読み込む (最新のTWITTER_付きを使用)
            client = tweepy.Client(
                consumer_key=os.environ.get('TWITTER_API_KEY'),
                consumer_secret=os.environ.get('TWITTER_API_SECRET'),
                access_token=os.environ.get('TWITTER_ACCESS_TOKEN'),
                access_token_secret=os.environ.get('TWITTER_ACCESS_TOKEN_SECRET')
            )
            client.delete_tweet(tweet_id)
            print(f"削除成功: {tweet_id}")
            remaining_ids.remove(tweet_id)
            count += 1
            time.sleep(10)
        except Exception as e:
            print(f"エラー (ID:{tweet_id}): {e}")
            if "401" in str(e): break

    with open(file_path, 'w') as f:
        json.dump(remaining_ids, f)
    print(f"今回の作業を終了しました。残り: {len(remaining_ids)}件")

# 3. 実行部分：サーバーと削除処理を同時に動かす
if __name__ == "__main__":
    # 削除処理をバックグラウンドで開始
    threading.Thread(target=start_delete, daemon=True).start()
    
    # Renderが指定するポートでサーバーを起動
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
