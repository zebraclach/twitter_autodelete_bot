import os
import json
import tweepy
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import requests

# Environment variables for Twitter API keys and tokens
API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.environ.get("ACCESS_TOKEN_SECRET")
BEARER_TOKEN = os.environ.get("BEARER_TOKEN")

app = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()

# Tweepy v1.1 authentication for posting and reading timeline
auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
api = tweepy.API(auth)

# File used to persist scheduled deletions
TWEET_STORE_FILE = "tweet_store.json"

# --- Schedule persistence helpers ---
def load_all_schedules():
    """Load all scheduled deletions from file."""
    if not os.path.exists(TWEET_STORE_FILE):
        return {}
    with open(TWEET_STORE_FILE, "r") as f:
        return json.load(f)

def save_all_schedules(data: dict) -> None:
    """Save all scheduled deletions to file."""
    with open(TWEET_STORE_FILE, "w") as f:
        json.dump(data, f)

def save_tweet_schedule(tweet_id: int, delete_time: datetime) -> None:
    """Save a single tweet's deletion schedule."""
    data = load_all_schedules()
    data[str(tweet_id)] = delete_time.isoformat()
    save_all_schedules(data)

def remove_tweet_schedule(tweet_id: int) -> None:
    """Remove a tweet's deletion schedule after deletion."""
    data = load_all_schedules()
    data.pop(str(tweet_id), None)
    save_all_schedules(data)

# --- Helper functions for checks ---
def is_liked_by_me(tweet_id: int) -> bool:
    """Check if the authenticated user has liked the tweet."""
    try:
        tweet = api.get_status(tweet_id)
        return getattr(tweet, "favorited", False)
    except Exception:
        return False

def get_impression(tweet_id: int) -> int:
    """Retrieve the impression count for a tweet using Twitter API v2."""
    url = f"https://api.twitter.com/2/tweets/{tweet_id}?tweet.fields=public_metrics"
    headers = {"Authorization": f"Bearer {BEARER_TOKEN}"}
    res = requests.get(url, headers=headers)
    if not res.ok:
        return 0
    data = res.json()
    return data.get("data", {}).get("public_metrics", {}).get("impression_count", 0)

# --- Core deletion logic ---
def delete_tweet(tweet_id: int) -> None:
    """Delete the given tweet if it passes like/impression checks."""
    if is_liked_by_me(tweet_id):
        print(f"Skipped delete (liked): {tweet_id}")
        return
    try:
        api.destroy_status(tweet_id)
        print(f"Deleted tweet: {tweet_id}")
        remove_tweet_schedule(tweet_id)
    except Exception as e:
        print(f"Error deleting tweet {tweet_id}: {e}")

def schedule_delete(tweet_id: int, delete_time: datetime) -> None:
    """Schedule a tweet for deletion at a future time."""
    scheduler.add_job(delete_tweet, "date", run_date=delete_time, args=[tweet_id])
    save_tweet_schedule(tweet_id, delete_time)

# --- Detection and scheduling of manual tweets ---
def detect_and_schedule_manual_tweets() -> None:
    """
    Scan the user's timeline and ensure each tweet is handled:
    - If the tweet is within the last 12 hours, schedule its deletion for 12 hours after creation.
    - If the tweet is older than 12 hours, delete it immediately if impressions < 10000 and not liked.
    """
    try:
        # Fetch up to 200 of the most recent tweets (excluding retweets)
        tweets = api.user_timeline(count=200, include_rts=False)
    except Exception as e:
        print(f"Error fetching timeline: {e}")
        return
    existing = load_all_schedules()
    now = datetime.utcnow()
    for tweet in tweets:
        tid = tweet.id
        tid_str = str(tid)
        # Skip if already scheduled
        if tid_str in existing:
            continue
        created_at = tweet.created_at  # UTC
        delete_time = created_at + timedelta(hours=12)
        if delete_time > now:
            # Schedule deletion for tweets younger than 12 hours
            print(f"Scheduling manual tweet {tid_str} for deletion at {delete_time}")
            schedule_delete(tid, delete_time)
        else:
            # For older tweets, delete immediately if under impression threshold and not liked
            impressions = get_impression(tid)
            if impressions < 10000 and not is_liked_by_me(tid):
                print(f"Deleting old manual tweet {tid_str} immediately (impressions: {impressions})")
                delete_tweet(tid)

# --- Monitor impressions and detect new manual tweets ---
def monitor_impressions_and_detect() -> None:
    """
    Periodic job that detects new manual tweets and monitors impressions of scheduled tweets.
    If a scheduled tweet crosses the impression threshold of 1000, delete it early.
    """
    # Detect and schedule any new manual tweets
    detect_and_schedule_manual_tweets()
    # Check impressions for scheduled tweets
    data = load_all_schedules()
    for tid_str in list(data.keys()):
        tid = int(tid_str)
        impressions = get_impression(tid)
        print(f"Tweet {tid_str} impressions: {impressions}")
        if impressions >= 1000:
            if not is_liked_by_me(tid):
                delete_tweet(tid)

# Schedule the monitoring job every 10 minutes
scheduler.add_job(monitor_impressions_and_detect, "interval", minutes=10)

# --- Flask API endpoints ---
@app.route("/tweet", methods=["POST"])
def post_tweet():
    """API endpoint to post a tweet and schedule its deletion 12 hours later."""
    text = request.json.get("text")
    if not text:
        return jsonify({"error": "No text provided"}), 400
    tweet = api.update_status(text)
    tweet_id = tweet.id
    delete_time = datetime.utcnow() + timedelta(hours=12)
    schedule_delete(tweet_id, delete_time)
    return jsonify({"tweet_id": tweet_id, "delete_time": delete_time.isoformat()})

@app.route("/delete_old", methods=["POST"])
def delete_old():
    """
    Delete tweets older than a specified number of hours (default 12).
    Excludes tweets liked by the user and tweets with impressions >= 10000.
    Request JSON body can include {"hours": <number>} to override the cutoff.
    """
    try:
        hours = float(request.json.get("hours", 12))
    except Exception:
        hours = 12
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    deleted = []
    try:
        tweets = api.user_timeline(count=200, include_rts=False)
    except Exception as e:
        return jsonify({"error": f"Error fetching timeline: {e}"}), 500
    for tweet in tweets:
        tid = tweet.id
        created_at = tweet.created_at
        if created_at <= cutoff:
            impressions = get_impression(tid)
            if impressions < 10000 and not is_liked_by_me(tid):
                delete_tweet(tid)
                deleted.append(str(tid))
    return jsonify({"deleted": deleted})

# --- Reschedule and initial detection on startup ---
def reschedule_all() -> None:
    """
    Reload scheduled deletions from file and either reschedule them or delete
    immediately if their scheduled time has passed (subject to checks).
    """
    data = load_all_schedules()
    now = datetime.utcnow()
    for tid_str, time_str in data.items():
        tid = int(tid_str)
        try:
            dt = datetime.fromisoformat(time_str)
        except Exception:
            continue
        if dt > now:
            schedule_delete(tid, dt)
        else:
            # If the scheduled time has passed, delete if appropriate
            impressions = get_impression(tid)
            if impressions < 10000 and not is_liked_by_me(tid):
                delete_tweet(tid)

if __name__ == "__main__":
    # Restore schedules and process past tweets on startup
    reschedule_all()
    detect_and_schedule_manual_tweets()
    app.run(host="0.0.0.0", port=10000)
