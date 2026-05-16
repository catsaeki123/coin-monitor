"""
코인 시가총액 순위 변동 텔레그램 알림 봇 v2.0
- CoinMarketCap API (순위 + 가격 + 시총)
- Google News RSS (호재/악재 뉴스 자동 검색)
- 텔레그램 알림
- Railway 클라우드 배포 대응
"""

import requests
import time
import os
from datetime import datetime
import xml.etree.ElementTree as ET
import urllib.parse

# =============================================
# ⚙️ 설정 (환경변수로 관리 — Railway에서 입력)
# =============================================
CMC_API_KEY           = os.environ.get("CMC_API_KEY", "여기에_CMC_API키_입력")
TELEGRAM_BOT_TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN", "여기에_봇_토큰_입력")
TELEGRAM_CHAT_ID      = os.environ.get("TELEGRAM_CHAT_ID", "여기에_채팅ID_입력")
RANK_CHANGE_THRESHOLD = int(os.environ.get("RANK_CHANGE_THRESHOLD", "10"))
MONITOR_TOP_N         = int(os.environ.get("MONITOR_TOP_N", "100"))
CHECK_INTERVAL        = int(os.environ.get("CHECK_INTERVAL", "300"))  # 5분
# =============================================

CMC_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
CMC_HEADERS = {
    "Accepts": "application/json",
    "X-CMC_PRO_API_KEY": CMC_API_KEY,
}
CMC_PARAMS = {
    "start": 1,
    "limit": MONITOR_TOP_N,
    "convert": "USD",
}

prev_ranks: dict[str, int] = {}


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def fetch_rankings() -> dict[str, dict]:
    """CoinMarketCap에서 현재 순위 데이터 가져오기"""
    try:
        res = requests.get(CMC_URL, headers=CMC_HEADERS, params=CMC_PARAMS, timeout=15)
        res.raise_for_status()
        data = res.json().get("data", [])
        return {
            coin["id"]: {
                "rank":       coin["cmc_rank"],
                "name":       coin["name"],
                "symbol":     coin["symbol"],
                "price":      coin["quote"]["USD"]["price"],
                "mcap":       coin["quote"]["USD"]["market_cap"],
                "change1h":   coin["quote"]["USD"].get("percent_change_1h", 0),
                "change24h":  coin["quote"]["USD"].get("percent_change_24h", 0),
                "change7d":   coin["quote"]["USD"].get("percent_change_7d", 0),
                "volume24h":  coin["quote"]["USD"].get("volume_24h", 0),
            }
            for coin in data
        }
    except Exception as e:
        print(f"[{now()}] CMC API 오류: {e}")
        return {}


def fetch_news(coin_name: str, symbol: str) -> list[dict]:
    """Google News RSS에서 최근 호재 뉴스 검색"""
    news_list = []
    try:
        query = urllib.parse.quote(f"{coin_name} {symbol} crypto news")
        rss_url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
        res = requests.get(rss_url, timeout=10)
        root = ET.fromstring(res.content)

        items = root.findall(".//item")[:3]  # 최근 3개
        for item in items:
            title = item.findtext("title", "")
            link  = item.findtext("link", "")
            pub   = item.findtext("pubDate", "")
            if title:
                news_list.append({"title": title, "link": link, "date": pub})
    except Exception as e:
        print(f"[{now()}] 뉴스 검색 오류 ({coin_name}): {e}")
    return news_list


def format_mcap(value: float) -> str:
    if value >= 1_000_000_000_000:
        return f"${value/1_000_000_000_000:.2f}T"
    elif value >= 1_000_000_000:
        return f"${value/1_000_000_000:.2f}B"
    return f"${value/1_000_000:.2f}M"


def format_price(price: float) -> str:
    if price >= 1:
        return f"${price:,.2f}"
    elif price >= 0.01:
        return f"${price:.4f}"
    return f"${price:.8f}"


def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"[{now()}] 텔레그램 전송 오류: {e}")


