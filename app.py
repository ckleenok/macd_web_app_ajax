from flask import Flask, render_template, request, jsonify
import pandas as pd
import threading
import requests
from bs4 import BeautifulSoup
import os

app = Flask(__name__)

progress = {
    "total": 0,
    "current": 0,
    "done": False
}

result_df = None  # 전역 결과 변수 초기화

def get_company_name_naver(ticker):
    try:
        url = f"https://finance.naver.com/item/main.nhn?code={ticker}"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, "html.parser")
        return soup.select_one("div.wrap_company h2").text.strip()
    except:
        return "Unknown"

def get_stock_data_naver(ticker):
    try:
        url = f"https://finance.naver.com/item/sise_day.nhn?code={ticker}"
        headers = {"User-Agent": "Mozilla/5.0"}
        all_data = []

        for page in range(1, 20):
            response = requests.get(f"{url}&page={page}", headers=headers)
            soup = BeautifulSoup(response.text, "html.parser")
            rows = soup.select("table.type2 tr")

            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 7:
                    continue
                date = cols[0].text.strip()
                close_price = cols[1].text.strip().replace(",", "")
                if date and close_price:
                    try:
                        all_data.append([ticker, pd.to_datetime(date), float(close_price)])
                    except:
                        continue

        df = pd.DataFrame(all_data, columns=["Ticker", "Date", "Close"])
        df.sort_values(by="Date", inplace=True)
        return df
    except:
        return pd.DataFrame()

def run_analysis(tickers):
    global result_df
    result_df = None
    progress["done"] = False

    results = []
    date_columns = []

    total = len(tickers)
    progress["total"] = total
    progress["current"] = 0

    for idx, ticker in enumerate(tickers, 1):
        progress["current"] = idx
        df = get_stock_data_naver(ticker)
        company = get_company_name_naver(ticker)
        if df.empty or len(df) < 35:
            continue

        df["EMA_12"] = df["Close"].ewm(span=12, adjust=False).mean()
        df["EMA_26"] = df["Close"].ewm(span=26, adjust=False).mean()
        df["MACD"] = df["EMA_12"] - df["EMA_26"]
        df["Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
        df["MACD_Gap"] = df["MACD"] - df["Signal"]

        macd_min, macd_max = df["MACD_Gap"].min(), df["MACD_Gap"].max()
        df["MACD_Normalized"] = (df["MACD_Gap"] - macd_min) / (macd_max - macd_min) * 200 - 100

        last_5 = df[["Date", "MACD_Normalized"]].dropna().tail(5).reset_index(drop=True)
        if len(last_5) < 5:
            continue

        if not date_columns:
            date_columns = [dt.strftime('%d-%b-%Y') for dt in last_5["Date"]]

        results.append({
            "Ticker": ticker,
            date_columns[0]: round(last_5.loc[0, "MACD_Normalized"], 2),
            date_columns[1]: round(last_5.loc[1, "MACD_Normalized"], 2),
            date_columns[2]: round(last_5.loc[2, "MACD_Normalized"], 2),
            date_columns[3]: round(last_5.loc[3, "MACD_Normalized"], 2),
            date_columns[4]: round(last_5.loc[4, "MACD_Normalized"], 2),
            "Company Name": company
        })

    if not results:
        return None, []

    df = pd.DataFrame(results)
    latest_date = date_columns[-1]
    df.sort_values(by=latest_date, ascending=True, inplace=True)
    result_df = df
    progress["done"] = True
    return df, date_columns

@app.route('/', methods=['GET'])
def upload():
    return render_template('upload.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    file = request.files['file']
    if file:
        tickers = file.read().decode('utf-8').splitlines()
        tickers = list(set([t.strip() for t in tickers if t.strip()]))

        def run_thread():
            run_analysis(tickers)

        thread = threading.Thread(target=run_thread)
        thread.start()

        return jsonify({"status": "processing", "total": len(tickers)})
    return jsonify({"error": "파일을 찾을 수 없습니다."}), 400

@app.route('/progress')
def get_progress():
    return jsonify(progress)

@app.route('/result')
def get_result():
    global result_df
    if result_df is not None:
        return render_template('result.html', table=result_df.to_html(index=False))
    return render_template('result.html', error="결과를 가져올 수 없습니다.")

if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False)

