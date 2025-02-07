import stripe
import logging
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
    endpoint_secret = "whsec_wT7g2urYrVwg96Tqv9AvBLwfqejaqQhS"  # In production, pull from settings

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        logger.error("Invalid payload")
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        logger.error("Invalid signature")
        return HttpResponse(status=400)

    if event.get("type") == "invoice.payment_succeeded":
        invoice = event.get("data", {}).get("object", {})

        # Try to get teacher_id from invoice metadata.
        teacher_id = invoice.get("metadata", {}).get("teacher_id")
        # Also get the subscription id from the invoice.
        sub_id = invoice.get("subscription")

        # If teacher_id is not in the invoice metadata, try retrieving it from the subscription.
        if not teacher_id and sub_id:
            try:
                subscription = stripe.Subscription.retrieve(sub_id)
                teacher_id = subscription.metadata.get("teacher_id")
                # Use the subscription id from the retrieved subscription.
                sub_id = subscription.id
            except Exception as e:
                logger.error(f"Error retrieving subscription: {e}")
                return HttpResponse(status=400)

        logger.info(f"Webhook received for teacher_id: {teacher_id}")

        if teacher_id:
            try:
                teacher = User.objects.get(id=teacher_id)
                before_exp = teacher.premium_expiration
                teacher.upgrade_to_premium(30)  # Add one month
                # Always update subscription_id if available
                teacher.subscription_id = sub_id
                teacher.save()
                teacher.refresh_from_db()
                after_exp = teacher.premium_expiration
                logger.info(f"Upgraded teacher {teacher_id}: before={before_exp}, after={after_exp}, subscription_id={teacher.subscription_id}")
            except User.DoesNotExist:
                logger.error(f"Teacher with id {teacher_id} does not exist")
    return HttpResponse(status=200)
