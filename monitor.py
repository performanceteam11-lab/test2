"""
네이버 쇼핑 검색 광고 모니터링
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
광고 순위  : Playwright (가격비교·N플러스 지면, PC/MO)
오가닉 순위: 네이버 쇼핑 API (100위 내, PC·MO 공통)
"""

import asyncio, json, re, sys, random, argparse
import urllib.request, urllib.parse
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import Stealth

sys.stdout.reconfigure(encoding='utf-8')

BASE_DIR     = Path(__file__).parent
EXCEL_FILE   = BASE_DIR / "쇼핑검색 키워드.xlsx"
KEYWORDS_FILE = BASE_DIR / "keywords.txt"
RESULTS_DIR  = BASE_DIR / "results"
DASHBOARD_FILE = BASE_DIR / "dashboard.html"

TARGET_SELLER   = "샤크닌자 코리아"
try:
    from config import API_CLIENT_ID, API_CLIENT_SECRET
except ImportError:
    API_CLIENT_ID   = ""
    API_CLIENT_SECRET = ""

RESULTS_DIR.mkdir(exist_ok=True)

# 지면 한글명 매핑
SECTION_LABEL = {
    "shopping": "가격비교",
    "nstore"  : "N플러스",
    "organic" : "오가닉",
}


# ──────────────────────────────────────────────
# 키워드 로드
# ──────────────────────────────────────────────
def load_keywords() -> list:
    if EXCEL_FILE.exists():
        try:
            import openpyxl
            wb = openpyxl.load_workbook(EXCEL_FILE)
            ws = wb.active
            kws = [str(r[0]).strip() for r in ws.iter_rows(values_only=True) if r[0]]
            print(f"[키워드] '{EXCEL_FILE.name}' → {len(kws)}개 로드")
            return kws
        except Exception as e:
            print(f"[경고] 엑셀 읽기 실패: {e}")
    if not KEYWORDS_FILE.exists():
        print(f"[오류] keywords.txt 없음"); sys.exit(1)
    kws = [l.strip() for l in KEYWORDS_FILE.read_text("utf-8").splitlines()
           if l.strip() and not l.startswith("#")]
    print(f"[키워드] keywords.txt → {len(kws)}개 로드")
    return kws


# ──────────────────────────────────────────────
# [A] 네이버 API → 오가닉 순위
# ──────────────────────────────────────────────
def api_organic(keyword: str, display: int = 100) -> list:
    """네이버 쇼핑 API로 오가닉 검색 순위 조회"""
    try:
        encoded = urllib.parse.quote(keyword)
        url = (f"https://openapi.naver.com/v1/search/shop.json"
               f"?query={encoded}&display={display}&sort=sim")
        req = urllib.request.Request(url)
        req.add_header("X-Naver-Client-Id", API_CLIENT_ID)
        req.add_header("X-Naver-Client-Secret", API_CLIENT_SECRET)
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode("utf-8"))

        results = []
        for i, item in enumerate(data.get("items", []), 1):
            if item.get("mallName") != TARGET_SELLER:
                continue
            name = re.sub(r'<[^>]+>', '', item.get("title", ""))
            price = int(item.get("lprice", 0) or 0)
            results.append(build_row(
                keyword=keyword,
                platform="공통",
                section="organic",
                rank=i,
                product_name=name,
                is_ad=False,
                ad_type="오가닉",
                price=price,
            ))
        return results
    except Exception as e:
        print(f"  [API] '{keyword}' 오류: {e}")
        return []


# ──────────────────────────────────────────────
# [B] Playwright → 광고 순위 (_INITIAL_STATE JSON)
# ──────────────────────────────────────────────
def parse_initial_state(html: str, section: str):
    pat = rf'naver\.search\.ext\.newshopping\["{re.escape(section)}"\]\._INITIAL_STATE\s*=\s*([\s\S]+?)\s*\n\s*naver\.search\.ext'
    m = re.search(pat, html)
    if not m:
        return None
    raw = re.sub(r'new Date\("([^"]+)"\)', r'"\1"', m.group(1).strip().rstrip(';'))
    raw = re.sub(r'\bundefined\b', 'null', raw)
    try:
        return json.loads(raw)
    except:
        return None


