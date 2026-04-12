import argparse
import sys
from pathlib import Path
from typing import TypedDict

# Allow running the script directly via `python scripts/live_seed_emails.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.dependencies import get_gmail
from app.settings import settings


class SeedEmail(TypedDict):
	subject: str
	body: str


TEST_EMAILS: list[SeedEmail] = [
	{
		"subject": "Discussion: Q3 Strategy Roadmap",
		"body": "Hi, I would like to schedule a 45-minute meeting to discuss the Q3 roadmap. Are you free on 2026-04-15 at 14:00 UTC?",
	},
	{
		"subject": "Partnership Sync",
		"body": "Hello, let's have a quick sync regarding the new partnership. How about 2026-04-15T10:00:00Z? It should take about an hour.",
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
	print(f"Starting to send {len(TEST_EMAILS)} test emails to {target_email}...")

	if dry_run:
		for item in TEST_EMAILS:
			print(f"[DRY-RUN] Would send: {item['subject']}")
		return

	gmail = get_gmail()

	for item in TEST_EMAILS:
		try:
			gmail.send_message(
				to=target_email,
				subject=item["subject"],
				body=item["body"],
			)
			print(f"Sent: {item['subject']}")
		except Exception as exc:
			print(f"Failed to send '{item['subject']}': {exc}")


def main() -> None:
	parser = argparse.ArgumentParser(description="Send predefined workflow test emails to a target inbox.")
	parser.add_argument(
		"--to",
		default="tomas.weber.ai.task@gmail.com",
		help="Target email address for test messages.",
	)
	parser.add_argument(
		"--dry-run",
		action="store_true",
		help="Print messages that would be sent without calling Gmail API.",
	)
	args = parser.parse_args()

	target = str(args.to or "").strip() or settings.MANAGER_EMAIL
	send_tests(target_email=target, dry_run=bool(args.dry_run))


if __name__ == "__main__":
	main()


