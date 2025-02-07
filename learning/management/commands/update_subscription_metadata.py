from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
import stripe
from django.conf import settings

User = get_user_model()

class Command(BaseCommand):
    help = "Update Stripe subscriptions to include teacher_id in metadata"

    def handle(self, *args, **kwargs):
        stripe.api_key = settings.STRIPE_SECRET_KEY

        # Retrieve a list of subscriptions (you may need to page through them if there are many)
        subscriptions = stripe.Subscription.list(limit=100)

        for subscription in subscriptions.auto_paging_iter():
            metadata = subscription.get("metadata", {})
            # If teacher_id is already set, skip
            if metadata.get("teacher_id"):
                continue

            # If the subscription's customer email can help us match a teacher,
            # retrieve the customer first.
            customer_id = subscription.get("customer")
            customer = stripe.Customer.retrieve(customer_id)
            customer_email = customer.get("email")

            try:
                teacher = User.objects.get(email=customer_email)
            except User.DoesNotExist:
                self.stdout.write(f"No teacher found with email {customer_email}")
                continue

            # Update the subscription with teacher_id in metadata
            stripe.Subscription.modify(
                subscription["id"],
                metadata={"teacher_id": str(teacher.id)}
            )
            self.stdout.write(f"Updated subscription {subscription['id']} with teacher_id {teacher.id}")

        self.stdout.write("Subscription metadata update completed.")