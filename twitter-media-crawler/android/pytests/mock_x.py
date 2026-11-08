"""테스트용 가짜 X API: gallery-dl의 TwitterAPI._call을 미리 만든 GraphQL 응답으로 바꾼다.

실제 X에 접속하지 않고 앱 쪽 로직(설정, 받은 기록, 빠른 새로고침, 중지, 오류 해석)을 끝까지 검증하기 위한 것.
미디어 파일 주소는 테스트가 띄운 로컬 HTTP 서버(base_url)를 가리킨다.
"""

import json

STATE = {"scenario": "normal", "base": "", "calls": [], "new": 0, "rate_limit_wait": 0}
_ORIGINAL = {}


def _user(uid, name):
    return {
        "__typename": "User",
        "rest_id": uid,
        "core": {"screen_name": name, "name": name.title(), "created_at": "Wed Jan 01 00:00:00 +0000 2020"},
        "legacy": {"description": "", "entities": {"description": {"urls": []}}, "pinned_tweet_ids_str": []},
        "location": {"location": ""},
        "verification": {"verified": False},
        "privacy": {"protected": False},
        "avatar": {"image_url": STATE["base"] + "/a_normal.jpg"},
    }


def _photo(key):
    return {
        "type": "photo",
        "media_url_https": f"{STATE['base']}/media/{key}.jpg",
        "original_info": {"width": 100, "height": 100},
    }


def _video(key, kind="video"):
    base = STATE["base"]
    if kind == "animated_gif":
        variants = [{"bitrate": 0, "content_type": "video/mp4", "url": f"{base}/gif/{key}.mp4"}]
    else:
        variants = [
            {"bitrate": 256000, "content_type": "video/mp4", "url": f"{base}/vid/{key}_low.mp4"},
            {"content_type": "application/x-mpegURL", "url": f"{base}/vid/{key}.m3u8"},
            {"bitrate": 2176000, "content_type": "video/mp4", "url": f"{base}/vid/{key}_high.mp4"},
        ]
    return {
        "type": kind,
        "media_url_https": f"{base}/thumb/{key}.jpg",
        "original_info": {"width": 100, "height": 100},
        "video_info": {"duration_millis": 1000, "variants": variants},
    }


def _tweet(tid, author, media=()):
    legacy = {
        "id_str": tid,
        "full_text": "hello",
        "lang": "en",
        "conversation_id_str": tid,
        "created_at": "Wed Oct 30 00:00:00 +0000 2024",
        "user_id_str": author["rest_id"],
        "entities": {"hashtags": [], "user_mentions": [], "urls": []},
    }
    if media:
        legacy["extended_entities"] = {"media": list(media)}
    return {
        "__typename": "Tweet",
        "rest_id": tid,
        "core": {"user_results": {"result": author}},
        "legacy": legacy,
        "views": {"count": "1"},
    }


def _instructions(tweets, next_cursor):
    entries = [
        {
            "entryId": f"tweet-{t['rest_id']}",
            "sortIndex": str(10**18 - i),
            "content": {
                "entryType": "TimelineTimelineItem",
                "itemContent": {"itemType": "TimelineTweet", "tweet_results": {"result": t}},
            },
        }
        for i, t in enumerate(tweets)
    ]
    entries.append(
        {
            "entryId": "cursor-bottom-1",
            "content": {"entryType": "TimelineTimelineCursor", "value": next_cursor, "cursorType": "Bottom"},
        }
    )
    return [{"type": "TimelineAddEntries", "entries": entries}]


def bookmarks():
    alice, bob = _user("100", "alice"), _user("200", "bob")
    scenario = STATE["scenario"]
    if scenario == "many":
        new = [_tweet(str(1870000000000000000 + i), bob, [_photo(f"new{i}")]) for i in range(STATE["new"], 0, -1)]
        return new + [_tweet(str(1850000000000001000 - i), alice, [_photo(f"m{i}")]) for i in range(30)]
    return [
        _tweet("1850000000000000001", alice, [_photo("p1"), _photo("p2")]),
        _tweet("1850000000000000002", bob, [_video("v1")]),
        _tweet("1850000000000000003", alice, [_video("g1", "animated_gif")]),
        _tweet("1850000000000000004", bob),
    ]


def nasa_tweets():
    nasa = _user("11348282", "nasa")
    return [_tweet("1860000000000000001", nasa, [_photo("n1")]), _tweet("1860000000000000002", nasa, [_video("nv1")])]


def _fake_call(self, endpoint, params, method="GET", auth=True, root=None):
    from gallery_dl import exception

    op = endpoint.rsplit("/", 1)[-1]
    variables = json.loads(params["variables"]) if params and params.get("variables") else {}
    STATE["calls"].append(
        {
            "op": op,
            "cursor": variables.get("cursor"),
            "auth_token": self.extractor.cookies.get("auth_token", domain=".x.com"),
            "csrf": self.headers.get("x-csrf-token"),
        }
    )
    scenario = STATE["scenario"]
    if scenario == "bad_cookie":
        raise exception.AbortExtraction("'Could not authenticate you'")
    if STATE["rate_limit_wait"]:
        wait, STATE["rate_limit_wait"] = STATE["rate_limit_wait"], 0
        self.extractor.wait(seconds=wait, reason="rate limit")
    if op == "UserByScreenName":
        return {"data": {"user": {"result": _user("11348282", "nasa")}}}
    if op == "SearchTimeline":
        return {"data": {"search_by_raw_query": {"search_timeline": {"timeline": {"instructions": []}}}}}
    if op == "TweetDetail":
        tid = variables["focalTweetId"]
        found = [t for t in nasa_tweets() if t["rest_id"] == tid]
        return {"data": {"threaded_conversation_with_injections_v2": {"instructions": _instructions(found, "END")}}}

    page = int((variables.get("cursor") or "P0")[1:])
    if op == "Bookmarks":
        items = bookmarks()
    elif op in ("UserMedia", "UserTweets"):
        items = nasa_tweets()
    else:
        raise exception.AbortExtraction(f"unexpected op {op}")
    chunk = items[page * 25 : (page + 1) * 25]
    instructions = _instructions(chunk, f"P{page + 1}") if chunk else []
    if op == "Bookmarks":
        return {"data": {"bookmark_timeline_v2": {"timeline": {"instructions": instructions}}}}
    return {"data": {"user": {"result": {"timeline": {"timeline": {"instructions": instructions}}}}}}


def install(base_url, scenario="normal", **knobs):
    from gallery_dl.extractor import twitter

    STATE.update(scenario=scenario, base=base_url, calls=[], new=0, rate_limit_wait=0)
    STATE.update(knobs)
    if not _ORIGINAL:
        _ORIGINAL["call"] = twitter.TwitterAPI._call
        _ORIGINAL["tid"] = twitter.TwitterAPI._transaction_id
    twitter.TwitterAPI._call = _fake_call
    twitter.TwitterAPI._transaction_id = lambda self, url, method="GET": None
