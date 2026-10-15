from __future__ import annotations
import re
from typing import Any

COUNTRY_ALIASES = {
    "美国": "us", "加拿大": "ca", "墨西哥": "mx", "巴西": "br",
    "英国": "uk", "德国": "de", "法国": "fr", "意大利": "it",
    "西班牙": "es", "荷兰": "nl", "瑞典": "se", "波兰": "pl",
    "比利时": "be", "日本": "jp", "澳大利亚": "au", "阿联酋": "ae",
    "沙特阿拉伯": "sa", "沙特": "sa", "印度": "in", "新加坡": "sg",
    "土耳其": "tr",
}


def business_key(store: Any, country: Any, msku: Any) -> tuple[str, str, str]:
    store_key = str(store or "").strip().casefold()
    store_key = re.sub(r"-(?:eu-)?[a-z]{2}$", "", store_key)
    country_text = str(country or "").strip().casefold().replace("站", "")
    country_key = COUNTRY_ALIASES.get(country_text, country_text)
    return store_key, country_key, str(msku or "").strip().casefold()
