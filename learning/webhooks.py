import stripe
import logging
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import get_user_model
from django.utils.timezone import now
from datetime import timedelta
from django.conf import settings

logger = logging.getLogger(__name__)

@csrf_exempt
def stripe_webhook(request):
    User = get_user_model()

    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    endpoint_secret = settings.STRIPE_WEBHOOK_SECRET

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        logger.error("Invalid payload")
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        logger.error("Invalid signature")
        return HttpResponse(status=400)

    event_type = event.get("type")

    # ✅ Handle Subscription Creation & Renewals
    if event_type == "invoice.payment_succeeded":
        invoice = event.get("data", {}).get("object", {})
        teacher_id = invoice.get("metadata", {}).get("teacher_id")
        sub_id = invoice.get("subscription")

        if not teacher_id and sub_id:
            try:
                subscription = stripe.Subscription.retrieve(sub_id)
                teacher_id = subscription.metadata.get("teacher_id")
            except Exception as e:
                logger.error(f"Error retrieving subscription: {e}")
                return HttpResponse(status=400)

        if teacher_id:
            try:
                teacher = User.objects.get(id=teacher_id)
                before_exp = teacher.premium_expiration
                teacher.upgrade_to_premium(30)  # Extend premium & add 5 Pavonicoins
                teacher.subscription_id = sub_id
                teacher.save()
                after_exp = teacher.premium_expiration
                logger.info(f"Upgraded teacher {teacher_id}: before={before_exp}, after={after_exp}, subscription_id={teacher.subscription_id}")
            except User.DoesNotExist:
                logger.error(f"Teacher with id {teacher_id} does not exist")

    # ✅ Handle Pavonicoins Purchase (One-Time Payment)
    elif event_type == "checkout.session.completed":
        session = event.get("data", {}).get("object", {})
        user_id = session.get("metadata", {}).get("user_id")

        if not user_id:
            logger.error("Checkout session completed but no user_id found in metadata.")
            return HttpResponse(status=400)

        try:
            user = User.objects.get(id=user_id)
            user.add_credits(20)  # Add 20 Pavonicoins
            logger.info(f"Added 20 Pavonicoins to user {user_id}. New balance: {user.ai_credits}")
        except User.DoesNotExist:
            logger.error(f"User with ID {user_id} not found for Pavonicoins purchase.")

    return HttpResponse(status=200)
