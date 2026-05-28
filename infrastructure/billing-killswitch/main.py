import json
import base64
from googleapiclient import discovery

PROJECT_ID = "astraphe-ai-coach"

def stop_billing(event, context):
    pubsub_data = base64.b64decode(event["data"]).decode("utf-8")
    budget_data = json.loads(pubsub_data)

    cost = budget_data.get("costAmount", 0)
    budget = budget_data.get("budgetAmount", 0)

    if cost <= budget:
        print(f"Cost ${cost} under budget ${budget}, no action.")
        return

    print(f"Cost ${cost} exceeded budget ${budget} — disabling billing.")
    _disable_billing()

def _disable_billing():
    service = discovery.build("cloudbilling", "v1")
    billing_name = f"projects/{PROJECT_ID}"
    service.projects().updateBillingInfo(
        name=billing_name,
        body={"billingAccountName": ""}  # empty string = unlink billing
    ).execute()
    print("Billing disabled.")