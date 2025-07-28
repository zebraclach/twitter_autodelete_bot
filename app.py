import os
import json
import tweepy
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import requests

# 環境変数から API キー類を取得
API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.environ.get("ACCESS_TOKEN_SECRET")
BEARER_TOKEN = os.environ.get("BEARER_TOKEN")

app = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()

# Tweepy v1.1 認証（ユーザータイムライン取得に利用）
auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
api = tweepy.API(auth)

TWEET_STORE_FILE = "tweet_store.json"

# --- スケジュール保存・読込関連 ---
def load_all_schedules():
    if not os.path.exists(TWEET_STORE_FILE):
        return {}
    with open(TWEET_STORE_FILE, "r") as f:
        return json.load(f)

def save_all_schedules(data):
    with open(TWEET_STORE_FILE, "w") as f:
        json.dump(data, f)

def save_tweet_schedule(tweet_id, delete_time):
    data = load_all_schedules()
    data[str(tweet_id)] = delete_time.isoformat()
    save_all_schedules(data)

def remove_tweet_schedule(tweet_id):
    data = load_all_schedules()
    data.pop(str(tweet_id), None)
    save_all_schedules(data)

# --- いいね判定 ---
def is_liked_by_me(tweet_id):
    tweet = api.get_status(tweet_id)
    return tweet.favorited

# --- インプレッション取得（v2 API） ---
def get_impression(tweet_id):
    url = f"https://api.twitter.com/2/tweets/{tweet_id}?tweet.fields=public_metrics"
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    res = requests.get(url, headers=headers)
    data = res.json()
    return data["data"]["public_metrics"].get("impression_count", 0)

# --- ツイート削除処理 ---
def delete_tweet(tweet_id):
    # 自分でいいねしている場合は削除しない
    if is_liked_by_me(tweet_id):
        print(f"Skipped delete (liked): {tweet_id}")
        return
    try:
        api.destroy_status(tweet_id)
        print(f"Deleted tweet: {tweet_id}")
        remove_tweet_schedule(tweet_id)
    except Exception as e:
        print(f"Error deleting tweet {tweet_id}: {e}")

# --- 削除ジョブ登録 ---
def schedule_delete(tweet_id, delete_time):
    scheduler.add_job(delete_tweet, 'date', run_date=delete_time, args=[tweet_id])
    save_tweet_schedule(tweet_id, delete_time)

# --- 手動ツイート検出・登録 ---
def detect_and_schedule_manual_tweets():
    """
    自分の最新ツイートを取得し、まだ登録していないものに対して
    12 時間後の削除ジョブを追加する。
    """
    try:
        # 最新50件ほど取得（必要に応じて調整）
        tweets = api.user_timeline(count=50, include_rts=False)
    except Exception as e:
        print(f"Error fetching timeline: {e}")
        return

    existing = load_all_schedules()
    now = datetime.utcnow()
    for tweet in tweets:
        tid_str = str(tweet.id)
        # 既に登録済みの場合はスキップ
        if tid_str in existing:
            continue
        # ツイート作成時刻（UTC）から 12 時間後を計算
        created_at = tweet.created_at  # UTC datetime
        delete_time = created_at + timedelta(hours=12)
        # 12時間以内のものだけ登録
        if delete_time > now:
            print(f"Scheduling manual tweet {tid_str} for deletion at {delete_time}")
            schedule_delete(tweet.id, delete_time)
                    else:
                    # Tweet is older than 12 hours; delete immediately if not liked and under 10000 impressions
                impressions = get_impression(tweet.id)
            if         impressions < 10000 and not is_liked_by_me(tweet.id):
                        print(f"Deleting old manual tweet {tid_str} immediately (impressions: {impressions})")
                delete_tweet(tweet.id)


# --- インプレッション監視 ---
def monitor_impressions_and_detect():
    """
    登録済みツイートのインプレッションを監視し、1000を超えたら削除。
    あわせて新しい手動ツイートの検出も行う。
    """
    # 新しい手動ツイートを検出
    detect_and_schedule_manual_tweets()

    data = load_all_schedules()
    for tid_str in list(data.keys()):
        impressions = get_impression(tid_str)
        print(f"Tweet {tid_str} impressions: {impressions}")
        if impressions >= 1000:
            if not is_liked_by_me(int(tid_str)):
                delete_tweet(int(tid_str))

# 10分ごとに監視ジョブを実行
scheduler.add_job(monitor_impressions_and_detect, 'interval', minutes=10)

# --- 投稿API（以前と同じ） ---
@app.route('/tweet', methods=['POST'])
def post_tweet():
    text = request.json.get('text')
    if not text:
        return jsonify({'error': 'No text provided'}), 400

    tweet = api.update_status(text)
    tweet_id = tweet.id

    # 12時間後に削除予約
    delete_time = datetime.utcnow() + timedelta(hours=12)
    schedule_delete(tweet_id, delete_time)

    return jsonify({'tweet_id': tweet_id, 'delete_time': delete_time.isoformat()})

# --- 一括削除API ---
@app.route('/delete_old', methods=['POST'])
def delete_old():
    """
    指定した時間より前に投稿されたツイートを一括削除するエンドポイント。
    リクエストボディがJSON形式の場合は "hours" フィールドを取得して削除対象期間を決めます。
    指定がない場合はデフォルトで12時間より前に投稿されたツイートを削除します。
    自分でいいねしているツイートは削除しません。
    削除したツイートIDのリストをJSONで返します。
    """
    # JSONボディがあれば hours を取得、なければデフォルト値を使用
    hours = 12
    if request.is_json:
        try:
            hours = int(request.json.get('hours', hours))
        except (ValueError, TypeError):
            pass
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    deleted = []
    try:
        # 最新200件ほど取得（必要に応じて調整）
        tweets = api.user_timeline(count=200, include_rts=False)
        for tweet in tweets:
            # cutoffより前に投稿され、かつ自分がいいねしていないツイートを削除
            if tweet.created_at < cutoff and not tweet.favorited:
                # インプレッション数が1万以上の場合は削除対象から除外する
                impressions = 0
                try:
                    impressions = get_impression(tweet.id)
                except Exception as e:
                    # 取得に失敗した場合は0として扱う
                    print(f"Error getting impressions for tweet {tweet.id}: {e}")
                if impressions >= 10000:
                    # 人気ツイートなので削除しない
                    continue
                try:
                    api.destroy_status(tweet.id)
                    # スケジュールに登録されていれば削除
                    remove_tweet_schedule(tweet.id)
                    deleted.append(tweet.id)
                except Exception as e:
                    print(f"Error deleting tweet {tweet.id}: {e}")
    except Exception as e:
        print(f"Error fetching timeline for bulk delete: {e}")
    return jsonify({'deleted_ids': deleted})

# --- 起動時に保存済みジョブを復元 ---
def reschedule_all():
    data = load_all_schedules()
    now = datetime.utcnow()
    for tid_str, time_str in data.items():
        dt = datetime.fromisoformat(time_str)
        # まだ先の削除スケジュールなら再登録、過ぎていたら即削除
        if dt > now:
            scheduler.add_job(delete_tweet, 'date', run_date=dt, args=[int(tid_str)])
        else:
            delete_tweet(int(tid_str))

if __name__ == '__main__':
    reschedule_all()
    # Renderでは0.0.0.0:10000で起動する設定
    app.run(host='0.0.0.0', port=10000)
