from django.http import HttpResponse
from django.shortcuts import render


def home(request):
    return render(request, "home.html")


def placeholder_login(request):
    return HttpResponse("Login page - implemented in the authentication issue.")
