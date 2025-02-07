# learning/webhooks.py
import json
import stripe
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from learning.models import User

# If you prefer, you can also import your webhook secret from settings:
# from django.conf import settings
# endpoint_secret = settings.STRIPE_WEBHOOK_SECRET
endpoint_secret = "whsec_wT7g2urYrVwg96Tqv9AvBLwfqejaqQhS"  # Replace with your environment variable in production

@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        # Invalid payload
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        # Invalid signature
        return HttpResponse(status=400)

    # Process the invoice.payment_succeeded event
    if event.get("type") == "invoice.payment_succeeded":
        invoice = event.get("data", {}).get("object", {})
        # Try to get teacher_id from the invoice metadata first.
        teacher_id = invoice.get("metadata", {}).get("teacher_id")
        # If not found, try to retrieve the subscription to get metadata.
        if not teacher_id and invoice.get("subscription"):
            try:
                subscription = stripe.Subscription.retrieve(invoice.get("subscription"))
                teacher_id = subscription.metadata.get("teacher_id")
            except Exception:
                return HttpResponse(status=400)
        if teacher_id:
            try:
                teacher = User.objects.get(id=teacher_id)
                teacher.upgrade_to_premium(30)  # Add one month premium
            except User.DoesNotExist:
                # Optionally log that no teacher was found for the given ID.
                pass

    return HttpResponse(status=200)
