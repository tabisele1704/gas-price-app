from flask import Flask, render_template, request
import re
import requests

app = Flask(__name__)

# 参照URL（ここだけを参照）
URL = "https://gogo.gs/ranking/average/"

FUEL_LABELS = {
    "regular": "レギュラー",
    "highoctane": "ハイオク",
    "diesel": "軽油",
}

# 現実的な価格レンジ（誤爆防止）
RANGE = {
    "regular": (80.0, 300.0),
    "highoctane": (80.0, 350.0),
    "diesel": (60.0, 300.0),
}


def _nearby_candidates(html: str, label: str, key: str) -> list[float]:
    """
    label（例：レギュラー）の近傍から、小数1桁の数値候補を複数拾う。
    ※「円」という文字に依存しない（タグ分割に強い）
    """
    lo, hi = RANGE[key]

    # gogo.gs の価格表記は「xxx.x」が多いので小数1桁を狙う（誤爆が減る）
    num_pat = r"(\d{2,3}\.\d)"

    candidates: list[float] = []

    # 1) label直後の短い範囲（強い）
    m = re.findall(label + r"[\s\S]{0,450}?" + num_pat, html)
    for x in m:
        p = float(x)
        if lo <= p <= hi:
            candidates.append(p)

    # 2) <tr>行内（表なら強い）
    rows = re.findall(r"<tr[\s\S]*?</tr>", html, flags=re.IGNORECASE)
    for row in rows:
        if label in row:
            m2 = re.findall(num_pat, row)
            for x in m2:
                p = float(x)
                if lo <= p <= hi:
                    candidates.append(p)

    # 3) label周辺の広めウィンドウ（保険）
    idx = html.find(label)
    if idx != -1:
        window = html[max(0, idx - 800): idx + 3500]
        m3 = re.findall(num_pat, window)
        for x in m3:
            p = float(x)
            if lo <= p <= hi:
                candidates.append(p)

    # 重複除去（順序維持）
    seen = set()
    uniq = []
    for p in candidates:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def fetch_prices_from_url() -> dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }

    r = requests.get(URL, headers=headers, timeout=20)
    r.raise_for_status()
    html = r.text

    cand = {k: _nearby_candidates(html, label, k) for k, label in FUEL_LABELS.items()}

    # まず、合っていることが多い “先頭候補” を採用
    high = cand["highoctane"][0] if cand["highoctane"] else None
    diesel = cand["diesel"][0] if cand["diesel"] else None

    # レギュラーは誤爆しやすいので整合性で選ぶ
    reg = None
    reg_cand = cand["regular"]

    if reg_cand:
        if high is not None and diesel is not None:
            # 軽油 < レギュラー < ハイオク の間に入る候補を優先
            between = [p for p in reg_cand if diesel < p < high]
            if between:
                # between の中で「最小」を採用（誤爆で高すぎる値を避けやすい）
                reg = min(between)
            else:
                # 間に入らないなら「最小」を採用（202みたいな異常高値より低いほうを選ぶ）
                reg = min(reg_cand)
        else:
            reg = min(reg_cand)

    prices = {"regular": reg, "highoctane": high, "diesel": diesel}

    # もし取得できなかった燃料があるなら、原因調査用に候補をログへ
    if any(v is None for v in prices.values()):
        print("PRICE_FETCH_FAILED")
        print("STATUS:", r.status_code, "CONTENT_TYPE:", r.headers.get("Content-Type"))
        print("CANDIDATES:", cand)
        print("HEAD_400:\n", html[:400])

    return prices


@app.route("/", methods=["GET", "POST"])
def index():
    error = None
    try:
        prices = fetch_prices_from_url()
    except Exception as e:
        prices = {k: None for k in FUEL_LABELS.keys()}
        error = f"単価取得エラー: {e}"

    fuel_key = request.form.get("fuel", "regular") if request.method == "POST" else "regular"
    fuel_label = FUEL_LABELS.get(fuel_key, "レギュラー")
    unit_price = prices.get(fuel_key)

    liters = None
    total = None
    formatted_total = None

    if request.method == "POST":
        try:
            liters = float(request.form.get("liters", "").strip())
            if unit_price is None:
                error = (error + " / " if error else "") + f"{fuel_label}の単価を取得できませんでした"
            else:
                total = round(liters * unit_price, 2)
                formatted_total = f"{total:,.0f}"
        except Exception:
            error = "給油量（L）の入力が正しくありません"

    return render_template(
        "index.html",
        title="燃料計算表",
        prices=prices,
        fuel_key=fuel_key,
        fuel_label=fuel_label,
        unit_price=unit_price,
        liters=liters,
        total=total,
        formatted_total=formatted_total,
        error=error
    )


if __name__ == "__main__":
    app.run(debug=True)
