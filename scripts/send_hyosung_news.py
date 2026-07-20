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

CATEGORIES = [
    (
        "공시/회사",
        5,
        ["공시", "유상증자", "전환사채", "채권", "매각", "인수", "합병", "분할", "소송"],
        "회사 공식 의사결정이나 재무구조에 직접 연결될 수 있습니다.",
    ),
    (
        "실적/재무",
        5,
        ["실적", "영업이익", "순손실", "매출", "부채", "차입", "자금", "재무", "신용등급"],
        "손익과 재무 안정성에 대한 시장 평가가 바뀔 수 있습니다.",
    ),
    (
        "산업/업황",
        4,
        ["화학", "스프레드", "프로판", "pp", "폴리프로필렌", "반도체", "수소", "탄소섬유", "증설"],
        "화학 업황과 제품 스프레드는 실적 방향을 가늠하는 선행 단서가 됩니다.",
    ),
    (
        "증권/리포트",
        3,
        ["목표가", "투자의견", "리포트", "증권", "전망", "컨센서스"],
        "증권사 시각 변화는 단기 수급과 기대치에 영향을 줄 수 있습니다.",
    ),
    (
        "주가/수급",
        1,
        ["상승", "하락", "급등", "급락", "강세", "약세", "특징주", "코스피"],
        "단기 가격 움직임 기사라서 원인 확인용으로만 보는 편이 좋습니다.",
    ),
]

LOW_VALUE_KEYWORDS = ["상승", "하락", "급등", "급락", "강세", "약세", "특징주"]


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


def normalize_title(value: str) -> str:
    value = re.sub(r"\[[^\]]+\]", "", value)
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.sub(r"[^0-9a-zA-Z가-힣]+", "", value)
    return value.lower()


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


def classify_article(title: str) -> tuple[str, int, str]:
    haystack = title.lower()
    for category, score, keywords, reason in CATEGORIES:
        if any(keyword.lower() in haystack for keyword in keywords):
            return category, score, reason
    return "일반", 2, "효성화학 관련 언급은 있으나 직접 영향은 추가 확인이 필요합니다."


def relation_to_hyosung(title: str) -> str:
    haystack = title.lower()
    if "효성화학" in title:
        return "효성화학이 기사 제목에 직접 언급된 직접 관련 기사입니다."
    if any(keyword in title for keyword in ["효성", "조현준", "효성티앤씨", "효성첨단소재", "효성중공업"]):
        return "효성그룹 또는 계열사 이슈로, 그룹 재무·투자심리 측면에서 효성화학과 함께 볼 만합니다."
    if any(keyword.lower() in haystack for keyword in ["화학", "프로판", "pp", "폴리프로필렌", "스프레드"]):
        return "효성화학의 주요 사업 환경과 연결되는 화학 업황 기사입니다."
    if any(keyword in title for keyword in ["신용등급", "차입", "채권", "부채", "자금", "유동성"]):
        return "효성화학의 재무 안정성이나 자금 조달 여건과 연결해서 볼 필요가 있습니다."
    if is_low_value_price_article(title):
        return "효성화학 관련 단기 주가·수급성 언급입니다. 실제 원인이 있는지 확인용으로 보세요."
    return "효성화학과의 연결 강도는 낮을 수 있어 원문에서 관련 대목을 확인하는 편이 좋습니다."


def importance_label(score: int) -> str:
    if score >= 5:
        return "높음"
    if score >= 3:
        return "보통"
    return "낮음"


def is_low_value_price_article(title: str) -> bool:
    return any(keyword in title for keyword in LOW_VALUE_KEYWORDS)


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

        key = normalize_title(title)
        if key in seen_titles:
            continue
        seen_titles.add(key)

        category, score, reason = classify_article(title)

        selected.append(
            {
                "title": title,
                "source": source,
                "published": published,
                "link": link,
                "category": category,
                "score": score,
                "reason": reason,
                "is_low_value": is_low_value_price_article(title),
            }
        )

    selected.sort(key=lambda item: (item["score"], not item["is_low_value"]), reverse=True)
    selected = selected[:MAX_ITEMS]

    header = f"[효성화학 모닝 브리핑] {now:%Y-%m-%d}"
    if not selected:
        return (
            f"{header}\n\n"
            "최근 24~48시간 내 효성화학 관련 주요 기사는 확인되지 않았습니다."
        )

    high_count = sum(1 for article in selected if article["score"] >= 5)
    price_count = sum(1 for article in selected if article["is_low_value"])
    categories = ", ".join(dict.fromkeys(article["category"] for article in selected))

    if high_count:
        today_core = f"중요도 높은 이슈가 {high_count}건 확인됐습니다. 우선 공시/재무/업황 영향을 확인하세요."
    elif price_count >= len(selected) / 2:
        today_core = "단순 주가·수급성 기사 비중이 높습니다. 제목보다 실제 원인과 공시 여부를 확인하는 편이 좋습니다."
    else:
        today_core = f"오늘 확인된 이슈는 {categories} 중심입니다."

    lines = [
        header,
        "",
        "오늘의 핵심",
        f"- {today_core}",
        "",
        "중요 기사",
    ]
    for index, article in enumerate(selected, start=1):
        lines.extend(
            [
                "",
                f"{index}. {article['title']}",
                f"- 분류: {article['category']} / 중요도: {importance_label(article['score'])}",
                f"- 효성화학 관련성: {relation_to_hyosung(article['title'])}",
                f"- 왜 봐야 하나: {article['reason']}",
                f"- 출처/날짜: {article['source']} / {article['published'] or '확인 필요'}",
                f"- 링크: {article['link']}",
            ]
        )
    lines.extend(
        [
            "",
            "오늘 체크할 것",
            "- 회사 공시, 신용등급, 차입/자금 조달 관련 새 소식",
            "- 화학 업황과 주요 제품 스프레드 변화",
            "- 단순 주가 기사라면 실제 원인이 따로 있는지",
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
