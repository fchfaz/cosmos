"""Login Gmail sekali (OAuth). Butuh data/gmail_credentials.json dari Google Cloud Console
(jenis OAuth client: Desktop app, Gmail API sudah diaktifkan).

    python -m scripts.gmail_auth
"""
from __future__ import annotations

from google_auth_oauthlib.flow import InstalledAppFlow

from core.config import Settings
from skills.email_skill import SCOPES


def main() -> None:
    s = Settings.load()
    creds_path = s.path("email.token_path").with_name("gmail_credentials.json")
    if not creds_path.exists():
        raise SystemExit(f"Tidak ditemukan: {creds_path}\nUnduh credentials.json dari Google Cloud Console lalu simpan di sana.")
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)
    token_path = s.path("email.token_path")
    token_path.write_text(creds.to_json())
    try:
        token_path.chmod(0o600)
    except OSError:
        pass
    print(f"Berhasil. Token disimpan di {token_path}")


if __name__ == "__main__":
    main()
