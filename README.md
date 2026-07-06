# Gmail Multi-Account Manager

Lightweight single-machine Gmail account management platform using Python 3.13 with:

- FastAPI backend
- SQLite3 storage
- Gmail App Password + IMAP read-only sync
- Gmail plus-alias generation and matching
- Proxy configuration
- Consumer API protected by `X-API-Key`
- React admin UI

## Backend

```powershell
cd backend
conda activate python313
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
python run.py --host 127.0.0.1 --port 8000 --reload
```

This project requires Python `>=3.13,<3.14`. On this machine, new PowerShell sessions now default to the conda `python313` environment.
If port `8000` is already occupied, use another port such as `8010` and start the frontend with `VITE_API_BASE` pointing to that backend URL.

Required values in `backend/.env`:

- `MASTER_KEY`, any strong random string; changing it makes existing encrypted tokens unreadable

For local admin protection, set `ADMIN_TOKEN` and send it as `X-Admin-Token`.

## Frontend

```powershell
cd frontend
npm install
$env:VITE_API_BASE = "http://127.0.0.1:8000"
npm run dev
```

Open `http://127.0.0.1:5173`.

## Gmail App Password Setup

Enable 2-Step Verification on each Gmail account, then create an App Password in Google Account security settings. Add the Gmail address and app password in the admin UI. The backend connects to:

```text
imap.gmail.com:993
```

The app password is encrypted at rest with `MASTER_KEY` and is never returned by the API.

## Alias Pattern Rules

Aliases are Gmail plus aliases generated from a pattern. Supported placeholders:

- `{n}`: sequence number, for example `shop-{n}` -> `shop-1`, `shop-2`
- `{n:00}`: zero-padded two-digit sequence, for example `shop-{n:00}` -> `shop-01`, `shop-02`
- `{n:000}`: zero-padded three-digit sequence, for example `shop-{n:000}` -> `shop-001`, `shop-002`
- `{rand:5}`: random lowercase letters and digits, for example `promo-{rand:5}` -> `promo-a8k2z`
- `{rand:8}`: random 8-character token

If a pattern has no `{n}` or `{rand:N}`, the sequence number is appended automatically.

## Proxy Notes

Gmail App Password sync uses IMAP over TLS to `imap.gmail.com:993`. If a proxy works for normal HTTPS web pages but account testing fails, confirm that the proxy allows raw TCP tunneling to port `993`.

- HTTP proxies must support the `CONNECT imap.gmail.com:993` tunnel method.
- Some HTTP web proxies only allow `CONNECT` to port `443`; those cannot be used for Gmail IMAP.
- SOCKS5 proxies are usually the best choice for IMAP traffic.
- If account testing reports an SSL EOF error, check that the selected proxy type matches the real endpoint type, for example do not save a SOCKS5 endpoint as HTTP.
- If sync fails with a Gmail IMAP TLS EOF through a proxy, test the proxy with the IMAP button in the Proxies page. For an account that should bypass all proxies, set its proxy mode to `direct` in the Accounts page.
- For local SOCKS5 clients such as `socks5://127.0.0.1:7890`, make sure `imap.gmail.com:993` is routed through a node that allows raw TCP/TLS IMAP traffic. Some proxy rules or nodes work for HTTPS web traffic but close non-web IMAP tunnels.

## API Quick Start

完整接口说明见 [API.md](API.md)。

1. Start the backend and frontend.
2. Add a Gmail account from the admin UI.
3. Generate aliases for the account.
4. Open the Messages page and run a manual sync. Manual sync defaults to the latest `1` message; change the count field to fetch more.
5. Click a synced message to view its details. Deleting one message or batch deleting selected messages in the admin UI only removes the local synced copy and cached attachment files; it does not delete the original message from Gmail.
6. Create an API key.
7. Call consumer APIs:

```powershell
curl -H "X-API-Key: mg_xxx" "http://127.0.0.1:8000/api/v1/messages"
```
