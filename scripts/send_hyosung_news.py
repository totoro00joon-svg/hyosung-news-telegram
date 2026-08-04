import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


QUERY = "효성화학 when:2d"
MAX_ITEMS = 5
HISTORY_PATH = Path("data/history.json")
MAX_HISTORY_RUNS = 14

CATEGORY_RULES = [
    (
        "공시/회사",
        5,
        ["공시", "유상증자", "전환사채", "채권", "매각", "인수", "합병", "분할", "소송"],
        "회사 의사결정",
    ),
    (
        "실적/재무",
        5,
        ["실적", "영업이익", "순손실", "매출", "부채", "차입", "자금", "재무", "신용등급", "유동성"],
        "재무 안정성",
    ),
    (
        "산업/업황",
        4,
        ["화학", "스프레드", "프로판", "pp", "폴리프로필렌", "반도체", "수소", "탄소섬유", "증설"],
        "사업 환경",
    ),
    (
        "증권/리포트",
        3,
        ["목표가", "투자의견", "리포트", "증권", "전망", "컨센서스", "추정"],
        "시장 기대치",
    ),
    (
        "주가/수급",
        1,
        ["상승", "하락", "급등", "급락", "강세", "약세", "특징주", "코스피"],
        "단기 수급",
    ),
]

DIRECT_KEYWORDS = ["효성화학"]
GROUP_KEYWORDS = ["효성", "조현준", "효성티앤씨", "효성첨단소재", "효성중공업"]
BUSINESS_KEYWORDS = ["화학", "프로판", "pp", "폴리프로필렌", "스프레드", "수소", "탄소섬유"]
RISK_KEYWORDS = ["신용등급", "차입", "채권", "부채", "자금", "유동성", "소송"]
PRICE_KEYWORDS = ["상승", "하락", "급등", "급락", "강세", "약세", "특징주"]


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


def has_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def signal_text(title: str) -> str:
    return title.replace("효성화학", "")


def classify_article(title: str) -> tuple[str, int, str]:
    title = signal_text(title)
    for category, score, keywords, signal in CATEGORY_RULES:
        if has_any(title, keywords):
            return category, score, signal
    return "일반", 2, "관련 언급"


def relation_profile(title: str) -> tuple[int, str, str]:
    if has_any(title, DIRECT_KEYWORDS):
        return 5, "직접", "효성화학이 제목에 직접 등장합니다."
    if has_any(title, GROUP_KEYWORDS):
        return 3, "그룹/계열", "효성그룹 전반의 투자심리와 계열 리스크를 통해 간접 연결됩니다."
    if has_any(title, RISK_KEYWORDS):
        return 1, "참고", "효성화학이 직접 언급되지 않은 재무·리스크 기사라 참고 강도로만 봅니다."
    if has_any(title, BUSINESS_KEYWORDS):
        return 1, "참고", "효성화학 직접 언급이 없는 업황 기사라 연결 강도는 낮습니다."
    if has_any(title, PRICE_KEYWORDS):
        return 2, "주가/수급", "가격 움직임 언급입니다. 원인 확인용으로만 보는 편이 좋습니다."
    return 1, "참고", "효성화학과의 연결 고리가 약할 수 있어 원문 확인이 필요합니다."


def issue_tags(title: str) -> list[str]:
    tags = []
    title_for_signals = signal_text(title)
    tag_rules = [
        ("재무", ["실적", "영업이익", "순손실", "부채", "차입", "자금", "유동성"]),
        ("신용", ["신용등급", "등급", "채권"]),
        ("업황", ["화학", "스프레드", "프로판", "pp", "폴리프로필렌"]),
        ("공시", ["공시", "유상증자", "전환사채", "매각", "인수", "합병", "분할"]),
        ("수급", PRICE_KEYWORDS),
        ("그룹", GROUP_KEYWORDS),
    ]
    for tag, keywords in tag_rules:
        if has_any(title_for_signals, keywords):
            tags.append(tag)
    if has_any(title, DIRECT_KEYWORDS):
        tags.append("직접")
    return tags or ["기타"]


def importance_label(score: int) -> str:
    if score >= 5:
        return "높음"
    if score >= 3:
        return "보통"
    return "낮음"


def load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {"runs": []}
    try:
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"runs": []}