def extract_from_state(state, keyword, platform, section) -> list:
    if not state:
        return []
    items = []
    if section == "shopping":
        for ps in state.get("initProps", {}).get("pagedSlot", []):
            items.extend([s.get("data", {}) for s in ps.get("slots", []) if s.get("data")])
    else:
        items = state.get("initProps", {}).get("products", [])

    results = []
    for idx, item in enumerate(items, 1):
        if item.get("mallName") != TARGET_SELLER:
            continue
        rank = item.get("rank") or idx
        name = re.sub(r'<[^>]+>', '', item.get("productName", "") or item.get("standardProductName", ""))
        price = item.get("discountedSalePrice") or item.get("salePrice") or 0
        is_ad = item.get("cardType") == "AD_CARD"
        results.append(build_row(
            keyword=keyword,
            platform=platform,
            section=section,
            rank=rank,
            product_name=name[:100],
            is_ad=is_ad,
            ad_type="광고" if is_ad else "일반",
            price=price,
        ))
    return results


def build_row(keyword, platform, section, rank, product_name, is_ad, ad_type, price) -> dict:
    return {
        "keyword"     : keyword,
        "platform"    : platform,
        "section"     : section,
        "section_label": SECTION_LABEL.get(section, section),
        "rank"        : rank,
        "product_name": product_name,
        "seller"      : TARGET_SELLER,
        "is_ad"       : is_ad,
        "ad_type"     : ad_type,
        "price"       : price,
        "price_str"   : f"{price:,}원" if price else "",
    }


# ──────────────────────────────────────────────
# 브라우저 세팅
# ──────────────────────────────────────────────
async def make_browser(pw, is_mobile=False):
    browser = await pw.chromium.launch(
        headless=False,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
              "--disable-infobars", "--lang=ko-KR"],
    )
    if is_mobile:
        ctx = await browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=(
                "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.6367.82 Mobile Safari/537.36"
            ),
            device_scale_factor=3, is_mobile=True, has_touch=True,
            locale="ko-KR", timezone_id="Asia/Seoul",
        )
    else:
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ko-KR", timezone_id="Asia/Seoul",
        )
    return browser, ctx


