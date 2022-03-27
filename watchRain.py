#!/usr/bin/env python3
# encoding: utf-8

import logging
import argparse

import configparser
import datetime
import sys
import os.path
import json

import urllib.request
import urllib.parse
import sqlite3
import subprocess

from pprint import pprint, pformat

class YOLP_Weather:
    def __init__ (self, appid = None, coordinates = None):
        self._api_url = urllib.parse.urlparse ('https://map.yahooapis.jp/weather/V1/place')
        self._appid = appid
        self._coordinates = coordinates

    def get (self):
        params = {
                'appid': self._appid,
                'coordinates': self._coordinates,
                'output': 'json',
                }
        url = urllib.parse.urlunparse ( (
                    self._api_url.scheme,
                    self._api_url.netloc,
                    self._api_url.path,
                    self._api_url.params,
                    urllib.parse.urlencode (params),
                    self._api_url.fragment,
                    ) )
        ret = urllib.request.urlopen (url)
        return json.load (ret) 

class Weather_DB:
    @staticmethod
    def rain_severity (rainfall):
        if rainfall <= 0:
            return 0
        elif rainfall <= 10:
            return 10
        elif rainfall <= 20:
            return 20
        elif rainfall <= 30:
            return 30
        elif rainfall <= 50:
            return 40
        elif rainfall <= 80:
            return 50
        else:
            return 60

    def __init__ (self, db):
        self.db = sqlite3.connect (db,
                detect_types = sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
                )
        self.db.row_factory = sqlite3.Row
        self.db.create_function ('rain_severity', 1, self.rain_severity, deterministic = True)

        cur = self.db.cursor()
        cur.executescript ("""
            CREATE TABLE IF NOT EXISTS Requests (
                id          INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                timestamp   TIMESTAMP DEFAULT( DATETIME('now', 'localtime') ),
                apiid       TEXT,
                coordinates TEXT,
                areacode    INTEGER

            );
            CREATE TABLE IF NOT EXISTS Weathers (
                id          INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                request     INTEGER NOT NULL REFERENCES Requests (id),
                type        TEXT,
                date        TIMESTAMP,
                rainfall    REAL
            );
            CREATE TABLE IF NOT EXISTS Alerts (
                id          INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                timestamp   TIMESTAMP DEFAULT( DATETIME('now', 'localtime') ),
                cause       INTEGER REFERENCES Weather (id),
                severity    INTEGER DEFAULT 0
            );
        """)
        self.db.commit()

    def register_yolpweather (self, ret):
        cur = self.db.cursor()

        for feature in ret['Feature']:
            cur.execute (
                    'INSERT INTO Requests (apiid, coordinates, areacode) VALUES (?,?,?);', [
                        feature['Id'],
                        feature['Geometry']['Coordinates'],
                        feature['Property']['WeatherAreaCode'],
                        ] )
            request_id = cur.lastrowid
            for weather in feature['Property']['WeatherList']['Weather']:
                cur.execute (
                        'INSERT INTO Weathers (request, type, date, rainfall) VALUES (?,?,?,?);', [
                            request_id,
                            weather['Type'],
                            datetime.datetime.strptime (weather['Date'], '%Y%m%d%H%M'),
                            weather['Rainfall'],
                            ] )
        self.db.commit()

    def pop_alert (self):
        ret = list()
        r = self.pop_alert_observation()
        if r is not None:
            ret.append (r)
        r = self.pop_alert_forecast()
        if r is not None:
            ret.append (r)
        return ret

    def pop_alert_observation (self):
        """
        ・最新の実測シビリティが1つ前の実測シビリティより高い
        ・現在有効なアラートが存在しない
        場合、アラートを出す。
        これは、予報なく急に実測で雨が降ってきたときに備えたアラートである。
        """
        cur = self.db.cursor()
        cur.execute ("""
            SELECT
                *,
                rain_severity(rainfall) AS rainseverity
            FROM Weathers
            WHERE
                -- 最新の実測シビリティであり、かつ、
                date = (
                    -- 最新の実測のdate
                    SELECT max(date)
                    FROM Weathers
                    WHERE type = 'observation'
                ) AND
                -- 実測であり、かつ、
                type = 'observation' AND
                -- 1つ前の実測シビリティより高い、かつ、
                rainseverity > ifnull( (
                    -- 1つ前の実測シビリティ
                    SELECT rain_severity(rainfall)
                    FROM Weathers
                    WHERE type = 'observation'
                    ORDER BY date DESC
                    LIMIT 1 OFFSET 1
                ), 0) AND
                -- 現在有効なアラートが存在しない
                (
                    -- 現在有効なアラート
                    SELECT count(*)
                    FROM Alerts LEFT JOIN Weathers ON Alerts.cause = Weathers.id
                    WHERE date > datetime('now','localtime')
                ) = 0
            ORDER BY date DESC
            LIMIT 1
        """)
        ret = cur.fetchone()
        if ret is None:
            return None
        self.register_alert (ret['id'], ret['rainseverity'])
        return ret

    def pop_alert_forecast (self):
        """
        予報シビリティの中に、
        ・最新の実測シビリティ
        ・現在有効なアラートのシビリティ
        のいずれよりも高いものが含まれている場合、アラートを出す。

        <<rainfall シビリティ>> (気象庁の分類をもとに設定)
        -  0:     0 mm/h: 雨なし。
        - 10:  < 10 mm/h: 雨。
        - 20:  < 20 mm/h: やや強い雨。
        - 30:  < 30 mm/h: 強い雨。
        - 40:  < 50 mm/h: 激しい雨。
        - 50:  < 80 mm/h: 非常に激しい雨。
        - 60: >= 80 mm/h: 猛烈な雨。
        """

        cur = self.db.cursor()
        cur.execute( """
            SELECT
                *,
                rain_severity(rainfall) AS rainseverity
            FROM Weathers
            WHERE
                -- 予報であり、かつ、
                type = 'forecast' AND
                -- 未来に関する情報であり、かつ、
                date > datetime('now', 'localtime') AND
                -- 今現在のシビリティよりも予報のシビリティが高く、かつ、
                rainseverity > (
                    -- 今現在のシビリティ
                    SELECT rain_severity(rainfall)
                    FROM Weathers
                    WHERE type = 'observation'
                    ORDER BY date DESC
                    LIMIT 1
                ) AND
                -- 現在有効なアラートの最大のシビリティよりも予報のシビリティが高い。
                rainseverity > ifnull( (
                    -- 現在有効なアラートの最大のシビリティ
                    SELECT max(severity)
                    FROM Alerts LEFT JOIN Weathers ON Alerts.cause = Weathers.id
                    WHERE date > datetime('now','localtime')
                ), 0)
            ORDER BY rainfall DESC
            LIMIT 1
            ;
        """)
        ret = cur.fetchone()
        if ret is None:
            return None
        self.register_alert (ret['id'], ret['rainseverity'])
        return ret

    def register_alert (self, weather_id, severity):
        cur = self.db.cursor()
        cur.execute (
                'INSERT INTO Alerts (cause, severity) VALUES (?,?);',
                [ weather_id, severity ] )
        self.db.commit()
        return cur.lastrowid

    def __del__ (self):
        self.db.close()

