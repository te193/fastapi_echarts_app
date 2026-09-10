import json
import subprocess


def _format(value, currency):
    script = (
        "const f=require('./app/static/js/ad_currency.js');"
        f"process.stdout.write(JSON.stringify(f.format({json.dumps(value)}, {json.dumps(currency)})));"
    )
    return json.loads(subprocess.check_output(["node", "-e", script]).decode("utf-8"))


def test_euro_amount_is_visibly_distinguished_from_renminbi():
    assert _format(1008.35, "EUR") == "€1,008.35"
    assert _format(1008.35, "CNY") == "¥1,008.35"


def test_unknown_currency_keeps_currency_code_visible():
    assert _format(12.5, "CHF") == "CHF 12.50"
    assert _format(None, "EUR") == "—"
