import logging
import stripe
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from learning.models import User
from django.utils.timezone import now
from datetime import timedelta

logger = logging.getLogger(__name__)

@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    endpoint_secret = "whsec_wT7g2urYrVwg96Tqv9AvBLwfqejaqQhS"  # In production, pull this from settings

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        # Invalid payload
        logger.error("Invalid payload")
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        # Invalid signature
        logger.error("Invalid signature")
        return HttpResponse(status=400)

    if event.get("type") == "invoice.payment_succeeded":
        invoice = event.get("data", {}).get("object", {})
        # Try to get teacher_id from invoice metadata first.
        teacher_id = invoice.get("metadata", {}).get("teacher_id")
        if not teacher_id and invoice.get("subscription"):
            try:
                subscription = stripe.Subscription.retrieve(invoice.get("subscription"))
                teacher_id = subscription.metadata.get("teacher_id")
            except Exception as e:
                logger.error(f"Error retrieving subscription: {e}")
                return HttpResponse(status=400)
        if teacher_id:
            try:
                teacher = User.objects.get(id=teacher_id)
                before_exp = teacher.premium_expiration
                teacher.upgrade_to_premium(30)  # Extend by one month
                teacher.refresh_from_db()
                after_exp = teacher.premium_expiration
                logger.info(f"Upgraded teacher {teacher_id}: before={before_exp}, after={after_exp}")
            except User.DoesNotExist:
                logger.error(f"Teacher with id {teacher_id} does not exist")
    return HttpResponse(status=200)
