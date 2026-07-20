import html
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo


QUERY = "효성화학 when:2d"
MAX_ITEMS = 5


def fetch_google_news_rss(query: str) -> bytes:
    encoded_query = urllib.parse.quote(query)
    url = (
        "https://news.google.com/rss/search?"
        f"q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 HyosungChemicalNewsBot/1.0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def source_from_item(item: ET.Element) -> str:
    source = item.find("source")
    if source is not None and source.text:
        return clean_text(source.text)
    title = clean_text(item.findtext("title", ""))
    if " - " in title:
        return title.rsplit(" - ", 1)[-1].strip()
    return "Google 뉴스"


def title_without_source(title: str, source: str) -> str:
    suffix = f" - {source}"
    if title.endswith(suffix):
        return title[: -len(suffix)].strip()
    return title


def build_digest() -> str:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    root = ET.fromstring(fetch_google_news_rss(QUERY))
    items = root.findall("./channel/item")

    seen_titles = set()
    selected = []
    for item in items:
        source = source_from_item(item)
        title = title_without_source(clean_text(item.findtext("title", "")), source)
        link = clean_text(item.findtext("link", ""))
        published = clean_text(item.findtext("pubDate", ""))
        if not title or not link:
            continue

        key = re.sub(r"\W+", "", title.lower())
        if key in seen_titles:
            continue
        seen_titles.add(key)

        selected.append(
            {
                "title": title,
                "source": source,
                "published": published,
                "link": link,
            }
        )
        if len(selected) >= MAX_ITEMS:
            break

    header = f"[효성화학 주요 기사] {now:%Y-%m-%d} 오전"
    if not selected:
        return (
            f"{header}\n\n"
            "최근 24~48시간 내 효성화학 관련 주요 기사는 확인되지 않았습니다."
        )

    lines = [header]
    for index, article in enumerate(selected, start=1):
        lines.extend(
            [
                "",
                f"{index}. {article['title']}",
                f"- 출처: {article['source']}",
                f"- 날짜: {article['published'] or '확인 필요'}",
                f"- 링크: {article['link']}",
            ]
        )
    return "\n".join(lines)


def send_telegram_message(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID secrets are required.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8", errors="replace")
        if response.status >= 400:
            raise RuntimeError(body)


def main() -> int:
    try:
        send_telegram_message(build_digest())
        return 0
    except Exception as exc:
        print(f"Failed to send digest: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
