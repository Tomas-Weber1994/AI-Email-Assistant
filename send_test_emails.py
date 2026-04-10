import asyncio
from app.dependencies import get_gmail
from app.settings import settings

# Test data based on the 7 scenarios
TEST_EMAILS = [
    {
        "subject": "Discussion: Q3 Strategy Roadmap",
        "body": "Hi, I would like to schedule a 45-minute meeting to discuss the Q3 roadmap. Are you free on 2026-04-15 at 14:00 UTC?"
    },
    {
        "subject": "Partnership Sync",
        "body": "Hello, let's have a quick sync regarding the new partnership. How about 2026-04-15T10:00:00Z? It should take about an hour."
    },
    {
        "subject": "URGENT: Server Migration Issue - Action Required",
        "body": "The database migration is failing with a 500 error on the production environment. We need your immediate attention."
    },
    {
        "subject": "Invoice #2026-044 - Cloud Services",
        "body": "Dear customer, attached is your monthly invoice for cloud services. Total amount: 150 USD."
    },
    {
        "subject": "Improve your lead generation with AI",
        "body": "Hi there, I saw your profile and thought you might be interested in our new AI tool. Do you have 5 minutes for a demo?"
    },
    {
        "subject": "Top 10 Tech Trends for April 2026",
        "body": "Weekly Newsletter: Discover how quantum computing is changing the world. Unsubscribe here."
    },
    {
        "subject": "SECURITY ALERT: Your account has been compromised!!",
        "body": "URGENT! Unusual activity detected. Click this link to verify: http://totally-not-a-scam.com/login"
    }
]

async def send_tests():
    gmail = get_gmail()
    target_email = "tomas.weber.ai.task@gmail.com"

    print(f"Starting to send {len(TEST_EMAILS)} test emails to {target_email}...")

    for test in TEST_EMAILS:
        try:
            gmail.send_message(
                to=target_email,
                subject=test["subject"],
                body=test["body"]
            )
            print(f"Sent: {test['subject']}")
        except Exception as e:
            print(f"Failed to send '{test['subject']}': {e}")

if __name__ == "__main__":
    asyncio.run(send_tests())
