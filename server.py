from flask import Flask, render_template, request, Response
import re
import requests
from functools import wraps
import os

app = Flask(__name__)

# 参照URL（ここだけを参照）
URL = "https://gogo.gs/ranking/average/"

FUEL_LABELS = {
    "regular": "レギュラー",
    "highoctane": "ハイオク",
    "diesel": "軽油",
}

RANGE = {
    "regular": (80.0, 300.0),
    "highoctane": (80.0, 350.0),
    "diesel": (60.0, 300.0),
}

def require_basic_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # ローカル開発中はバイパスできる（RenderではOFFにする）
        if os.environ.get("DEV_BYPASS_AUTH") == "1":
            return f(*args, **kwargs)

        user = os.environ.get("BASIC_USER", "")
        pw = os.environ.get("BASIC_PASS", "")
        # 未設定なら安全側で拒否
        if not user or not pw:
            return Response(
                "Auth not configured", 401,
                {"WWW-Authenticate": 'Basic realm="Login Required"'}
            )

        auth = request.authorization
        if not auth or auth.username != user or auth.password != pw:
            return Response(
                "Authentication required", 401,
                {"WWW-Authenticate": 'Basic realm="Login Required"'}
            )
        return f(*args, **kwargs)
    return decorated


def _nearby_candidates(html: str, label: str, key: str) -> list[float]:
    lo, hi = RANGE[key]
    num_pat = r"(\d{2,3}\.\d)"
    candidates: list[float] = []

    m = re.findall(label + r"[\s\S]{0,450}?" + num_pat, html)
    for x in m:
        p = float(x)
        if lo <= p <= hi:
            candidates.append(p)

    rows = re.findall(r"<tr[\s\S]*?</tr>", html, flags=re.IGNORECASE)
    for row in rows:
        if label in row:
            m2 = re.findall(num_pat, row)
            for x in m2:
                p = float(x)
                if lo <= p <= hi:
                    candidates.append(p)

    idx = html.find(label)
    if idx != -1:
        window = html[max(0, idx - 800): idx + 3500]
        m3 = re.findall(num_pat, window)
        for x in m3:
            p = float(x)
            if lo <= p <= hi:
                candidates.append(p)

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

    high = cand["highoctane"][0] if cand["highoctane"] else None
    diesel = cand["diesel"][0] if cand["diesel"] else None

    reg = None
    reg_cand = cand["regular"]
    if reg_cand:
        if high is not None and diesel is not None:
            between = [p for p in reg_cand if diesel < p < high]
            reg = min(between) if between else min(reg_cand)
        else:
            reg = min(reg_cand)

    prices = {"regular": reg, "highoctane": high, "diesel": diesel}
    return prices


@app.route("/", methods=["GET", "POST"])
@require_basic_auth
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