def play_notification (typ, severity, cwd = None):
    subprocess.run (['play', '-q', f'{typ}-{severity:2d}.wav'], cwd = cwd)

def main():
    parser = argparse.ArgumentParser (formatter_class = argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument ('--config', default = '~/.watchRain.conf',
            help = 'コンフィグファイル ※仕様上、コンフィグファイルは引数指定よりも強いので注意してください！')
    parser.add_argument ('--app-id', default = None, help = 'Yahoo! API Application ID')
    parser.add_argument ('--coordinates', default = '139.6916944444,35.6895', help = '経度,緯度')
    parser.add_argument ('--db', default = '~/.watchRain.sqlite', help = '蓄積データベースファイル(SQLite3)')
    parser.add_argument ('--sound-dir', default = '.', help = '通知サウンドファイルがあるディレクトリ')
    parser.add_argument ('action', choices = ['fetch-notify', 'fetch-only', 'notify'],
            help = 'fetch-notify: 取得して通知, fetch-only: 取得するが通知しない, notify: 最新のアラートを通知')
    args = parser.parse_args()

    # パス名(チルダ)を解決
    args.config = os.path.expanduser (args.config)
    # コンフィグファイルを読む
    if os.path.exists (args.config):
        config = configparser.ConfigParser()
        config.read (args.config)
        if 'app-id' in config['DEFAULT']:
            args.app_id = config['DEFAULT']['app-id']
        if 'coordinates' in config['DEFAULT']:
            args.coordinates = config['DEFAULT']['coordinates']
        if 'sound-dir' in config['DEFAULT']:
            args.sound_dir = config['DEFAULT']['sound-dir']
    # パス名(チルダ)を解決
    args.db = os.path.expanduser (args.db)
    args.sound_dir = os.path.expanduser (args.sound_dir)

    if args.action in ['fetch-notify', 'fetch-only']:
        if args.app_id is None:
            parser.error ('app-id がありません。')
        # Yahoo から天気予報情報を取得
        yolp = YOLP_Weather (appid = args.app_id, coordinates = args.coordinates)
        weather = yolp.get()
        # 予報DBを開いて書き込む
        weathdb = Weather_DB (args.db)
        weathdb.register_yolpweather (weather)

        # アラートを取得する
        alerts = weathdb.pop_alert()
        if args.action == 'fetch-notify':
            for alert in alerts:
                play_notification (alert['type'], alert['rainseverity'], cwd = args.sound_dir)
    else:
        sys.exit(1)

if __name__ == '__main__':
    main()

