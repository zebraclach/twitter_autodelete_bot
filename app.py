import os
import json
import time
import tweepy

# Renderの環境変数からカギを読み込む
API_KEY = os.environ.get('TWITTER_API_KEY')
API_SECRET = os.environ.get('TWITTER_API_SECRET')
ACCESS_TOKEN = os.environ.get('TWITTER_ACCESS_TOKEN')
ACCESS_TOKEN_SECRET = os.environ.get('TWITTER_ACCESS_TOKEN_SECRET')

# X API 認証 (v2を使用)
client = tweepy.Client(
    consumer_key=API_KEY, consumer_secret=API_SECRET,
    access_token=ACCESS_TOKEN, access_token_secret=ACCESS_TOKEN_SECRET
)

def start_delete():
    # 削除リストを読み込む
    file_path = 'delete_list.json'
    if not os.path.exists(file_path):
        print("削除リスト(delete_list.json)が見つかりません。作業を終了します。")
        return

    with open(file_path, 'r') as f:
        target_ids = json.load(f)

    if not target_ids:
        print("削除対象がもうありません！")
        return

    print(f"削除開始。現在の残り件数: {len(target_ids)}")

    # X API Freeプランの1日あたりの上限（約50件）を考慮し、45件で止める
    MAX_DELETE_PER_RUN = 45
    count = 0
    remaining_ids = target_ids.copy()

    for tweet_id in target_ids:
        if count >= MAX_DELETE_PER_RUN:
            print(f"今回の削除上限({MAX_DELETE_PER_RUN}件)に達しました。")
            break
            
        try:
            # 削除実行
            client.delete_tweet(tweet_id)
            print(f"成功: {tweet_id} を削除しました。")
            remaining_ids.remove(tweet_id)
            count += 1
            time.sleep(10)  # 連続リクエストを避けるための待機
        except Exception as e:
            print(f"エラー (ID:{tweet_id}): {e}")
            # 権限エラー(401)が出た場合は設定ミスなので中断
            if "401" in str(e):
                print("認証エラーです。環境変数の値を確認してください。")
                return

    # 残ったリストを上書き保存する（次回続きから消すため）
    with open(file_path, 'w') as f:
        json.dump(remaining_ids, f)
    
    print(f"本日の作業完了。リストを更新しました。残り: {len(remaining_ids)}件")

if __name__ == "__main__":
    start_delete()