def build_alert_message(a: dict, news: list[dict]) -> str:
    sign = "+" if a["change"] > 0 else ""
    direction_emoji = "🚀" if a["change"] > 0 else "💥"
    direction_text  = "급등" if a["change"] > 0 else "급락"
    rank_emoji      = "📈" if a["change"] > 0 else "📉"

    msg = (
        f"{direction_emoji} <b>[시총순위 {direction_text}!]</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>{a['name']} ({a['symbol']})</b>\n\n"
        f"{rank_emoji} <b>순위 변동</b>\n"
        f"   #{a['prev_rank']} → #{a['cur_rank']} "
        f"(<b>{sign}{a['change']}단계</b>)\n\n"
        f"💰 <b>현재 가격</b>: {format_price(a['price'])}\n"
        f"🏦 <b>시가총액</b>: {format_mcap(a['mcap'])}\n\n"
        f"📊 <b>가격 변동률</b>\n"
        f"   • 1시간:  {a['change1h']:+.2f}%\n"
        f"   • 24시간: {a['change24h']:+.2f}%\n"
        f"   • 7일:    {a['change7d']:+.2f}%\n"
        f"📦 <b>24h 거래량</b>: {format_mcap(a['volume24h'])}\n"
    )

    if news:
        msg += f"\n🔥 <b>최근 뉴스</b>\n"
        for i, n in enumerate(news, 1):
            title = n['title'][:50] + "..." if len(n['title']) > 50 else n['title']
            msg += f"   {i}. {title}\n"

    msg += (
        f"\n⏰ {now()}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"#코인배틀 #{a['symbol']} #시총순위 #암호화폐"
    )
    return msg


def check_changes(current: dict):
    global prev_ranks
    alerts = []

    for coin_id, data in current.items():
        cur_rank = data["rank"]
        if coin_id in prev_ranks:
            prev_rank = prev_ranks[coin_id]
            change = prev_rank - cur_rank  # 양수=상승, 음수=하락
            if abs(change) >= RANK_CHANGE_THRESHOLD:
                alerts.append({**data, "prev_rank": prev_rank, "cur_rank": cur_rank, "change": change})

    alerts.sort(key=lambda x: abs(x["change"]), reverse=True)

    for a in alerts:
        print(f"[{now()}] 알림: {a['name']} #{a['prev_rank']}→#{a['cur_rank']} ({a['change']:+}단계)")
        news = fetch_news(a["name"], a["symbol"])
        msg  = build_alert_message(a, news)
        send_telegram(msg)
        time.sleep(1)

    prev_ranks = {cid: d["rank"] for cid, d in current.items()}


def main():
    print("=" * 50)
    print("  코인 순위 모니터 v2.0 시작!")
    print(f"  상위 {MONITOR_TOP_N}개 | {RANK_CHANGE_THRESHOLD}단계 이상 알림")
    print(f"  체크 주기: {CHECK_INTERVAL}초 ({CHECK_INTERVAL//60}분)")
    print("=" * 50)

    send_telegram(
        f"✅ <b>코인 순위 모니터 v2.0 시작!</b>\n\n"
        f"📊 상위 {MONITOR_TOP_N}개 코인 모니터링\n"
        f"🔔 {RANK_CHANGE_THRESHOLD}단계 이상 변동 시 알림\n"
        f"📰 호재/악재 뉴스 자동 포함\n"
        f"⏱ 체크 주기: {CHECK_INTERVAL//60}분\n"
        f"📡 출처: CoinMarketCap\n\n"
        f"⏰ {now()}"
    )

    print(f"[{now()}] 초기 데이터 로드 중...")
    current = fetch_rankings()
    if current:
        prev_ranks.update({cid: d["rank"] for cid, d in current.items()})
        print(f"[{now()}] {len(prev_ranks)}개 코인 기준점 설정 완료 ✅")
    else:
        print(f"[{now()}] 초기 로드 실패!")

    while True:
        time.sleep(CHECK_INTERVAL)
        print(f"[{now()}] 순위 체크 중...")
        current = fetch_rankings()
        if current:
            check_changes(current)
        else:
            print(f"[{now()}] 데이터 로드 실패, 다음 주기에 재시도")


if __name__ == "__main__":
    main()
