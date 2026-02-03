import os
import json
import time
import tweepy

# RenderのEnvironmentで設定したカギを読み込む
API_KEY = os.environ.get('TWITTER_API_KEY')
API_SECRET = os.environ.get('TWITTER_API_SECRET')
ACCESS_TOKEN = os.environ.get('TWITTER_ACCESS_TOKEN')
ACCESS_TOKEN_SECRET = os.environ.get('TWITTER_ACCESS_TOKEN_SECRET')

# 認証設定 (API v2 を使用)
client = tweepy.Client(
    consumer_key=API_KEY, consumer_secret=API_SECRET,
    access_token=ACCESS_TOKEN, access_token_secret=ACCESS_TOKEN_SECRET
)

def load_tweets_from_archive():
    # ここでアーカイブ(tweets.js)を読み込み、条件に合うIDだけを抽出する
    # ※アーカイブが届いたらここの詳細を書き込みます
    delete_list = []
    return delete_list

def delete_tweets():
    targets = load_tweets_from_archive()
    for tweet_id in targets:
        try:
            client.delete_tweet(tweet_id)
            print(f"Deleted: {tweet_id}")
            time.sleep(15) # API制限に引っかからないよう間隔をあける
        except Exception as e:
            print(f"Error on {tweet_id}: {e}")

if __name__ == "__main__":
    delete_tweets()
