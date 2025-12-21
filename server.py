# -*- coding: utf-8 -*-
"""
server.py

ガソリンの給油量から、参照単価を使って請求金額を計算する
シンプルなWebアプリのサーバー部分です。

✔ Python（Flask）で動作
✔ HTMLテンプレート（templates/index.html）と連携
✔ gogo.gs の「全国のガソリン平均価格」→「レギュラー」を取得して計算
✔ 後でクラウド（Render等）に置けるように PORT 環境変数にも対応
"""

from flask import Flask, render_template, request, jsonify
import os

# ★ 追加：gogo.gs から単価を取得するためのライブラリ
import requests
from bs4 import BeautifulSoup
import re

# Flask アプリ本体を作成
app = Flask(__name__, template_folder="templates")

# ★ 変更：単価を掲載しているサイトのURL
REFERENCE_URL = "https://gogo.gs/ranking/average/"


def get_unit_price():
    """
    ガソリン1Lあたりの単価（円）を取得する関数。

    gogo.gs の「都道府県平均 ガソリン価格ランキング - レギュラー」
    ページから「全国のガソリン平均価格」→「レギュラー」の価格を
    スクレイピングして取得します。

    戻り値:
        float: レギュラーの単価（例: 162.2）

    取得できない場合は RuntimeError を投げます。
    """

    headers = {
        # ブラウザっぽい User-Agent を付けておく
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    # gogo.gs にアクセス
    res = requests.get(REFERENCE_URL, headers=headers, timeout=10)
    res.raise_for_status()  # 200 以外ならここで例外

    # HTML を解析
    soup = BeautifulSoup(res.text, "html.parser")

    # ページ全体のテキストを 1 行の文字列にまとめる
    # 例: "… 全国のガソリン平均価格 レギュラー 162.2 - 2.5 ハイオク 173.5 …"
    text = soup.get_text(" ", strip=True)

    # 「全国のガソリン平均価格 レギュラー 162.2 …」の 162.2 を抜き出す
    m = re.search(r"全国のガソリン平均価格\s*レギュラー\s*([\d.,]+)", text)

    if not m:
        # レイアウト変更などで見つからなかった場合
        raise RuntimeError("レギュラー価格が見つかりませんでした。サイト構成が変わった可能性があります。")

    price_str = m.group(1).replace(",", "")  # "162.2" → "162.2" / "1,234.5" → "1234.5"
    unit_price = float(price_str)

    return unit_price # 円/リットル


@app.route("/", methods=["GET"])
def index():
    """
    トップページ表示用（フォーム画面）。

    templates/index.html を表示します。
    単価だけ渡して、金額はまだ計算しない状態。
    """
    try:
        unit_price = get_unit_price()
        error_message = None
    except Exception as e:
        # 単価取得に失敗した場合でも画面自体は表示したい
        unit_price = None
        error_message = f"ガソリン価格の取得に失敗しました：{e}"

    return render_template(
        "index.html",
        unit_price=unit_price,   # 画面に表示する単価
        total_price=None,        # まだ計算前なので None
        liters=None,             # 入力値もまだなし
        error_message=error_message,
    )


@app.route("/calculate", methods=["POST"])
def calculate():
    """
    フォームから送信された給油量を使って請求金額を計算するルート。

    ・給油量（liters）を受け取る
    ・単価を取得（get_unit_price）
    ・金額 = 単価 × 給油量 を計算
    ・結果を index.html に渡して再表示
    """
    try:
        # フォームから文字列として取得
        liters_str = request.form.get("liters", "").strip()

        if liters_str == "":
            # 空欄だった場合
            raise ValueError("給油量が入力されていません。")

        # 数値（float）に変換
        liters = float(liters_str)

        if liters <= 0:
            # マイナスや0はNG
            raise ValueError("給油量は0より大きい数値を入力してください。")

        # ★ ここで gogo.gs から最新の単価を取得
        unit_price = get_unit_price()

        # 金額を計算（小数点は四捨五入して整数円に）
        total_price = int(round(liters * unit_price))

        # 結果を画面に表示（index.html を再利用）
        return render_template(
            "index.html",
            unit_price=unit_price,
            total_price=total_price,
            liters=liters,
            error_message=None,
        )

    except ValueError as e:
        # 入力ミスなどのわかりやすいエラー
        try:
            unit_price = get_unit_price()
        except Exception:
            unit_price = None
        return render_template(
            "index.html",
            unit_price=unit_price,
            total_price=None,
            liters=None,
            error_message=str(e),
        )

    except Exception as e:
        # 通信エラー・スクレイピング失敗など
        try:
            unit_price = get_unit_price()
        except Exception:
            unit_price = None
        return render_template(
            "index.html",
            unit_price=unit_price,
            total_price=None,
            liters=None,
            error_message=f"予期しないエラーが発生しました：{e}",
        )


@app.route("/api/price", methods=["GET"])
def api_price():
    """
    現在の単価を返すAPI（JSON）。

    フロント側のJavaScriptから使いたい場合用です。
    例：fetch('/api/price') で単価を取得。
    """
    try:
        unit_price = get_unit_price()
        return jsonify({"unit_price": unit_price})
    except Exception as e:
        return jsonify({"error": f"単価取得に失敗しました: {e}"}), 500


@app.route("/api/calculate", methods=["POST"])
def api_calculate():
    """
    JSONで給油量を受け取って金額を返すAPI。

    リクエスト例：
        POST /api/calculate
        Content-Type: application/json
        { "liters": 35 }

    レスポンス例：
        {
          "liters": 35.0,
          "unit_price": 172.5,
          "total_price": 6038
        }
    """
    data = request.get_json(silent=True) or {}
    liters = data.get("liters")

    # 入力チェック
    try:
        liters = float(liters)
        if liters <= 0:
            raise ValueError
    except Exception:
        return jsonify({"error": "liters は 0 より大きい数値を指定してください。"}), 400

    try:
        unit_price = get_unit_price()
    except Exception as e:
        return jsonify({"error": f"単価取得に失敗しました: {e}"}), 500

    total_price = int(round(liters * unit_price))

    return jsonify(
        {
            "liters": liters,
            "unit_price": unit_price,
            "total_price": total_price,
        }
    )


if __name__ == "__main__":
    """
    アプリを起動する部分。

    ・ローカルPCで起動するとき：
        python server.py
      → http://127.0.0.1:5050/ にアクセス

    ・将来Renderなどのクラウドに置くとき：
        そのサービス側が PORT という環境変数を渡してくるので、
        os.environ.get("PORT", 5050) で拾って使う。
    """
    # 環境変数 PORT が設定されていればそれを使い、なければ 5050 番を使う
    port = int(os.environ.get("PORT", 5050))

    # host="0.0.0.0" にすることで、同じネットワーク内のスマホなどからもアクセス可能
    app.run(host="0.0.0.0", port=port)