def save_history(history: dict, articles: list[dict], now: datetime) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    run = {
        "date": now.strftime("%Y-%m-%d"),
        "title_keys": [article["key"] for article in articles],
        "categories": [article["category"] for article in articles],
        "tags": sorted({tag for article in articles for tag in article["tags"]}),
        "top_titles": [article["title"] for article in articles[:3]],
    }
    runs = [item for item in history.get("runs", []) if item.get("date") != run["date"]]
    runs.append(run)
    history["runs"] = runs[-MAX_HISTORY_RUNS:]
    HISTORY_PATH.write_text(
        json.dumps(history, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def previous_run(history: dict) -> dict | None:
    runs = history.get("runs", [])
    return runs[-1] if runs else None


def fetch_articles() -> list[dict]:
    root = ET.fromstring(fetch_google_news_rss(QUERY))
    seen_keys = set()
    articles = []

    for item in root.findall("./channel/item"):
        source = source_from_item(item)
        title = title_without_source(clean_text(item.findtext("title", "")), source)
        link = clean_text(item.findtext("link", ""))
        published = clean_text(item.findtext("pubDate", ""))
        if not title or not link:
            continue

        key = normalize_title(title)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        category, base_score, signal = classify_article(title)
        relation_score, relation_type, relation_reason = relation_profile(title)
        if relation_score < 3:
            continue
        tags = issue_tags(title)
        score = base_score + relation_score

        articles.append(
            {
                "title": title,
                "source": source,
                "published": published,
                "link": link,
                "key": key,
                "category": category,
                "signal": signal,
                "score": score,
                "importance": base_score,
                "relation_score": relation_score,
                "relation_type": relation_type,
                "relation_reason": relation_reason,
                "tags": tags,
                "is_price_only": has_any(title, PRICE_KEYWORDS) and base_score <= 1,
            }
        )

    articles.sort(key=lambda item: (item["score"], item["relation_score"], not item["is_price_only"]), reverse=True)
    return articles[:MAX_ITEMS]


def trend_sentence(articles: list[dict], prev: dict | None) -> str:
    direct_articles = [item for item in articles if item["relation_score"] >= 5]
    indirect_articles = [item for item in articles if item["relation_score"] < 5]
    direct_count = len(direct_articles)
    direct_high_count = sum(1 for item in direct_articles if item["importance"] >= 5)
    indirect_high_count = sum(1 for item in indirect_articles if item["importance"] >= 5)
    category_counts = Counter(item["category"] for item in articles)
    top_category = category_counts.most_common(1)[0][0]

    current_tags = {tag for item in articles for tag in item["tags"]}
    previous_tags = set(prev.get("tags", [])) if prev else set()
    new_tags = sorted(current_tags - previous_tags)

    if prev and new_tags:
        change = f"어제 기록 대비 새로 부각된 축은 {', '.join(new_tags[:3])}입니다."
    elif prev:
        change = "어제와 비교하면 새 주제보다 기존 이슈의 반복 확인에 가깝습니다."
    else:
        change = "첫 기록이라 전일 비교는 내일부터 더 선명해집니다."

    if direct_high_count:
        stance = "효성화학 직접 이슈 중 공시·재무성 신호가 있어 원문 확인 우선순위가 높습니다."
    elif direct_count and indirect_high_count:
        stance = "효성화학 직접 기사는 제한적이고, 오늘의 강한 신호는 계열사 실적·공시 쪽에 더 가깝습니다."
    elif top_category == "산업/업황":
        stance = "개별 이벤트보다 업황 변화가 효성화학 실적 기대를 흔드는지 보는 날입니다."
    elif direct_count == 0:
        stance = "직접 기사는 약하므로 효성화학과의 연결 강도를 낮춰 읽는 편이 좋습니다."
    else:
        stance = "직접 언급은 있으나 주가성 기사라면 원인과 지속성을 분리해서 봐야 합니다."

    return f"{stance} {change}"


def angle_lines(articles: list[dict]) -> list[str]:
    direct_articles = [item for item in articles if item["relation_score"] >= 5]
    indirect_articles = [item for item in articles if item["relation_score"] < 5]
    direct_tags = {tag for item in direct_articles for tag in item["tags"]}
    indirect_tags = {tag for item in indirect_articles for tag in item["tags"]}
    risk = {"재무", "신용", "공시"} & direct_tags
    indirect_risk = {"재무", "신용", "공시"} & indirect_tags
    business = {"업황"} & direct_tags
    indirect_business = {"업황"} & indirect_tags

    investment = (
        "직접 기사에 재무·공시 신호가 있어 주가 반응보다 원문 확인이 먼저입니다."
        if risk
        else "직접 기사는 있으나 강한 재무·공시 신호는 약합니다. 계열사 뉴스를 효성화학 이슈로 과대해석하지 마세요."
        if direct_articles
        else "직접 기사 비중이 낮아 효성화학 자체 이슈로 과대해석하지 않는 편이 좋습니다."
    )
    business_line = (
        "직접 기사 안에 업황 신호가 있어 제품 스프레드와 원재료 가격 방향을 같이 봐야 합니다."
        if business
        else "업황 신호는 계열/간접 기사 쪽에만 보입니다. 효성화학 제품군과 실제 연결되는지 확인하세요."
        if indirect_business
        else "사업환경 신호는 약합니다. 오늘은 개별 회사 이벤트 여부가 더 중요합니다."
    )
    risk_line = (
        f"직접 기사에서 {', '.join(sorted(risk))} 신호가 보입니다. 신용도와 자금 조달 관련 원문을 우선 확인하세요."
        if risk
        else f"{', '.join(sorted(indirect_risk))} 신호는 계열/간접 기사에 있습니다. 효성화학으로 전이될 사안인지 구분하세요."
        if indirect_risk
        else "리스크 신호는 두드러지지 않습니다. 단순 수급성 기사와 구분해 보세요."
    )

    return [
        f"- 투자: {investment}",
        f"- 사업: {business_line}",
        f"- 리스크: {risk_line}",
    ]


def article_insight(article: dict) -> str:
    if article["relation_score"] >= 5 and article["importance"] >= 5:
        return "직접 관련성과 중요도가 모두 높아 원문 확인 우선순위가 가장 높습니다."
    if article["relation_score"] >= 5:
        return "효성화학 직접 기사입니다. 기사 제목의 방향성이 실적·재무·업황 중 어디에 닿는지 원문에서 확인하세요."
    if article["relation_type"] == "사업환경":
        return "효성화학 실적에는 가격보다 스프레드 방향이 더 중요할 수 있습니다."
    if article["relation_type"] == "재무/리스크":
        return "주가보다 차입 여건과 신용도에 미치는 영향을 먼저 보세요."
    if article["is_price_only"]:
        return "가격 움직임 자체보다 원인이 새 정보인지 반복 보도인지 구분해야 합니다."
    if article["relation_type"] == "그룹/계열":
        return "효성화학 직접 이슈가 아니라면 계열 리스크 전이 가능성만 제한적으로 봅니다."
    return "효성화학과의 연결 고리가 약하면 참고 기사로 낮춰 보는 편이 좋습니다."


def build_digest() -> tuple[str, dict, list[dict], datetime]:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    history = load_history()
    prev = previous_run(history)
    articles = fetch_articles()

    header = f"[효성화학 모닝 인사이트] {now:%Y-%m-%d}"
    if not articles:
        return (
            f"{header}\n\n"
            "최근 24~48시간 내 효성화학 관련 주요 기사는 확인되지 않았습니다."
        ), history, articles, now

    current_keys = {article["key"] for article in articles}
    previous_keys = set(prev.get("title_keys", [])) if prev else set()
    new_article_count = len(current_keys - previous_keys)

    direct_articles = [article for article in articles if article["relation_score"] >= 5]
    indirect_articles = [article for article in articles if article["relation_score"] < 5]

    lines = [
        header,
        "",
        "오늘의 판단",
        f"- {trend_sentence(articles, prev)}",
        f"- 직접 관련: {sum(1 for article in articles if article['relation_score'] >= 5)}건 / 계열·간접 참고: {sum(1 for article in articles if article['relation_score'] < 5)}건",
        f"- 새로 잡힌 기사: {new_article_count}건 / 추적 기사: {len(articles) - new_article_count}건",
        "",
        "관점별 인사이트",
        *angle_lines(articles),
        "",
        "핵심 기사",
    ]

    if direct_articles:
        lines.extend(["", "직접 관련"])
    for index, article in enumerate(direct_articles, start=1):
        lines.extend(
            [
                "",
                f"{index}. {article['title']}",
                f"- 관련성: {article['relation_type']} {article['relation_score']}/5 - {article['relation_reason']}",
                f"- 분류/중요도: {article['category']} / {importance_label(article['importance'])}",
                f"- 읽는 포인트: {article_insight(article)}",
                f"- 출처/날짜: {article['source']} / {article['published'] or '확인 필요'}",
                f"- 링크: {article['link']}",
            ]
        )

    if indirect_articles:
        lines.extend(["", "계열/간접 참고"])
    for index, article in enumerate(indirect_articles, start=1):
        lines.extend(
            [
                "",
                f"{index}. {article['title']}",
                f"- 관련성: {article['relation_type']} {article['relation_score']}/5 - {article['relation_reason']}",
                f"- 분류/중요도: {article['category']} / {importance_label(article['importance'])}",
                f"- 읽는 포인트: {article_insight(article)}",
                f"- 출처/날짜: {article['source']} / {article['published'] or '확인 필요'}",
                f"- 링크: {article['link']}",
            ]
        )

    lines.extend(
        [
            "",
            "오늘 확인할 것",
            "- 직접 공시나 신용등급 변화가 있는지",
            "- 업황 기사라면 효성화학 제품과 실제로 연결되는지",
            "- 주가성 기사라면 새 정보인지 단순 반복인지",
        ]
    )

    return "\n".join(lines), history, articles, now


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
        digest, history, articles, now = build_digest()
        if os.environ.get("DRY_RUN") == "1":
            print(digest)
        else:
            send_telegram_message(digest)
            save_history(history, articles, now)
        return 0
    except Exception as exc:
        print(f"Failed to send digest: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
