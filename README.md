# 샤크닌자 코리아 · 네이버 쇼핑 모니터링

네이버 쇼핑 검색에서 **샤크닌자 코리아** 상품의 광고 및 오가닉 노출 순위를 자동으로 수집하여 대시보드로 시각화합니다.

## 대시보드 보기

👉 **[라이브 대시보드](https://performanceteam11-lab.github.io/test2/dashboard.html)**

> 매일 오전 9:30에 자동 업데이트됩니다.

---

## 수집 데이터

| 지면 | 수집 방법 | 범위 |
|------|----------|------|
| 가격비교 | Playwright (PC/MO) | 상위 8위 이내 |
| N플러스 | Playwright (PC/MO) | 노출 섹션 전체 |
| 오가닉 | 네이버 쇼핑 API | 100위 이내 |

- 모니터링 키워드: **124개**
- 대상 셀러: 샤크닌자 코리아

---

## 로컬 실행

```bash
# 의존성 설치
pip install -r requirements.txt
playwright install chromium

# 전체 키워드 실행
python monitor.py

# 특정 키워드만 테스트
python monitor.py --keywords 샤크무선청소기 샤크청소기
```

> `config.py`에 네이버 쇼핑 API 키를 입력해야 오가닉 순위가 수집됩니다.
