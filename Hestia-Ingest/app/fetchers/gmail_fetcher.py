import os
import imaplib
import email
from datetime import datetime
from email.header import decode_header
from core.base_fetcher import BaseFetcher


class GmailIMAPFetcher(BaseFetcher):
    def __init__(self):
        self.email_address = os.getenv("GMAIL_ADDRESS")
        self.app_password = os.getenv("GMAIL_APP_PASSWORD")
        self.mail = None

    def connect(self) -> bool:
        if not self.email_address or not self.app_password:
            print("[-] Gmail credentials missing from .env!")
            return False

        try:
            self.mail = imaplib.IMAP4_SSL("imap.gmail.com")
            self.mail.login(self.email_address, self.app_password)
            return True
        except Exception as e:
            print(f"[-] Gmail connection failed: {e}")
            return False

    def fetch_new_data(self, since_date: datetime, custom_filter: str) -> list:
        self.mail.select("inbox")

        # CLEANUP: Bulletproof English IMAP dates
        english_months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        imap_date_str = f"{since_date.day:02d}-{english_months[since_date.month - 1]}-{since_date.year}"

        search_criteria = f'(SINCE "{imap_date_str}" {custom_filter})'

        status, messages = self.mail.search(None, search_criteria)
        if not messages[0]:
            return []

        email_ids = messages[0].split()
        extracted_data = []

        for e_id in email_ids:
            res, msg_data = self.mail.fetch(e_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])

                    subject_header = msg.get("Subject", "No Subject")
                    subject, encoding = decode_header(subject_header)[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(
                            encoding if encoding else "utf-8", errors="ignore")

                    extracted_data.append({
                        # Duplicate protection!
                        "reference_id": str(msg.get("Message-ID", "Unknown")),
                        "source": "gmail_imap",
                        "title": str(subject),
                        "sender": str(msg.get("From", "Unknown Sender")),
                        # Assuming your helper method is still here
                        "body": self._get_email_body(msg),
                        "timestamp": str(msg.get("Date", "Unknown Date"))
                    })
        return extracted_data

    def _get_email_body(self, msg):
        """A bulletproof extractor that digs through deeply nested email structures."""
        body_text = ""

        for part in msg.walk():
            # Skip the 'container' parts, we only want the actual content
            if part.get_content_maintype() == 'multipart':
                continue

            content_type = part.get_content_type()

            # Grab both Plain Text and HTML
            if content_type in ['text/plain', 'text/html']:
                try:
                    # Find the correct character encoding (crucial for Italian emails!)
                    charset = part.get_content_charset() or 'utf-8'
                    payload = part.get_payload(decode=True)

                    if payload:
                        body_text += payload.decode(charset,
                                                    errors='ignore') + "\n\n"
                except Exception as e:
                    print(f"[-] Failed to decode a part of the email: {e}")
                    pass

        return body_text.strip() if body_text.strip() else "Could not extract text body."

    def disconnect(self):
        """Cleanly closes the connection to Gmail when the Factory is done."""
        if hasattr(self, 'mail') and self.mail:
            try:
                self.mail.close()
                self.mail.logout()
            except Exception:
                pass  # If it's already closed, just ignore
            print("[*] Disconnected from Gmail.")
