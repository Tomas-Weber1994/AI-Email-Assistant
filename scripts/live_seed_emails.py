import argparse
import sys
import smtplib
from pathlib import Path
from typing import TypedDict
from email.message import EmailMessage

# Upravená konfigurace pro Seznam
SEZNAM_USER = "weber35@seznam.cz"
SEZNAM_PASSWORD = "BBB"
SMTP_SERVER = "smtp.seznam.cz"
SMTP_PORT = 465

# Allow running the script directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.settings import settings


class SeedEmail(TypedDict):
    subject: str
    body: str


TEST_EMAILS: list[SeedEmail] = [
    {
        "subject": "Discussion: Q3 Strategy Roadmap",
        "body": "Hi, I would like to schedule a 45-minute meeting to discuss the Q3 roadmap. Are you free on 2026-04-15 at 14:00?",
    },
    {
        "subject": "Partnership Sync",
        "body": "Hello, let's have a quick sync regarding the new partnership. How about 2026-04-15 at 10:00? It should take about an hour.",
    },
    {
        "subject": "URGENT: Server Migration Issue - Action Required",
        "body": "The database migration is failing with a 500 error on the production environment. We need your immediate attention.",
    },
    {
        "subject": "Invoice #2026-044 - Cloud Services",
        "body": "Dear customer, attached is your monthly invoice for cloud services. Total amount: 150 USD.",
    },
    {
        "subject": "Improve your lead generation with AI",
        "body": "Hi there, I saw your profile and thought you might be interested in our new AI tool. Do you have 5 minutes for a demo?",
    },
    {
        "subject": "Top 10 Tech Trends for April 2026",
        "body": "Weekly Newsletter: Discover how quantum computing is changing the world. Unsubscribe here.",
    },
    {
        "subject": "SECURITY ALERT: Your account has been compromised!!",
        "body": "URGENT! Unusual activity detected. Click this link to verify: http://totally-not-a-scam.com/login",
    },
]


def send_tests(target_email: str, dry_run: bool = False) -> None:
    print(f"Starting to send {len(TEST_EMAILS)} test emails from {SEZNAM_USER} to {target_email}...")

    if dry_run:
        for item in TEST_EMAILS:
            print(f"[DRY-RUN] Would send: {item['subject']}")
        return

    # Používáme SMTP Seznamu pro legitimní odeslání
    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(SEZNAM_USER, SEZNAM_PASSWORD)

            for item in TEST_EMAILS:
                msg = EmailMessage()
                msg.set_content(item["body"])
                msg["Subject"] = item["subject"]
                msg["From"] = SEZNAM_USER
                msg["To"] = target_email

                server.send_message(msg)
                print(f"Sent from Seznam: {item['subject']}")

    except Exception as exc:
        print(f"SMTP Error: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send predefined workflow test emails to a target inbox.")
    parser.add_argument(
        "--to",
        default="tomas.weber.ai.task@gmail.com",  # Zde je botova adresa
        help="Target email address for test messages.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print messages that would be sent.",
    )
    args = parser.parse_args()

    target = str(args.to or "").strip()
    send_tests(target_email=target, dry_run=bool(args.dry_run))


if __name__ == "__main__":
    main()