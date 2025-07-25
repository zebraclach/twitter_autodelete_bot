import os
import json
import tweepy
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import requests

# 環境変数からAPIキーを取得
API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.environ.get("ACCESS_TOKEN_SECRET")
BEARER_TOKEN = os.environ.get("BEARER_TOKEN")

app = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()

# Tweepy認証
auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
api = tweepy.API(auth)

TWEET_STORE_FILE = "tweet_store.json"

# --- 保存・読込関数 ---
def save_tweet_schedule(tweet_id: int, delete_time: datetime) -> None:
    """投稿したツイートの削除予定時刻をファイルに保存する"""
    data = load_all_schedules()
    data[str(tweet_id)] = delete_time.isoformat()
    with open(TWEET_STORE_FILE, "w") as f:
        json.dump(data, f)

def load_all_schedules() -> dict:
    """保存済みスケジュールをすべて読み込む"""
    if not os.path.exists(TWEET_STORE_FILE):
        return {}
    with open(TWEET_STORE_FILE, "r") as f:
        return json.load(f)

def remove_tweet_schedule(tweet_id: int) -> None:
    """削除済みツイートをストアから取り除く"""
    data = load_all_schedules()
    data.pop(str(tweet_id), None)
    with open(TWEET_STORE_FILE, "w") as f:
        json.dump(data, f)

# --- いいね判定 ---
def is_liked_by_me(tweet_id: int) -> bool:
    """自分がそのツイートにいいねしているか確認する"""
    tweet = api.get_status(tweet_id)
    return getattr(tweet, 'favorited', False)

# --- インプレッション取得 ---
def get_impression(tweet_id: int) -> int:
    """ツイートのインプレッション数を取得する (v2 API)"""
    url = f"https://api.twitter.com/2/tweets/{tweet_id}?tweet.fields=public_metrics"
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    res = requests.get(url, headers=headers)
    if not res.ok:
        return 0
    data = res.json()
    return data.get("data", {}).get("public_metrics", {}).get("impression_count", 0)

# --- ツイート削除処理 ---
def delete_tweet(tweet_id: int) -> None:
    """ツイートを削除する。ただし自分がいいねしたものはスキップ"""
    if is_liked_by_me(tweet_id):
        # 自分でいいねした場合は削除せず終了
        print(f"Skipped delete (liked): {tweet_id}")
        return
    try:
        api.destroy_status(tweet_id)
        print(f"Deleted tweet: {tweet_id}")
        remove_tweet_schedule(tweet_id)
    except Exception as e:
        print(f"Error deleting tweet {tweet_id}: {e}")

# --- 12時間後の削除ジョブ ---
def schedule_delete(tweet_id: int, delete_time: datetime) -> None:
    """指定時刻にツイートを削除するジョブを登録"""
    scheduler.add_job(delete_tweet, 'date', run_date=delete_time, args=[tweet_id])
    save_tweet_schedule(tweet_id, delete_time)

# --- インプレッション監視ジョブ（10分ごと） ---
def monitor_impressions() -> None:
    """登録済みツイートのインプレッションを監視し、規定値を超えたら即削除"""
    data = load_all_schedules()
    for tweet_id_str in list(data.keys()):
        tweet_id = int(tweet_id_str)
        impressions = get_impression(tweet_id)
        print(f"Tweet {tweet_id} impressions: {impressions}")
        if impressions >= 1000:
            if not is_liked_by_me(tweet_id):
                delete_tweet(tweet_id)

# 10分ごとにインプレッション監視
scheduler.add_job(monitor_impressions, 'interval', minutes=10)

# --- ツイート投稿API ---
@app.route('/tweet', methods=['POST'])
def post_tweet():
    """POST /tweet エンドポイント。受け取ったテキストを投稿し、削除をスケジュール"""
    text = request.json.get('text')
    if not text:
        return jsonify({'error': 'No text provided'}), 400

    # ツイート投稿
    tweet = api.update_status(text)
    tweet_id = tweet.id

    # 12時間後に削除をスケジュール
    delete_time = datetime.now() + timedelta(hours=12)
    schedule_delete(tweet_id, delete_time)

    return jsonify({'tweet_id': tweet_id, 'delete_time': delete_time.isoformat()})

# --- サーバ起動時に残タスク復元 ---
def reschedule_all() -> None:
    """保存済みの削除予定を復元し、必要に応じて即時削除"""
    data = load_all_schedules()
    now = datetime.now()
    for tweet_id_str, time_str in data.items():
        tweet_id = int(tweet_id_str)
        dt = datetime.fromisoformat(time_str)
        if dt > now:
            schedule_delete(tweet_id, dt)
        else:
            # 予定時刻を過ぎていた場合は削除
            delete_tweet(tweet_id)

if __name__ == '__main__':
    # アプリ起動時に保存済みのジョブを復元
    reschedule_all()
    # Flaskアプリ起動
    app.run(host='0.0.0.0', port=10000)