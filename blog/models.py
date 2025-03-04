from django.db import models
from django.utils.timezone import now
from django.contrib.auth import get_user_model

User = get_user_model()

class BlogPost(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, help_text="URL-friendly version of the title")
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    featured_image = models.ImageField(upload_to="blog_images/", blank=True, null=True)
    created_at = models.DateTimeField(default=now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]  # Show newest posts first

    def __str__(self):
        return self.title
