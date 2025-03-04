from django.shortcuts import render, get_object_or_404
from .models import BlogPost

def blog_list(request):
    """Show all blog posts."""
    posts = BlogPost.objects.all()
    return render(request, "blog/blog_list.html", {"posts": posts})

def blog_detail(request, slug):
    """Show a single blog post."""
    post = get_object_or_404(BlogPost, slug=slug)
    return render(request, "blog/blog_detail.html", {"post": post})