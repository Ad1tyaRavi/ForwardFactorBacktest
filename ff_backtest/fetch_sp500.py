import pandas as pd
import requests

def get_sp500_tickers():
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'}
    response = requests.get(url, headers=headers)
    tables = pd.read_html(response.text)
    sp500_table = tables[0]
    tickers = sp500_table['Symbol'].tolist()
    return tickers

if __name__ == '__main__':
    tickers = get_sp500_tickers()
    df = pd.DataFrame(tickers, columns=['ticker'])
    df.to_csv('sp500_tickers.csv', index=False)