# LtBooks — jsonenc.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

import datetime
import decimal
import json


class Encoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return float(o)
        if isinstance(o, (datetime.date, datetime.datetime)):
            return o.isoformat()[:10] if isinstance(o, datetime.date) and not isinstance(o, datetime.datetime) else o.isoformat(sep=" ", timespec="milliseconds")
        if isinstance(o, set):
            return list(o)
        if isinstance(o, bytes):
            return o.decode("utf-8", "replace")
        return super().default(o)
