#!/usr/bin/env python3
"""
Helper script to obtain a VK access token via the browser.
Usage: python get_token.py
"""

import webbrowser
import urllib.parse

# VK Admin app — public client_id, read-only scope
CLIENT_ID = "6614620"
SCOPE = "wall,photos,groups,offline"
REDIRECT = "https://oauth.vk.com/blank.html"
VERSION = "5.199"

url = (
    f"https://oauth.vk.com/authorize"
    f"?client_id={CLIENT_ID}"
    f"&display=page"
    f"&redirect_uri={urllib.parse.quote(REDIRECT)}"
    f"&scope={SCOPE}"
    f"&response_type=token"
    f"&v={VERSION}"
)

print("=" * 60)
print("A browser window will open with the VK authorization page.")
print()
print("Steps:")
print("  1. Log in to VK (if not already logged in)")
print("  2. Click 'Allow'")
print("  3. The browser will redirect to a blank page —")
print("     copy the full URL from the address bar")
print("  4. Paste it here and press Enter")
print("=" * 60)
print()

webbrowser.open(url)

raw = input("Paste the URL from the address bar: ").strip()

try:
    # URL format: https://oauth.vk.com/blank.html#access_token=XXX&...
    fragment = raw.split("#", 1)[1]
    params = dict(p.split("=", 1) for p in fragment.split("&"))
    token = params["access_token"]
    expires = params.get("expires_in", "0")
    user_id = params.get("user_id", "?")

    print()
    print("Token obtained!")
    print(f"  User ID : {user_id}")
    print(f"  Expires : {'never' if expires == '0' else expires + ' sec'}")
    print()
    print("Your token:")
    print("-" * 60)
    print(token)
    print("-" * 60)
    print()
    print("Use it like this:")
    print(f'  python vk_save.py <group> --token {token}')
    print()
    print("Or save it as an environment variable to avoid passing it each time:")
    print(f'  $env:VK_TOKEN = "{token}"')
    print(f'  python vk_save.py <group>')

except Exception:
    print()
    print("Could not extract the token from the URL.")
    print("Make sure you copied the full URL after the redirect.")
    print("Example of a valid URL:")
    print("  https://oauth.vk.com/blank.html#access_token=vk1.a.XXX&expires_in=0&...")