async def init_page(ctx, stealth, is_mobile=False):
    page = await ctx.new_page()
    await stealth.apply_stealth_async(page)
    label = "[MO]" if is_mobile else "[PC]"
    print(f"  {label} 네이버 메인 방문 (세션 획득)...")
    await page.goto("https://www.naver.com", wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_timeout(random.randint(1200, 2000))
    return page


def _is_blocked(body_text: str) -> bool:
    return any(m in body_text for m in ["접속이 일시적으로 제한", "비정상적인 접근이 감지", "로봇이 아님을 확인"])


async def search_pw(page, keyword: str, platform: str) -> list:
    encoded = urllib.parse.quote(keyword)
    where = "m_shopping" if platform == "MO" else "shopping"
    url = f"https://search.naver.com/search.naver?where={where}&query={encoded}"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(random.randint(1800, 2800))
        body = await page.evaluate("document.body.innerText")
        if _is_blocked(body):
            print(f"  [{platform}] '{keyword}' ⛔ 차단"); return []
        html = await page.content()
        results = []
        for sec in ("shopping", "nstore"):
            state = parse_initial_state(html, sec)
            results.extend(extract_from_state(state, keyword, platform, sec))
        return results
    except PlaywrightTimeoutError:
        print(f"  [{platform}] '{keyword}' 타임아웃"); return []
    except Exception as e:
        print(f"  [{platform}] '{keyword}' 오류: {e}"); return []


# ──────────────────────────────────────────────
# 결과 출력 (표 형식)
# ──────────────────────────────────────────────
def print_results(keyword: str, rows: list):
    if not rows:
        print(f"  → {TARGET_SELLER} 노출 없음")
        return
    print(f"\n  {'지면':<8} {'플랫폼':<6} {'순위':>4}  {'구분':<6}  상품명")
    print(f"  {'-'*65}")
    for r in rows:
        ad = r["ad_type"]
        sec = r["section_label"]
        plat = r["platform"]
        name = r["product_name"][:40]
        print(f"  {sec:<8} {plat:<6} {r['rank']:>3}위  {ad:<6}  {name}")


# ──────────────────────────────────────────────
# 메인 모니터링
# ──────────────────────────────────────────────
async def run_monitoring(limit: int = 0, keyword_filter: list = None):
    keywords = load_keywords()
    if keyword_filter:
        keywords = [k for k in keywords if k in keyword_filter]
    if limit and limit > 0:
        keywords = keywords[:limit]
        print(f"[제한] 처음 {limit}개만 실행")

    timestamp = datetime.now()
    ts_str = timestamp.strftime("%Y%m%d_%H%M%S")

    print(f"\n{'='*60}")
    print(f"  네이버 쇼핑 광고 모니터링")
    print(f"  시각: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  키워드: {len(keywords)}개  |  대상: {TARGET_SELLER}")
    print(f"{'='*60}\n")

    all_results = []
    stealth = Stealth(navigator_webdriver=True)

    async with async_playwright() as pw:
        browser_pc, ctx_pc = await make_browser(pw, is_mobile=False)
        page_pc = await init_page(ctx_pc, stealth, False)
        browser_mo, ctx_mo = await make_browser(pw, is_mobile=True)
        page_mo = await init_page(ctx_mo, stealth, True)

        for i, kw in enumerate(keywords, 1):
            print(f"\n[{i}/{len(keywords)}] 키워드: '{kw}'")

            # Playwright: PC
            pc_rows = await search_pw(page_pc, kw, "PC")
            # Playwright: MO
            mo_rows = await search_pw(page_mo, kw, "MO")
            # API: 오가닉
            organic_rows = api_organic(kw, display=100)

            combined = pc_rows + mo_rows + organic_rows
            all_results.extend(combined)
            print_results(kw, combined)

            await asyncio.sleep(random.uniform(1.0, 2.0))

        await browser_pc.close()
        await browser_mo.close()

    # JSON 저장
    output = {
        "timestamp": timestamp.isoformat(),
        "target_seller": TARGET_SELLER,
        "keywords": keywords,
        "results": all_results,
    }
    result_file = RESULTS_DIR / f"result_{ts_str}.json"
    result_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTS_DIR / "latest.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    ad_cnt = sum(1 for r in all_results if r["is_ad"])
    org_cnt = sum(1 for r in all_results if r["ad_type"] == "오가닉")

    print(f"\n{'='*60}")
    print(f"  완료! → {result_file}")
    print(f"  광고 노출: {ad_cnt}건  |  오가닉 노출: {org_cnt}건")
    print(f"{'='*60}\n")

    update_dashboard(all_results, timestamp, keywords)
    return all_results


# ──────────────────────────────────────────────
# 대시보드 업데이트
# ──────────────────────────────────────────────
def update_dashboard(results: list, timestamp: datetime, keywords: list):
    if not DASHBOARD_FILE.exists():
        print("  [경고] dashboard.html 없음"); return

    # keyword → { PC:[], MO:[], organic:[] }
    summary = {kw: {"PC": [], "MO": [], "organic": []} for kw in keywords}
    for r in results:
        kw = r["keyword"]
        if kw not in summary:
            summary[kw] = {"PC": [], "MO": [], "organic": []}
        if r["platform"] == "공통":
            summary[kw]["organic"].append(r)
        else:
            summary[kw][r["platform"]].append(r)

    data = {
        "timestamp"    : timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "target_seller": TARGET_SELLER,
        "keywords"     : keywords,
        "summary"      : summary,
        "results"      : results,
    }
    html = DASHBOARD_FILE.read_text(encoding="utf-8")
    new_data_str = f"const MONITOR_DATA = {json.dumps(data, ensure_ascii=False)};"
    updated = re.sub(
        r"const MONITOR_DATA\s*=\s*.*;",
        new_data_str,
        html,
    )
    DASHBOARD_FILE.write_text(updated, encoding="utf-8")
    print(f"  대시보드 업데이트 완료: {DASHBOARD_FILE}")
    _git_push(data["timestamp"])


def _git_push(timestamp: str):
    """dashboard.html 변경사항을 GitHub에 자동 push"""
    import subprocess
    try:
        base = str(BASE_DIR)
        subprocess.run(["git", "-C", base, "add", "dashboard.html"], check=True)
        result = subprocess.run(
            ["git", "-C", base, "diff", "--cached", "--quiet"],
            capture_output=True
        )
        if result.returncode == 0:
            print("  [git] 변경사항 없음, push 생략")
            return
        subprocess.run(
            ["git", "-C", base, "commit", "-m", f"data: {timestamp} 모니터링 결과 업데이트"],
            check=True
        )
        subprocess.run(["git", "-C", base, "push"], check=True)
        print("  [git] GitHub push 완료")
    except Exception as e:
        print(f"  [git] push 실패 (수동으로 push 필요): {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="네이버 쇼핑 광고 모니터링")
    parser.add_argument("--limit", type=int, default=0, help="처음 N개만 실행")
    parser.add_argument("--keywords", nargs="+", help="특정 키워드 지정")
    args = parser.parse_args()
    asyncio.run(run_monitoring(limit=args.limit, keyword_filter=args.keywords))
