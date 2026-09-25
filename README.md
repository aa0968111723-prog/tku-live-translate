# tku-live-translate

課堂即時字幕：老師瀏覽器做中文語音辨識，伺服器只做詞庫正規化、翻譯與房間廣播。

## 本機

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app
```

開 http://127.0.0.1:8787/host
學生頁：http://127.0.0.1:8787/r/tea930

## Zeabur

Import 這個 GitHub repo。環境變數：

- `HOST_TOKEN`
- `PUBLIC_BASE_URL`（公開網址，不要結尾斜線）
- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `GROQ_API_KEY`（可選備援）
- `GLOSSARY_PATH`（可省略，預設 `data/glossary.json`）

老師開 `/host`，學生或平板開 `/r/tea930`。

## 詞庫

`data/glossary.json` 預設是空的。系統沒有詞也能翻譯。
要鎖特定譯名時，自己改這個檔，或對 `/api/glossary` 送：

```json
{ "zh": "", "en": "", "aliases": [], "lock": true, "cat": "term" }
```

Header：`X-Host-Token`。
