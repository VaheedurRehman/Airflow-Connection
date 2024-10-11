# -*- coding: utf-8 -*-
"""Airflow_Snowflake_Connection.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1U-Yh1fE6hCWhiLVGcFGTsNTqMdN15QCz
"""

from airflow import DAG
from airflow.models import Variable
from airflow.decorators import task
from airflow.providers.snowflake.hooks.snowflake import SnowflakeHook

from datetime import timedelta, datetime
import requests


def return_snowflake_conn():
    """
    Returns a Snowflake connection cursor using SnowflakeHook.
    """
    hook = SnowflakeHook(snowflake_conn_id='snowflake_conn')
    conn = hook.get_conn()
    return conn.cursor()


@task
def extract(symbol):
    """
    Extracts the last 90 days of stock data for a given symbol using Alpha Vantage API.
    """
    vantage_api_key = Variable.get("vantage_api_key")
    url = f'https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={symbol}&outputsize=compact&apikey={vantage_api_key}'

    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        result = []
        for day, values in list(data['Time Series (Daily)'].items())[:90]:
            values['date'] = day
            values['symbol'] = symbol
            result.append(values)
        return result
    else:
        raise ValueError(f"Failed to fetch data: {response.status_code}")


@task
def transform(records):
    """
    Transforms the raw stock data into a list of dictionaries (JSON-serializable).
    """
    stock_data_list = []
    for record in records:
        stock_data = {
            "symbol": record['symbol'],
            "date": record['date'],
            "open": float(record['1. open']),
            "high": float(record['2. high']),
            "low": float(record['3. low']),
            "close": float(record['4. close']),
            "volume": int(record['5. volume'])
        }
        stock_data_list.append(stock_data)
    return stock_data_list


@task
def load(cur, stock_data_list, target_table):
    """
    Loads the transformed stock data into Snowflake, performing a MERGE operation.
    """
    try:
        cur.execute("BEGIN;")

        # Create table if not exists
        cur.execute(f"""
            CREATE OR REPLACE TABLE {target_table} (
                symbol VARCHAR(5),
                date DATE,
                open FLOAT,
                high FLOAT,
                low FLOAT,
                close FLOAT,
                volume INT,
                PRIMARY KEY (symbol, date)
            );
        """)

        # Proper MERGE SQL query for Snowflake
        merge_query = f"""
        MERGE INTO {target_table} AS target
        USING (
            SELECT %s AS symbol, %s AS date, %s AS open, %s AS high, %s AS low, %s AS close, %s AS volume
        ) AS source
        ON target.symbol = source.symbol AND target.date = source.date
        WHEN MATCHED THEN UPDATE SET
            target.open = source.open,
            target.high = source.high,
            target.low = source.low,
            target.close = source.close,
            target.volume = source.volume
        WHEN NOT MATCHED THEN
            INSERT (symbol, date, open, high, low, close, volume)
            VALUES (source.symbol, source.date, source.open, source.high, source.low, source.close, source.volume);
        """

        # Execute the query for each stock data record
        for stock_data in stock_data_list:
            cur.execute(merge_query, (
                stock_data["symbol"],
                stock_data["date"],
                stock_data["open"],
                stock_data["high"],
                stock_data["low"],
                stock_data["close"],
                stock_data["volume"]
            ))

        cur.execute("COMMIT;")
        print(f"Inserted or updated {len(stock_data_list)} records into {target_table}.")
    except Exception as e:
        cur.execute("ROLLBACK;")
        print(e)
        raise e


# Define the DAG
with DAG(
    dag_id='stock_data_etl_v2',
    start_date=datetime(2024, 9, 21),
    catchup=False,
    tags=['ETL'],
    schedule_interval='30 2 * * *'
) as dag:

    # Fully qualified target table in Snowflake (database.schema.table)
    target_table = "HOMEWORK.AIRFLOW.TARGET_TABLE"  # Change to your actual Snowflake database/schema/table if necessary

    # Stock symbol to fetch
    symbol = "NVDA"

    # Snowflake cursor
    cur = return_snowflake_conn()

    # Define the ETL task flow
    stock_data = extract(symbol)
    transformed_data = transform(stock_data)
    load(cur, transformed_data, target_table)
