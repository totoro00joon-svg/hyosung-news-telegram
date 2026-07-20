# 효성화학 텔레그램 뉴스 알림

GitHub Actions가 매일 한국시간 오전 7시 50분에 효성화학 관련 최근 뉴스를 찾아 텔레그램 개인 채팅으로 보냅니다.

## 설정 방법

1. GitHub에서 새 저장소를 만듭니다.
2. 이 폴더 안의 파일을 그대로 업로드합니다.
3. 저장소 화면에서 `Settings` > `Secrets and variables` > `Actions`로 갑니다.
4. `New repository secret`을 눌러 아래 2개를 추가합니다.

| Name | Value |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | BotFather가 준 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 받을 개인 채팅 ID |

5. `Actions` 탭에서 `Hyosung Chemical Telegram News`를 선택합니다.
6. `Run workflow`를 눌러 테스트 발송합니다.

## 예약 시간

GitHub Actions 예약은 UTC 기준이라서, 한국시간 오전 7시 50분은 아래처럼 설정되어 있습니다.

```yaml
cron: "50 22 * * *"
```

## 참고

- GitHub Actions 무료 계정에서도 보통 이 정도 자동화는 비용 없이 쓸 수 있습니다.
- 공개 저장소에 봇 토큰을 직접 올리면 안 됩니다. 반드시 GitHub Secrets에 넣으세요.
- GitHub Actions 예약 실행은 몇 분 늦게 시작될 수 있습니다.
